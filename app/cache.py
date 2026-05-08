"""Clawzd — Cache layer (re-export shim).

This module has been moved to ``app.core.cache``.
This shim exists for backward compatibility — import from ``app.core.cache`` in new code.
"""
from app.core.cache import *  # noqa: F401,F403
from app.core.cache import cache_stats  # noqa: F401 — explicit re-export
