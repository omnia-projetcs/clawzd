"""Clawzd — Playbook engine (re-export shim).

This module has been moved to ``app.automation.playbook``.
This shim exists for backward compatibility — import from ``app.automation.playbook`` in new code.
"""
from app.automation.playbook import *  # noqa: F401,F403
from app.automation.playbook import router  # noqa: F401
