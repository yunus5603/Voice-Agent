from google.adk.agents import Agent

from voice_agent.config import live_model
from voice_agent.room_tools import find_rooms

root_agent = Agent(
    name="room_agent",
    model=live_model(),
    instruction=(
        "You are a concise voice assistant for finding meeting rooms. Ask one question at a "
        "time, use find_rooms when you know time and capacity, and use the speaker's newest "
        "correction. Explain tool failures without technical details. This service finds rooms "
        "but never books them."
    ),
    tools=[find_rooms],
)
