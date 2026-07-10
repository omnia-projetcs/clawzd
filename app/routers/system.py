"""
Clawzd — System / Health / Metrics router.
Extracted from the monolithic gateway.py for better maintainability.
Contains health checks, metrics, token usage, and token prefetch endpoints.
"""
import asyncio
import os as _os
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.core.metrics import get_metrics
from app.cache import cache_stats
from config import OLLAMA_HOST, DB_PATH, CHROMA_DB_PATH, OLLAMA_VERIFY_SSL

router = APIRouter(tags=["system"])


def _safe_ollama_probe_url(base_url: str) -> str:
    """Build a fast health-check URL without localhost DNS resolution."""
    from urllib.parse import urlparse

    parsed = urlparse(base_url)
    if parsed.hostname in {"localhost", "::1"}:
        netloc = "127.0.0.1"
        if parsed.port:
            netloc = f"{netloc}:{parsed.port}"
        parsed = parsed._replace(netloc=netloc)
    # Always use /api/tags for health (Ollama)
    return f"{parsed.scheme}://{parsed.netloc}/api/tags"


@router.get("/health")
async def health_check():
    """Health check with dependency status."""
    import httpx as _httpx
    from config import OLLAMA_HOST, DB_PATH, CHROMA_DB_PATH

    status = {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}
    deps = {}

    # Check Ollama
    try:
        timeout = _httpx.Timeout(1.0, connect=0.3, read=0.7, write=0.3, pool=0.3)
        async with _httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            resp = await asyncio.wait_for(
                client.get(_safe_ollama_probe_url(OLLAMA_HOST), verify=OLLAMA_VERIFY_SSL),
                timeout=1.2,
            )
            deps["ollama"] = "ok" if resp.status_code == 200 else "degraded"
    except Exception:
        deps["ollama"] = "unavailable"

    # Check SQLite
    try:
        import sqlite3
        conn = sqlite3.connect(DB_PATH, timeout=2)
        conn.execute("SELECT 1")
        conn.close()
        deps["sqlite"] = "ok"
    except Exception:
        deps["sqlite"] = "error"

    # Check ChromaDB directory
    deps["chromadb"] = "ok" if _os.path.isdir(CHROMA_DB_PATH) else "missing"

    status["dependencies"] = deps
    if any(v == "error" for v in deps.values()):
        status["status"] = "degraded"
    return status


@router.get("/api/metrics")
async def metrics_endpoint():
    """Return system and application metrics."""
    metrics = get_metrics().get_summary()
    metrics["cache"] = cache_stats()
    return metrics


@router.get("/api/token-usage")
async def token_usage_endpoint():
    """Return lightweight token consumption data for the header counter."""
    m = get_metrics()
    with m._lock:
        calls = list(m._llm_calls)
    total_input = sum(c.get("input_tokens", 0) for c in calls)
    total_output = sum(c.get("output_tokens", 0) for c in calls)
    total_calls = len(calls)
    return {
        "input_tokens": total_input,
        "output_tokens": total_output,
        "total_tokens": total_input + total_output,
        "total_calls": total_calls,
    }


@router.post("/api/tokenize/prefetch")
async def prefetch_tokens(request: Request):
    """Trigger background tokenization for the given text to eliminate latency during generation."""
    body = await request.json()
    text = body.get("text", "")
    model = body.get("model", "gpt-4o")
    if text:
        from app.core.tokens import shadow_tokenizer
        shadow_tokenizer.prefetch(text, model)
    return {"status": "accepted"}


@router.get("/notifications")
async def get_notifications(session_id: str = "", limit: int = 20):
    """Get recent notifications (REST fallback for non-WebSocket clients)."""
    try:
        from app.core.notifications import get_recent
        return get_recent(limit=limit, session_id=session_id or None)
    except Exception:
        return []
