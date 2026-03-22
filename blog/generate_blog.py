"""
VoiceStax Blog Generator
Reads the VoiceStax project and generates a detailed Medium blog post.
"""

import os
import re
import sys
import json
from pathlib import Path


def read_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def extract_readme_features(readme: str) -> dict:
    """Parse README to extract structured info."""
    features = []
    in_features = False
    lines = readme.split("\n")
    for line in lines:
        if "## Features" in line:
            in_features = True
            continue
        if in_features and line.startswith("##"):
            break
        if in_features and line.strip().startswith("- "):
            features.append(line.strip()[2:])
    return features


def extract_architecture(readme: str) -> str:
    """Extract architecture section."""
    match = re.search(r"## Architecture(.*?)(?=##|$)", readme, re.DOTALL)
    return match.group(1).strip() if match else ""


def extract_pipeline_flow(readme: str) -> str:
    """Extract pipeline flow."""
    match = re.search(r"### Pipeline flow(.*?)(?=###|##|$)", readme, re.DOTALL)
    return match.group(1).strip() if match else ""


def extract_quickstart(readme: str) -> str:
    """Extract quick start code block."""
    match = re.search(r"```python(.*?)```", readme, re.DOTALL)
    return match.group(1).strip() if match else ""


def extract_websocket_protocol(readme: str) -> str:
    """Extract WebSocket protocol section."""
    match = re.search(r"## WebSocket Protocol(.*?)(?=##|$)", readme, re.DOTALL)
    return match.group(1).strip() if match else ""


def extract_folder_structure(readme: str) -> str:
    """Extract folder structure."""
    match = re.search(r"## Folder Structure(.*?)(?=##|$)", readme, re.DOTALL)
    return match.group(1).strip() if match else ""


def read_core_files(base: Path) -> dict:
    """Read all core module files."""
    files = {}
    core_dir = base / "voicestax" / "core"
    if core_dir.exists():
        for f in core_dir.glob("*.py"):
            if f.name != "__init__.py":
                files[f.stem] = read_file(f)
    return files


def read_providers(base: Path) -> dict:
    """Read provider implementations."""
    providers = {}
    prov_dir = base / "voicestax" / "providers"
    if prov_dir.exists():
        for sub_dir in prov_dir.iterdir():
            if sub_dir.is_dir() and not sub_dir.name.startswith("_"):
                impl_file = sub_dir / f"{sub_dir.name}.py"
                if impl_file.exists():
                    providers[sub_dir.name] = read_file(impl_file)
    return providers


def extract_code_snippets(core_files: dict) -> dict:
    """Extract meaningful code snippets from core files."""
    snippets = {}
    for name, content in core_files.items():
        # Find class definitions
        classes = re.findall(r"(class \w+.*?(?=\nclass |\Z))", content, re.DOTALL)
        if classes:
            snippets[name] = "\n\n".join(c[:500] for c in classes)
    return snippets


def generate_blog(project_path: str, title_override: str = None) -> str:
    base = Path(project_path)
    readme = read_file(base / "README.md")
    pyproject = read_file(base / "pyproject.toml")

    if not readme:
        raise ValueError("README.md not found. Are you sure this is VoiceStax?")

    # Project metadata
    project_name = "VoiceStax"
    pypi_name = "voice-stax"
    github = "sunithalv/voice-stax"
    tagline = "A modular Python library for building real-time voice-enabled conversational AI applications"

    title = title_override or f"Building a Real-Time Voice AI Pipeline with {project_name}"

    # Extract sections
    features = extract_readme_features(readme)
    arch = extract_architecture(readme)
    pipeline = extract_pipeline_flow(readme)
    quickstart = extract_quickstart(readme)
    ws_protocol = extract_websocket_protocol(readme)
    folder = extract_folder_structure(readme)

    # Core files for deep dive
    core_files = read_core_files(base)
    providers = read_providers(base)
    snippets = extract_code_snippets(core_files)

    # Extract dependencies from pyproject
    deps_match = re.search(r'dependencies = \[(.*?)\]', pyproject, re.DOTALL)
    deps = []
    if deps_match:
        deps = [d.strip().strip('"').strip("'") for d in deps_match.group(1).split(",") if d.strip()]

    blog = f"""---
title: {title}
subtitle: {tagline}
tags: #python #voice-ai #pypi #open-source #real-time #websockets #fastapi
canonicalUrl: https://github.com/{github}
---

# {title}

*Building a production-ready voice AI pipeline shouldn't require a PhD in audio engineering.*

When I started building voice-enabled applications, I kept hitting the same wall: stitching together STT, LLM, and TTS providers meant writing throwaway glue code every single time. Each provider had its own quirks, its own streaming semantics, its own way of handling interruptions. I wanted something clean, modular, and actually fun to use.

That's why I built **{project_name}** — a Python library that gives you a complete real-time voice pipeline in a few lines of code.

---

## What is {project_name}?

{tagline}.

At its core, {project_name} orchestrates three services in a continuous loop:

- **Speech-to-Text (STT)** — AssemblyAI for real-time transcription
- **Large Language Model (LLM)** — Groq for fast inference
- **Text-to-Speech (TTS)** — ElevenLabs for natural voice output

The magic isn't just connecting these providers — it's handling the hard parts automatically: **barge-in** (interrupting the AI mid-sentence), **session state management**, **streaming audio over WebSockets**, and **conversation context**.

---

## Features

"""

    for feat in features:
        # Clean up any existing bold markers in feature text
        feat_clean = re.sub(r'\*\*(.*?)\*\*', r'\1', feat)
        blog += f"- **{feat_clean}**\n"

    blog += f"""

## Architecture

{project_name} follows a clean layered architecture:

```
voicestax/
├── api/              # FastAPI + WebSocket endpoint
├── core/             # Voice pipeline orchestration
│   ├── voice_agent   # Main pipeline (STT → LLM → TTS)
│   ├── audio_manager # TTS streaming + word timing
│   ├── chat_engine   # LLM conversation + history
│   └── timing        # Word-level audio sync
├── providers/        # Pluggable provider interfaces
│   ├── stt/          # AssemblyAI
│   ├── llm/          # Groq
│   └── tts/          # ElevenLabs
├── session/          # Session state + barge-in
└── utils/            # Logging, exceptions, helpers
```

The design principle is simple: **providers are interfaces, not implementations**. If you want to swap AssemblyAI for Deepgram, or Groq for OpenAI, you only need to implement the provider interface — the rest of the pipeline stays untouched.

### Pipeline Flow

The real-time pipeline runs in a tight loop:

1. **Client connects** to `/ws/chat` via WebSocket
2. **Server sends `system_ready`** — providers initialized
3. **Client sends `{{"type": "start"}}`** — session begins
4. **AI greets first** (if configured) — TTS streams greeting audio
5. **STT starts listening** — server sends `listening_ready`
6. **Client streams PCM audio** — real-time transcription
7. **STT fires `transcription`** — final user transcript received
8. **LLM generates response** — streamed token-by-token
9. **TTS streams audio chunks** — client plays in real-time
10. **User can interrupt anytime** — barge-in cancels TTS instantly

---

## Getting Started

### Installation

```bash
pip install {pypi_name}
```

You'll also need API keys for AssemblyAI, Groq, and ElevenLabs.

### Create a `.env` file

```env
STT_API_KEY=your_assemblyai_api_key
LLM_API_KEY=your_groq_api_key
TTS_API_KEY=your_elevenlabs_api_key
TTS_VOICE_ID=your_preferred_voice_id
```

### Run your voice app

```python
from voicestax import create_voice_app, VoiceSettings
import uvicorn

settings = VoiceSettings(
    llm_system_prompt="You are a helpful AI assistant.",
    first_speaker="assistant",
    initial_message="Hello! How can I help you today?",
)

app = create_voice_app(settings=settings)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

Navigate to `http://localhost:8000` and you'll see a built-in HTML chatbot interface ready to go. No frontend code needed.

---

## Deep Dive: How the Pipeline Works

### VoiceAgent — The Orchestrator

The heart of {project_name} is `VoiceAgent`. It coordinates the full STT → LLM → TTS pipeline and handles barge-in correctly:

```python
async def handle_user_message(self, text: str, websocket: WebSocket):
    # 1. Cancel any in-flight TTS (barge-in)
    interrupted = self.barge_manager.handle_user_input(text)
    if not interrupted and self.session.was_interrupted:
        await self._cancel_tts(websocket)

    # 2. Get LLM response (locked to prevent concurrent calls)
    async with self.session.processing_lock:
        raw_result = await self.chat_engine.get_intent_and_response(
            user_text=text,
            session=self.session,
        )
        intent = validated.intent
        response = validated.response

    # 3. Stream TTS — runs OUTSIDE the lock so barge-in can cancel without deadlock
    await self._stream_and_track(websocket, response)
```

Notice that TTS runs *outside* the processing lock. This is intentional — it means a barge-in can cancel TTS immediately without waiting to acquire any lock. It's a small detail that makes interruption feel instant.

### ChatEngine — Conversation with Memory

ChatEngine manages conversation history and streams LLM responses token-by-token:

```python
class ChatEngine:
    def __init__(self, llm_client, max_history: int = 12):
        self.llm_client = llm_client
        self.conversation_history: List[Dict] = []
        self.max_history = max_history

    async def get_intent_and_response(self, user_text: str, session):
        self.conversation_history.append({{"role": "user", "content": user_text}})
        self.conversation_history = self.conversation_history[-self.max_history:]
        
        messages = [{{"role": "system", "content": session.system_prompt}}] + self.conversation_history
        
        full_response = ""
        for chunk in self.llm_client.stream_chat(messages=messages):
            if session.cancel_event.is_set():
                break  # Barge-in — stop streaming
            full_response += chunk.choices[0].delta.content
        
        parsed = json.loads(full_response)
        self.conversation_history.append({{"role": "assistant", "content": parsed["response"]}})
        return parsed
```

The LLM is expected to return JSON with an `intent` and `response` field — a simple but effective way to let the model decide when to end a session.

### AudioManager — Streaming TTS with Word Sync

AudioManager streams TTS audio chunks to the client and sends word-level timing events so the frontend can highlight words as they're spoken:

```python
async def stream_text(self, websocket, text: str, session):
    response_id = session.current_response_id
    session.is_speaking = True

    # Stream chunks as they're generated
    for chunk in self.tts_client.stream_tts(text=text):
        if self._is_cancelled(session, response_id):
            return  # Barge-in
        encoded_audio = base64.b64encode(chunk).decode()
        await websocket.send_json({{
            "type": "audio_chunk",
            "audio": encoded_audio,
            "response_id": response_id,
        }})

    # After streaming, send word timing for UI sync
    delay_per_word_ms = timing.calculate_word_delays(combined_audio, text=text)
    for i, word in enumerate(text.split()):
        if self._is_cancelled(session, response_id):
            return
        await websocket.send_json({{"type": "word", "word": word, "index": i}})
        await asyncio.sleep(delay_per_word_ms / 1000)
```

The word timing calculation uses the generated audio itself to determine how long each word is spoken — so the UI highlights are perfectly synced with the actual audio.

### SessionData — State Machine

SessionData is a rich state container for each WebSocket session:

```python
class SessionData:
    def __init__(self):
        self.session_id: str = str(uuid.uuid4())
        self.state: str = "idle"  # idle → listening → processing → speaking
        self.is_speaking: bool = False
        self.processing_lock: asyncio.Lock = asyncio.Lock()
        self.cancel_event: asyncio.Event = asyncio.Event()
        self.current_response_id: int = 0  # Barge-in invalidates old responses
        self.latency_metrics: dict = {{}}
```

The `current_response_id` is clever — every time barge-in fires, it's incremented. Any TTS chunk or word event with a stale response ID is ignored by the frontend. This means you don't need to cancel anything complex; just bump a number.

---

## WebSocket Protocol

The protocol is clean and minimal. All messages are JSON except binary audio frames.

### Client → Server

| Message | Description |
|---------|-------------|
| `{{"type": "start"}}` | Begin session; triggers greeting + STT |
| `{{"type": "stop"}}` | End session |
| `{{"type": "audio", "data": "<base64>"}}` | Send PCM audio |
| `{{"type": "interrupt"}}` | Barge-in; cancel current TTS |
| Binary frame | Raw PCM bytes (preferred over base64) |

### Server → Client

| Message | Description |
|---------|-------------|
| `{{"type": "system_ready"}}` | Providers initialized |
| `{{"type": "listening_ready"}}` | STT is active |
| `{{"type": "transcription", "text": "..."}}` | User speech transcribed |
| `{{"type": "audio_chunk", "audio": "<base64>"}}` | TTS audio chunk |
| `{{"type": "word", "word": "...", "index": 0}}` | Word spoken (for UI sync) |
| `{{"type": "complete"}}` | Utterance finished |
| `{{"type": "stop_audio"}}` | Barge-in — stop playback |
| `{{"type": "session_ended"}}` | Session ended |

---

## The Tech Stack

{project_name} is built on:

- **FastAPI** — async HTTP + WebSocket server
- **AssemblyAI** — real-time speech-to-text
- **Groq** — fast LLM inference with streaming
- **ElevenLabs** — natural text-to-speech
- **PyAudio** — microphone capture
- **Pydantic** — settings management
- **Uvicorn** — ASGI server

All providers are abstracted behind clean interfaces:

```python
class BaseLLMProvider(ABC):
    @abstractmethod
    def stream_chat(self, messages: List[Dict]) -> Iterator: ...

class BaseSTTProvider(ABC):
    @abstractmethod
    def stream_from_websocket(self, websocket: WebSocket, session: SessionData): ...

class BaseTTSProvider(ABC):
    @abstractmethod
    def stream_tts(self, text: str) -> Iterator[bytes]: ...
```

Adding a new provider means implementing these three interfaces. The rest of the codebase doesn't change.

---

## What's Next

{pypi_name} is production-ready for simple use cases, but there's more to come:

- [ ] More STT providers (Deepgram, Whisper)
- [ ] More LLM providers (OpenAI, Anthropic)
- [ ] More TTS providers (AWS Polly, Google TTS)
- [ ] Audio河道 recording and playback
- [ ] Multi-turn conversation improvements
- [ ] Python package on PyPI

Check out the [GitHub repo](https://github.com/{github}) for the full source, issues, and contributions. PRs welcome!

---

## Try It Out

```bash
pip install {pypi_name}
```

Set up your `.env` with three API keys, copy the three-line app, run it, and talk to your AI. It's that simple.

If you run into issues or want to discuss the architecture, feel free to open an issue on GitHub. I'd love to hear what you build with it.

*Thanks for reading!*
"""

    return blog


def main():
    if len(sys.argv) < 2:
        print("Usage: python generate_blog.py <project_path> [--title 'Custom Title']")
        sys.exit(1)

    project_path = sys.argv[1]
    title_override = None

    if "--title" in sys.argv:
        idx = sys.argv.index("--title")
        title_override = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else None

    output_dir = Path(project_path) / "blog"
    output_dir.mkdir(exist_ok=True)

    print(f"Reading project at: {project_path}")
    blog_content = generate_blog(project_path, title_override)

    output_path = output_dir / "output.md"
    output_path.write_text(blog_content, encoding="utf-8")

    print(f"Blog generated: {output_path}")
    print(f"Word count: {len(blog_content.split())}")
    print(f"Character count: {len(blog_content)}")


if __name__ == "__main__":
    main()
