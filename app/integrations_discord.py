"""Clawzd — Discord integration (re-export shim).

This module has been moved to ``app.integrations.discord``.
This shim exists for backward compatibility — import from ``app.integrations.discord`` in new code.
"""
from app.integrations.discord import *  # noqa: F401,F403
from app.integrations.discord import start_discord_bot  # noqa: F401
