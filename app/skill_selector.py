"""Clawzd — Skill selector (re-export shim).

This module has been moved to ``app.skills.selector``.
This shim exists for backward compatibility — import from ``app.skills.selector`` in new code.
"""
from app.skills.selector import *  # noqa: F401,F403
from app.skills.selector import (  # noqa: F401
    select_skills,
    get_skill_description,
    get_skill_catalog_entry,
    get_skill_full_instructions,
)

