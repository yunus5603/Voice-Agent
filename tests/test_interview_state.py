"""Interview progress logic, including the milestone gate: a scripted
interviewer completes a full 5-question interview through the real tools."""

from types import SimpleNamespace

import pytest

from voice_agent.interview import state as st
from voice_agent.interview import tools
from voice_agent.interview.models import InterviewConfig, InterviewType, Persona
from voice_agent.interview.planner import plan_from_pack

JOB = "Machine Learning Engineer\nBuild RAG and LLM evaluation pipelines in Python."


def plan(minutes=12, interview_type=InterviewType.TECHNICAL):
    return plan_from_pack(
        InterviewConfig(job_description=JOB, interview_type=interview_type, minutes=minutes)
    )


def test_new_state_is_json_ready_and_not_started():
    s = st.new_state(plan(), Persona.FRIENDLY)
    assert s["status"] == "ready"
    assert s["persona"] == "friendly"
    assert s["index"] == -1
    assert isinstance(s["plan"]["questions"][0]["text"], str)


def test_questions_come_in_order_and_run_out():
    s = st.new_state(plan(minutes=7))  # 3 questions
    numbers = []
    for t in range(3):
        s, result = st.next_question(s, now=100.0 + t)
        numbers.append(result["number"])
    assert numbers == [1, 2, 3]
    s, result = st.next_question(s, now=104.0)
    assert result["status"] == "no_more_questions"
    assert s["index"] == 2


def test_time_up_stops_new_questions():
    s = st.new_state(plan(minutes=10))
    s, _ = st.next_question(s, now=0.0)
    s, result = st.next_question(s, now=601.0)
    assert result["status"] == "time_up"
    assert st.time_left(s, now=601.0)["minutes_left"] == 0


def test_time_left_suggests_moving_on_when_a_question_overruns():
    s = st.new_state(plan(minutes=10))  # 4 questions: 150 s each
    s, _ = st.next_question(s, now=0.0)
    assert "suggestion" not in st.time_left(s, now=100.0)
    late = st.time_left(s, now=200.0)
    assert late["suggestion"].startswith("Over time")
    assert late["questions_left"] == 3


def test_notes_are_bounded_and_attached_to_the_current_question():
    s = st.new_state(plan())
    s, result = st.add_note(s, "too early", now=0.0)
    assert result["status"] == "error"
    s, q = st.next_question(s, now=0.0)
    s, result = st.add_note(s, "  Named   recall@k  " + "x" * 400, now=1.0)
    qid = result["question_id"]
    assert len(s["notes"][qid][0]) == st.MAX_NOTE_CHARS
    assert s["notes"][qid][0].startswith("Named recall@k")
    for _ in range(10):
        s, result = st.add_note(s, "more", now=2.0)
    assert len(s["notes"][qid]) == st.MAX_NOTES_PER_QUESTION
    assert result["status"] == "error"


def test_state_functions_do_not_mutate_their_input():
    s = st.new_state(plan())
    before = repr(s)
    st.next_question(s, now=0.0)
    assert repr(s) == before


def test_end_is_final_and_idempotent():
    s = st.new_state(plan())
    s, _ = st.next_question(s, now=0.0)
    s, result = st.end_interview(s, "candidate asked to stop", now=30.0)
    assert result == {"status": "ended", "questions_asked": 1}
    s, again = st.end_interview(s, "other", now=40.0)
    assert s["ended_reason"] == "candidate asked to stop"
    assert st.next_question(s, now=41.0)[1]["status"] == "ended"


@pytest.fixture
def frozen_time(monkeypatch):
    clock = SimpleNamespace(now=1_000.0)
    monkeypatch.setattr(tools.time, "time", lambda: clock.now)
    return clock


def test_gate_scripted_interviewer_completes_a_five_question_interview(frozen_time):
    """Milestone 1 gate: drive the real ADK tools the way the live agent does."""
    ctx = SimpleNamespace(state={st.STATE_KEY: st.new_state(plan(minutes=12))})  # 5 questions
    asked = []
    while True:
        result = tools.next_question(tool_context=ctx)
        if result["status"] != "ok":
            break
        asked.append(result["question"])
        frozen_time.now += 90  # candidate answers
        assert (
            tools.add_note(f"Answer {result['number']} was specific", tool_context=ctx)["status"]
            == "ok"
        )
        assert tools.time_left(tool_context=ctx)["questions_left"] == 5 - result["number"]
        frozen_time.now += 45  # follow-up

    assert result["status"] == "no_more_questions"
    assert tools.end_interview("completed", tool_context=ctx) == {
        "status": "ended",
        "questions_asked": 5,
    }
    final = ctx.state[st.STATE_KEY]
    assert len(asked) == len(set(asked)) == 5
    assert final["status"] == "ended"
    assert len(final["notes"]) == 5


def test_tool_declarations_hide_tool_context_from_the_model():
    from google.adk.tools import FunctionTool

    params = {}
    for fn in tools.INTERVIEW_TOOLS:
        decl = FunctionTool(fn)._get_declaration()
        schema = decl.parameters_json_schema or {}
        params[decl.name] = sorted(schema.get("properties", {}))
    assert params == {
        "next_question": [],
        "add_note": ["note"],
        "time_left": [],
        "end_interview": ["reason"],
    }
