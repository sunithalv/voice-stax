# VoiceStax

**VoiceStax** is a modular, installable Python framework for building real-time voice agents.

It provides the infrastructure required to turn an existing AI application into a real-time voice experience, including:

* Speech-to-text (STT)
* Voice activity detection (VAD)
* Turn and utterance management
* LLM orchestration
* Conversation and session management
* Text-to-speech (TTS)
* Real-time audio streaming
* Barge-in and interruption handling
* Provider abstraction
* Structured LLM responses
* Logging and runtime diagnostics

VoiceStax is designed for applications that already have, or want to add, their own **LLM, RAG, business logic, databases, tools, APIs, or domain-specific instructions**.

The application remains responsible for **what the agent knows and does**.

VoiceStax manages **the real-time voice conversation around that intelligence**.

---

# Quick Start

The fastest way to try VoiceStax is to run the included browser-based example.

## Requirements

* Python 3.12+
* API keys for the configured providers

## 1. Install

Clone the repository:

```bash
git clone <repository-url>
cd voice-stax
```

Install VoiceStax and its dependencies:

```bash
pip install -e .
```

## 2. Configure API Keys

Create a `.env` file in the project root:

```text
ASSEMBLYAI_API_KEY=your_assemblyai_key
ELEVENLABS_API_KEY=your_elevenlabs_key
GROQ_API_KEY=your_groq_key
```

The default VoiceStax providers are currently:

| Capability | Default provider |
| ---------- | ---------------- |
| STT        | AssemblyAI       |
| TTS        | ElevenLabs       |
| LLM        | Groq             |
| VAD        | WebRTC VAD       |

## 3. Run the Example

Start the example application:

```bash
python main.py
```

Then open the browser client included with the project and start speaking.

The example exercises the complete VoiceStax pipeline:

```text
Microphone
    │
    ▼
WebSocket
    │
    ▼
AudioManager
    │
    ▼
VAD / Turn Detection
    │
    ▼
STT
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
Streaming Audio
    │
    ▼
Browser
```

This is the quickest way to verify that the VoiceStax pipeline is working.

---

# Using VoiceStax

VoiceStax is designed to support different levels of integration.

You can start with the framework defaults and introduce more control only when your application requires it.

```text
Less configuration
       │
       ▼
Framework defaults
       │
       ▼
VoiceSettings
       │
       ▼
User-defined provider parameters
       │
       ▼
Custom application LLM logic
       │
       ▼
Full application integration
       │
       ▼
More control
```

---

## 1. Use VoiceStax with Defaults

The simplest option is to let VoiceStax load its configuration and use the configured default providers.

```python
from voicestax import create_voice_app

app = create_voice_app()
```

This is useful when:

* You want to get started quickly.
* You are using the default providers.
* You do not need provider-specific customization.
* You want VoiceStax to manage the standard configuration.

Provider API keys can be supplied through environment variables or a `.env` file.

---

## 2. Use `VoiceSettings`

Applications can explicitly create a `VoiceSettings` object when they want to control VoiceStax configuration.

```python
from voicestax import create_voice_app, VoiceSettings

settings = VoiceSettings(
    app_name="Acme Support",
    stt_provider="assemblyai",
    tts_provider="elevenlabs",
    llm_provider="groq",
    vad_provider="webrtc",
)

app = create_voice_app(settings=settings)
```

You can also provide application-specific instructions:

```python
settings = VoiceSettings(
    app_name="Acme Support",
    llm_system_prompt=(
        "You are the Acme customer support assistant. "
        "Answer using the provided application context. "
        "Keep responses concise and natural for voice conversation."
    ),
)

app = create_voice_app(settings=settings)
```

VoiceStax continues to manage the real-time voice pipeline while the application controls its own configuration and instructions.

---

## 3. Use User-Defined Provider Parameters

Provider-specific parameters can be supplied through the corresponding configuration fields.

```python
from voicestax import create_voice_app, VoiceSettings

settings = VoiceSettings(

    stt_provider="assemblyai",
    stt_config={
        "sample_rate": 16000,
        "encoding": "pcm_s16le",
        "end_of_turn_confidence_threshold": 0.6,
    },

    tts_provider="elevenlabs",
    tts_config={
        "voice_id": "your_voice_id",
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

app = create_voice_app(settings=settings)
```

Provider-specific configuration is passed to the selected provider and validated by the corresponding provider implementation.

This allows applications to customize provider behavior without modifying the VoiceStax core pipeline.

---

## 4. Use Custom Application LLM Logic

VoiceStax is designed to work with applications that already have their own AI logic.

An application may already have:

* An LLM
* RAG
* A vector database
* Database queries
* Business rules
* Tools and APIs
* Domain-specific prompts
* Existing AI orchestration

That logic can participate in the VoiceStax conversational flow.

Conceptually:

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
Application Logic
    │
    ├── RAG
    ├── Database
    ├── Business Rules
    ├── Tools / APIs
    └── Domain Context
    │
    ▼
VoiceStax ChatEngine
    │
    ├── Voice-agent instructions
    ├── Application instructions
    ├── Conversation history
    └── Application context
    │
    ▼
LLM
    │
    ▼
VoiceStax Response Handling
    │
    ▼
TTS
```

Applications can also provide custom LLM/provider logic when required:

```python
from voicestax import create_voice_app

app = create_voice_app(
    custom_llm_provider=my_llm_provider
)
```

This allows an existing AI application to retain its own domain-specific intelligence while VoiceStax manages the real-time conversational voice infrastructure.

---

# Choosing the Level of Configuration

| Usage                 | Application provides                          | VoiceStax provides                               |
| --------------------- | --------------------------------------------- | ------------------------------------------------ |
| **Defaults**          | Environment configuration and API keys        | Providers, configuration and voice pipeline      |
| **VoiceSettings**     | Framework configuration                       | Voice pipeline and built-in providers            |
| **Custom parameters** | Provider-specific configuration               | Voice pipeline and provider abstraction          |
| **Custom LLM logic**  | Application LLM/RAG/business logic            | Voice pipeline and conversational infrastructure |
| **Full integration**  | LLM, RAG, tools, databases and business logic | Real-time voice infrastructure                   |

You do not have to configure everything up front.

Start with the defaults and introduce additional configuration as your application becomes more complex.

---

# What VoiceStax Provides

A typical AI application may already contain:

* An LLM
* RAG or document retrieval
* Business logic
* Databases
* Tools or APIs
* Domain-specific prompts and instructions

VoiceStax adds the real-time voice layer around that application.

It handles:

* 🎙️ Real-time audio input
* 📝 Speech-to-text
* 🔊 Voice activity detection
* ⏱️ Turn and utterance management
* 🧠 LLM orchestration
* 💬 Conversation and session management
* 🔈 Text-to-speech
* ⚡ Streaming audio
* 🛑 Barge-in and interruption handling
* 🔌 Provider abstraction
* ⚙️ Configurable provider settings
* 📋 Structured LLM responses
* 🪵 Logging and runtime diagnostics

The goal is to allow an application developer to focus on **what the agent should know and do**, while VoiceStax manages the infrastructure required for a real-time voice conversation.

---

# Architecture

At a high level, VoiceStax sits between the application and the real-time voice interface.

```text
                  Your Application

        ┌─────────────────────────────────┐
        │                                 │
        │  RAG                            │
        │  Business Logic                 │
        │  Database Context               │
        │  Tools / APIs                   │
        │  Domain Instructions             │
        │  Application LLM Logic           │
        │                                 │
        └───────────────┬─────────────────┘
                        │
                        │ Application context /
                        │ logic integration
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
                      LLM
                        │
                        ▼
                       TTS
                        │
                        ▼
                 User's Voice
```

An important design characteristic of VoiceStax is that it has its own **LLM orchestration layer**.

The application supplies domain-specific intelligence, while VoiceStax combines that information with the conversational requirements of a real-time voice agent.

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

This allows an existing AI application to add real-time voice interaction without implementing the complete:

```text
STT → VAD → turn detection → LLM → TTS → streaming → interruption
```

pipeline itself.

---

# LLM Orchestration

LLM orchestration is a core part of VoiceStax.

VoiceStax does not simply send the user's transcript directly to an LLM.

The `ChatEngine` coordinates conversational context and combines VoiceStax-level instructions with application-specific logic.

For example, an application may provide:

```text
Answer questions using the product manuals and FAQ knowledge base.

Use order information when answering questions about customer orders.

Do not invent product specifications.
```

VoiceStax can combine this with voice-agent instructions such as:

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
          │
          ▼
   Combined LLM Context
          │
          ▼
      LLM Provider
          │
          ▼
    Structured Response
```

This separation allows VoiceStax to provide consistent voice-agent behavior while allowing applications to control their domain-specific intelligence.

---

# Core Components

## VoiceAgent

`VoiceAgent` coordinates the overall voice-agent lifecycle.

It connects the different parts of the framework and manages the interaction between:

* Session state
* Audio handling
* VAD
* STT
* LLM processing
* TTS
* Interruption handling

---

## ChatEngine

`ChatEngine` manages the conversational LLM flow.

Responsibilities include:

* Constructing the LLM request
* Combining VoiceStax instructions with application-provided logic
* Incorporating conversation history
* Handling structured LLM responses
* Managing conversation-level behavior
* Coordinating with the configured LLM provider

This is the main layer where **application intelligence and VoiceStax voice-agent behavior come together**.

---

## AudioManager

`AudioManager` manages real-time audio processing.

Responsibilities include:

* Receiving PCM audio
* Buffering audio frames
* Passing frames to VAD
* Forwarding appropriate audio to STT
* Handling audio streaming
* Managing TTS audio playback
* Handling streaming and buffered audio paths
* Coordinating interruption-related audio behavior

---

## VADManager

`VADManager` contains VoiceStax-level utterance state management.

The VAD provider determines whether an individual audio frame contains speech.

`VADManager` uses those results to manage higher-level events such as:

* Speech started
* Speech ended
* Silence duration
* Maximum utterance duration

This keeps provider-specific speech detection separate from VoiceStax's conversation state machine.

---

## SessionData

Each voice interaction maintains session state.

Session data can contain information such as:

* Conversation history
* Current voice-agent state
* STT/TTS/LLM providers
* Speech timing information
* Interruption state
* Session identifiers
* Runtime information required by the voice pipeline

---

# Provider Architecture

VoiceStax separates the core voice-agent logic from external AI providers.

Providers are selected through configuration and accessed through common provider interfaces.

Current default implementations include:

### STT

**AssemblyAI**

### TTS

**ElevenLabs**

### LLM

**Groq**

### VAD

**WebRTC VAD**

The provider architecture allows alternative implementations to be added without changing the core voice-agent pipeline.

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

Provider-specific configuration is handled by the corresponding provider.

This allows VoiceStax to maintain common framework configuration while allowing individual providers to expose their own capabilities.

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

When integrated with VoiceStax, that application logic can participate in the VoiceStax conversational flow:

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
    └── Retrieved / business context
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

The browser or other audio client sends audio to the server through a WebSocket connection.

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

VoiceStax therefore treats interruption handling as a first-class part of the real-time voice pipeline.

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
Cancel current TTS / audio
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

RAG is **not required** by the core framework.

An application can provide its own:

* Document retrieval
* Vector database
* Metadata filtering
* Database queries
* Business rules
* Retrieved context

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

# WebSocket Interface

The current VoiceStax implementation uses a FastAPI WebSocket endpoint for real-time communication.

The client sends audio to the server, while VoiceStax sends events and audio back to the client.

The protocol supports the real-time interaction required by the voice pipeline, including:

* Audio input
* Transcripts
* Assistant responses
* Streamed audio
* Word/audio synchronization events
* Completion events
* Interruption events
* Connection/session events

The WebSocket protocol is kept separate from the core provider interfaces so that additional transports can be introduced later.

---

# Example Application

A minimal application can configure VoiceStax and provide application-level instructions.

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

The application can then extend this with its own:

* LLM logic
* RAG
* Business rules
* Tools
* APIs
* Database context
* Domain-specific instructions

---

# Project Structure

```text
voice-stax/
│
├── voicestax/                    # Core VoiceStax framework
│   ├── api/                      # FastAPI application and WebSocket interface
│   ├── cli/                      # Command-line interface
│   ├── config/                   # Framework configuration and settings
│   ├── core/                     # Voice-agent orchestration and audio pipeline
│   ├── providers/                # STT, TTS, LLM and VAD implementations
│   ├── schemas/                  # Structured LLM response schemas
│   ├── session/                  # Voice session state and interruption handling
│   └── utils/                    # Logging, exceptions and utility functions
│
├── examples/                     # Example client/application code
│   └── html/                     # Browser-based voice chat interface
│
├── sample_providers/             # Example application-level integrations
│   └── rag/                      # Example RAG integration with VoiceStax
│
├── tests/                        # VoiceStax test suite
│
├── main.py                       # Basic browser-based VoiceStax example
├── pyproject.toml                # Package metadata and dependencies
├── LICENSE                       # Apache License 2.0
├── NOTICE                        # Project copyright notice
└── README.md                     # Project documentation
```

---

# Design Principles

VoiceStax is built around several principles.

## Modular Providers

STT, TTS, LLM and VAD implementations are isolated behind provider interfaces.

New providers can be added without changing the core voice-agent pipeline.

## Application-Aware LLM Orchestration

VoiceStax provides its own conversational LLM behavior while allowing application-specific instructions, RAG, business context and other application logic to participate in the LLM flow.

## Real-Time First

Audio processing, turn detection, streaming and interruption handling are treated as first-class concerns.

## Separation of Responsibilities

VoiceStax handles the real-time voice-agent infrastructure.

The application supplies domain-specific intelligence and integrations.

## Configurable

Provider selection and provider-specific settings can be changed through configuration rather than modifying the core pipeline.

## Extensible

New providers, transports and application integrations can be added without redesigning the complete voice-agent architecture.

---

# Current Status

## v0.1

The initial release focuses on a stable browser-based real-time voice-agent pipeline.

Current areas include:

* FastAPI integration
* WebSocket-based browser communication
* Streaming STT
* WebRTC VAD
* Utterance and turn management
* LLM orchestration
* Structured LLM responses
* Streaming TTS
* Conversation/session management
* Barge-in/interruption handling
* Configurable providers
* Logging
* Custom application LLM logic
* Optional RAG example
* Provider validation
* Runtime testing and reliability

The v0.1 release establishes the core VoiceStax architecture before expanding the framework to additional transports and capabilities.

---

# Roadmap

## V1

### Telephony

Expand VoiceStax to support telephony-based voice agents.

Initial language targets:

* English
* Hindi
* Malayalam

### Observability

Provide more detailed visibility into:

* STT latency
* Retrieval latency
* LLM latency
* TTS latency
* End-to-end response latency
* Interruptions
* Turn timing
* Provider errors

### Evaluation

Add evaluation capabilities for:

* Voice-agent behavior
* Conversation flow
* Response quality
* Latency and runtime behavior

### Guardrails

Add configurable guardrails for areas such as:

* Input validation
* Output validation
* Tool-related behavior
* Unsafe or unwanted responses

### Additional Providers

Expand provider support across:

* STT
* TTS
* LLM
* VAD

### Reliability and Latency

Continue improving:

* Streaming behavior
* Interruption handling
* Provider failure handling
* Latency
* Audio processing
* Session stability

---

# Why VoiceStax?

Building a real-time voice agent involves considerably more than connecting an STT provider to an LLM and then connecting the LLM to TTS.

A usable voice agent also needs to coordinate:

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

* Audio streaming
* VAD behavior
* STT turn detection
* LLM responses
* TTS streaming
* Interruption handling
* Session state
* Latency
* Provider configuration
* Error handling

---

# License

VoiceStax is licensed under the **Apache License, Version 2.0**.

See [`LICENSE`](LICENSE) for the full license text.

Copyright 2026 Sunitha L V.
