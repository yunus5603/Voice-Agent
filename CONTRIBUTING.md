# Contributing

Thanks for your interest! Issues and pull requests are welcome, from typo
fixes to new tools.

## Set up

```bash
git clone https://github.com/yunus5603/Voice-Agent.git
cd Voice-Agent
uv sync
cp .env.example .env   # add GEMINI_API_KEY to try the voice app
```

You do **not** need an API key to run the tests: Gemini Live is replaced by a
scripted fake in `tests/test_websocket.py`.

## Before you open a PR

```bash
uv run ruff format .
uv run ruff check .
uv run pytest
```

CI runs the same three commands on Python 3.11, 3.12 and 3.13, plus a Docker
build.

## Where things live

| Path | What |
| --- | --- |
| `src/voice_agent/server.py` | FastAPI app, WebSocket bridge, guardrails |
| `src/voice_agent/agent.py` | ADK agent definition and system prompt |
| `src/voice_agent/room_tools.py` | Tools the agent can call |
| `src/voice_agent/metrics.py` | Per-turn latency tracking |
| `src/voice_agent/static/` | Browser UI (mic capture, playback, metrics panel) |
| `workshop/` | The step-by-step workshop the app grew out of |
| `docs/` | Architecture and deployment notes |

## Good first contributions

- **Add a tool.** Write a typed function with a docstring in `room_tools.py`
  (or a new module), return `{"status": "success" | "error", ...}` instead of
  raising, register it in `agent.py`, and add a unit test.
- **Another room backend.** Replace the in-memory `ROOMS` list with Google
  Calendar, Microsoft Graph or a JSON file behind the same function signature.
- **AudioWorklet.** Replace the deprecated `ScriptProcessorNode` in `app.js`.
- **Metrics.** Export `turn_metrics` as OpenTelemetry histograms.

Look for issues labelled `good first issue`.

## Guidelines

- Keep PRs focused: one feature or fix per PR.
- Never commit API keys, `.env` files or real transcripts. A test fails if a
  Google API key pattern appears in the repo.
- Logs must not contain transcript text; log IDs, outcomes and timings.
- New behaviour needs a test.

By contributing you agree that your contributions are licensed under the MIT
License.
