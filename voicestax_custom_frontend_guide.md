# VoiceStax — Custom Frontend Developer Guide

> This guide is for developers who want to build their own HTML/JS frontend  
> instead of using the provided `chatbot.html` sample.  
> You only need a WebSocket connection and basic audio handling — no framework required.

---

## Table of Contents

1. [How VoiceStax Works](#1-how-voicestax-works)
2. [WebSocket Connection](#2-websocket-connection)
3. [Audio Requirements](#3-audio-requirements)
4. [Client → Server Messages](#4-client--server-messages)
5. [Server → Client Messages](#5-server--client-messages)
6. [Full Session Flow](#6-full-session-flow)
7. [Minimal Implementation Skeleton](#7-minimal-implementation-skeleton)
8. [VAD — Voice Activity Detection](#8-vad--voice-activity-detection)
9. [Word Sync (Optional)](#9-word-sync-optional)
10. [Critical Rules](#10-critical-rules)
11. [Reference — chatbot.html Sample](#11-reference--chathtmlsample)

---

## 1. How VoiceStax Works

VoiceStax runs as a **FastAPI server**. Your frontend connects to it over a **WebSocket**.  
Once connected, the conversation flows like this:

```
Your UI  ──────────────────────────────────  VoiceStax Server
  |                                                |
  |  WebSocket connect                             |
  |  ─────────────────────────────────────────▶   |
  |                                                |
  |           system_ready                         |
  |  ◀─────────────────────────────────────────   |
  |                                                |
  |  { type: "start" }                             |
  |  ─────────────────────────────────────────▶   |
  |                                                |
  |           greeting audio + words               |
  |  ◀─────────────────────────────────────────   |
  |                                                |
  |           listening_ready                      |
  |  ◀─────────────────────────────────────────   |
  |                                                |
  |  PCM binary (mic audio, continuous)            |
  |  ─────────────────────────────────────────▶   |
  |                                                |
  |           transcription, words, audio          |
  |  ◀─────────────────────────────────────────   |
  |                                                |
  |  [conversation loop repeats]                   |
  |                                                |
  |  { type: "stop" }                              |
  |  ─────────────────────────────────────────▶   |
  |                                                |
  |           session_ended                        |
  |  ◀─────────────────────────────────────────   |
```

---

## 2. WebSocket Connection

Connect to:

```
ws://your-host:8000/ws/chat
```

Or for HTTPS deployments:

```
wss://your-host/ws/chat
```

Auto-detect in JavaScript:

```javascript
const WS_URL = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/chat`;
const ws = new WebSocket(WS_URL);
```

> **Always reconnect on close.** The server may restart or drop idle connections.

```javascript
ws.onclose = () => {
    setTimeout(connect, 2000);  // reconnect after 2 seconds
};
```

---

## 3. Audio Requirements

VoiceStax has strict audio format requirements on both input and output.

### Microphone Input (Client → Server)

| Property | Value |
|---|---|
| Format | Raw binary (ArrayBuffer) |
| Encoding | Int16 PCM (Little Endian) |
| Sample Rate | **16000 Hz** |
| Channels | Mono (1 channel) |

Send raw binary frames (not JSON) directly over the WebSocket:

```javascript
ws.send(floatTo16BitPCM(e.inputBuffer.getChannelData(0)));
```

PCM conversion helper:

```javascript
function floatTo16BitPCM(float32) {
    const buf = new ArrayBuffer(float32.length * 2);
    const view = new DataView(buf);
    for (let i = 0, off = 0; i < float32.length; i++, off += 2) {
        const s = Math.max(-1, Math.min(1, float32[i]));
        view.setInt16(off, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
    }
    return buf;
}
```

### Audio Output (Server → Client)

| Property | Value |
|---|---|
| Format | Base64-encoded string (in JSON message) |
| Encoding | MP3 (`audio/mpeg`) |
| Delivery | Multiple `audio_chunk` messages, then a `complete` signal |

Collect all chunks, merge, then play as a Blob:

```javascript
const blob = new Blob([mergedBytes], { type: "audio/mpeg" });
const audio = new Audio(URL.createObjectURL(blob));
audio.play();
```

---

## 4. Client → Server Messages

All messages are JSON strings sent via `ws.send(JSON.stringify({...}))`,  
**except PCM audio which is sent as raw binary.**

| Type | When to Send | Payload |
|---|---|---|
| `start` | User initiates conversation | `{ "type": "start" }` |
| `stop` | User ends conversation | `{ "type": "stop" }` |
| `interrupt` | User speaks while AI is speaking | `{ "type": "interrupt" }` |
| *(binary)* | While mic is active | Raw Int16 PCM ArrayBuffer |

### Example

```javascript
// Start session
ws.send(JSON.stringify({ type: "start" }));

// Stop session
ws.send(JSON.stringify({ type: "stop" }));

// Interrupt AI while it is speaking
ws.send(JSON.stringify({ type: "interrupt" }));

// Send mic audio (binary — NOT JSON)
ws.send(floatTo16BitPCM(audioData));
```

---

## 5. Server → Client Messages

All messages from the server are JSON. Parse with `JSON.parse(event.data)`.

### Session Lifecycle Messages

| `type` | When It Fires | What To Do |
|---|---|---|
| `system_ready` | Server is fully initialized | Enable your Start button |
| `greeting_started` | AI is about to deliver opening message | Stop mic, prepare to receive audio |
| `greeting_done` | All greeting audio received | Play buffered audio |
| `listening_ready` | STT engine is ready | Start mic, begin sending PCM |
| `session_ended` | Server ended the session | Stop mic, reset UI |

### Conversation Messages

| `type` | Key Fields | What To Do |
|---|---|---|
| `transcription` | `text` | Display user's speech as text |
| `word` | `word`, `index` | Append word to AI bubble (optional, for animation) |
| `audio_chunk` | `audio` (base64), `encoding` | Buffer the chunk |
| `complete` | — | Play all buffered audio chunks |

### Control Messages

| `type` | What To Do |
|---|---|
| `stop_audio` | Stop playback immediately, clear buffer |
| `clear_audio` | Discard buffered chunks without playing |
| `error` | `message` field — display error to user |

---

## 6. Full Session Flow

Understanding the exact sequence prevents timing bugs.

```
1.  WebSocket connects
2.  Server sends:        system_ready
3.  User clicks Start
4.  Client sends:        { type: "start" }
5.  Server sends:        greeting_started        ← stop mic here
6.  Server sends:        word  (×N)              ← optional display
7.  Server sends:        audio_chunk  (×N)       ← buffer these
8.  Server sends:        greeting_done           ← play buffered audio now
9.  Server sends:        listening_ready         ← start mic here
10. Client sends:        PCM binary (continuous)
11. Server sends:        transcription           ← show user text
12. Server sends:        word  (×N)              ← optional AI text display
13. Server sends:        audio_chunk  (×N)       ← buffer these
14. Server sends:        complete                ← play buffered audio now
    [steps 10–14 repeat for each turn]
15. User clicks Stop
16. Client sends:        { type: "stop" }
17. Server sends:        session_ended           ← stop mic, reset UI
```

### Interrupt Flow

```
[AI is speaking — isAiSpeaking = true]
User speaks → VAD detects voice
Client sends:   { type: "interrupt" }
Client also:    stops local audio immediately
Server sends:   stop_audio                      ← confirms stop
Server sends:   listening_ready                 ← resume mic
```

---

## 7. Minimal Implementation Skeleton

This is the complete minimum needed to build any custom UI.  
Replace the placeholder UI functions with your own implementation.

```javascript
const WS_URL = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/chat`;

let ws;
let audioChunks  = [];
let isAiSpeaking = false;
let currentAudio = null;
let micStream    = null;
let processor    = null;
let micContext   = null;

// ── 1. Connect ───────────────────────────────────────────────────────────────
function connect() {
    ws = new WebSocket(WS_URL);

    ws.onopen = () => {
        console.log("WebSocket connected");
    };

    ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        handleMessage(msg);
    };

    ws.onclose = () => {
        console.log("WebSocket closed — reconnecting in 2s");
        stopMic();
        setTimeout(connect, 2000);
    };
}

// ── 2. Message Handler ───────────────────────────────────────────────────────
function handleMessage(msg) {
    switch (msg.type) {

        // --- Session lifecycle ---
        case "system_ready":
            // Enable your Start button here
            onReady();
            break;

        case "greeting_started":
            isAiSpeaking = true;
            audioChunks  = [];
            stopMic();                          // don't send audio during greeting
            onGreetingStarted();
            break;

        case "greeting_done":
            playBufferedAudio();                // play collected greeting audio
            break;

        case "listening_ready":
            startMic();                         // start sending PCM
            onListening();
            break;

        case "session_ended":
            stopMic();
            isAiSpeaking = false;
            onSessionEnded();
            break;

        // --- Conversation ---
        case "transcription":
            onTranscription(msg.text);          // show user's words
            break;

        case "word":
            onWord(msg.word, msg.index);        // optional: animate AI text
            break;

        case "audio_chunk":
            audioChunks.push(msg.audio);        // buffer base64 chunks
            break;

        case "complete":
            playBufferedAudio();                // play full AI response
            break;

        // --- Control ---
        case "stop_audio":
            stopPlayback();
            isAiSpeaking = false;
            break;

        case "clear_audio":
            audioChunks = [];
            break;

        case "error":
            onError(msg.message);
            break;
    }
}

// ── 3. Microphone ────────────────────────────────────────────────────────────
async function startMic() {
    if (micStream) return;                      // already running

    micContext = new AudioContext({ sampleRate: 16000 });   // must be 16000
    micStream  = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true }
    });

    const source = micContext.createMediaStreamSource(micStream);
    processor    = micContext.createScriptProcessor(2048, 1, 1);

    source.connect(processor);
    processor.connect(micContext.destination);

    processor.onaudioprocess = (e) => {
        if (ws.readyState !== WebSocket.OPEN) return;
        ws.send(floatTo16BitPCM(e.inputBuffer.getChannelData(0)));
    };
}

function stopMic() {
    if (processor)  { processor.disconnect(); processor = null; }
    if (micStream)  { micStream.getTracks().forEach(t => t.stop()); micStream = null; }
    if (micContext) { micContext.close(); micContext = null; }
}

function floatTo16BitPCM(float32) {
    const buf  = new ArrayBuffer(float32.length * 2);
    const view = new DataView(buf);
    for (let i = 0, off = 0; i < float32.length; i++, off += 2) {
        const s = Math.max(-1, Math.min(1, float32[i]));
        view.setInt16(off, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
    }
    return buf;
}

// ── 4. Audio Playback ────────────────────────────────────────────────────────
function playBufferedAudio() {
    if (!audioChunks.length) return;

    // Decode all base64 chunks and merge into one Uint8Array
    const byteArrays = audioChunks.map(b64 => {
        const bin   = atob(b64);
        const bytes = new Uint8Array(bin.length);
        for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
        return bytes;
    });

    const total  = byteArrays.reduce((s, a) => s + a.length, 0);
    const merged = new Uint8Array(total);
    let   offset = 0;
    for (const arr of byteArrays) { merged.set(arr, offset); offset += arr.length; }

    // Play as blob
    const blob = new Blob([merged], { type: "audio/mpeg" });
    const url  = URL.createObjectURL(blob);

    stopPlayback();                             // stop any previous audio

    currentAudio         = new Audio(url);
    currentAudio.onended = () => {
        isAiSpeaking = false;
        URL.revokeObjectURL(url);
        currentAudio = null;
    };
    currentAudio.play();
    audioChunks = [];
}

function stopPlayback() {
    if (currentAudio) {
        currentAudio.pause();
        try { URL.revokeObjectURL(currentAudio.src); } catch (_) {}
        currentAudio = null;
    }
    audioChunks  = [];
    isAiSpeaking = false;
}

// ── 5. Session Controls ──────────────────────────────────────────────────────
function startSession() {
    ws.send(JSON.stringify({ type: "start" }));
}

function stopSession() {
    ws.send(JSON.stringify({ type: "stop" }));
    stopMic();
    stopPlayback();
}

function interruptAI() {
    if (!isAiSpeaking) return;
    ws.send(JSON.stringify({ type: "interrupt" }));
    stopPlayback();                             // stop local audio immediately
}

// ── 6. Your UI Callbacks (replace with your own logic) ───────────────────────
function onReady()                  { console.log("Ready"); }
function onGreetingStarted()        { console.log("AI greeting..."); }
function onListening()              { console.log("Listening..."); }
function onSessionEnded()           { console.log("Session ended"); }
function onTranscription(text)      { console.log("User said:", text); }
function onWord(word, index)        { /* optional word-by-word display */ }
function onError(message)           { console.error("Error:", message); }

// ── Start ────────────────────────────────────────────────────────────────────
window.onload = connect;
```

---

## 8. VAD — Voice Activity Detection

VAD detects when the user starts speaking while the AI is talking, and fires an interrupt.  
It is **optional but strongly recommended** for a natural conversation feel.

```javascript
const VAD_THRESHOLD   = 0.015;    // mic sensitivity — increase for noisy environments
const VAD_COOLDOWN_MS = 400;      // min ms between interrupts

let analyser       = null;
let vadHandle      = null;
let lastInterrupt  = 0;

function startVAD(micContext, micSource) {
    analyser = micContext.createAnalyser();
    analyser.fftSize               = 512;
    analyser.smoothingTimeConstant = 0.3;
    micSource.connect(analyser);

    const buf = new Float32Array(analyser.fftSize);

    function tick() {
        analyser.getFloatTimeDomainData(buf);
        let sum = 0;
        for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i];
        const rms = Math.sqrt(sum / buf.length);

        if (isAiSpeaking && rms > VAD_THRESHOLD) {
            const now = Date.now();
            if (now - lastInterrupt > VAD_COOLDOWN_MS) {
                lastInterrupt = now;
                interruptAI();
            }
        }
        vadHandle = requestAnimationFrame(tick);
    }
    vadHandle = requestAnimationFrame(tick);
}

function stopVAD() {
    if (vadHandle !== null) { cancelAnimationFrame(vadHandle); vadHandle = null; }
}
```

Attach VAD inside `startMic()` after creating the source:

```javascript
const source = micContext.createMediaStreamSource(micStream);
startVAD(micContext, source);       // ← add this line
```

---

## 9. Word Sync (Optional)

The server sends individual `word` messages alongside audio chunks.  
You can use these to animate text appearing in sync with the AI's speech.

```javascript
let pendingWords  = [];
let shownWords    = 0;
let syncHandle    = null;

// Called on each "word" message
function onWord(word, index) {
    pendingWords.push({ word, index });
}

// Call this when audio starts playing
function startWordSync(audioElement) {
    function tick() {
        if (!audioElement || audioElement.paused || audioElement.ended) return;

        const progress    = audioElement.currentTime / audioElement.duration;
        const totalWords  = pendingWords.length + shownWords;
        const targetShown = Math.ceil(progress * totalWords);

        while (shownWords < targetShown && pendingWords.length > 0) {
            const { word } = pendingWords.shift();
            appendWordToUI(word);                   // your UI function
            shownWords++;
        }
        syncHandle = requestAnimationFrame(tick);
    }
    syncHandle = requestAnimationFrame(tick);
}

function stopWordSync() {
    if (syncHandle !== null) { cancelAnimationFrame(syncHandle); syncHandle = null; }
    // Flush any remaining words
    while (pendingWords.length > 0) {
        appendWordToUI(pendingWords.shift().word);
    }
}
```

Attach to `currentAudio` in `playBufferedAudio()`:

```javascript
currentAudio.addEventListener("canplay", () => startWordSync(currentAudio), { once: true });
currentAudio.onended = () => {
    stopWordSync();
    // ... rest of onended
};
```

---

## 10. Critical Rules

These are non-negotiable — violating them causes silent failures or broken audio.

```
✅  Mic audio MUST be Int16 PCM at exactly 16000 Hz, mono
✅  Never send PCM before listening_ready — wait for the signal
✅  Always buffer audio_chunk messages and play on complete or greeting_done
✅  Always reconnect on ws.onclose — use setTimeout(connect, 2000)
✅  Stop local audio immediately on interrupt — don't wait for server confirmation
✅  word messages are optional — safe to ignore if you don't need text animation
❌  Do NOT modify the message type names — they are part of the VoiceStax protocol
❌  Do NOT send JSON for audio — PCM must be raw binary ArrayBuffer
❌  Do NOT start the mic before listening_ready
```

---

## 11. Reference — chatbot.html Sample

The file `examples/html/chatbot.html` shipped with VoiceStax is a fully working  
reference implementation. Use it to understand how everything fits together.

It demonstrates:

- Full WebSocket lifecycle management with auto-reconnect
- Mic capture using `ScriptProcessorNode` with PCM conversion
- Audio buffering and Blob playback
- VAD-based interrupt detection
- Word-by-word text sync with `requestAnimationFrame`
- Responsive dark UI with CSS variables for easy re-theming
- Session state management (`isAiSpeaking`, `interruptSent`, `sessionEnded`)

### File Location

```
your-project/
└── examples/
    └── html/
        └── chatbot.html     ← reference implementation
```

### Key Sections to Study

| Lines | What It Shows |
|---|---|
| `floatTo16BitPCM()` | PCM conversion from Float32 mic data |
| `startMic()` | Mic setup with `AudioContext` at 16000 Hz |
| `startVAD()` | Voice activity detection loop |
| `playBufferedAudio()` | Merging base64 chunks into a Blob |
| `ws.onmessage` | Complete message type handler |
| `startWordSync()` | `requestAnimationFrame` word-timing loop |
| `:root { }` CSS block | All theme colors in one place |

> **Note:** `chatbot.html` uses `ScriptProcessorNode` which is deprecated but  
> has the widest browser support. For modern browsers you can replace it  
> with `AudioWorkletNode` for better performance.

---


