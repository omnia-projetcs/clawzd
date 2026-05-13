"""Clawzd — Database layer (re-export shim).

This module has been moved to ``app.core.database``.
This shim exists for backward compatibility — import from ``app.core.database`` in new code.
"""
from app.core.database import *  # noqa: F401,F403
from app.core.database import (  # noqa: F401 — explicit re-exports
    init_db,
    create_session,
    list_sessions,
    get_session,
    update_session,
    delete_session,
    clear_all_sessions,
    clear_session_messages,
    add_message,
    get_messages,
    export_session_markdown,
    auto_title,
    fork_at_message,
    list_branches,
    delete_branch,
)

