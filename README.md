# VoiceStax

A modular Python library for building voice-enabled conversational AI applications. VoiceStax provides a complete real-time voice pipeline — Speech-to-Text (STT), LLM integration, and Text-to-Speech (TTS) — wrapped in a FastAPI server with WebSocket support for live voice conversations.

## Features

- **Modular architecture**: Pluggable STT, LLM, and TTS providers
- **Real-time voice pipeline**: STT → LLM → TTS with barge-in support
- **FastAPI + WebSocket**: Real-time audio streaming over WebSocket
- **Voice Activity Detection (VAD)**: Intelligent speech detection and interruption handling
- **Session management**: Persistent conversation state across turns
- **Provider support**:
  - **STT**: AssemblyAI
  - **LLM**: Groq
  - **TTS**: ElevenLabs

## Requirements

- Python 3.12+
- API keys for AssemblyAI, Groq, and ElevenLabs

## Installation

```bash
pip install voice-stax
```

## Quick Start

**1. Set up environment variables**

Create a `.env` file in your project root:

```env
STT_API_KEY=your_assemblyai_api_key
LLM_API_KEY=your_groq_api_key
TTS_API_KEY=your_elevenlabs_api_key
TTS_VOICE_ID=your_preferred_voice_id
```

**2. Create and run the application**

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

**3. Open the chatbot**

Navigate to `http://localhost:8000` to use the built-in HTML chatbot interface.

> The built-in UI is only served if you mount `chatbot.html` at the root route yourself, as shown in the example `main.py`. The `create_voice_app()` call alone only sets up the WebSocket endpoint at `/ws/chat`.

---

## Configuration

All settings are managed via `VoiceSettings`, a Pydantic model. Values can be passed directly or read from environment variables.

```python
from voicestax import VoiceSettings

settings = VoiceSettings(
    # Provider selection
    stt_provider="assemblyai",
    llm_provider="groq",
    tts_provider="elevenlabs",

    # LLM
    llm_system_prompt="You are a helpful assistant.",
    llm_model="llama-3.3-70b-versatile",
    llm_max_tokens=120,

    # STT
    stt_sample_rate=16000,
    stt_encoding="linear16",

    # TTS
    tts_voice_id="your_voice_id",
    tts_model="eleven_monolingual_v1",
    tts_sample_rate=24000,
    tts_output_format="mp3_22050_32",
    tts_optimize_latency=True,

    # Conversation
    first_speaker="assistant",   # "assistant" or "user"
    initial_message="Hello! How can I help?",

    # VAD
    vad_threshold=0.015,
    vad_cooldown_ms=400,
)
```

### Environment variables

```env
# Required
STT_API_KEY=your_stt_api_key
LLM_API_KEY=your_llm_api_key
TTS_API_KEY=your_tts_api_key

# Optional overrides
TTS_VOICE_ID=your_voice_id
LLM_SYSTEM_PROMPT=Your custom system prompt
```

---

## Architecture

VoiceStax follows a layered architecture with clear separation of concerns.

### Components

- **API layer** — FastAPI application with WebSocket routes for real-time communication
- **Voice agent** — Orchestrates the complete voice pipeline (STT → LLM → TTS)
- **Chat engine** — Manages conversation history and streams LLM responses
- **Audio manager** — Handles TTS audio streaming and encoding
- **Session** — Holds conversation state, barge-in detection, and cancel events
- **Provider layer** — Abstract interfaces for STT, LLM, and TTS with concrete implementations

### Pipeline flow

1. Client connects to `/ws/chat` over WebSocket
2. Server initialises STT, LLM, and TTS providers and sends `system_ready`
3. Client sends `{"type": "start"}` to begin the session
4. If `first_speaker` is `"assistant"`, the greeting is streamed as TTS audio
5. STT provider starts streaming; server sends `listening_ready`
6. Client streams raw PCM audio as binary WebSocket frames
7. STT transcribes speech and fires a transcript callback
8. LLM generates a response, streamed token-by-token into TTS
9. TTS audio chunks are sent back to the client as binary frames
10. The user can interrupt at any time — barge-in cancels TTS and restarts listening

---

## WebSocket Protocol

All messages are JSON unless noted as binary.

### Client → Server

| Message | Description |
|---------|-------------|
| `{"type": "start"}` | Begin the session; triggers greeting and STT start |
| `{"type": "stop"}` | End the session and close the connection |
| `{"type": "audio", "data": "<base64>"}` | Send audio as base64-encoded PCM |
| `{"type": "interrupt"}` | Interrupt current TTS and force STT to end the turn |
| Binary frame | Raw PCM audio bytes (preferred over base64 audio messages) |

### Server → Client

| Message | Description |
|---------|-------------|
| `{"type": "system_ready"}` | Providers initialised successfully |
| `{"type": "greeting_started"}` | Initial greeting TTS is starting |
| `{"type": "greeting_done"}` | Initial greeting TTS has finished |
| `{"type": "listening_ready"}` | STT is active and ready for audio |
| `{"type": "transcription", "text": "..."}` | Final transcript of user speech |
| `{"type": "word", "word": "..."}` | Individual word during TTS playback |
| `{"type": "complete"}` | TTS utterance finished |
| `{"type": "session_ended"}` | Session was ended (e.g. user said goodbye) |
| `{"type": "error", "message": "..."}` | An error occurred |
| Binary frame | Raw TTS audio bytes |

---

## Folder Structure

```
voice-stax/
├── main.py                             # Example entry point
├── pyproject.toml
├── requirements.txt
├── README.md
├── voicestax_custom_frontend_guide.md
├── examples/
│   └── html/
│       └── chatbot.html                # Built-in chatbot UI
├── tests/
└── voicestax/
    ├── __init__.py
    ├── api/
    │   ├── app.py                      # FastAPI app factory
    │   └── websocket_routes.py         # WebSocket endpoint
    ├── config/
    │   └── settings.py                 # VoiceSettings + env loading
    ├── core/
    │   ├── audio_manager.py            # TTS streaming and audio
    │   ├── chat_engine.py              # LLM conversation handling
    │   ├── timing.py                   # Timing utilities
    │   └── voice_agent.py              # Pipeline orchestration
    ├── providers/
    │   ├── llm/
    │   │   ├── base.py                 # BaseLLMProvider interface
    │   │   ├── factory.py
    │   │   └── groq.py
    │   ├── stt/
    │   │   ├── base.py                 # BaseSTTProvider interface
    │   │   ├── factory.py
    │   │   └── assemblyai.py
    │   └── tts/
    │       ├── base.py                 # BaseTTSProvider interface
    │       ├── factory.py
    │       └── elevenlabs.py
    ├── session/
    │   ├── barge_in.py
    │   └── voice_session.py
    └── utils/
        ├── exceptions.py
        ├── logger.py
        └── text_processing.py
```

---

## Custom Frontend

To build your own frontend instead of using the provided HTML interface, refer to the [VoiceStax Custom Frontend Developer Guide](voicestax_custom_frontend_guide.md). It covers WebSocket connection setup, audio handling, VAD implementation, and a minimal skeleton to get started.

---

## License

MIT License — see the LICENSE file for details.

## Contributing

Contributions are welcome. Please feel free to open a PR or issue.