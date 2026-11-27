"""End-to-end WebSocket tests with a scripted stand-in for Gemini Live.

No API key or network access is needed: the ADK runner is replaced by a fake
that replays a realistic event sequence (transcripts, a tool call, audio,
turn completion), so the full browser <-> server contract is exercised.
"""

import asyncio
import base64
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from voice_agent import server
from voice_agent.interview.store import InterviewStore
from voice_agent.interview.tools import INTERVIEW_TOOLS

ORIGIN = {"origin": "http://localhost:8002"}
AUDIO = b"\x01\x02" * 8


JOB = (
    "Senior Backend Engineer, Payments\n"
    "Design and run Python APIs on Postgres and Kafka; own reliability and on-call."
)


def part(*, audio=None, call=None, result=None, response=None):
    return SimpleNamespace(
        inline_data=SimpleNamespace(mime_type="audio/pcm;rate=24000", data=audio)
        if audio
        else None,
        function_call=SimpleNamespace(name=call) if call else None,
        function_response=SimpleNamespace(name=result, response=response) if result else None,
    )


def event(*, heard=None, said=None, parts=(), interrupted=False, turn_complete=False):
    return SimpleNamespace(
        input_transcription=SimpleNamespace(text=heard) if heard else None,
        output_transcription=SimpleNamespace(text=said) if said else None,
        content=SimpleNamespace(parts=list(parts)) if parts else None,
        interrupted=interrupted,
        turn_complete=turn_complete,
    )


def tool(name, **args):
    """A scripted tool call; FakeRunner runs the REAL tool against session state."""
    return ("tool", name, args)


TOOLS = {t.__name__: t for t in INTERVIEW_TOOLS}

SCRIPT = [
    tool("next_question"),
    event(said="Tell me about a rate limiter you would design.", parts=[part(audio=AUDIO)]),
    event(turn_complete=True),
    event(heard="I would use a token bucket in Redis"),
    tool("add_note", note="Chose token bucket; no mention of multi-server state."),
    event(said="How does it work across servers?", parts=[part(audio=AUDIO)]),
    event(turn_complete=True),
]


class FakeRunner:
    """Stands in for ADK's InMemoryRunner and Gemini Live."""

    def __init__(self, script):
        self.script = script
        self.sessions = {}
        self.kickoff = None
        self.session_service = SimpleNamespace(
            create_session=self._create_session, get_session=self._get_session
        )

    async def _create_session(self, app_name, user_id, state=None):
        session = SimpleNamespace(id=f"s{len(self.sessions)}", user_id=user_id, state=state or {})
        self.sessions[session.id] = session
        return session

    async def _get_session(self, app_name, user_id, session_id):
        return self.sessions.get(session_id)

    def run_live(self, *, user_id, session_id, live_request_queue, run_config):
        session = self.sessions[session_id]
        self.queue = live_request_queue

        async def events():
            for item in self.script:
                if isinstance(item, tuple):
                    _, name, args = item
                    response = TOOLS[name](
                        tool_context=SimpleNamespace(state=session.state), **args
                    )
                    yield event(parts=[part(call=name)])
                    yield event(parts=[part(result=name, response=response)])
                else:
                    yield item
            await asyncio.Event().wait()  # stay open until the browser disconnects

        return events()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(server, "runner", FakeRunner(SCRIPT))
    monkeypatch.setattr(server, "active_sessions", set())
    monkeypatch.setattr(server, "interviews", InterviewStore())
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    return TestClient(server.app)


def new_interview(client, **overrides):
    body = {"job_description": JOB, "interview_type": "technical", "minutes": 10, **overrides}
    response = client.post("/api/interviews", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def ws_url(interview):
    return f"/ws?interview_id={interview['interview_id']}"


def receive_until(ws, message_type):
    seen = []
    while True:
        message = ws.receive_json()
        seen.append(message)
        if message["type"] == message_type:
            return seen


def test_healthz(client):
    assert client.get("/healthz").json()["status"] == "ok"


def test_index_serves_ui(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Interview" in response.text


def test_create_interview_plans_without_revealing_questions(client):
    interview = new_interview(client)
    assert interview["role_title"] == "Senior Backend Engineer, Payments"
    assert interview["question_count"] == 4
    assert "questions" not in interview


def test_create_interview_validates_input(client):
    assert client.post("/api/interviews", json={"job_description": "too short"}).status_code == 422
    too_long = {"job_description": JOB, "minutes": 90}
    assert client.post("/api/interviews", json=too_long).status_code == 422


def test_live_interview_streams_progress_audio_and_metrics(client):
    interview = new_interview(client)
    with client.websocket_connect(ws_url(interview), headers=ORIGIN) as ws:
        first_turn = receive_until(ws, "metrics")
        second_turn = receive_until(ws, "metrics")

    types = [m["type"] for m in first_turn]
    assert types == ["tool", "tool", "progress", "transcript", "audio", "turn_complete", "metrics"]
    assert first_turn[2] == {"type": "progress", "number": 1, "total": 4}
    assert base64.b64decode(first_turn[4]["data"]) == AUDIO
    assert second_turn[0] == {
        "type": "transcript",
        "speaker": "you",
        "text": "I would use a token bucket in Redis",
    }
    assert second_turn[-1]["turn"]["response_ms"] is not None
    # Question text never reaches the browser outside the spoken transcript.
    assert all("probes" not in m and "follow_ups" not in m for m in first_turn + second_turn)


def test_kickoff_prompt_is_sent_so_the_interviewer_speaks_first(client):
    interview = new_interview(client)
    with client.websocket_connect(ws_url(interview), headers=ORIGIN) as ws:
        receive_until(ws, "metrics")
    queued = server.runner.queue._queue.get_nowait()
    assert queued.content.parts[0].text == server.KICKOFF


def test_final_interview_state_is_saved_after_disconnect(client):
    interview = new_interview(client)
    with client.websocket_connect(ws_url(interview), headers=ORIGIN) as ws:
        receive_until(ws, "metrics")
        receive_until(ws, "metrics")
    for _ in range(50):
        status = client.get(f"/api/interviews/{interview['interview_id']}").json()
        if status["status"] != "joined":
            break
        time.sleep(0.01)
    assert status["status"] == "in_progress"
    assert status["questions_asked"] == 1
    record = server.interviews.get(interview["interview_id"])
    assert list(record.final_state["notes"].values()) == [
        ["Chose token bucket; no mention of multi-server state."]
    ]


def test_interview_end_is_forwarded(client, monkeypatch):
    script = [
        tool("next_question"),
        tool("end_interview", reason="completed"),
        event(turn_complete=True),
    ]
    monkeypatch.setattr(server, "runner", FakeRunner(script))
    interview = new_interview(client)
    with client.websocket_connect(ws_url(interview), headers=ORIGIN) as ws:
        messages = receive_until(ws, "metrics")
    assert {"type": "interview_ended", "questions_asked": 1} in messages


def test_rejects_unknown_interview(client):
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws?interview_id=nope", headers=ORIGIN) as ws:
            ws.receive_json()
    assert exc.value.code == 1008


def test_interview_can_only_be_joined_once(client):
    interview = new_interview(client)
    with client.websocket_connect(ws_url(interview), headers=ORIGIN) as ws:
        receive_until(ws, "metrics")
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(ws_url(interview), headers=ORIGIN) as ws:
            ws.receive_json()
    assert exc.value.code == 1008


def test_interruption_is_forwarded(client, monkeypatch):
    script = [
        event(heard="find a room"),
        event(parts=[part(audio=AUDIO)]),
        event(interrupted=True),
        event(turn_complete=True),
    ]
    monkeypatch.setattr(server, "runner", FakeRunner(script))
    with client.websocket_connect(ws_url(new_interview(client)), headers=ORIGIN) as ws:
        messages = receive_until(ws, "metrics")

    assert {"type": "interrupted"} in messages
    assert messages[-1]["turn"]["interrupted"] is True
    assert messages[-1]["session"]["interruptions"] == 1


def test_rejects_unknown_origin(client):
    with pytest.raises(WebSocketDisconnect) as exc:
        url = ws_url(new_interview(client))
        with client.websocket_connect(url, headers={"origin": "https://evil.example"}) as ws:
            ws.receive_json()
    assert exc.value.code == 1008


def test_refuses_sessions_over_capacity(client, monkeypatch):
    monkeypatch.setattr(server, "MAX_ACTIVE_SESSIONS", 1)
    monkeypatch.setattr(server, "active_sessions", {"someone-else"})
    interview = new_interview(client)
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(ws_url(interview), headers=ORIGIN) as ws:
            ws.receive_json()
    assert exc.value.code == 1013
    # A busy server must not burn the candidate's interview: it can be joined later.
    assert server.interviews.get(interview["interview_id"]).claimed is False


def test_invalid_client_message_gets_safe_error(client, monkeypatch):
    monkeypatch.setattr(server, "runner", FakeRunner([]))
    with client.websocket_connect(ws_url(new_interview(client)), headers=ORIGIN) as ws:
        ws.send_text('{"type":"admin"}')
        assert ws.receive_json() == {"type": "error", "message": "Invalid audio message"}


def test_session_slot_is_released_after_disconnect(client):
    with client.websocket_connect(ws_url(new_interview(client)), headers=ORIGIN) as ws:
        receive_until(ws, "metrics")
    for _ in range(50):
        if not server.active_sessions:
            break
        time.sleep(0.01)
    assert server.active_sessions == set()
