const transcript = document.getElementById('transcript');
const statusEl   = document.getElementById('status');
const micBtn     = document.getElementById('micBtn');
const micLabel   = document.getElementById('micLabel');
const textInput  = document.getElementById('textInput');
const hint       = document.getElementById('hint');

let ws = null, recognition = null, isListening = false;
let audioQueue = [], playingAudio = false;

function connect() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.binaryType = 'arraybuffer';
  ws.onopen = () => { setStatus('online'); hint.textContent = 'Click the mic and speak, or type below'; };
  ws.onmessage = (event) => {
    if (typeof event.data === 'string') {
      const msg = JSON.parse(event.data);
      if (msg.type === 'text') { addMessage('assistant', msg.content); setStatus('speaking'); }
      else if (msg.type === 'tts_error') { setStatus('online'); }
    } else { enqueueAudio(event.data); }
  };
  ws.onclose = () => { setStatus('offline'); setTimeout(connect, 3000); };
  ws.onerror = (e) => console.error('WS error', e);
}

function sendMessage(text) {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  ws.send(JSON.stringify({ type: 'user_message', content: text }));
  addMessage('user', text);
  setStatus('thinking');
}

function enqueueAudio(buf) { audioQueue.push(buf); if (!playingAudio) playNext(); }

async function playNext() {
  if (!audioQueue.length) { playingAudio = false; setStatus('online'); return; }
  playingAudio = true;
  const buf = audioQueue.shift();
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const decoded = await ctx.decodeAudioData(buf.slice(0));
    const src = ctx.createBufferSource();
    src.buffer = decoded;
    src.connect(ctx.destination);
    src.onended = playNext;
    src.start(0);
  } catch(e) { console.error(e); playNext(); }
}

function setupRecognition() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) { hint.textContent = 'Use Chrome for voice'; micBtn.disabled = true; return false; }
  recognition = new SR();
  recognition.lang = 'en-US'; recognition.interimResults = true; recognition.continuous = false;
  recognition.onstart = () => { isListening = true; micBtn.classList.add('active'); micLabel.textContent = 'Listening...'; setStatus('listening'); };
  recognition.onresult = (e) => {
    let interim = '', final = '';
    for (let i = e.resultIndex; i < e.results.length; i++) {
      const t = e.results[i][0].transcript;
      if (e.results[i].isFinal) final += t; else interim += t;
    }
    hint.textContent = interim || final || '...';
    if (final) { stopListening(); sendMessage(final.trim()); }
  };
  recognition.onerror = (e) => { stopListening(); hint.textContent = 'Speech error: ' + e.error; };
  recognition.onend = stopListening;
  return true;
}

function startListening() { if (!recognition && !setupRecognition()) return; if (!isListening) try { recognition.start(); } catch(e) {} }
function stopListening() {
  if (!isListening) return;
  isListening = false; micBtn.classList.remove('active'); micLabel.textContent = 'Hold to speak';
  setStatus(playingAudio ? 'speaking' : 'online'); hint.textContent = 'Click the mic and speak, or type below';
  try { recognition && recognition.stop(); } catch(e) {}
}
function toggleMic() { if (isListening) stopListening(); else startListening(); }

function sendText() { const t = textInput.value.trim(); if (!t) return; textInput.value = ''; sendMessage(t); }
textInput.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendText(); } });
document.addEventListener('keydown', (e) => { if (e.code === 'Space' && e.target === document.body && !isListening) { e.preventDefault(); startListening(); } });
document.addEventListener('keyup', (e) => { if (e.code === 'Space' && e.target === document.body && isListening) { e.preventDefault(); stopListening(); } });

function setStatus(s) { statusEl.className = 'status ' + s; statusEl.textContent = s; }
function addMessage(role, text) {
  const div = document.createElement('div'); div.className = `message ${role}`;
  const label = document.createElement('span'); label.className = 'label'; label.textContent = role === 'user' ? 'You' : 'Baymax';
  const p = document.createElement('p'); p.textContent = text;
  div.appendChild(label); div.appendChild(p); transcript.appendChild(div);
  transcript.scrollTop = transcript.scrollHeight;
}

connect();
