"""Per-turn latency measurement for live voice sessions.

The server feeds every ADK live event into :class:`TurnTracker`. When a turn
completes, the tracker returns a :class:`TurnMetrics` record that is logged
(numbers only, never transcript text) and streamed to the browser panel.

What is measured, all on the server's monotonic clock:

* ``response_ms``: last user transcription chunk -> first agent audio chunk.
  Input transcription trails the user's speech slightly, so this is a close
  lower bound on the latency the user perceives, without browser playback.
* ``tool_ms``: function call -> function response, per tool call.
* ``turn_ms``: first event of the turn -> ``turn_complete``.
* ``interrupted``: whether the user barged in during the turn.
"""

from __future__ import annotations

import statistics
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field

Clock = Callable[[], float]


def _ms(start: float, end: float) -> int:
    return max(0, round((end - start) * 1000))


@dataclass(frozen=True)
class TurnMetrics:
    turn: int
    response_ms: int | None
    turn_ms: int
    tool_ms: list[int]
    interrupted: bool

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SessionStats:
    """Running aggregates across the turns of one live session."""

    turns: int = 0
    interruptions: int = 0
    response_samples: list[int] = field(default_factory=list)
    tool_samples: list[int] = field(default_factory=list)

    def add(self, metrics: TurnMetrics) -> None:
        self.turns += 1
        self.interruptions += int(metrics.interrupted)
        if metrics.response_ms is not None:
            self.response_samples.append(metrics.response_ms)
        self.tool_samples.extend(metrics.tool_ms)

    def to_dict(self) -> dict:
        return {
            "turns": self.turns,
            "interruptions": self.interruptions,
            "response_p50_ms": percentile(self.response_samples, 50),
            "response_p95_ms": percentile(self.response_samples, 95),
            "tool_p50_ms": percentile(self.tool_samples, 50),
        }


def percentile(samples: list[int], pct: int) -> int | None:
    """Nearest-rank percentile; ``None`` when there are no samples."""
    if not samples:
        return None
    if len(samples) == 1:
        return samples[0]
    if pct == 50:
        return round(statistics.median(samples))
    ordered = sorted(samples)
    rank = max(1, -(-pct * len(ordered) // 100))  # ceil without floats
    return ordered[rank - 1]


class TurnTracker:
    """Turns a stream of live events into per-turn timing records."""

    def __init__(self, clock: Clock = time.perf_counter) -> None:
        self._clock = clock
        self._turn = 0
        self.stats = SessionStats()
        self._reset()

    def _reset(self) -> None:
        self._started: float | None = None
        self._last_user_speech: float | None = None
        self._first_response: float | None = None
        self._tool_started: dict[str, list[float]] = {}
        self._tool_ms: list[int] = []
        self._interrupted = False

    def _touch(self) -> float:
        now = self._clock()
        if self._started is None:
            self._started = now
        return now

    def user_speech(self) -> None:
        now = self._touch()
        if self._first_response is None:
            self._last_user_speech = now

    def agent_audio(self) -> None:
        now = self._touch()
        if self._first_response is None:
            self._first_response = now

    def tool_call(self, name: str) -> None:
        self._tool_started.setdefault(name, []).append(self._touch())

    def tool_result(self, name: str) -> None:
        now = self._touch()
        starts = self._tool_started.get(name)
        if starts:
            self._tool_ms.append(_ms(starts.pop(0), now))

    def interrupted(self) -> None:
        self._touch()
        self._interrupted = True

    def turn_complete(self) -> TurnMetrics:
        now = self._touch()
        self._turn += 1
        response_ms = None
        if self._last_user_speech is not None and self._first_response is not None:
            response_ms = _ms(self._last_user_speech, self._first_response)
        metrics = TurnMetrics(
            turn=self._turn,
            response_ms=response_ms,
            turn_ms=_ms(self._started, now),
            tool_ms=list(self._tool_ms),
            interrupted=self._interrupted,
        )
        self.stats.add(metrics)
        self._reset()
        return metrics
