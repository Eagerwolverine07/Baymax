# Baymax — Personal Voice AI Assistant

A local voice assistant that runs on your Mac. Talk to it with your mic, it thinks with Groq + Llama 3.3, and speaks back with ElevenLabs (Jon voice).

## Features

- 🎙️ **Voice input** — click the mic button (or hold spacebar) to speak
- 🔊 **Natural voice output** — ElevenLabs TTS (Jon — Natural Authority)
- 🧠 **Free AI brain** — Groq + Llama 3.3 70B (fast, free tier)
- 📋 **Task management** — add, list, and complete tasks
- ⏰ **Reminders** — set reminders with natural language
- 💾 **Persistent memory** — SQLite local DB, remembers across sessions
- 💬 **Multi-turn conversation** — context-aware, keeps last 20 exchanges
- ⌨️ **Text fallback** — type if you don't want to speak

## Requirements

- Python 3.12+
- Google Chrome (for voice input via Web Speech API)
- Groq API key (free at [console.groq.com](https://console.groq.com))
- ElevenLabs API key (free at [elevenlabs.io](https://elevenlabs.io))

## Install & Run

```bash
git clone https://github.com/Eagerwolverine07/Baymax.git
cd Baymax
pip3 install -r requirements.txt
cp .env.example .env
# Edit .env and add your actual API keys
python3 app.py
```

Then open **http://localhost:8000** in Chrome.

## Usage

| Action | How |
|---|---|
| Speak | Click 🎙️ or hold **Spacebar** |
| Type | Use the text box at the bottom |
| Add a task | Say "add task: buy groceries" |
| List tasks | Say "what's on my to-do list?" |
| Complete a task | Say "mark buy groceries as done" |
| Set a reminder | Say "remind me to call mom" |

## Project Structure

```
Baymax/
├── app.py
├── memory.py
├── templates/index.html
├── static/app.js
├── static/style.css
├── requirements.txt
├── .env.example
└── .gitignore
```

## Environment Variables

| Variable | Description |
|---|---|
| `GROQ_API_KEY` | From [console.groq.com](https://console.groq.com) |
| `ELEVENLABS_API_KEY` | From [elevenlabs.io](https://elevenlabs.io) |
| `ELEVENLABS_VOICE_ID` | Jon voice: `sB7vwSCyX0tQmU24cW2C` |

## Planned features

- [ ] Wake word ("Hey Baymax") via Porcupine
- [ ] Google Calendar integration
- [ ] Google Tasks sync
- [ ] macOS background agent (launchd)
