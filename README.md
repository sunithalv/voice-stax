# VoiceStax

**VoiceStax** is a modular, installable Python framework for building real-time voice agents.

It provides the infrastructure required to turn an existing AI application into a real-time voice experience, including **speech-to-text (STT), voice activity detection (VAD), conversation and turn management, LLM orchestration, text-to-speech (TTS), audio streaming, session management, and interruption handling**.

VoiceStax is designed so that application-specific intelligence—such as RAG, business rules, database context, tools, and domain-specific instructions—can be integrated into the VoiceStax conversational and LLM flow rather than requiring the application to implement the complete real-time voice pipeline itself.

---

## What VoiceStax Provides

A typical AI application may already have:

* an LLM
* RAG or document retrieval
* business logic
* databases
* tools or APIs
* domain-specific prompts and instructions

VoiceStax adds the real-time voice layer around that application.

It handles:

* 🎙️ Real-time audio input
* 📝 Speech-to-text
* 🔊 Voice activity detection
* ⏱️ Turn and utterance management
* 🧠 LLM orchestration
* 💬 Conversation/session management
* 🔈 Text-to-speech
* ⚡ Streaming audio
* 🛑 Barge-in and interruption handling
* 🔌 Provider abstraction
* ⚙️ Configurable provider settings
* 📋 Structured LLM responses
* 🪵 Logging and runtime diagnostics

The goal is to allow an application developer to focus on **what the agent should know and do**, while VoiceStax manages the complexities of a real-time voice conversation.

---

## Architecture

At a high level, VoiceStax sits between the user's application logic and the real-time voice interface.

```text
                  Your Application
        ┌─────────────────────────────────┐
        │                                 │
        │  RAG                            │
        │  Business Logic                 │
        │  Database Context               │
        │  Tools / APIs                   │
        │  Domain Instructions            │
        │  Application-specific LLM Logic │
        │                                 │
        └───────────────┬─────────────────┘
                        │
                        │ Injected / integrated
                        ▼
        ┌─────────────────────────────────┐
        │           VoiceStax             │
        │                                 │
        │  VoiceAgent                     │
        │      │                          │
        │      ├── Session Management      │
        │      ├── ChatEngine              │
        │      ├── Prompt Composition      │
        │      ├── Conversation Handling   │
        │      ├── VAD / Turn Management   │
        │      ├── Audio Management        │
        │      └── Provider Abstraction    │
        │                                 │
        └───────────────┬─────────────────┘
                        │
                        ▼
              ┌─────────────────┐
              │      LLM        │
              └────────┬────────┘
                       │
                       ▼
                    TTS
                       │
                       ▼
                 User's Voice
```

The important distinction is that **VoiceStax has its own LLM orchestration layer**.

The application provides its domain-specific intelligence, while VoiceStax combines that information with the conversational behavior and requirements needed by the real-time voice agent.

---

# How It Works

A typical interaction follows this flow:

```text
User speaks
    │
    ▼
Audio received
    │
    ▼
VAD / utterance detection
    │
    ▼
STT
    │
    ▼
Final transcript
    │
    ▼
VoiceStax ChatEngine
    │
    ├── VoiceStax conversation instructions
    ├── Conversation history
    ├── Application LLM logic
    ├── RAG / retrieved context
    ├── Business context
    └── Other application-provided information
    │
    ▼
Configured LLM provider
    │
    ▼
Structured LLM response
    │
    ▼
VoiceStax response handling
    │
    ▼
TTS
    │
    ▼
Streaming audio
    │
    ▼
User hears response
```

This allows an existing AI application to add real-time voice interaction without having to implement the complete STT → VAD → turn detection → LLM → TTS → streaming → interruption pipeline itself.

---

# LLM Orchestration

LLM orchestration is a core part of VoiceStax.

VoiceStax does not simply send the user's transcript directly to an LLM.

Instead, the `ChatEngine` coordinates the conversational context and combines VoiceStax-level instructions with application-specific logic.

For example, an application may provide instructions such as:

```text
Answer questions using the product manuals and FAQ knowledge base.
Use order information when answering questions about customer orders.
Do not invent product specifications.
```

VoiceStax can incorporate this into the voice-agent behavior, which may include instructions such as:

```text
You are a real-time voice assistant.

Keep responses concise and natural for spoken conversation.

Follow the required response structure.

Determine whether the conversation should continue,
requires clarification, should end, or requires human handoff.
```

Conceptually:

```text
VoiceStax Instructions
          +
Application Instructions
          +
Conversation History
          +
RAG / Business Context
          ↓
     Combined LLM Context
          ↓
       LLM Provider
          ↓
   Structured Response
```

This separation allows VoiceStax to provide consistent voice-agent behavior while allowing applications to control their domain-specific intelligence.

---

# Core Components

## VoiceAgent

`VoiceAgent` coordinates the overall voice-agent lifecycle.

It connects the different parts of the framework and manages the interaction between:

* session state
* audio handling
* VAD
* STT
* LLM processing
* TTS
* interruption handling

---

## ChatEngine

`ChatEngine` manages the conversational LLM flow.

Responsibilities include:

* constructing the LLM request
* combining VoiceStax instructions with application-provided logic
* incorporating conversation history
* handling structured LLM responses
* managing conversation-level behavior
* coordinating with the configured LLM provider

This is the main layer where **application intelligence and VoiceStax voice-agent behavior come together**.

---

## AudioManager

`AudioManager` manages real-time audio processing.

Responsibilities include:

* receiving PCM audio
* buffering audio frames
* passing frames to VAD
* forwarding appropriate audio to STT
* handling audio streaming
* managing TTS audio playback
* handling streaming/buffered audio paths
* coordinating interruption-related audio behavior

---

## VADManager

`VADManager` contains VoiceStax-level utterance state management.

The VAD provider determines whether an individual audio frame contains speech.

`VADManager` uses those results to manage higher-level events such as:

* speech started
* speech ended
* silence duration
* maximum utterance duration

This keeps provider-specific speech detection separate from VoiceStax's conversation state machine.

---

## SessionData

Each voice interaction maintains session state.

Session data can contain information such as:

* conversation history
* current voice-agent state
* STT/TTS/LLM providers
* speech timing information
* interruption state
* session identifiers
* runtime information required by the voice pipeline

---

# Provider Architecture

VoiceStax separates the core voice-agent logic from external AI providers.

Providers are selected through configuration and accessed through common provider interfaces.

Current provider default implementations include:

### STT

* AssemblyAI

### TTS

* ElevenLabs

### LLM

* Groq

### VAD

* WebRTC VAD

The provider architecture is intended to make it possible to add alternative providers without changing the core voice-agent pipeline.

---

# Configurable Providers

Provider configuration is separated by capability.

For example:

```python
settings = VoiceSettings(
    stt_provider="assemblyai",
    stt_config={
        "sample_rate": 16000,
        "encoding": "pcm_s16le",
    },

    tts_provider="elevenlabs",
    tts_config={
        "voice_id": "...",
        "model_id": "eleven_turbo_v2_5",
        "output_format": "pcm_24000",
    },

    llm_provider="groq",
    llm_config={
        "model": "llama-3.3-70b-versatile",
        "max_tokens": 120,
    },

    vad_provider="webrtc",
    vad_config={
        "aggressiveness": 2,
        "sample_rate": 16000,
        "frame_duration_ms": 20,
    },
)
```

Provider-specific configuration is validated by the corresponding provider.

This allows VoiceStax to maintain common configuration at the framework level while allowing individual providers to expose their own capabilities.

---

# Custom Application LLM Logic

VoiceStax is designed to work with applications that already contain their own AI logic.

For example, an application may already have:

```text
User Question
      │
      ▼
Retrieve documents
      │
      ▼
Retrieve customer/order information
      │
      ▼
Build application-specific context
      │
      ▼
LLM
```

When integrated with VoiceStax, that application logic can become part of the VoiceStax conversational flow:

```text
User Voice
    │
    ▼
VoiceStax STT
    │
    ▼
Transcript
    │
    ▼
Application Logic / RAG / Business Context
    │
    ▼
VoiceStax ChatEngine
    │
    ├── Voice-agent instructions
    ├── Application instructions
    ├── Conversation history
    └── Retrieved/business context
    │
    ▼
LLM
    │
    ▼
VoiceStax response handling
    │
    ▼
TTS
```

This allows an existing AI application to retain its domain-specific intelligence while VoiceStax manages the real-time conversational voice behavior.

---

# Structured LLM Responses

VoiceStax uses structured responses to allow the framework to distinguish between different conversational outcomes.

The current response model includes intents such as:

```text
conversation
clarification
end_conversation
human_handoff
```

This allows the voice pipeline to make decisions based on the LLM response rather than treating every response as plain text.

For example:

```json
{
  "intent": "conversation",
  "response": "The product is available in two models."
}
```

The exact response schema can evolve as VoiceStax's conversational capabilities expand.

---

# Real-Time Voice Pipeline

VoiceStax is designed for streaming interaction rather than request/response voice processing.

The browser or other audio client sends audio to the WebSocket endpoint.

```text
Client
  │
  │ PCM audio
  ▼
WebSocket
  │
  ▼
AudioManager
  │
  ▼
VAD
  │
  ├── Speech
  │
  └── Silence
        │
        ▼
   Turn detection
        │
        ▼
       STT
        │
        ▼
    Transcript
        │
        ▼
    ChatEngine
        │
        ▼
       LLM
        │
        ▼
       TTS
        │
        ▼
 Streaming audio
        │
        ▼
      Client
```

---

# Barge-In and Interruption Handling

Voice conversations require the assistant to stop speaking when the user starts talking.

VoiceStax therefore includes interruption handling as part of the real-time voice pipeline.

The general flow is:

```text
Assistant is speaking
        │
        ▼
User starts speaking
        │
        ▼
VAD detects speech
        │
        ▼
VoiceStax detects interruption
        │
        ▼
Cancel current TTS/audio
        │
        ▼
Switch back to listening
```

This prevents the assistant from continuing to speak over the user.

---

# Conversation State

VoiceStax maintains conversation state during a session.

The voice agent can transition between states such as:

```text
Idle
  │
  ▼
Listening
  │
  ▼
Processing
  │
  ▼
Speaking
  │
  ├──── User interruption ────► Listening
  │
  ▼
Listening
```

Session state allows the different parts of the real-time pipeline to coordinate without requiring the application to manage every low-level voice event.

---

# RAG Support

VoiceStax can be integrated with applications that use Retrieval-Augmented Generation (RAG).

RAG is not required by the core framework.

An application can provide its own:

* document retrieval
* vector database
* metadata filtering
* database queries
* business rules
* retrieved context

For example:

```text
User:
"Does the Acme X100 support fast charging?"

        │
        ▼
      STT

        │
        ▼
VoiceStax transcript

        │
        ▼
Application RAG
        │
        ├── Product manual
        ├── FAQ
        └── Product metadata

        │
        ▼
Combined LLM context

        │
        ▼
       LLM

        │
        ▼
Voice response

        │
        ▼
      TTS
```

A sample RAG integration is included separately from the core framework.

---

# Project Structure

```text
voice-stax/
│
├── voicestax/
│   │
│   ├── api/
│   │   ├── app.py
│   │   └── websocket_routes.py
│   │
│   ├── config/
│   │   └── settings.py
│   │
│   ├── core/
│   │   ├── voice_agent.py
│   │   ├── chat_engine.py
│   │   ├── audio_manager.py
│   │   └── vad_manager.py
│   │
│   ├── providers/
│   │   ├── stt/
│   │   ├── tts/
│   │   ├── llm/
│   │   └── vad/
│   │
│   ├── session/
│   │
│   └── utils/
│
├── examples/
│
├── sample_providers/
│   └── rag/
│
├── main.py
├── main_rag.py
├── pyproject.toml
├── LICENSE
├── NOTICE
└── README.md
```

---

# WebSocket Interface

The current VoiceStax implementation uses a FastAPI WebSocket endpoint for real-time browser communication.

The client sends audio to the server, while VoiceStax sends events and audio back to the client.

The protocol supports the real-time interaction required by the voice pipeline, including:

* audio input
* transcripts
* assistant responses
* streamed audio
* word/audio synchronization events
* completion events
* interruption events
* connection/session events

The WebSocket protocol is intentionally kept separate from the core provider interfaces so that additional transports can be introduced later.

---

# Running the Example

## Requirements

* Python 3.12+
* API keys for the configured providers

Install the project dependencies:

```bash
pip install -e .
```

Configure the required environment variables.

For example:

```text
ASSEMBLYAI_API_KEY=...
ELEVENLABS_API_KEY=...
GROQ_API_KEY=...
```

Then start the example application:

```bash
python main.py
```

The example provides a browser-based voice interaction using the configured VoiceStax pipeline.

---

# Example Application

A minimal application can configure VoiceStax and provide its own application-level instructions.

Conceptually:

```python
from voicestax import create_voice_app, VoiceSettings


settings = VoiceSettings(
    app_name="Acme Support",

    llm_system_prompt=(
        "You are the Acme customer support assistant. "
        "Answer questions using the provided application context. "
        "Keep responses concise and natural for voice conversation."
    ),

    stt_provider="assemblyai",

    tts_provider="elevenlabs",

    llm_provider="groq",

    vad_provider="webrtc",
)


app = create_voice_app(settings=settings)
```

The application can then extend this with its own LLM, RAG, business logic, tools, or other domain-specific context.

---

# Design Principles

VoiceStax is built around several principles.

### Modular providers

STT, TTS, LLM, and VAD implementations are isolated behind provider interfaces.

### Application-aware LLM orchestration

VoiceStax provides its own conversational LLM behavior while allowing application-specific instructions, RAG, business context, and other logic to participate in the same LLM flow.

### Real-time first

Audio processing, turn detection, streaming, and interruption handling are treated as first-class concerns.

### Separation of responsibilities

VoiceStax handles real-time voice-agent infrastructure.

The application supplies domain-specific intelligence and integrations.

### Configurable

Provider selection and provider-specific settings can be changed through configuration rather than modifying the core pipeline.

### Extensible

New providers and application integrations can be added without redesigning the complete voice-agent architecture.

---

# Current Status

## v0.1

The initial release focuses on a stable browser-based voice-agent pipeline.

Current focus areas include:

* FastAPI integration
* WebSocket-based browser communication
* streaming STT
* WebRTC VAD
* utterance/turn management
* LLM orchestration
* structured LLM responses
* streaming TTS
* conversation/session management
* barge-in/interruption handling
* configurable providers
* logging
* custom application LLM logic
* optional RAG example
* provider validation
* runtime testing and reliability

The v0.1 release is intended to establish the core architecture before expanding VoiceStax to additional transports and production-oriented capabilities.

---

# Roadmap

## V1

Planned areas include:

### Telephony

Support for telephony-based voice agents, initially targeting:

* English
* Hindi
* Malayalam

### Observability

More detailed visibility into:

* STT latency
* retrieval latency
* LLM latency
* TTS latency
* end-to-end response latency
* interruptions
* turn timing
* provider errors

### Evaluation

Evaluation capabilities for voice-agent behavior and response quality.

### Guardrails

Configurable guardrails for areas such as:

* input validation
* output validation
* tool-related behavior
* unsafe or unwanted responses

### Additional providers

Expand provider support across:

* STT
* TTS
* LLM
* VAD

### Reliability and latency

Continue improving:

* streaming behavior
* interruption handling
* provider failure handling
* latency
* audio processing
* session stability

---

# Why VoiceStax?

Building a voice agent involves considerably more than connecting an STT provider to an LLM and then connecting the LLM to TTS.

A usable real-time voice agent also needs to handle:

```text
Audio
  ↓
Frame processing
  ↓
VAD
  ↓
Turn detection
  ↓
STT
  ↓
Conversation state
  ↓
Prompt / context composition
  ↓
LLM
  ↓
Structured response
  ↓
TTS
  ↓
Audio streaming
  ↓
Interruption / barge-in
```

VoiceStax brings these responsibilities together into a reusable framework while allowing the application to retain control over its own domain intelligence.

The intention is to make it possible to take an existing AI application and add a real-time conversational voice interface without rebuilding the underlying voice-agent infrastructure from scratch.

---

# Development

VoiceStax currently targets:

```text
Python >= 3.12
```

The project is being developed as an installable Python package with a provider-oriented architecture.

During development, the browser-based voice pipeline is used to test:

* audio streaming
* VAD behavior
* STT turn detection
* LLM responses
* TTS streaming
* interruption handling
* session state
* latency
* provider configuration
* error handling

---

# License

VoiceStax is licensed under the **Apache License, Version 2.0**.

See [`LICENSE`](LICENSE) for the full license text.

Copyright 2026 Sunitha L V.
