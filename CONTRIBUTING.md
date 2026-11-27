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
| `src/voice_agent/server.py` | FastAPI app: REST API, WebSocket bridge, guardrails |
| `src/voice_agent/interview/` | Planner, question packs, interview state, tools, interviewer agent |
| `src/voice_agent/interview/packs/` | Question packs (YAML) |
| `src/voice_agent/metrics.py` | Per-turn latency tracking |
| `src/voice_agent/static/` | Browser UI (setup, interview room, mic capture, playback) |
| `workshop/` | The step-by-step workshop the app grew out of |
| `docs/` | Architecture and deployment notes |

## Good first contributions

- **Add a question pack.** Copy `src/voice_agent/interview/packs/backend.yaml`,
  set a new `id`, `title`, `interview_type` and `keywords` (words that appear in
  matching job descriptions), and write at least 6 questions with what each
  probes and two follow-ups. `uv run pytest tests/test_planner.py` validates it.
  Wanted: frontend, data engineering, DevOps/SRE, product management, mobile.
- **A new interviewer persona.** Add one to `Persona` and `PERSONAS` in
  `interview/agent.py`, with a test.
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
