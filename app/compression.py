"""Clawzd — Context compression (re-export shim).

This module has been moved to ``app.core.compression``.
This shim exists for backward compatibility — import from ``app.core.compression`` in new code.
"""
from app.core.compression import *  # noqa: F401,F403
from app.core.compression import optimize_for_provider  # noqa: F401
