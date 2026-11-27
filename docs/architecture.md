# Architecture

The app is a single FastAPI service. The browser streams microphone audio over
one WebSocket, and the server bridges it to a Gemini Live session through
Google ADK. Everything below refers to [`src/voice_agent/server.py`](../src/voice_agent/server.py).

## One conversational turn

```mermaid
sequenceDiagram
    autonumber
    participant B as Browser (mic + speaker)
    participant S as FastAPI /ws
    participant Q as ADK LiveRequestQueue
    participant R as ADK Runner (run_live)
    participant G as Gemini Live
    participant T as find_rooms tool

    B->>S: {"type":"audio", data: PCM16 @16 kHz} (about every 85 ms)
    S->>S: validate size, MIME, Base64
    S->>Q: send_realtime(Blob)
    Q->>R: stream
    R->>G: bidirectional audio stream
    G-->>R: input transcription
    R-->>S: event.input_transcription
    S-->>B: {"type":"transcript","speaker":"you"}
    G-->>R: function_call find_rooms(after_hour, minimum_capacity)
    R->>T: run in tool thread pool (max 4 workers)
    T-->>R: {"status":"success","rooms":[...]}
    R->>G: function_response
    S-->>B: {"type":"tool","phase":"call" / "result"}
    G-->>R: audio chunks (PCM @24 kHz) + output transcription
    R-->>S: events
    S-->>B: {"type":"audio"} … {"type":"transcript","speaker":"agent"}
    G-->>R: turn_complete
    S-->>B: {"type":"turn_complete"} + {"type":"metrics"}
```

Two asyncio tasks run per connection, `browser_to_agent` (upstream) and
`agent_to_browser` (downstream). The server waits on whichever finishes first,
cancels the other, closes the queue and frees the session slot in a `finally`
block, so a dropped tab or a Gemini error never leaks a live session.

## Interruptions (barge-in)

Gemini Live runs voice activity detection on the incoming stream. When the
user starts speaking while the agent is talking:

1. Gemini stops generating and ADK emits an event with `interrupted=True`.
2. The server forwards `{"type":"interrupted"}` immediately.
3. The browser stops every scheduled `AudioBufferSourceNode` and resets its
   playback clock, so stale audio is dropped instead of finishing the old
   sentence.
4. The new utterance is handled as the next turn, and the system prompt tells
   the agent to use the speaker's newest correction ("actually, after three").

The interruption is recorded in the turn metrics, so barge-in rate is visible
in the UI and logs.

## Slow and failing tools

A voice agent cannot go silent for five seconds. The approach, demonstrated in
[`workshop/checkpoints/04_slow_failure`](../workshop/checkpoints/04_slow_failure):

- The agent says it is checking **before** it calls a slow tool.
- Tools return structured errors (`{"status":"error","retryable":true}`) instead
  of raising, so the model can apologise in plain language without leaking a
  stack trace.
- The agent does not retry automatically; it offers another time instead.
- Tool calls run in a bounded thread pool, and `max_llm_calls` caps how many
  model calls one session can make.

## Guardrails at the edge

| Risk | Control |
| --- | --- |
| Cross-site WebSocket hijacking | `Origin` allowlist (`WS_ALLOWED_ORIGINS`), close code 1008 |
| Oversized or malformed frames | 32 KB message cap, 16 KB decoded audio cap, strict JSON, Base64 and MIME checks |
| Quota exhaustion | `MAX_ACTIVE_SESSIONS` (close code 1013 when full), `max_llm_calls=100` |
| Very long sessions | Context window compression (100k trigger, 80k sliding window) and session resumption handles |
| Transcript leakage | Logs carry connection IDs, outcomes and timings only, never transcript text |
| Opaque failures | Users get a short error reference ID; the full trace stays in server logs |

## Measuring latency

[`metrics.py`](../src/voice_agent/metrics.py) turns the event stream into a
record per turn:

| Field | Meaning |
| --- | --- |
| `response_ms` | Last user transcription chunk to first agent audio chunk |
| `tool_ms` | Function call to function response, per call |
| `turn_ms` | First event of the turn to `turn_complete` |
| `interrupted` | Whether the user barged in |

The session also keeps p50/p95 response time, tool p50, turn count and
interruption count. Each turn is logged as one line, for example:

```text
turn_metrics connection_id=3f9c1a2b7d4e turn=2 response_ms=612 turn_ms=4310 tool_ms=[3] interrupted=False
```

and streamed to the browser, where the panel under the connect button shows
the latest values.

**Caveat:** input transcription trails the end of speech slightly, so
`response_ms` is a close lower bound on what the user perceives. Browser
playback buffering adds a little on top. For an end-to-end number, record the
screen with audio and measure from end of speech to first sound.

To collect numbers from a session:

```bash
uv run uvicorn voice_agent.server:app --port 8002 2>&1 | tee session.log
grep turn_metrics session.log
```
