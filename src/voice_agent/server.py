from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import json
import logging
import os
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from google.adk.agents import LiveRequestQueue
from google.adk.agents.run_config import RunConfig, StreamingMode, ToolThreadPoolConfig
from google.adk.runners import InMemoryRunner
from google.genai import errors as genai_errors
from google.genai import types

from voice_agent import __version__
from voice_agent.interview.agent import interviewer_agent
from voice_agent.interview.models import InterviewConfig
from voice_agent.interview.planner import create_plan
from voice_agent.interview.state import STATE_KEY, new_state
from voice_agent.interview.store import InterviewStore
from voice_agent.metrics import TurnTracker

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("voice_agent.server")

APP_NAME = "voice-interview-coach"
STATIC_DIR = Path(__file__).resolve().with_name("static")
MAX_WS_MESSAGE_BYTES = int(os.getenv("MAX_WS_MESSAGE_BYTES", "32768"))
MAX_AUDIO_CHUNK_BYTES = int(os.getenv("MAX_AUDIO_CHUNK_BYTES", "16384"))
MAX_ACTIVE_SESSIONS = int(os.getenv("MAX_ACTIVE_SESSIONS", "20"))
ALLOWED_ORIGINS = {
    origin.strip()
    for origin in os.getenv(
        "WS_ALLOWED_ORIGINS",
        "http://127.0.0.1:8002,http://localhost:8002",
    ).split(",")
    if origin.strip()
}

runner = InMemoryRunner(app_name=APP_NAME, agent=interviewer_agent)
interviews = InterviewStore()
active_sessions: set[str] = set()
active_sessions_lock = asyncio.Lock()

app = FastAPI(title="Voice Interview Coach", version=__version__)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class ClientMessageError(ValueError):
    """Raised when a browser message violates the WebSocket contract."""


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/healthz")
async def healthz() -> dict:
    """Liveness probe for Cloud Run and other orchestrators."""
    return {"status": "ok", "version": __version__}


@app.post("/api/interviews", status_code=201)
async def create_interview(config: InterviewConfig) -> dict:
    """Plan an interview from a job description. The questions stay server-side."""
    plan = await create_plan(config)
    record = interviews.add(config, plan)
    logger.info(
        "interview_planned interview_id=%s type=%s questions=%d",
        record.id,
        plan.interview_type.value,
        len(plan.questions),
    )
    return {
        "interview_id": record.id,
        "role_title": plan.role_title,
        "summary": plan.summary,
        "minutes": plan.minutes,
        "question_count": len(plan.questions),
    }


@app.get("/api/interviews/{interview_id}")
async def get_interview(interview_id: str) -> dict:
    record = interviews.get(interview_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Interview not found")
    state = record.final_state or {}
    return {
        "interview_id": record.id,
        "role_title": record.plan.role_title,
        "status": state.get("status", "joined" if record.claimed else "ready"),
        "questions_asked": state.get("index", -1) + 1,
        "question_count": len(record.plan.questions),
    }


def is_normal_close(exc: Exception) -> bool:
    return isinstance(exc, genai_errors.APIError) and exc.status_code == 1000


def transcript_text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return getattr(value, "text", None)


def parse_client_message(raw_message: str) -> dict:
    if len(raw_message.encode("utf-8")) > MAX_WS_MESSAGE_BYTES:
        raise ClientMessageError("Message is too large")
    try:
        message = json.loads(raw_message)
    except json.JSONDecodeError as exc:
        raise ClientMessageError("Message must be valid JSON") from exc
    if not isinstance(message, dict):
        raise ClientMessageError("Message must be a JSON object")
    if message.get("type") not in {
        "audio",
        "activity_start",
        "activity_end",
        "audio_stream_end",
    }:
        raise ClientMessageError("Unsupported message type")
    return message


def decode_audio(message: dict) -> bytes:
    if message.get("mime_type", "audio/pcm;rate=16000") != "audio/pcm;rate=16000":
        raise ClientMessageError("Unsupported audio format")
    encoded = message.get("data")
    if not isinstance(encoded, str):
        raise ClientMessageError("Audio data is required")
    try:
        audio = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ClientMessageError("Audio data is invalid") from exc
    if not audio or len(audio) > MAX_AUDIO_CHUNK_BYTES:
        raise ClientMessageError("Audio chunk size is invalid")
    return audio


def build_run_config() -> RunConfig:
    return RunConfig(
        streaming_mode=StreamingMode.BIDI,
        response_modalities=[types.Modality.AUDIO],
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        # Gemini API keys support standard session-resumption handles. The
        # transparent mode is reserved for the Vertex AI backend.
        session_resumption=types.SessionResumptionConfig(),
        context_window_compression=types.ContextWindowCompressionConfig(
            trigger_tokens=100_000,
            sliding_window=types.SlidingWindow(target_tokens=80_000),
        ),
        tool_thread_pool_config=ToolThreadPoolConfig(max_workers=4),
        max_llm_calls=100,
    )


async def browser_to_agent(websocket: WebSocket, queue: LiveRequestQueue) -> None:
    """Validate browser messages before adding them to the LiveRequestQueue."""
    while True:
        message = parse_client_message(await websocket.receive_text())
        message_type = message["type"]
        if message_type == "audio":
            queue.send_realtime(
                types.Blob(data=decode_audio(message), mime_type="audio/pcm;rate=16000")
            )
        elif message_type == "activity_start":
            queue.send_activity_start()
        elif message_type == "activity_end":
            queue.send_activity_end()
        elif message_type == "audio_stream_end":
            queue.send_audio_stream_end()


async def agent_to_browser(
    websocket: WebSocket,
    events,
    tracker: TurnTracker | None = None,
    connection_id: str = "-",
) -> None:
    """Forward audio and safe event metadata without logging transcript content."""
    tracker = tracker or TurnTracker()
    async for event in events:
        input_text = transcript_text(getattr(event, "input_transcription", None))
        output_text = transcript_text(getattr(event, "output_transcription", None))
        if input_text:
            tracker.user_speech()
            await websocket.send_json({"type": "transcript", "speaker": "you", "text": input_text})
        if output_text:
            await websocket.send_json(
                {"type": "transcript", "speaker": "agent", "text": output_text}
            )

        for part in event.content.parts if event.content and event.content.parts else []:
            mime_type = part.inline_data.mime_type if part.inline_data else None
            if part.inline_data and mime_type and mime_type.startswith("audio/pcm"):
                tracker.agent_audio()
                await websocket.send_json(
                    {
                        "type": "audio",
                        "mime_type": mime_type,
                        "data": base64.b64encode(part.inline_data.data).decode("ascii"),
                    }
                )
            if part.function_call:
                tracker.tool_call(part.function_call.name)
                await websocket.send_json(
                    {"type": "tool", "phase": "call", "name": part.function_call.name}
                )
            if part.function_response:
                tracker.tool_result(part.function_response.name)
                await websocket.send_json(
                    {"type": "tool", "phase": "result", "name": part.function_response.name}
                )
                progress = progress_event(part.function_response)
                if progress:
                    await websocket.send_json(progress)

        if event.interrupted:
            tracker.interrupted()
            await websocket.send_json({"type": "interrupted"})
        if event.turn_complete:
            metrics = tracker.turn_complete()
            logger.info(
                "turn_metrics connection_id=%s turn=%d response_ms=%s turn_ms=%d "
                "tool_ms=%s interrupted=%s",
                connection_id,
                metrics.turn,
                metrics.response_ms,
                metrics.turn_ms,
                metrics.tool_ms,
                metrics.interrupted,
            )
            await websocket.send_json({"type": "turn_complete"})
            await websocket.send_json(
                {
                    "type": "metrics",
                    "turn": metrics.to_dict(),
                    "session": tracker.stats.to_dict(),
                }
            )


KICKOFF = "(The candidate has joined the call. Greet them and begin the interview.)"


def progress_event(function_response) -> dict | None:
    """Browser-facing progress for interview tools; never exposes question text."""
    response = function_response.response or {}
    if function_response.name == "next_question" and response.get("status") == "ok":
        return {"type": "progress", "number": response["number"], "total": response["total"]}
    if function_response.name == "end_interview":
        return {"type": "interview_ended", "questions_asked": response.get("questions_asked")}
    return None


@app.websocket("/ws")
async def voice_socket(websocket: WebSocket, interview_id: str = "") -> None:
    origin = websocket.headers.get("origin")
    if origin not in ALLOWED_ORIGINS:
        await websocket.close(code=1008, reason="Origin not allowed")
        return
    connection_id = uuid4().hex[:12]
    async with active_sessions_lock:
        has_capacity = len(active_sessions) < MAX_ACTIVE_SESSIONS
        if has_capacity:
            active_sessions.add(connection_id)
    if not has_capacity:
        await websocket.close(code=1013, reason="Server is busy")
        return
    record = interviews.claim(interview_id)
    if record is None:
        async with active_sessions_lock:
            active_sessions.discard(connection_id)
        await websocket.close(code=1008, reason="Unknown or already used interview")
        return

    queue: LiveRequestQueue | None = None
    tasks: list[asyncio.Task] = []
    session = None
    try:
        await websocket.accept()
        logger.info("live_session_started connection_id=%s", connection_id)

        user_id = f"user-{uuid4().hex[:8]}"
        session = await runner.session_service.create_session(
            app_name=APP_NAME,
            user_id=user_id,
            state={STATE_KEY: new_state(record.plan, record.config.persona)},
        )
        queue = LiveRequestQueue()
        queue.send_content(types.Content(role="user", parts=[types.Part(text=KICKOFF)]))
        events = runner.run_live(
            user_id=user_id,
            session_id=session.id,
            live_request_queue=queue,
            run_config=build_run_config(),
        )

        upstream = asyncio.create_task(browser_to_agent(websocket, queue))
        downstream = asyncio.create_task(
            agent_to_browser(websocket, events, TurnTracker(), connection_id)
        )
        tasks = [upstream, downstream]
        done, pending = await asyncio.wait(
            {upstream, downstream}, return_when=asyncio.FIRST_COMPLETED
        )
        for task in done:
            task.result()
        for task in pending:
            task.cancel()
    except WebSocketDisconnect:
        pass
    except ClientMessageError as exc:
        logger.warning("client_message_rejected connection_id=%s reason=%s", connection_id, exc)
        with contextlib.suppress(Exception):
            await websocket.send_json({"type": "error", "message": "Invalid audio message"})
            await websocket.close(code=1008)
    except Exception as exc:
        error_id = uuid4().hex[:10]
        if not is_normal_close(exc):
            logger.exception(
                "live_session_failed connection_id=%s error_id=%s",
                connection_id,
                error_id,
            )
            with contextlib.suppress(Exception):
                await websocket.send_json(
                    {"type": "error", "message": f"Live session ended ({error_id})"}
                )
    finally:
        if queue is not None:
            queue.close()
        async with active_sessions_lock:
            active_sessions.discard(connection_id)
        for task in tasks:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        if session is not None:
            with contextlib.suppress(Exception):
                final = await runner.session_service.get_session(
                    app_name=APP_NAME, user_id=session.user_id, session_id=session.id
                )
                record.final_state = (final.state if final else {}).get(STATE_KEY)
        logger.info("live_session_ended connection_id=%s interview_id=%s", connection_id, record.id)
