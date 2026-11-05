"""
Baymax — Personal Voice AI Assistant
FastAPI + WebSocket + Groq (Llama 3.3) + ElevenLabs TTS
"""
import os
from dotenv import load_dotenv
load_dotenv()

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from groq import Groq

from memory import (
    init_db, add_task, list_tasks, complete_task,
    add_reminder, log_message, recent_conversations
)

GROQ_API_KEY        = os.getenv("GROQ_API_KEY")
ELEVENLABS_API_KEY  = os.getenv("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "sB7vwSCyX0tQmU24cW2C")
ELEVENLABS_MODEL    = "eleven_turbo_v2_5"
GROQ_MODEL          = "llama-3.3-70b-versatile"
USER_NAME           = "Amber"

SYSTEM_PROMPT = f"""You are Baymax, {USER_NAME}'s personal AI assistant.

Your personality:
- Calm, natural, confident — like a helpful junior colleague
- Humble but occasionally funny — light dry humour, never forced
- Concise. You speak, so keep responses SHORT (1-3 sentences max unless asked for more)
- Never say "As an AI..." or "I'm just an assistant..."

You can help with:
- Managing tasks and to-do lists
- Setting reminders
- General questions and conversation
- Job search support — {USER_NAME} is targeting GTM Strategy, BizOps, RevOps roles at tech companies

To manage tasks, embed these tags anywhere in your response (they'll be hidden from the user):
- [ADD_TASK: <task text>] — to add a task
- [LIST_TASKS] — to retrieve and read the pending task list
- [COMPLETE_TASK: <task name>] — to mark a task done
- [ADD_REMINDER: <text> | <optional datetime>] — to save a reminder

Always respond in plain spoken English. No markdown, no asterisks, no bullet points.
Keep it conversational. You're talking, not writing.
Be brief unless the user asks for detail."""

groq_client = Groq(api_key=GROQ_API_KEY)

def get_ai_response(conversation_history: list) -> str:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + conversation_history
    response = groq_client.chat.completions.create(
        model=GROQ_MODEL,
        messages=messages,
        max_tokens=350,
        temperature=0.75,
    )
    return response.choices[0].message.content

async def text_to_speech(text: str) -> bytes:
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}"
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Content-Type": "application/json",
    }
    payload = {
        "text": text,
        "model_id": ELEVENLABS_MODEL,
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75,
            "style": 0.3,
            "use_speaker_boost": True,
        }
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        return resp.content

import re

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

app = FastAPI(title="Baymax")
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.on_event("startup")
async def startup():
    init_db()
    if not GROQ_API_KEY: print("WARNING: GROQ_API_KEY not set")
    if not ELEVENLABS_API_KEY: print("WARNING: ELEVENLABS_API_KEY not set")

@app.get("/")
async def root():
    with open("templates/index.html") as f:
        return HTMLResponse(f.read())

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    conversation_history: list[dict] = []
    greeting = f"Hey {USER_NAME}. I'm Baymax, ready when you are."
    log_message("assistant", greeting)
    await websocket.send_json({"type": "text", "content": greeting})
    try:
        audio = await text_to_speech(greeting)
        await websocket.send_bytes(audio)
    except Exception as e:
        print(f"TTS greeting error: {e}")
    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") != "user_message": continue
            user_text = data.get("content", "").strip()
            if not user_text: continue
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
                await websocket.send_bytes(audio)
            except Exception as e:
                print(f"TTS error: {e}")
                await websocket.send_json({"type": "tts_error", "content": str(e)})
    except WebSocketDisconnect:
        print("Client disconnected")

if __name__ == "__main__":
    import uvicorn
    print("\nBaymax starting at http://localhost:8000\n")
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=False)
