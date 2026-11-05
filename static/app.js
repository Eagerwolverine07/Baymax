// ── WebSocket ────────────────────────────────────────────────────────────────────────────────
let ws, audioCtx, audioQueue = [], isPlaying = false;

function connect() {
  ws = new WebSocket(`ws://${location.host}/ws`);
  ws.binaryType = "arraybuffer";

  ws.onopen = () => setStatus("online");
  ws.onclose = () => { setStatus("offline"); setTimeout(connect, 3000); };

  ws.onmessage = async (e) => {
    if (typeof e.data === "string") {
      const msg = JSON.parse(e.data);

      if (msg.type === "wake_word") {
        // "Hey Baymax" detected — start mic automatically
        startListening();
        return;
      }

      if (msg.type === "text") {
        addTranscript("baymax", msg.content);
        setStatus("speaking");
      }
      if (msg.type === "status" && msg.content === "thinking") {
        setStatus("thinking");
      }
    } else {
      // Audio bytes from ElevenLabs TTS
      enqueueAudio(e.data);
    }
  };
}

// ── Audio queue ─────────────────────────────────────────────────────────────────────────────────
function getAudioCtx() {
  if (!audioCtx || audioCtx.state === "closed") {
    audioCtx = new AudioContext();
  }
  if (audioCtx.state === "suspended") audioCtx.resume();
  return audioCtx;
}

function enqueueAudio(buffer) {
  audioQueue.push(buffer);
  if (!isPlaying) playNext();
}

async function playNext() {
  if (!audioQueue.length) { isPlaying = false; setStatus("online"); return; }
  isPlaying = true;
  const ctx = getAudioCtx();
  try {
    const decoded = await ctx.decodeAudioData(audioQueue.shift());
    const src = ctx.createBufferSource();
    src.buffer = decoded;
    src.connect(ctx.destination);
    src.onended = playNext;
    src.start();
  } catch {
    playNext();
  }
}

// ── Speech recognition ────────────────────────────────────────────────────────────────────────────
let recognition, isListening = false;

function startListening() {
  if (isListening) return;
  if (!("webkitSpeechRecognition" in window || "SpeechRecognition" in window)) {
    alert("Your browser doesn't support speech recognition. Use Chrome.");
    return;
  }

  // Stop any playing audio so Baymax stops talking when you speak
  if (audioCtx) { audioCtx.close(); audioCtx = null; }
  audioQueue = []; isPlaying = false;

  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  recognition = new SR();
  recognition.lang = "en-US";
  recognition.interimResults = false;
  recognition.maxAlternatives = 1;

  recognition.onstart = () => { isListening = true; setStatus("listening"); };
  recognition.onend   = () => { isListening = false; setStatus("online"); };
  recognition.onerror = () => { isListening = false; setStatus("online"); };

  recognition.onresult = (e) => {
    const text = e.results[0][0].transcript.trim();
    if (text) {
      addTranscript("you", text);
      sendMessage(text);
    }
  };

  recognition.start();
}

function stopListening() {
  if (recognition && isListening) recognition.stop();
}

// ── Send message ────────────────────────────────────────────────────────────────────────────────────
function sendMessage(text) {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  ws.send(JSON.stringify({ type: "user_message", content: text }));
  setStatus("thinking");
}

// ── UI helpers ────────────────────────────────────────────────────────────────────────────────────────
function setStatus(state) {
  const badge = document.getElementById("status");
  const labels = { online: "online", listening: "listening…", thinking: "thinking…", speaking: "speaking", offline: "offline" };
  badge.textContent = labels[state] || state;
  badge.className = `status ${state}`;
}

function addTranscript(speaker, text) {
  const div = document.getElementById("transcript");
  const p = document.createElement("p");
  p.className = speaker === "you" ? "user-msg" : "baymax-msg";
  p.textContent = `${speaker === "you" ? "You" : "Baymax"}: ${text}`;
  div.appendChild(p);
  div.scrollTop = div.scrollHeight;
}

// ── Mic button ────────────────────────────────────────────────────────────────────────────────────
const micBtn = document.getElementById("micBtn");
micBtn.addEventListener("mousedown", startListening);
micBtn.addEventListener("mouseup",   stopListening);
micBtn.addEventListener("touchstart", (e) => { e.preventDefault(); startListening(); });
micBtn.addEventListener("touchend",   (e) => { e.preventDefault(); stopListening(); });

// ── Spacebar shortcut ──────────────────────────────────────────────────────────────────────────────────
document.addEventListener("keydown", (e) => {
  if (e.code === "Space" && e.target.tagName !== "INPUT") {
    e.preventDefault();
    startListening();
  }
});
document.addEventListener("keyup", (e) => {
  if (e.code === "Space" && e.target.tagName !== "INPUT") stopListening();
});

// ── Text input fallback ───────────────────────────────────────────────────────────────────────────────────
const textInput = document.getElementById("textInput");
textInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && textInput.value.trim()) {
    const text = textInput.value.trim();
    textInput.value = "";
    addTranscript("you", text);
    sendMessage(text);
  }
});

// ── Boot ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
connect();
