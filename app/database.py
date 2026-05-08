"""Clawzd — Database layer (re-export shim).

This module has been moved to ``app.core.database``.
This shim exists for backward compatibility — import from ``app.core.database`` in new code.
"""
from app.core.database import *  # noqa: F401,F403
from app.core.database import (  # noqa: F401 — explicit re-exports
    init_db,
    create_session,
    get_session,
    add_message,
    get_messages,
    auto_title,
    update_session,
)
