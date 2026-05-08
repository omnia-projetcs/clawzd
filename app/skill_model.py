"""Clawzd — Skill model (re-export shim).

This module has been moved to ``app.skills.model``.
This shim exists for backward compatibility — import from ``app.skills.model`` in new code.
"""
from app.skills.model import *  # noqa: F401,F403
from app.skills.model import (  # noqa: F401 — explicit re-exports
    BaseSkill,
    SkillContext,
    SkillResult,
    SKILL_CATEGORIES,
    generate_skill_template,
)
