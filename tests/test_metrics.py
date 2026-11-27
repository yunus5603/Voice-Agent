from voice_agent.metrics import TurnTracker, percentile


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_response_latency_runs_from_last_user_speech_to_first_audio():
    clock = FakeClock()
    tracker = TurnTracker(clock)

    tracker.user_speech()
    clock.advance(0.8)
    tracker.user_speech()  # user keeps talking; latency starts from the last chunk
    clock.advance(0.35)
    tracker.agent_audio()
    clock.advance(0.5)
    tracker.agent_audio()  # later chunks do not move the first-response mark
    clock.advance(0.1)
    metrics = tracker.turn_complete()

    assert metrics.turn == 1
    assert metrics.response_ms == 350
    assert metrics.turn_ms == 1750
    assert metrics.tool_ms == []
    assert metrics.interrupted is False


def test_tool_durations_and_interruptions_are_recorded():
    clock = FakeClock()
    tracker = TurnTracker(clock)

    tracker.user_speech()
    clock.advance(0.2)
    tracker.tool_call("find_rooms")
    clock.advance(0.04)
    tracker.tool_result("find_rooms")
    clock.advance(0.3)
    tracker.agent_audio()
    tracker.interrupted()
    metrics = tracker.turn_complete()

    assert metrics.tool_ms == [40]
    assert metrics.response_ms == 540
    assert metrics.interrupted is True
    assert tracker.stats.interruptions == 1


def test_turn_without_user_speech_has_no_response_latency():
    tracker = TurnTracker(FakeClock())
    tracker.agent_audio()
    assert tracker.turn_complete().response_ms is None


def test_session_stats_aggregate_across_turns():
    clock = FakeClock()
    tracker = TurnTracker(clock)
    for latency in (0.3, 0.5, 0.9):
        tracker.user_speech()
        clock.advance(latency)
        tracker.agent_audio()
        tracker.turn_complete()

    stats = tracker.stats.to_dict()
    assert stats["turns"] == 3
    assert stats["response_p50_ms"] == 500
    assert stats["response_p95_ms"] == 900
    assert stats["tool_p50_ms"] is None


def test_percentile_edge_cases():
    assert percentile([], 95) is None
    assert percentile([120], 95) == 120
    assert percentile(list(range(1, 101)), 95) == 95
