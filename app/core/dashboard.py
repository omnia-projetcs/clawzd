"""
Clawzd — Performance Dashboard (OpenClaw OS-inspired).

Aggregates performance metrics from across the system into a single
dashboard endpoint. Sources:

- Tool Replay: execution counts, duration, error rates
- Upload Store: storage statistics
- Plugin System: active plugins
- Artifacts: counts and sizes
- Notifications: queue depth
- App Builder: generated apps

Endpoint: GET /dashboard/metrics
"""
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from config import DATA_DIR

logger = logging.getLogger("clawzd.dashboard")


def get_system_metrics() -> dict:
    """Aggregate metrics from all subsystems."""
    metrics = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "subsystems": {},
    }

    # ── Plugins ──
    try:
        from app.core.plugin_system import list_plugins
        plugins = list_plugins()
        metrics["subsystems"]["plugins"] = {
            "total": len(plugins),
            "enabled": sum(1 for p in plugins if p["enabled"]),
            "list": [p["name"] for p in plugins],
        }
    except Exception:
        metrics["subsystems"]["plugins"] = {"error": "unavailable"}

    # ── Upload Store ──
    try:
        from app.core.upload_store import get_store_stats
        metrics["subsystems"]["upload_store"] = get_store_stats()
    except Exception:
        metrics["subsystems"]["upload_store"] = {"error": "unavailable"}

    # ── Notifications ──
    try:
        from app.core.notifications import _notifications, _subscribers
        metrics["subsystems"]["notifications"] = {
            "queue_size": len(_notifications),
            "active_subscribers": len(_subscribers),
        }
    except Exception:
        metrics["subsystems"]["notifications"] = {"error": "unavailable"}

    # ── Tool Replay ──
    try:
        from app.core.tool_replay import list_replays, REPLAY_DIR
        replays = list_replays(limit=100)
        total_size = 0
        if os.path.isdir(REPLAY_DIR):
            for f in os.listdir(REPLAY_DIR):
                fp = os.path.join(REPLAY_DIR, f)
                if os.path.isfile(fp):
                    total_size += os.path.getsize(fp)
        metrics["subsystems"]["replays"] = {
            "total_sessions": len(replays),
            "total_size_kb": round(total_size / 1024, 1),
        }
    except Exception:
        metrics["subsystems"]["replays"] = {"error": "unavailable"}

    # ── App Builder ──
    try:
        from app.core.app_builder import list_apps
        apps = list_apps(limit=100)
        metrics["subsystems"]["app_builder"] = {
            "total_apps": len(apps),
        }
    except Exception:
        metrics["subsystems"]["app_builder"] = {"error": "unavailable"}

    # ── Artifacts ──
    try:
        from app.core.artifacts import list_artifacts
        all_artifacts = list_artifacts(limit=1000)
        pinned = sum(1 for a in all_artifacts if a.get("pinned"))
        metrics["subsystems"]["artifacts"] = {
            "total": len(all_artifacts),
            "pinned": pinned,
        }
    except Exception:
        metrics["subsystems"]["artifacts"] = {"error": "unavailable"}

    # ── Database ──
    try:
        db_path = os.path.join(DATA_DIR, "clawzd.db")
        if os.path.exists(db_path):
            db_size = os.path.getsize(db_path)
            wal_path = db_path + "-wal"
            wal_size = os.path.getsize(wal_path) if os.path.exists(wal_path) else 0
            metrics["subsystems"]["database"] = {
                "db_size_mb": round(db_size / (1024 * 1024), 2),
                "wal_size_mb": round(wal_size / (1024 * 1024), 2),
            }
    except Exception:
        metrics["subsystems"]["database"] = {"error": "unavailable"}

    # ── Typed Contracts ──
    try:
        from app.tools.contracts import get_all_schemas
        schemas = get_all_schemas()
        metrics["subsystems"]["contracts"] = {
            "registered_schemas": len(schemas),
            "tools": list(schemas.keys()),
        }
    except Exception:
        metrics["subsystems"]["contracts"] = {"error": "unavailable"}

    return metrics
