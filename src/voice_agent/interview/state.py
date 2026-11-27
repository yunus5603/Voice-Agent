"""Interview progress as plain, JSON-serialisable session state.

The plan is held here, not in the prompt: the interviewer asks for the next
question through a tool, so it cannot skip or repeat questions, and timing is
enforced in code. Every function is pure (state in, new state + result out)
so the logic is unit-tested without ADK or a model.
"""

from __future__ import annotations

import copy
from typing import Any

from voice_agent.interview.models import InterviewPlan, Persona

STATE_KEY = "interview"
MAX_NOTE_CHARS = 300
MAX_NOTES_PER_QUESTION = 5

State = dict[str, Any]


def new_state(plan: InterviewPlan, persona: Persona = Persona.NEUTRAL) -> State:
    return {
        "plan": plan.model_dump(mode="json"),
        "persona": persona.value,
        "status": "ready",
        "index": -1,
        "started_at": None,
        "question_started_at": None,
        "ended_at": None,
        "ended_reason": None,
        "notes": {},
    }


def _budget_seconds(state: State) -> float:
    return state["plan"]["minutes"] * 60


def seconds_left(state: State, now: float) -> float:
    if state["started_at"] is None:
        return _budget_seconds(state)
    return max(0.0, _budget_seconds(state) - (now - state["started_at"]))


def _questions(state: State) -> list[dict]:
    return state["plan"]["questions"]


def next_question(state: State, now: float) -> tuple[State, dict]:
    s = copy.deepcopy(state)
    if s["status"] == "ended":
        return s, {"status": "ended", "instruction": "The interview is over. Do not ask more."}
    questions = _questions(s)
    if s["started_at"] is None:
        s["started_at"] = now
        s["status"] = "in_progress"
    elif seconds_left(s, now) <= 0:
        return s, {
            "status": "time_up",
            "instruction": "Time is up. Thank the candidate warmly and call end_interview.",
        }
    if s["index"] + 1 >= len(questions):
        return s, {
            "status": "no_more_questions",
            "instruction": "All questions are done. Ask if they have a question for you, "
            "answer briefly, then call end_interview.",
        }
    s["index"] += 1
    s["question_started_at"] = now
    q = questions[s["index"]]
    return s, {
        "status": "ok",
        "number": s["index"] + 1,
        "total": len(questions),
        "question": q["text"],
        "probes": q["probes"],
        "follow_ups": q["follow_ups"],
        "minutes_left": round(seconds_left(s, now) / 60, 1),
    }


def time_left(state: State, now: float) -> dict:
    questions = _questions(state)
    remaining_questions = max(0, len(questions) - state["index"] - 1)
    result = {
        "minutes_left": round(seconds_left(state, now) / 60, 1),
        "questions_left": remaining_questions,
    }
    if state["question_started_at"] is not None and state["status"] == "in_progress":
        per_question = _budget_seconds(state) / len(questions)
        on_question = now - state["question_started_at"]
        result["seconds_on_current_question"] = round(on_question)
        if on_question > per_question * 1.25 and remaining_questions:
            result["suggestion"] = "Over time on this question: wrap up kindly and move on."
    return result


def add_note(state: State, note: str, now: float) -> tuple[State, dict]:
    s = copy.deepcopy(state)
    if s["index"] < 0 or s["status"] != "in_progress":
        return s, {"status": "error", "message": "No question is in progress."}
    note = " ".join(note.split())[:MAX_NOTE_CHARS]
    if not note:
        return s, {"status": "error", "message": "The note is empty."}
    qid = _questions(s)[s["index"]]["id"]
    notes = s["notes"].setdefault(qid, [])
    if len(notes) >= MAX_NOTES_PER_QUESTION:
        return s, {"status": "error", "message": "Enough notes for this question."}
    notes.append(note)
    return s, {"status": "ok", "question_id": qid}


def end_interview(state: State, reason: str, now: float) -> tuple[State, dict]:
    s = copy.deepcopy(state)
    if s["status"] != "ended":
        s["status"] = "ended"
        s["ended_at"] = now
        s["ended_reason"] = " ".join(reason.split())[:120] or "completed"
    return s, {"status": "ended", "questions_asked": s["index"] + 1}
