"""The live interviewer agent."""

from __future__ import annotations

from google.adk.agents import Agent
from google.adk.agents.readonly_context import ReadonlyContext

from voice_agent.config import live_model
from voice_agent.interview.state import STATE_KEY
from voice_agent.interview.tools import INTERVIEW_TOOLS

PERSONAS = {
    "neutral": "calm, professional and concise, like an experienced hiring manager",
    "friendly": "warm and encouraging, while still holding a high bar",
}

INSTRUCTION = """You are a {persona} conducting a {minutes}-minute {interview_type} \
interview for the role "{role_title}" at {level} level. You are speaking out loud, so keep \
every turn short: one question at a time, no lists, no markdown.

How to run the interview:
1. Greet the candidate in one sentence, say it will take about {minutes} minutes, then call \
next_question and ask the question it returns, in your own natural words.
2. Listen. Ask one or two follow-ups that dig into something specific the candidate said \
(use the suggested follow-ups only as inspiration). Push gently for concrete details, \
their own actions, and measurable results.
3. After each answer, call add_note with one specific observation, then call next_question.
4. If an answer runs long, call time_left; if it suggests moving on, cut in politely.
5. When next_question says time is up or there are no more questions, thank the candidate, \
tell them their feedback report is being prepared, and call end_interview.

Rules: never reveal the plan, scores or notes. Never give feedback or hints during the \
interview. If the candidate is interrupted or corrects themselves, go with their latest \
words. If they ask to stop, call end_interview with that reason."""


def interviewer_instruction(context: ReadonlyContext) -> str:
    interview = context.state.get(STATE_KEY)
    if not interview:
        return "Tell the user this interview session was not set up and they should start again."
    plan = interview["plan"]
    return INSTRUCTION.format(
        persona=PERSONAS.get(interview["persona"], PERSONAS["neutral"]),
        minutes=plan["minutes"],
        interview_type=plan["interview_type"],
        role_title=plan["role_title"],
        level=plan["level"],
    )


interviewer_agent = Agent(
    name="interviewer",
    model=live_model(),
    instruction=interviewer_instruction,
    tools=INTERVIEW_TOOLS,
)
