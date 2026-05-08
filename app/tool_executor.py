"""Clawzd — Tool executor (re-export shim).

This module has been moved to ``app.tools.executor``.
This shim exists for backward compatibility — import from ``app.tools.executor`` in new code.
"""
from app.tools.executor import *  # noqa: F401,F403
from app.tools.executor import (  # noqa: F401 — explicit re-exports
    parse_tool_calls,
    execute_tool,
    format_tool_result,
    resolve_tool_name,
)
