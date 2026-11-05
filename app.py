import os
import re
import json
import asyncio
import threading
import numpy as np
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

import httpx
from groq import Groq
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request

from memory import (
    init_db, add_task, list_tasks, complete_task,
    add_reminder, log_message, recent_conversations
)

# ─ Config ─
GROQ_API_KEY        = os.getenv("GROQ_API_KEY")
ELEVENLABS_API_KEY  = os.getenv("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "sB7vwSCyX0tQmU24cW2C")
GROQ_MODEL          = "llama-3.3-70b-versatile"
ELEVENLABS_MODEL    = "eleven_turbo_v2_5"
USER_NAME           = "Amber"

SYSTEM_PROMPT = f"""You are Baymax, {USER_NAME}'s personal AI assistant.

Your personality:
- Calm, natural, confident - like a helpful junior colleague
- Humble but occasionally funny - light dry humour, never forced
- Concise. You speak, so keep responses SHORT (1-3 sentences max unless asked for more)
- Never say "As an AI..." or "I'm just an assistant..."

You can help with:
- Managing tasks and to-do lists
- Setting reminders
- General questions and conversation
- Job search support - {USER_NAME} is targeting GTM Strategy, BizOps, RevOps roles at tech companies

To manage tasks, embed these tags anywhere in your response (they'll be hidden from the user):
- [ADD_TASK: <task text>] - to add a task
- [LIST_TASKS] - to retrieve and read the pending task list
- [COMPLETE_TASK: <task name>] - to mark a task done
- [ADD_REMINDER: <text> | <optional datetime>] - to save a reminder

Always respond in plain spoken English. No markdown, no asterisks, no bullet points.
Keep it conversational. You're talking, not writing.
Be brief unless the user asks for detail."""

groq_client = Groq(api_key=GROQ_API_KEY)

# ─ FastAPI app ─
app = FastAPI(title="Baymax")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Track all active WebSocket connections for wake-word broadcasts
active_connections: list[WebSocket] = []
connections_lock = asyncio.Lock()

# ─ AI response ─
def get_ai_response(conversation_history: list) -> str:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + conversation_history
    response = groq_client.chat.completions.create(
        model=GROQ_MODEL,
        messages=messages,
        max_tokens=350,
        temperature=0.75,
    )
    return response.choices[0].message.content

# ─ TTS ─
async def text_to_speech(text: str) -> bytes | None:
    if not ELEVENLABS_API_KEY or not text.strip():
        return None
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}"
    headers = {"xi-api-key": ELEVENLABS_API_KEY, "Content-Type": "application/json"}
    payload = {
        "text": text,
        "model_id": ELEVENLABS_MODEL,
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75, "style": 0.3, "use_speaker_boost": True},
    }
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(url, headers=headers, json=payload)
        if r.status_code == 200:
            return r.content
    return None

# ─ Action parser ─
def parse_and_execute_actions(text: str) -> str:
    clean = text
    for m in re.finditer(r'\[ADD_TASK:\s*(.+?)\]', text):
        add_task(m.group(1).strip())
        clean = clean.replace(m.group(0), "")
    if "[LIST_TASKS]" in text:
        tasks = list_tasks()
        clean = clean.replace("[LIST_TASKS]", "")
        if tasks:
            names = ", ".join(t["task"] for t in tasks[:8])
            clean += f" Your pending tasks are: {names}."
        else:
            clean += " You have no pending tasks right now."
    for m in re.finditer(r'\[COMPLETE_TASK:\s*(.+?)\]', text):
        complete_task(m.group(1).strip())
        clean = clean.replace(m.group(0), "")
    for m in re.finditer(r'\[ADD_REMINDER:\s*(.+?)(?:\s*\|\s*(.+?))?\]', text):
        add_reminder(m.group(1).strip(), m.group(2).strip() if m.group(2) else None)
        clean = clean.replace(m.group(0), "")
    return clean.strip()

# ─ Wake word thread ─
def start_wake_word_listener(loop: asyncio.AbstractEventLoop):
    """Background thread: listens for the wake phrase and signals the browser."""
    try:
        import sounddevice as sd
        import openwakeword
        from openwakeword.model import Model as WakeModel

        openwakeword.utils.download_models(["hey_jarvis"])
        wake_model = WakeModel(wakeword_models=["hey_jarvis"], inference_framework="onnx")

        SAMPLE_RATE = 16000
        CHUNK = int(SAMPLE_RATE * 0.08)  # 80 ms frames

        def audio_callback(indata, frames, time_info, status):
            audio = np.squeeze(indata)
            audio_int16 = (audio * 32767).astype(np.int16)
            prediction = wake_model.predict(audio_int16)
            score = max(prediction.values()) if prediction else 0.0
            if score > 0.5:
                wake_model.reset()
                asyncio.run_coroutine_threadsafe(_broadcast_wake_word(), loop)

        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                            blocksize=CHUNK, callback=audio_callback):
            print("Wake word listener active - say Hey Baymax")
            threading.Event().wait()

    except ImportError:
        print("Wake word deps not installed. Run: pip install openwakeword sounddevice")
    except Exception as e:
        print(f"Wake word listener error: {e}")


async def _broadcast_wake_word():
    async with connections_lock:
        dead = []
        for ws in active_connections:
            try:
                await ws.send_text(json.dumps({"type": "wake_word"}))
            except Exception:
                dead.append(ws)
        for ws in dead:
            active_connections.remove(ws)

# ─ Startup ─
@app.on_event("startup")
async def startup():
    init_db()
    if not GROQ_API_KEY:
        print("WARNING: GROQ_API_KEY not set")
    if not ELEVENLABS_API_KEY:
        print("WARNING: ELEVENLABS_API_KEY not set")
    loop = asyncio.get_event_loop()
    t = threading.Thread(target=start_wake_word_listener, args=(loop,), daemon=True)
    t.start()

# ─ Routes ─
@app.get("/")
async def root():
    with open("templates/index.html") as f:
        from fastapi.responses import HTMLResponse
        return HTMLResponse(f.read())

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    async with connections_lock:
        active_connections.append(websocket)

    conversation_history: list[dict] = []
    greeting = f"Hey {USER_NAME}. I'm Baymax, ready when you are."
    log_message("assistant", greeting)
    await websocket.send_json({"type": "text", "content": greeting})
    try:
        audio = await text_to_speech(greeting)
        if audio:
            await websocket.send_bytes(audio)
    except Exception as e:
        print(f"TTS greeting error: {e}")

    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") != "user_message":
                continue
            user_text = data.get("content", "").strip()
            if not user_text:
                continue
            log_message("user", user_text)
            conversation_history.append({"role": "user", "content": user_text})
            if len(conversation_history) > 20:
                conversation_history = conversation_history[-20:]
            try:
                ai_raw = get_ai_response(conversation_history)
            except Exception as e:
                print(f"Groq error: {e}")
                ai_raw = "Sorry, I had a brain freeze. Try again?"
            clean = parse_and_execute_actions(ai_raw) or "Done."
            log_message("assistant", clean)
            conversation_history.append({"role": "assistant", "content": clean})
            await websocket.send_json({"type": "text", "content": clean})
            try:
                audio = await text_to_speech(clean)
                if audio:
                    await websocket.send_bytes(audio)
            except Exception as e:
                print(f"TTS error: {e}")
                await websocket.send_json({"type": "tts_error", "content": str(e)})
    except WebSocketDisconnect:
        print("Client disconnected")
    finally:
        async with connections_lock:
            if websocket in active_connections:
                active_connections.remove(websocket)

if __name__ == "__main__":
    import uvicorn
    print("\nBaymax starting at http://localhost:8000\n")
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=False)
