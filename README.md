# 🎙️ ADK Voice Agent

[![Python](https://img.shields.io/badge/Python-3.11--3.13-blue?logo=python&logoColor=white)](https://www.python.org/)
[![Google ADK](https://img.shields.io/badge/Google%20ADK-Agent%20Framework-4285F4?logo=google&logoColor=white)](https://google.github.io/adk-docs/)
[![Gemini Live](https://img.shields.io/badge/Gemini%20Live-Voice%20API-8E75B2)](https://ai.google.dev/gemini-api/docs/live)
[![FastAPI](https://img.shields.io/badge/FastAPI-Backend-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![uv](https://img.shields.io/badge/uv-Package%20Manager-DE5FE9)](https://docs.astral.sh/uv/)

A real-time voice assistant that helps users find meeting rooms through natural
conversation. It combines Google ADK, Gemini Live, FastAPI, WebSockets, browser
audio, typed tools, and streaming transcripts.

![ADK Voice Agent interface](docs/images/adk-voice-agent.png)

## ✨ Key Features

- 🎙️ Real-time voice conversations with interruption support
- 🏢 Meeting-room search through a typed agent tool
- 🔊 Live audio, transcripts, tool events, and status updates
- ⚡ Browser-to-agent streaming over WebSockets
- 🛡️ Origin checks, payload limits, session limits, and safe errors
- 📋 Privacy-aware logging and deterministic session cleanup

## 🛠️ Technology Stack

### Core Components

- **Agent Framework**: Google ADK
- **Models**: Gemini text and Gemini Live
- **Backend**: FastAPI and Uvicorn
- **Transport**: WebSockets
- **Frontend**: HTML, CSS, and JavaScript
- **Package Manager**: uv

### Quality and Operations

- **Configuration**: `.env` with `python-dotenv`
- **Testing**: pytest
- **Linting**: Ruff
- **Runtime Controls**: origin validation, message limits, concurrency limits,
  session resumption, and privacy-aware logs

## 🚀 Quick Start

### Prerequisites

- Python 3.11, 3.12, or 3.13
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- A Chromium-based browser with microphone access
- A Google AI Studio API key with Gemini Live access

### Installation

1. **Clone the repository**

	```bash
	git clone <repository-url>
	cd adk-voice-agent
	```

2. **Install dependencies**

	```bash
	uv sync
	```

3. **Create the environment file**

	Windows:

	```bash
	copy .env.example .env
	```

	macOS/Linux:

	```bash
	cp .env.example .env
	```

	Add `GEMINI_API_KEY` or `GOOGLE_API_KEY` to `.env`. Keep the file private
	and never commit the key.

4. **Run the environment check**

	```bash
	uv run python scripts/preflight.py
	```

5. **Start the application**

	```bash
	cd checkpoints/06_production
	uv run uvicorn server:app --reload --port 8002
	```

	Open [http://localhost:8002](http://localhost:8002), connect the microphone,
	and ask for a meeting room. Headphones are recommended to prevent feedback.

For the minimal streaming server, run it on port `8001`:

```bash
cd checkpoints/05_custom_streaming
uv run uvicorn server:app --reload --port 8001
```

## ⚙️ Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `GEMINI_API_KEY` or `GOOGLE_API_KEY` | unset | Gemini authentication |
| `TEXT_MODEL` | `gemini-3.6-flash` | Text model |
| `LIVE_MODEL` | `gemini-3.1-flash-live-preview` | Voice model |
| `WS_ALLOWED_ORIGINS` | `http://localhost:8002,http://127.0.0.1:8002` | WebSocket origin allowlist |
| `MAX_WS_MESSAGE_BYTES` | `32768` | Maximum WebSocket message size |
| `MAX_AUDIO_CHUNK_BYTES` | `16384` | Maximum decoded audio chunk size |
| `MAX_ACTIVE_SESSIONS` | `20` | Concurrent live-session limit |
| `LOG_LEVEL` | `INFO` | Server log level |

## 🏗️ Project Structure

```text
adk-voice-agent/
├── checkpoints/
│   ├── 05_custom_streaming/   # Minimal FastAPI/WebSocket app
│   └── 06_production/         # Hardened voice application
├── src/                       # Configuration and room-agent tools
├── scripts/preflight.py       # Environment and configuration checks
├── tests/                     # Automated tests
├── docs/images/               # Application screenshots
├── .env.example               # Environment template
└── pyproject.toml             # Project metadata and dependencies
```

## 🔄 Data Flow

1. The browser captures microphone audio as PCM data.
2. Audio and control messages travel to the server over a WebSocket.
3. The server forwards input to a Google ADK `LiveRequestQueue`.
4. Gemini Live generates audio, transcripts, and tool events.
5. The server streams events back to the browser for playback and display.

## ✅ Tests

```bash
uv run pytest
uv run ruff check .
```

The test suite covers room filtering, input validation, tool failure handling,
production server guards, and repository secret safety.

## 🔒 Security

Keep API keys server-side and never commit `.env`, credentials, or private
transcripts. Before exposing the application publicly, add authentication,
TLS, rate limiting, durable session storage, managed secrets, monitoring, and
retention policies.

---

<p align="center">Built with Google ADK and Gemini Live</p>
