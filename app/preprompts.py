"""Clawzd — Preprompts/system prompts (re-export shim).

This module has been moved to ``app.core.preprompts``.
This shim exists for backward compatibility — import from ``app.core.preprompts`` in new code.
"""
from app.core.preprompts import *  # noqa: F401,F403
from app.core.preprompts import (  # noqa: F401 — explicit re-exports
    get_preprompt,
    list_preprompts,
    get_jailbreak_wrapper,
    _load_dev_profile,
)
