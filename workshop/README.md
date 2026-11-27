# Workshop: build a voice agent with Google ADK

The app in [`src/voice_agent`](../src/voice_agent) started life as this
55-minute workshop. Each checkpoint adds one idea, so you can follow the path
from a text agent to a hardened real-time voice service.

| Checkpoint | Idea | Run |
| --- | --- | --- |
| [`00_start`](checkpoints/00_start) | Empty agent you edit live | `uv run adk web` |
| [`01_basic`](checkpoints/01_basic) | Instruction-only agent | `uv run adk web` |
| [`02_tool`](checkpoints/02_tool) | Typed tool call (`find_rooms`) | `uv run adk web` |
| [`03_voice`](checkpoints/03_voice) | Switch to Gemini Live: mic, native audio, interruptions | `uv run adk web` |
| [`04_slow_failure`](checkpoints/04_slow_failure) | Slow and failing tool, structured errors | `uv run adk web` |
| [`05_custom_streaming`](checkpoints/05_custom_streaming) | Own FastAPI/WebSocket server and browser client | `uv run uvicorn server:app --port 8001` |
| [`06_production`](checkpoints/06_production) | Guardrails; graduated into `src/voice_agent` | `uv run uvicorn server:app --port 8002` |

Run each command from inside that checkpoint's folder (for example
`cd workshop/checkpoints/02_tool && uv run adk web`), then pick `room_agent`
in the ADK Web UI. Checkpoints 00 to 02 use a text model, so
don't start microphone mode there.

Before the session, everyone should reach `READY`:

```bash
uv sync
cp .env.example .env   # add GEMINI_API_KEY
uv run python scripts/preflight.py
```

Running it for a group? See the [facilitator runbook](FACILITATOR.md).
