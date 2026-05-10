"""
Clawzd — Centralized Task Manager.

Lightweight in-memory registry that tracks all active background tasks
across studios (Research, Media, Audio, etc.). Allows the frontend to
detect running tasks after a tab switch or page refresh, and provides
a unified stop endpoint.
"""
import logging
import time
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException

logger = logging.getLogger("clawzd.task_manager")
router = APIRouter()

# ── In-memory task registry ──
# Key: task_id (str), Value: dict with type, label, started_at, metadata
_active_tasks: dict[str, dict] = {}


def register_task(
    task_id: str,
    task_type: str,
    label: str = "",
    metadata: dict | None = None,
) -> dict:
    """Register an active background task.

    Args:
        task_id: Unique identifier (e.g. research project id, generation UUID).
        task_type: Category string — 'research', 'image', 'video', 'audio'.
        label: Human-readable short description.
        metadata: Extra data (prompt, model, etc.).
    """
    entry = {
        "id": task_id,
        "type": task_type,
        "label": label,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "metadata": metadata or {},
    }
    _active_tasks[task_id] = entry
    logger.info("Task registered: %s [%s] %s", task_id, task_type, label)
    return entry


def unregister_task(task_id: str):
    """Remove a completed/stopped task from the registry."""
    removed = _active_tasks.pop(task_id, None)
    if removed:
        logger.info("Task unregistered: %s [%s]", task_id, removed.get("type"))


def get_active_tasks() -> list[dict]:
    """Return all currently active tasks."""
    return list(_active_tasks.values())


def get_task(task_id: str) -> dict | None:
    """Get a specific task by ID."""
    return _active_tasks.get(task_id)


def is_task_active(task_id: str) -> bool:
    """Check if a task is currently registered as active."""
    return task_id in _active_tasks


# ── API Endpoints ──

@router.get("/tasks/active")
async def api_active_tasks():
    """Return all currently active background tasks."""
    return {"tasks": get_active_tasks()}


@router.get("/tasks/{task_id}")
async def api_task_status(task_id: str):
    """Get status of a specific task."""
    task = get_task(task_id)
    if not task:
        return {"active": False, "task": None}
    return {"active": True, "task": task}


@router.post("/tasks/{task_id}/stop")
async def api_stop_task(task_id: str):
    """Stop a specific task by delegating to the correct studio.

    This is a unified stop endpoint — it detects the task type and
    calls the appropriate backend stop function.
    """
    task = get_task(task_id)
    if not task:
        raise HTTPException(404, "Task not found or already completed")

    task_type = task.get("type", "")

    if task_type == "research":
        from app.tools_research import _running, _load, _save
        if task_id in _running:
            _running[task_id].cancel()
            _running.pop(task_id, None)
        proj = _load(task_id)
        if proj:
            proj["status"] = "paused"
            _save(proj)
        unregister_task(task_id)
        return {"status": "stopped", "type": "research"}

    elif task_type in ("image", "video"):
        from app.tools_image import _cancel_generation
        _cancel_generation(task_id)
        unregister_task(task_id)
        return {"status": "stopped", "type": task_type}

    elif task_type == "audio":
        from app.tools_audio import _cancel_audio_generation
        _cancel_audio_generation(task_id)
        unregister_task(task_id)
        return {"status": "stopped", "type": "audio"}

    # Unknown type — just unregister
    unregister_task(task_id)
    return {"status": "stopped", "type": task_type}
