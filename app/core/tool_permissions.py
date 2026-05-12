"""
Clawzd — Per-Tool Permission System (Human-in-the-Loop).

OpenSwarm-inspired granular tool permissions. Each tool can be configured as:
  - "always" — execute without asking
  - "ask"    — pause and request user approval before executing
  - "deny"   — block execution entirely

The approval workflow uses asyncio.Event to pause the tool pipeline
until the user responds via the /api/tool-approval endpoint.
"""
import asyncio
import json
import os
import logging
import time
from typing import Optional

from config import DATA_DIR

logger = logging.getLogger("clawzd.tool_permissions")

PERMISSIONS_FILE = os.path.join(DATA_DIR, "tool_permissions.json")

# ---------------------------------------------------------------------------
# Default permission levels per tool
# ---------------------------------------------------------------------------
# "always" = auto-execute (safe tools)
# "ask"    = require user confirmation (destructive/expensive tools)
# "deny"   = block entirely

DEFAULT_PERMISSIONS: dict[str, str] = {
    # Safe / read-only — always allow
    "search_web": "always",
    "read_file": "always",
    "rag_search": "always",
    "screenshot_remote": "always",
    "screenshot_local": "always",
    "search_twitter": "always",
    "search_linkedin": "always",
    "list_files": "always",
    "analyze_data": "always",
    "graphify_query": "always",
    "graphify_explain": "always",
    "graphify_path": "always",

    # Code execution — ask by default
    "execute_python": "ask",
    "run_command": "ask",

    # File mutation — ask by default
    "edit_file": "ask",
    "create_app": "always",
    "update_app": "always",
    "todo_write": "always",

    # External actions — ask by default
    "send_email": "ask",
    "post_to_twitter": "ask",
    "post_to_linkedin": "ask",
    "post_to_medium": "ask",
    "trigger_n8n": "ask",

    # Media generation — always (expensive but not destructive)
    "generate_image": "always",
    "generate_animation": "always",
    "create_document": "always",

    # Security/audit — always (read-only analysis)
    "audit_code": "always",

    # Web automation — ask (can interact with external sites)
    "browse_web": "ask",

    # Skills & memory — always
    "create_skill": "always",
    "rebuild_skill": "always",
    "memory": "always",
    "undo": "always",
}


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

_perms_cache: dict[str, str] | None = None
_perms_cache_ts: float = 0
_PERMS_CACHE_TTL = 5  # seconds


def load_permissions() -> dict[str, str]:
    """Load tool permissions from disk, falling back to defaults.

    Results are cached for 5s to avoid disk reads on every tool call.
    """
    global _perms_cache, _perms_cache_ts
    now = time.time()
    if _perms_cache is not None and (now - _perms_cache_ts) < _PERMS_CACHE_TTL:
        return dict(_perms_cache)

    perms = dict(DEFAULT_PERMISSIONS)
    if os.path.isfile(PERMISSIONS_FILE):
        try:
            with open(PERMISSIONS_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            perms.update(saved)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load tool permissions: %s", e)

    _perms_cache = perms
    _perms_cache_ts = now
    return dict(perms)


def save_permissions(perms: dict[str, str]):
    """Save tool permissions to disk."""
    global _perms_cache, _perms_cache_ts
    os.makedirs(os.path.dirname(PERMISSIONS_FILE), exist_ok=True)
    with open(PERMISSIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(perms, f, indent=2)
    _perms_cache = None  # Invalidate cache
    _perms_cache_ts = 0


def get_tool_permission(tool_name: str) -> str:
    """Get the permission level for a single tool."""
    perms = load_permissions()
    return perms.get(tool_name, "always")


def set_tool_permission(tool_name: str, level: str):
    """Set the permission level for a single tool."""
    if level not in ("always", "ask", "deny"):
        raise ValueError(f"Invalid permission level: {level}")
    perms = load_permissions()
    perms[tool_name] = level
    save_permissions(perms)
    logger.info("Tool permission updated: %s → %s", tool_name, level)


# ---------------------------------------------------------------------------
# Pending Approvals (in-memory, per-session)
# ---------------------------------------------------------------------------

class PendingApproval:
    """A tool execution waiting for user approval."""

    def __init__(self, approval_id: str, session_id: str,
                 tool_name: str, params: dict):
        self.id = approval_id
        self.session_id = session_id
        self.tool_name = tool_name
        self.params = params
        self.created_at = time.time()
        self.event = asyncio.Event()
        self.approved: Optional[bool] = None
        self.always_allow: bool = False  # If user checks "always allow"

    def to_dict(self) -> dict:
        """Serialize for the frontend (excluding the event)."""
        # Truncate params for display (avoid sending massive code blocks)
        display_params = {}
        for k, v in self.params.items():
            if isinstance(v, str) and len(v) > 500:
                display_params[k] = v[:500] + "…"
            else:
                display_params[k] = v

        return {
            "id": self.id,
            "session_id": self.session_id,
            "tool_name": self.tool_name,
            "params": display_params,
            "created_at": self.created_at,
        }


# Global registry of pending approvals
_pending_approvals: dict[str, PendingApproval] = {}

# Timeout for waiting for approval (seconds)
APPROVAL_TIMEOUT = 120


async def request_approval(
    session_id: str,
    tool_name: str,
    params: dict,
    queue: asyncio.Queue,
) -> bool:
    """Request approval for a tool execution.

    Sends an approval request to the frontend via the SSE queue,
    then waits for the user to approve or deny.

    Returns True if approved, False if denied/timed out.
    """
    import uuid
    approval_id = f"approval-{uuid.uuid4().hex[:8]}"

    approval = PendingApproval(
        approval_id=approval_id,
        session_id=session_id,
        tool_name=tool_name,
        params=params,
    )
    _pending_approvals[approval_id] = approval

    # Emit approval request via SSE
    approval_msg = (
        f"\n\n__TOOL_APPROVAL__{json.dumps(approval.to_dict())}__TOOL_APPROVAL__"
    )
    await queue.put(approval_msg)

    # Wait for user response
    try:
        await asyncio.wait_for(approval.event.wait(), timeout=APPROVAL_TIMEOUT)
    except asyncio.TimeoutError:
        logger.warning("Tool approval timed out: %s / %s", tool_name, approval_id)
        approval.approved = False

    # Clean up
    _pending_approvals.pop(approval_id, None)

    # If user checked "always allow", update the permission
    if approval.always_allow and approval.approved:
        set_tool_permission(tool_name, "always")

    return approval.approved is True


def resolve_approval(approval_id: str, approved: bool, always_allow: bool = False) -> bool:
    """Resolve a pending approval (called from the API endpoint).

    Returns True if the approval was found and resolved.
    """
    approval = _pending_approvals.get(approval_id)
    if not approval:
        return False

    approval.approved = approved
    approval.always_allow = always_allow
    approval.event.set()
    logger.info(
        "Tool approval resolved: %s → %s (always_allow=%s)",
        approval.tool_name, "approved" if approved else "denied", always_allow,
    )
    return True


def list_pending_approvals(session_id: str = "") -> list[dict]:
    """List all pending approvals, optionally filtered by session."""
    approvals = []
    for a in _pending_approvals.values():
        if session_id and a.session_id != session_id:
            continue
        approvals.append(a.to_dict())
    return approvals
