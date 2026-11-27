"""ADK tools the live interviewer calls. Thin wrappers over :mod:`state`."""

from __future__ import annotations

import time

from google.adk.tools import ToolContext

from voice_agent.interview import state as st


def _load(tool_context: ToolContext) -> st.State:
    return tool_context.state[st.STATE_KEY]


def _save(tool_context: ToolContext, new: st.State) -> None:
    # Reassign (never mutate in place) so ADK records the state change.
    tool_context.state[st.STATE_KEY] = new


def next_question(tool_context: ToolContext) -> dict:
    """Get the next planned interview question. Call this to start the interview and
    whenever the current question has been answered and followed up."""
    new, result = st.next_question(_load(tool_context), time.time())
    _save(tool_context, new)
    return result


def add_note(note: str, tool_context: ToolContext) -> dict:
    """Save a short private note about the candidate's answer to the current question,
    such as a specific claim, a missing result, or a strong example.

    Args:
        note: One short sentence, specific to what the candidate said.
    """
    new, result = st.add_note(_load(tool_context), note, time.time())
    _save(tool_context, new)
    return result


def time_left(tool_context: ToolContext) -> dict:
    """Check how much interview time and how many questions are left."""
    return st.time_left(_load(tool_context), time.time())


def end_interview(reason: str, tool_context: ToolContext) -> dict:
    """End the interview after thanking the candidate.

    Args:
        reason: Why it ended, e.g. "completed", "time up", "candidate asked to stop".
    """
    new, result = st.end_interview(_load(tool_context), reason, time.time())
    _save(tool_context, new)
    return result


INTERVIEW_TOOLS = [next_question, add_note, time_left, end_interview]
