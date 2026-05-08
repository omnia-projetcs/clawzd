"""
Clawzd — Notification Center (OpenClaw OS-inspired).

Centralized notification system that pushes events to connected
WebSocket clients in real-time. Supports:
- Tool execution results (image generated, code audit complete)
- Cron task completions
- Long-running process status updates
- System alerts (disk space, model loading)

Notifications are stored in-memory (recent 100) and pushed over
WebSocket when a client is connected.
"""
import asyncio
import json
import logging
import time
from typing import Optional

logger = logging.getLogger("clawzd.notifications")


# ---------------------------------------------------------------------------
# Notification types
# ---------------------------------------------------------------------------

class NotificationType:
    """Standard notification categories."""
    TOOL_COMPLETE = "tool_complete"
    CRON_COMPLETE = "cron_complete"
    ERROR = "error"
    INFO = "info"
    WARNING = "warning"
    SYSTEM = "system"


# ---------------------------------------------------------------------------
# Notification store
# ---------------------------------------------------------------------------

_notifications: list[dict] = []
_MAX_NOTIFICATIONS = 100
_subscribers: dict[str, asyncio.Queue] = {}  # session_id → queue


def _add_notification(notification: dict):
    """Store a notification and push to all subscribers."""
    _notifications.append(notification)
    # Trim old notifications
    while len(_notifications) > _MAX_NOTIFICATIONS:
        _notifications.pop(0)

    # Push to all WebSocket subscribers
    for session_id, queue in list(_subscribers.items()):
        try:
            queue.put_nowait(notification)
        except asyncio.QueueFull:
            logger.warning("Notification queue full for session %s", session_id)


def notify(
    title: str,
    message: str,
    ntype: str = NotificationType.INFO,
    session_id: Optional[str] = None,
    data: Optional[dict] = None,
):
    """Create and dispatch a notification.

    Args:
        title: Short notification title.
        message: Notification body text.
        ntype: Notification type (see NotificationType).
        session_id: Optional — target a specific session.
        data: Optional — extra data payload.
    """
    notification = {
        "type": "notification",
        "ntype": ntype,
        "title": title,
        "message": message,
        "timestamp": time.time(),
        "session_id": session_id,
        "data": data or {},
    }
    _add_notification(notification)
    logger.info("Notification [%s]: %s — %s", ntype, title, message)


def notify_tool_complete(tool_name: str, session_id: str, success: bool = True, detail: str = ""):
    """Convenience: notify when a tool finishes execution."""
    notify(
        title=f"{'✅' if success else '❌'} {tool_name}",
        message=detail or (f"{tool_name} completed successfully" if success else f"{tool_name} failed"),
        ntype=NotificationType.TOOL_COMPLETE if success else NotificationType.ERROR,
        session_id=session_id,
    )


def notify_cron_complete(task_name: str, success: bool = True, detail: str = ""):
    """Convenience: notify when a cron task finishes."""
    notify(
        title=f"⏰ Cron: {task_name}",
        message=detail or (f"Task '{task_name}' completed" if success else f"Task '{task_name}' failed"),
        ntype=NotificationType.CRON_COMPLETE if success else NotificationType.ERROR,
    )


# ---------------------------------------------------------------------------
# Subscriber management (for WebSocket push)
# ---------------------------------------------------------------------------

def subscribe(session_id: str) -> asyncio.Queue:
    """Subscribe a session to receive push notifications.

    Returns a queue that will receive notification dicts.
    """
    if session_id not in _subscribers:
        _subscribers[session_id] = asyncio.Queue(maxsize=50)
    return _subscribers[session_id]


def unsubscribe(session_id: str):
    """Remove a session's notification subscription."""
    _subscribers.pop(session_id, None)


def get_recent(limit: int = 20, session_id: Optional[str] = None) -> list[dict]:
    """Get recent notifications, optionally filtered by session."""
    if session_id:
        filtered = [n for n in _notifications if n.get("session_id") in (session_id, None)]
        return filtered[-limit:]
    return _notifications[-limit:]
