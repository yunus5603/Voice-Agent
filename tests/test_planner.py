import asyncio
from types import SimpleNamespace

import pytest

from voice_agent.interview.models import (
    InterviewConfig,
    InterviewPlan,
    InterviewType,
    Level,
    question_count,
)
from voice_agent.interview.packs import best_pack, load_packs
from voice_agent.interview.planner import create_plan, guess_role_title, plan_from_pack

BACKEND_JD = "Backend Engineer\nBuild REST APIs in Python with Postgres, Redis and Kafka."
ML_JD = "## AI Engineer\nShip LLM features: RAG, embeddings and evaluation with PyTorch."


@pytest.fixture(autouse=True)
def no_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)


def config(jd=BACKEND_JD, **kw):
    return InterviewConfig(job_description=jd, interview_type=InterviewType.TECHNICAL, **kw)


@pytest.mark.parametrize("minutes,expected", [(5, 3), (10, 4), (12, 5), (15, 6), (30, 6)])
def test_question_count_scales_with_length(minutes, expected):
    assert question_count(minutes) == expected


def test_packs_are_valid_and_unique():
    packs = load_packs()
    assert {p.id for p in packs} >= {"behavioral", "backend", "ml-engineer"}
    for pack in packs:
        ids = [q.id for q in pack.questions]
        assert len(ids) == len(set(ids)), pack.id
        assert len(pack.questions) >= 6, f"{pack.id} needs 6 questions for a 15-minute interview"
        assert all(q.criteria for q in pack.with_rubric())


def test_best_pack_matches_the_job_description():
    assert best_pack(InterviewType.TECHNICAL, BACKEND_JD).id == "backend"
    assert best_pack(InterviewType.TECHNICAL, ML_JD).id == "ml-engineer"
    assert best_pack(InterviewType.BEHAVIORAL, ML_JD).id == "behavioral"


def test_keyword_match_is_whole_word():
    pack = next(p for p in load_packs() if p.id == "ml-engineer")
    assert pack.match_score("We value email etiquette") == 0  # "ai" and "ml" inside words


def test_guess_role_title_strips_markdown():
    assert guess_role_title(ML_JD) == "AI Engineer"
    assert guess_role_title("\n\n  **Data Engineer**  \nmore") == "Data Engineer"


def test_offline_plan_without_api_key():
    plan = asyncio.run(create_plan(config(minutes=10, level=Level.SENIOR)))
    assert plan.role_title == "Backend Engineer"
    assert plan.level is Level.SENIOR
    assert len(plan.questions) == 4
    assert all(q.criteria for q in plan.questions)


class FakeModels:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, []

    async def generate_content(self, *, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        if self.error:
            raise self.error
        return SimpleNamespace(parsed=self.result, text=None)


def fake_client(models):
    return SimpleNamespace(aio=SimpleNamespace(models=models))


def test_gemini_plan_is_tailored_and_normalised():
    base = plan_from_pack(config(minutes=15))
    messy = base.model_copy(
        update={
            "minutes": 99,
            "level": Level.JUNIOR,
            "questions": [
                q.model_copy(update={"id": "Same ID!", "criteria": []}) for q in base.questions
            ]
            + base.questions[:2],
        }
    )
    models = FakeModels(result=messy)
    plan = asyncio.run(create_plan(config(minutes=10), client=fake_client(models)))

    call = models.calls[0]
    assert call["config"]["response_schema"] is InterviewPlan
    assert "Write exactly 4 questions" in call["contents"]
    assert BACKEND_JD in call["contents"]
    assert plan.minutes == 10 and plan.level is Level.MID  # pinned to the request
    assert len(plan.questions) == 4
    assert len({q.id for q in plan.questions}) == 4
    assert plan.questions[0].id == "same-id"
    assert all(q.criteria for q in plan.questions)  # filled from the pack rubric


def test_model_failure_falls_back_to_question_pack():
    models = FakeModels(error=RuntimeError("quota"))
    plan = asyncio.run(create_plan(config(minutes=10), client=fake_client(models)))
    assert [q.id for q in plan.questions] == [q.id for q in plan_from_pack(config()).questions]
