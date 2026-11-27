"""Typed contracts for an interview: what the candidate asks for and what gets planned."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class InterviewType(StrEnum):
    BEHAVIORAL = "behavioral"
    TECHNICAL = "technical"


class Level(StrEnum):
    JUNIOR = "junior"
    MID = "mid"
    SENIOR = "senior"


class Persona(StrEnum):
    NEUTRAL = "neutral"
    FRIENDLY = "friendly"


class InterviewConfig(BaseModel):
    """What the candidate submits on the setup screen."""

    job_description: str = Field(min_length=40, max_length=8000)
    interview_type: InterviewType = InterviewType.BEHAVIORAL
    level: Level = Level.MID
    minutes: int = Field(default=10, ge=5, le=30)
    persona: Persona = Persona.NEUTRAL


class Criterion(BaseModel):
    name: str = Field(description="Short rubric criterion name, e.g. 'Result'.")
    description: str = Field(description="What a strong answer shows for this criterion.")


class Question(BaseModel):
    id: str = Field(description="Stable slug, e.g. 'incident-response'.")
    text: str = Field(description="The question exactly as the interviewer should ask it.")
    probes: str = Field(description="What this question is testing, in one sentence.")
    follow_ups: list[str] = Field(
        default_factory=list,
        description="Two or three follow-up questions to dig deeper.",
    )
    criteria: list[Criterion] = Field(
        default_factory=list,
        description="Rubric used to score the answer after the interview.",
    )


class InterviewPlan(BaseModel):
    role_title: str = Field(description="The job title the interview is for.")
    summary: str = Field(description="One sentence on what the interview focuses on.")
    interview_type: InterviewType
    level: Level
    minutes: int
    questions: list[Question] = Field(min_length=1, max_length=8)


def question_count(minutes: int) -> int:
    """About 2.5 minutes per question including follow-ups, between 3 and 6 questions."""
    return max(3, min(6, round(minutes / 2.5)))
