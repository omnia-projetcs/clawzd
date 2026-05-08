"""Clawzd — Telegram integration (re-export shim).

This module has been moved to ``app.integrations.telegram``.
This shim exists for backward compatibility — import from ``app.integrations.telegram`` in new code.
"""
from app.integrations.telegram import *  # noqa: F401,F403
from app.integrations.telegram import router  # noqa: F401
