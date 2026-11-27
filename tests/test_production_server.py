import base64
import json

import pytest

from voice_agent import server as production_server


def test_production_server_validates_audio_messages():
    audio = b"\x00\x01\x02\x03"
    raw_message = json.dumps(
        {
            "type": "audio",
            "mime_type": "audio/pcm;rate=16000",
            "data": base64.b64encode(audio).decode("ascii"),
        }
    )
    message = production_server.parse_client_message(raw_message)
    assert production_server.decode_audio(message) == audio


def test_production_server_rejects_unknown_message_types():
    with pytest.raises(production_server.ClientMessageError):
        production_server.parse_client_message('{"type":"admin"}')


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        "[1, 2, 3]",
        json.dumps({"type": "audio", "data": "x" * 40_000}),
    ],
)
def test_production_server_rejects_malformed_messages(raw):
    with pytest.raises(production_server.ClientMessageError):
        production_server.parse_client_message(raw)


@pytest.mark.parametrize(
    "message",
    [
        {"type": "audio", "mime_type": "audio/wav", "data": "AAAA"},
        {"type": "audio", "data": "!!!not-base64!!!"},
        {"type": "audio", "data": ""},
        {"type": "audio"},
    ],
)
def test_production_server_rejects_bad_audio(message):
    with pytest.raises(production_server.ClientMessageError):
        production_server.decode_audio(message)


def test_production_run_config_has_session_guards():
    run_config = production_server.build_run_config()
    assert run_config.max_llm_calls == 100
    assert run_config.session_resumption is not None
    assert run_config.session_resumption.transparent is None
    assert run_config.context_window_compression.trigger_tokens == 100_000
    assert run_config.context_window_compression.sliding_window.target_tokens == 80_000
    assert run_config.tool_thread_pool_config.max_workers == 4
