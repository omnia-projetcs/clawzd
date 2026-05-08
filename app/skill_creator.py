"""Clawzd — Dynamic skill creation engine (re-export shim).

This module has been moved to ``app.skills.creator``.
This shim exists for backward compatibility — import from ``app.skills.creator`` in new code.
"""
from app.skills.creator import *  # noqa: F401,F403
from app.skills.creator import create_skill_core  # noqa: F401
