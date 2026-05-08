"""Clawzd — Memory management (re-export shim).

This module has been moved to ``app.core.memory``.
This shim exists for backward compatibility — import from ``app.core.memory`` in new code.
"""
from app.core.memory import *  # noqa: F401,F403
from app.core.memory import (  # noqa: F401 — explicit re-exports
    router,
    build_memory_prompt,
    MEMORY_GUIDANCE,
    handle_memory_tool,
    optimize_memory_files,
)
