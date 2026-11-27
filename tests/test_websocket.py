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

ORIGIN = {"origin": "http://localhost:8002"}
AUDIO = b"\x01\x02" * 8


def part(*, audio=None, call=None, result=None):
    return SimpleNamespace(
        inline_data=SimpleNamespace(mime_type="audio/pcm;rate=24000", data=audio)
        if audio
        else None,
        function_call=SimpleNamespace(name=call) if call else None,
        function_response=SimpleNamespace(name=result) if result else None,
    )


def event(*, heard=None, said=None, parts=(), interrupted=False, turn_complete=False):
    return SimpleNamespace(
        input_transcription=SimpleNamespace(text=heard) if heard else None,
        output_transcription=SimpleNamespace(text=said) if said else None,
        content=SimpleNamespace(parts=list(parts)) if parts else None,
        interrupted=interrupted,
        turn_complete=turn_complete,
    )


SCRIPT = [
    event(heard="find a room after four for eight people"),
    event(parts=[part(call="find_rooms")]),
    event(parts=[part(result="find_rooms")]),
    event(said="Atlas and Cedar are free.", parts=[part(audio=AUDIO)]),
    event(turn_complete=True),
]


class FakeRunner:
    def __init__(self, script):
        self.script = script
        self.received = []
        self.session_service = SimpleNamespace(create_session=self._create_session)

    async def _create_session(self, app_name, user_id):
        return SimpleNamespace(id="session-1")

    def run_live(self, *, user_id, session_id, live_request_queue, run_config):
        async def events():
            for item in self.script:
                yield item
            await asyncio.Event().wait()  # stay open until the browser disconnects

        return events()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(server, "runner", FakeRunner(SCRIPT))
    monkeypatch.setattr(server, "active_sessions", set())
    return TestClient(server.app)


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
    assert "Room agent" in response.text


def test_full_turn_streams_transcripts_tools_audio_and_metrics(client):
    with client.websocket_connect("/ws", headers=ORIGIN) as ws:
        messages = receive_until(ws, "metrics")

    types = [m["type"] for m in messages]
    assert types == [
        "transcript",
        "tool",
        "tool",
        "transcript",
        "audio",
        "turn_complete",
        "metrics",
    ]
    assert messages[0] == {
        "type": "transcript",
        "speaker": "you",
        "text": "find a room after four for eight people",
    }
    assert [m["phase"] for m in messages if m["type"] == "tool"] == ["call", "result"]
    assert base64.b64decode(messages[4]["data"]) == AUDIO

    metrics = messages[-1]
    assert metrics["turn"]["turn"] == 1
    assert metrics["turn"]["response_ms"] is not None
    assert len(metrics["turn"]["tool_ms"]) == 1
    assert metrics["session"]["turns"] == 1


def test_interruption_is_forwarded(client, monkeypatch):
    script = [
        event(heard="find a room"),
        event(parts=[part(audio=AUDIO)]),
        event(interrupted=True),
        event(turn_complete=True),
    ]
    monkeypatch.setattr(server, "runner", FakeRunner(script))
    with client.websocket_connect("/ws", headers=ORIGIN) as ws:
        messages = receive_until(ws, "metrics")

    assert {"type": "interrupted"} in messages
    assert messages[-1]["turn"]["interrupted"] is True
    assert messages[-1]["session"]["interruptions"] == 1


def test_rejects_unknown_origin(client):
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws", headers={"origin": "https://evil.example"}) as ws:
            ws.receive_json()
    assert exc.value.code == 1008


def test_refuses_sessions_over_capacity(client, monkeypatch):
    monkeypatch.setattr(server, "MAX_ACTIVE_SESSIONS", 1)
    monkeypatch.setattr(server, "active_sessions", {"someone-else"})
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws", headers=ORIGIN) as ws:
            ws.receive_json()
    assert exc.value.code == 1013


def test_invalid_client_message_gets_safe_error(client, monkeypatch):
    monkeypatch.setattr(server, "runner", FakeRunner([]))
    with client.websocket_connect("/ws", headers=ORIGIN) as ws:
        ws.send_text('{"type":"admin"}')
        assert ws.receive_json() == {"type": "error", "message": "Invalid audio message"}


def test_session_slot_is_released_after_disconnect(client):
    with client.websocket_connect("/ws", headers=ORIGIN) as ws:
        receive_until(ws, "metrics")
    for _ in range(50):
        if not server.active_sessions:
            break
        time.sleep(0.01)
    assert server.active_sessions == set()
