"""Clawzd — Skill registry (re-export shim).

This module has been moved to ``app.skills.registry``.
This shim exists for backward compatibility — import from ``app.skills.registry`` in new code.
"""
from app.skills.registry import *  # noqa: F401,F403
from app.skills.registry import (  # noqa: F401 — explicit re-exports
    get_registry,
    SKILLS_DIR,
    load_active_skills,
)
