"""Clawzd — Model manager (re-export shim).

This module has been moved to ``app.ai_models.manager``.
This shim exists for backward compatibility — import from ``app.ai_models.manager`` in new code.
"""
from app.ai_models.manager import *  # noqa: F401,F403
from app.ai_models.manager import router  # noqa: F401
