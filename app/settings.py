"""Clawzd — Settings management (re-export shim).

This module has been moved to ``app.core.settings``.
This shim exists for backward compatibility — import from ``app.core.settings`` in new code.
"""
from app.core.settings import *  # noqa: F401,F403
from app.core.settings import router, load_settings  # noqa: F401
