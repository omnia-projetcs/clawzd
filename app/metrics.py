"""Clawzd — Metrics collection (re-export shim).

This module has been moved to ``app.core.metrics``.
This shim exists for backward compatibility — import from ``app.core.metrics`` in new code.
"""
from app.core.metrics import *  # noqa: F401,F403
from app.core.metrics import get_metrics  # noqa: F401
