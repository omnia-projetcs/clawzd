"""
Clawzd - Centralized Task Manager.

Persistent registry for long-running background tasks across studios
(Research, Media, Audio, Presentation, Automation, etc.).

The legacy API remains compatible:
  - register_task(...)
  - unregister_task(...)
  - GET /api/tasks/active
  - GET /api/tasks/history
  - GET /api/tasks/summary
  - GET /api/tasks/{task_id}
  - POST /api/tasks/{task_id}/stop
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query

from config import DATA_DIR

logger = logging.getLogger("clawzd.task_manager")
router = APIRouter()

_TASKS_DIR = os.path.join(DATA_DIR, "tasks")
_TASKS_PATH = os.path.join(_TASKS_DIR, "tasks.json")
_MAX_HISTORY = 500
_MAX_EVENTS_PER_TASK = 30

_store_lock = threading.RLock()

# Key: task_id (str), Value: dict with id, type, label, status, metadata, etc.
_active_tasks: dict[str, dict] = {}
_task_history: list[dict] = []


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _duration_seconds(started_at: str | None, ended_at: str | None = None) -> float:
    if not started_at:
        return 0.0
    try:
        start = datetime.fromisoformat(started_at)
        end = datetime.fromisoformat(ended_at or _now())
        return round(max(0.0, (end - start).total_seconds()), 3)
    except Exception:
        return 0.0


def _ensure_store_dir() -> None:
    os.makedirs(_TASKS_DIR, exist_ok=True)


def _trim_history_locked() -> None:
    if len(_task_history) > _MAX_HISTORY:
        del _task_history[:-_MAX_HISTORY]


def _persist_locked() -> None:
    """Persist the task store atomically. Caller must hold _store_lock."""
    try:
        _ensure_store_dir()
        _trim_history_locked()
        payload = {
            "version": 1,
            "updated_at": _now(),
            "active": list(_active_tasks.values()),
            "history": _task_history[-_MAX_HISTORY:],
        }
        tmp_path = _TASKS_PATH + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, _TASKS_PATH)
    except Exception as exc:
        logger.warning("Task store persist failed: %s", exc)


def _event(event_type: str, message: str = "", data: dict | None = None) -> dict:
    return {
        "at": _now(),
        "type": event_type,
        "message": message,
        "data": data or {},
    }


def _append_event_locked(task: dict, event_type: str, message: str = "", data: dict | None = None) -> None:
    events = task.setdefault("events", [])
    events.append(_event(event_type, message, data))
    if len(events) > _MAX_EVENTS_PER_TASK:
        del events[:-_MAX_EVENTS_PER_TASK]
    task["event_count"] = int(task.get("event_count", 0)) + 1


def _load_store() -> None:
    """Load persisted history and mark previously active tasks as interrupted."""
    with _store_lock:
        _active_tasks.clear()
        _task_history.clear()
        if not os.path.exists(_TASKS_PATH):
            return

        try:
            with open(_TASKS_PATH, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception as exc:
            logger.warning("Task store load failed: %s", exc)
            return

        for task in payload.get("history", []):
            if isinstance(task, dict) and task.get("id"):
                task["active"] = False
                _task_history.append(task)

        interrupted_at = _now()
        for task in payload.get("active", []):
            if not isinstance(task, dict) or not task.get("id"):
                continue
            task["active"] = False
            task["status"] = "interrupted"
            task["stage"] = "interrupted"
            task["ended_at"] = interrupted_at
            task["updated_at"] = interrupted_at
            task["duration_seconds"] = _duration_seconds(task.get("started_at"), interrupted_at)
            task["error"] = task.get("error") or "Server restarted before task completion."
            _append_event_locked(task, "interrupted", "Server restarted before task completion.")
            _task_history.append(task)

        _trim_history_locked()
        _persist_locked()


def register_task(
    task_id: str,
    task_type: str,
    label: str = "",
    metadata: dict | None = None,
) -> dict:
    """Register an active background task."""
    if not task_id:
        raise ValueError("task_id is required")

    now = _now()
    with _store_lock:
        existing = _active_tasks.get(task_id)
        if existing:
            existing["type"] = task_type or existing.get("type", "")
            existing["label"] = label or existing.get("label", "")
            existing["metadata"] = {**existing.get("metadata", {}), **(metadata or {})}
            existing["updated_at"] = now
            _append_event_locked(existing, "registered", "Task registration refreshed.")
            _persist_locked()
            return dict(existing)

        entry = {
            "id": task_id,
            "type": task_type,
            "label": label,
            "status": "running",
            "active": True,
            "progress": 0.0,
            "stage": "queued",
            "started_at": now,
            "updated_at": now,
            "metadata": metadata or {},
            "events": [_event("registered", "Task registered.")],
            "event_count": 1,
        }
        _active_tasks[task_id] = entry
        _persist_locked()

    logger.info("Task registered: %s [%s] %s", task_id, task_type, label)
    return dict(entry)


def update_task(
    task_id: str,
    *,
    progress: float | None = None,
    stage: str | None = None,
    status: str | None = None,
    label: str | None = None,
    metadata: dict | None = None,
    result: dict | None = None,
    error: str | None = None,
    event: str | dict | None = None,
) -> dict | None:
    """Update progress, stage, metadata or event info for an active task."""
    with _store_lock:
        task = _active_tasks.get(task_id)
        if not task:
            return None

        if progress is not None:
            task["progress"] = max(0.0, min(100.0, float(progress)))
        if stage is not None:
            task["stage"] = stage
        if status is not None:
            task["status"] = status
        if label is not None:
            task["label"] = label
        if metadata:
            task["metadata"] = {**task.get("metadata", {}), **metadata}
        if result is not None:
            task["result"] = result
        if error is not None:
            task["error"] = error

        task["updated_at"] = _now()
        task["duration_seconds"] = _duration_seconds(task.get("started_at"))

        if event:
            if isinstance(event, dict):
                _append_event_locked(
                    task,
                    str(event.get("type", "event")),
                    str(event.get("message", "")),
                    event.get("data") if isinstance(event.get("data"), dict) else {},
                )
            else:
                _append_event_locked(task, "event", str(event))

        _persist_locked()
        return dict(task)


def unregister_task(
    task_id: str,
    status: str = "completed",
    *,
    result: dict | None = None,
    error: str | None = None,
) -> dict | None:
    """Move a task from active registry to persistent history."""
    with _store_lock:
        removed = _active_tasks.pop(task_id, None)
        if not removed:
            return None

        now = _now()
        removed["active"] = False
        removed["status"] = status
        removed["stage"] = status
        removed["ended_at"] = now
        removed["updated_at"] = now
        removed["duration_seconds"] = _duration_seconds(removed.get("started_at"), now)
        removed["progress"] = 100.0 if status == "completed" else removed.get("progress", 0.0)
        if result is not None:
            removed["result"] = result
        if error is not None:
            removed["error"] = error
        _append_event_locked(removed, status, f"Task {status}.")
        _task_history.append(removed)
        _persist_locked()

    logger.info("Task unregistered: %s [%s] status=%s", task_id, removed.get("type"), status)
    return dict(removed)


def get_active_tasks() -> list[dict]:
    """Return all currently active tasks."""
    with _store_lock:
        tasks = list(_active_tasks.values())
    return sorted(tasks, key=lambda t: t.get("started_at", ""))


def get_task(task_id: str) -> dict | None:
    """Get a specific task by ID from active tasks or history."""
    with _store_lock:
        if task_id in _active_tasks:
            return dict(_active_tasks[task_id])
        for task in reversed(_task_history):
            if task.get("id") == task_id:
                return dict(task)
    return None


def is_task_active(task_id: str) -> bool:
    """Check if a task is currently registered as active."""
    with _store_lock:
        return task_id in _active_tasks


def get_task_history(
    *,
    limit: int = 50,
    task_type: str | None = None,
    status: str | None = None,
) -> list[dict]:
    """Return recent completed/interrupted task records."""
    limit = max(1, min(int(limit), _MAX_HISTORY))
    with _store_lock:
        tasks = list(reversed(_task_history))
    if task_type:
        tasks = [t for t in tasks if t.get("type") == task_type]
    if status:
        tasks = [t for t in tasks if t.get("status") == status]
    return tasks[:limit]


def get_task_summary() -> dict:
    """Return compact task counts for dashboards."""
    with _store_lock:
        active = list(_active_tasks.values())
        history = list(_task_history)
    by_status: dict[str, int] = {}
    by_type: dict[str, int] = {}
    for task in active + history:
        by_status[task.get("status", "unknown")] = by_status.get(task.get("status", "unknown"), 0) + 1
        by_type[task.get("type", "unknown")] = by_type.get(task.get("type", "unknown"), 0) + 1
    return {
        "active": len(active),
        "history": len(history),
        "by_status": by_status,
        "by_type": by_type,
    }


_load_store()


# -- API Endpoints -----------------------------------------------------------

@router.get("/tasks/active")
async def api_active_tasks():
    """Return all currently active background tasks."""
    return {"tasks": get_active_tasks()}


@router.get("/tasks/history")
async def api_task_history(
    limit: int = 50,
    task_type: str | None = Query(None, alias="type"),
    status: str | None = None,
):
    """Return recent task history."""
    return {"tasks": get_task_history(limit=limit, task_type=task_type, status=status)}


@router.get("/tasks/summary")
async def api_task_summary():
    """Return compact task counts."""
    return get_task_summary()


@router.get("/tasks/{task_id}")
async def api_task_status(task_id: str):
    """Get status of a specific task."""
    task = get_task(task_id)
    if not task:
        return {"active": False, "task": None}
    return {"active": bool(task.get("active")), "task": task}


@router.post("/tasks/{task_id}/stop")
async def api_stop_task(task_id: str):
    """Stop a specific task by delegating to the correct studio."""
    task = get_task(task_id)
    if not task or not task.get("active"):
        raise HTTPException(404, "Task not found or already completed")

    task_type = task.get("type", "")

    if task_type == "research":
        from app.tools_research import stop_research
        await stop_research(task_id)
        return {"status": "stopped", "type": "research"}

    if task_type in ("image", "video"):
        from app.tools_image import _cancel_generation
        _cancel_generation(task_id)
        unregister_task(task_id, status="stopped")
        return {"status": "stopped", "type": task_type}

    if task_type == "audio":
        from app.tools_audio import _cancel_audio_generation
        _cancel_audio_generation(task_id)
        unregister_task(task_id, status="stopped")
        return {"status": "stopped", "type": "audio"}

    # Unknown or non-cancellable type: remove it from active tasks, but keep history.
    unregister_task(task_id, status="stopped")
    return {"status": "stopped", "type": task_type}
