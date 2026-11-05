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

# ââ Config ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
GROQ_API_KEY       = os.getenv("GROQ_API_KEY")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "sB7vwSCyX0tQmU24cW2C")
GROQ_MODEL         = "llama-3.3-70b-versatile"
ELEVENLABS_MODEL   = "eleven_turbo_v2_5"
USER_NAME          = "Amber"

SYSTEM_PROMPT = f"""You are Baymax, a calm and helpful personal AI assistant for {USER_NAME}.
You speak naturally and concisely â responses should feel like a real conversation, not a lecture.
Keep spoken answers brief (2-4 sentences max) unless asked to elaborate.
{USER_NAME} is exploring roles in GTM, BizOps, and RevOps. Help with job search, planning, and daily tasks.

You can take actions by embedding tags (they will be stripped before you speak):
- Add a task: [ADD_TASK: description]
- List tasks: [LIST_TASKS]
- Complete a task: [COMPLETE_TASK: description]
- Add a reminder: [ADD_REMINDER: text | YYYY-MM-DD HH:MM]

Always be warm, supportive, and direct."""

# ââ Groq client âââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
groq_client = Groq(api_key=GROQ_API_KEY)

# ââ FastAPI app ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Track all active WebSocket connections for wake-word broadcasts
active_connections: list[WebSocket] = []
connections_lock = asyncio.Lock()

# ââ AI response ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
def get_ai_response(conversation_history: list) -> str:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + conversation_history
    response = groq_client.chat.completions.create(
        model=GROQ_MODEL,
        messages=messages,
        max_tokens=350,
        temperature=0.75,
    )
    return response.choices[0].message.content

# ââ TTS ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
async def text_to_speech(text: str) -> bytes | None:
    if not ELEVENLABS_API_KEY or not text.strip():
        return None
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}"
    headers = {"xi-api-key": ELEVENLABS_API_KEY, "Content-Type": "application/json"}
    payload = {
        "text": text,
        "model_id": ELEVENLABS_MODEL,
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75, "style": 0.3},
    }
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(url, headers=headers, json=payload)
        if r.status_code == 200:
            return r.content
    return None

# ââ Action parser âââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
def parse_and_execute_actions(text: str) -> str:
    if "[LIST_TASKS]" in text:
        tasks = list_tasks()
        task_text = "\n".join(f"- {t}" for t in tasks) if tasks else "No tasks yet."
        text = text.replace("[LIST_TASKS]", f"\n{task_text}\n")

    for match in re.finditer(r"\[ADD_TASK:\s*(.+?)\]", text):
        add_task(match.group(1).strip())
        text = text.replace(match.group(0), "")

    for match in re.finditer(r"\[COMPLETE_TASK:\s*(.+?)\]", text):
        complete_task(match.group(1).strip())
        text = text.replace(match.group(0), "")

    for match in re.finditer(r"\[ADD_REMINDER:\s*(.+?)\|(.+?)\]", text):
        add_reminder(match.group(1).strip(), match.group(2).strip())
        text = text.replace(match.group(0), "")

    return text.strip()

# ââ Wake word thread ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
def start_wake_word_listener(loop: asyncio.AbstractEventLoop):
    """Background thread: listen for 'hey jarvis' (closest pre-trained model to 'hey baymax')."""
    try:
        import sounddevice as sd
        import openwakeword
        from openwakeword.model import Model as WakeModel

        # Download models on first run (no-op after)
        openwakeword.utils.download_models(["hey_jarvis"])

        wake_model = WakeModel(wakeword_models=["hey_jarvis"], inference_framework="onnx")

        SAMPLE_RATE = 16000
        CHUNK = int(SAMPLE_RATE * 0.08)   # 80 ms frames

        THRESHOLD = 0.3   # lower = more sensitive (default was 0.5)
        _debug_counter = [0]

        def audio_callback(indata, frames, time_info, status):
            audio = np.squeeze(indata)
            audio_int16 = (audio * 32767).astype(np.int16)
            prediction = wake_model.predict(audio_int16)
            score = max(prediction.values()) if prediction else 0.0
            # Print score every ~2 seconds so you can tune the threshold
            _debug_counter[0] += 1
            if _debug_counter[0] % 25 == 0 and score > 0.05:
                print(f"[wake] score={score:.3f} (trigger>{THRESHOLD})")
            if score > THRESHOLD:
                print(f"[wake] DETECTED! score={score:.3f}")
                wake_model.reset()
                asyncio.run_coroutine_threadsafe(_broadcast_wake_word(), loop)

        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            blocksize=CHUNK,
            callback=audio_callback,
        ):
            print("ðï¸  Wake word listener active â say 'Hey Baymax'")
            threading.Event().wait()   # block forever

    except ImportError:
        print("â ï¸  Wake word deps not installed. Run: pip install openwakeword sounddevice")
    except Exception as e:
        print(f"â ï¸  Wake word listener error: {e}")

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

# ââ Startup âââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
@app.on_event("startup")
async def startup():
    init_db()
    loop = asyncio.get_event_loop()
    t = threading.Thread(target=start_wake_word_listener, args=(loop,), daemon=True)
    t.start()

# ââ Routes ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    async with connections_lock:
        active_connections.append(ws)

    conversation: list = []
    history = recent_conversations(limit=5)
    for role, content in history:
        if role in ("user", "assistant"):  # only valid Groq roles
            conversation.append({"role": role, "content": content})

    # Greeting
    greeting = f"Hey {USER_NAME}! I'm Baymax â ready when you are."
    await ws.send_text(json.dumps({"type": "text", "content": greeting}))
    audio = await text_to_speech(greeting)
    if audio:
        await ws.send_bytes(audio)

    try:
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)

            if msg.get("type") != "user_message":
                continue

            user_text = msg["content"].strip()
            if not user_text:
                continue

            log_message("user", user_text)
            conversation.append({"role": "user", "content": user_text})
            if len(conversation) > 20:
                conversation = conversation[-20:]

            await ws.send_text(json.dumps({"type": "status", "content": "thinking"}))

            ai_raw = get_ai_response(conversation)
            ai_clean = parse_and_execute_actions(ai_raw)

            log_message("assistant", ai_clean)
            conversation.append({"role": "assistant", "content": ai_clean})

            await ws.send_text(json.dumps({"type": "text", "content": ai_clean}))
            audio = await text_to_speech(ai_clean)
            if audio:
                await ws.send_bytes(audio)

    except WebSocketDisconnect:
        pass
    finally:
        async with connections_lock:
            if ws in active_connections:
                active_connections.remove(ws)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=False)
