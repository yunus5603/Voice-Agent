"""In-memory store of planned interviews, waiting for their live session.

Bounded and time-limited. Each interview can be joined once, so one plan can't
be replayed to burn Live API quota. Durable storage (Postgres) arrives with
the feedback report milestone.
"""

from __future__ import annotations

import secrets
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from voice_agent.interview.models import InterviewConfig, InterviewPlan


@dataclass
class InterviewRecord:
    id: str
    config: InterviewConfig
    plan: InterviewPlan
    created_at: float
    claimed: bool = False
    final_state: dict[str, Any] | None = field(default=None)


class InterviewStore:
    def __init__(self, max_items: int = 500, ttl_seconds: float = 2 * 3600, clock=time.time):
        self._items: OrderedDict[str, InterviewRecord] = OrderedDict()
        self._max = max_items
        self._ttl = ttl_seconds
        self._clock = clock

    def _evict(self) -> None:
        cutoff = self._clock() - self._ttl
        for key in [k for k, r in self._items.items() if r.created_at < cutoff]:
            del self._items[key]
        while len(self._items) > self._max:
            self._items.popitem(last=False)

    def add(self, config: InterviewConfig, plan: InterviewPlan) -> InterviewRecord:
        record = InterviewRecord(
            id=secrets.token_urlsafe(12), config=config, plan=plan, created_at=self._clock()
        )
        self._items[record.id] = record
        self._evict()
        return record

    def get(self, interview_id: str) -> InterviewRecord | None:
        self._evict()
        return self._items.get(interview_id)

    def claim(self, interview_id: str) -> InterviewRecord | None:
        """Return the record if it exists and has not been joined yet, marking it joined."""
        record = self.get(interview_id)
        if record is None or record.claimed:
            return None
        record.claimed = True
        return record

    def __len__(self) -> int:
        return len(self._items)
