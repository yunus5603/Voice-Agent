"""Turn a job description into an interview plan.

With a Gemini key, a text model tailors the questions to the job description
and returns a validated ``InterviewPlan`` (structured output). Without a key,
or if the model call fails, the plan comes from the best-matching question
pack, so the app always works and tests never need the network.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

from voice_agent.config import text_model
from voice_agent.interview.models import InterviewConfig, InterviewPlan, question_count
from voice_agent.interview.packs import QuestionPack, best_pack

logger = logging.getLogger(__name__)

PROMPT = """You are planning a {minutes}-minute {interview_type} interview for a {level}-level \
candidate. Write exactly {count} questions tailored to the job description below.

Rules:
- Each question must be answerable out loud in about two minutes.
- Tie questions to the skills and responsibilities in the job description.
- For behavioural interviews, ask for specific past situations.
- For technical interviews, ask design, debugging or trade-off questions, not trivia.
- Give each question a short slug id, one sentence on what it probes, two or three
  follow-ups, and three or four rubric criteria describing a strong answer.
- role_title is the job title from the description.

Example questions in the house style:
{examples}

Job description:
\"\"\"
{job_description}
\"\"\"
"""


def guess_role_title(job_description: str) -> str:
    for line in job_description.splitlines():
        line = re.sub(r"^[#*\-\s]+|[*\s]+$", "", line)
        if line:
            return line[:80]
    return "Software Engineer"


def plan_from_pack(config: InterviewConfig, pack: QuestionPack | None = None) -> InterviewPlan:
    """Deterministic plan from curated questions; used offline and as the fallback."""
    pack = pack or best_pack(config.interview_type, config.job_description)
    questions = pack.with_rubric()[: question_count(config.minutes)]
    return InterviewPlan(
        role_title=guess_role_title(config.job_description),
        summary=f"{pack.title} questions for a {config.level.value}-level candidate.",
        interview_type=config.interview_type,
        level=config.level,
        minutes=config.minutes,
        questions=questions,
    )


def _build_prompt(config: InterviewConfig, pack: QuestionPack) -> str:
    examples = "\n".join(f"- {q.text}" for q in pack.questions[:4])
    return PROMPT.format(
        minutes=config.minutes,
        interview_type=config.interview_type.value,
        level=config.level.value,
        count=question_count(config.minutes),
        examples=examples,
        job_description=config.job_description,
    )


def _normalise(plan: InterviewPlan, config: InterviewConfig, pack: QuestionPack) -> InterviewPlan:
    """Pin the fields the model must not change and repair small gaps."""
    seen: set[str] = set()
    questions = []
    for i, q in enumerate(plan.questions[: question_count(config.minutes)]):
        qid = re.sub(r"[^a-z0-9-]+", "-", q.id.lower()).strip("-") or f"q{i + 1}"
        if qid in seen:
            qid = f"{qid}-{i + 1}"
        seen.add(qid)
        questions.append(
            q.model_copy(update={"id": qid, "criteria": q.criteria or list(pack.criteria)})
        )
    return plan.model_copy(
        update={
            "interview_type": config.interview_type,
            "level": config.level,
            "minutes": config.minutes,
            "questions": questions,
        }
    )


def has_api_key() -> bool:
    return any(
        os.getenv(name, "") not in {"", "replace_me"}
        for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY")
    )


async def create_plan(config: InterviewConfig, client: Any | None = None) -> InterviewPlan:
    """Plan an interview, tailored by Gemini when available, else from a question pack."""
    pack = best_pack(config.interview_type, config.job_description)
    if client is None:
        if not has_api_key():
            return plan_from_pack(config, pack)
        from google import genai

        client = genai.Client()
    try:
        response = await client.aio.models.generate_content(
            model=text_model(),
            contents=_build_prompt(config, pack),
            config={
                "response_mime_type": "application/json",
                "response_schema": InterviewPlan,
                "temperature": 0.4,
            },
        )
        plan = response.parsed
        if not isinstance(plan, InterviewPlan):
            plan = InterviewPlan.model_validate_json(response.text)
        return _normalise(plan, config, pack)
    except Exception:
        logger.warning("planner_fallback reason=model_call_failed", exc_info=True)
        return plan_from_pack(config, pack)
