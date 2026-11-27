"""Checkpoint 06 graduated into the main application in ``src/voice_agent``.

This shim keeps the workshop command working:

    cd workshop/checkpoints/06_production
    uv run uvicorn server:app --reload --port 8002
"""

from voice_agent.server import app

__all__ = ["app"]
