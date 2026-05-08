"""Clawzd — RAG (Retrieval-Augmented Generation) (re-export shim).

This module has been moved to ``app.ai_models.rag``.
This shim exists for backward compatibility — import from ``app.ai_models.rag`` in new code.
"""
from app.ai_models.rag import *  # noqa: F401,F403
from app.ai_models.rag import (  # noqa: F401 — explicit re-exports
    router,
    explicit_rag_search,
    auto_rag_context,
    scan_rag_folder,
)