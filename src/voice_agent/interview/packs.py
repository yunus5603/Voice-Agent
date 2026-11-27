"""Question packs: curated, contributor-friendly YAML files of interview questions."""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from voice_agent.interview.models import Criterion, InterviewType, Question

PACKS_DIR = Path(__file__).with_name("packs")


class QuestionPack(BaseModel):
    id: str
    title: str
    interview_type: InterviewType
    keywords: list[str] = Field(default_factory=list)
    criteria: list[Criterion]
    questions: list[Question] = Field(min_length=3)

    def with_rubric(self) -> list[Question]:
        """Questions with the pack's rubric filled in where a question has none."""
        return [
            q if q.criteria else q.model_copy(update={"criteria": list(self.criteria)})
            for q in self.questions
        ]

    def match_score(self, text: str) -> int:
        """How many of the pack's keywords appear in a job description."""
        lowered = text.lower()
        return sum(
            1 for kw in self.keywords if re.search(rf"(?<![a-z]){re.escape(kw)}(?![a-z])", lowered)
        )


@cache
def load_packs(directory: Path = PACKS_DIR) -> tuple[QuestionPack, ...]:
    packs = []
    for path in sorted(directory.glob("*.yaml")):
        packs.append(QuestionPack.model_validate(yaml.safe_load(path.read_text("utf-8"))))
    ids = [p.id for p in packs]
    if len(ids) != len(set(ids)):
        raise ValueError(f"Duplicate question pack ids in {directory}")
    return tuple(packs)


def best_pack(
    interview_type: InterviewType,
    job_description: str,
    packs: tuple[QuestionPack, ...] | None = None,
) -> QuestionPack:
    """The pack of the requested type whose keywords best match the job description."""
    candidates = [p for p in (packs or load_packs()) if p.interview_type == interview_type]
    if not candidates:
        raise LookupError(f"No question pack for {interview_type}")
    # max() keeps the first of equal scores, and packs are sorted by file name.
    return max(candidates, key=lambda p: p.match_score(job_description))
