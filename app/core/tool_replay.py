"""
Clawzd — Tool Replay System (OpenClaw OS-inspired).

Records tool execution sequences during chat sessions and enables
replaying them for debugging, testing, or automation purposes.

Use cases:
- "Why did the AI do X?" — inspect the exact tool_call sequence
- "Run the same analysis again" — replay a recorded sequence
- "Make a workflow from this conversation" — export as automation

Storage: JSONL file per session in data/replays/
"""
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional

from config import DATA_DIR

logger = logging.getLogger("clawzd.tool_replay")

REPLAY_DIR = os.path.join(DATA_DIR, "replays")


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------

def record_tool_call(
    session_id: str,
    tool_name: str,
    params: dict,
    result: dict,
    duration_ms: float = 0,
    round_num: int = 0,
) -> None:
    """Record a single tool call execution to the session's replay log."""
    os.makedirs(REPLAY_DIR, exist_ok=True)
    filepath = os.path.join(REPLAY_DIR, f"{session_id}.jsonl")

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "round": round_num,
        "tool": tool_name,
        "params": _sanitize_params(params),
        "result_preview": _preview_result(result),
        "success": "error" not in result if isinstance(result, dict) else True,
        "duration_ms": round(duration_ms, 1),
    }

    try:
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except IOError as e:
        logger.warning("Failed to record tool call: %s", e)


def _sanitize_params(params: dict) -> dict:
    """Remove or truncate sensitive/large parameter values."""
    sanitized = {}
    for key, value in params.items():
        if isinstance(value, str) and len(value) > 500:
            sanitized[key] = value[:500] + f"... ({len(value)} chars)"
        else:
            sanitized[key] = value
    return sanitized


def _preview_result(result) -> str:
    """Create a short preview of a tool result for the replay log."""
    if isinstance(result, dict):
        if "error" in result:
            return f"ERROR: {str(result['error'])[:200]}"
        if "images" in result:
            return f"Generated {len(result['images'])} image(s)"
        if "output" in result:
            out = str(result["output"])
            return out[:300] + "..." if len(out) > 300 else out
        # Generic preview
        preview = json.dumps(result, ensure_ascii=False)
        return preview[:300] + "..." if len(preview) > 300 else preview
    return str(result)[:300]


# ---------------------------------------------------------------------------
# Replay retrieval
# ---------------------------------------------------------------------------

def get_session_replay(session_id: str) -> list[dict]:
    """Get the full tool replay log for a session."""
    filepath = os.path.join(REPLAY_DIR, f"{session_id}.jsonl")
    if not os.path.exists(filepath):
        return []

    entries = []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except IOError:
        pass

    return entries


def get_replay_summary(session_id: str) -> dict:
    """Get a summary of a session's tool replay."""
    entries = get_session_replay(session_id)
    if not entries:
        return {"session_id": session_id, "total_calls": 0}

    tools_used = {}
    total_duration = 0
    errors = 0

    for e in entries:
        tool = e.get("tool", "unknown")
        tools_used[tool] = tools_used.get(tool, 0) + 1
        total_duration += e.get("duration_ms", 0)
        if not e.get("success", True):
            errors += 1

    return {
        "session_id": session_id,
        "total_calls": len(entries),
        "unique_tools": len(tools_used),
        "tools_used": tools_used,
        "total_duration_ms": round(total_duration, 1),
        "error_count": errors,
        "first_call": entries[0].get("timestamp"),
        "last_call": entries[-1].get("timestamp"),
    }


def list_replays(limit: int = 20) -> list[dict]:
    """List all available replay sessions."""
    if not os.path.isdir(REPLAY_DIR):
        return []

    replays = []
    for fname in sorted(os.listdir(REPLAY_DIR), reverse=True):
        if not fname.endswith(".jsonl"):
            continue
        session_id = fname.removesuffix(".jsonl")
        filepath = os.path.join(REPLAY_DIR, fname)
        stat = os.stat(filepath)
        replays.append({
            "session_id": session_id,
            "file_size": stat.st_size,
            "modified_at": datetime.fromtimestamp(
                stat.st_mtime, tz=timezone.utc
            ).isoformat(),
        })

    return replays[:limit]


def delete_replay(session_id: str) -> bool:
    """Delete a replay log."""
    filepath = os.path.join(REPLAY_DIR, f"{session_id}.jsonl")
    if os.path.exists(filepath):
        os.remove(filepath)
        logger.info("Deleted replay log for session %s", session_id)
        return True
    return False


def export_as_workflow(session_id: str) -> dict:
    """Export a replay as a reusable workflow definition.

    Can be used by the automation system to create playbooks
    from observed tool sequences.
    """
    entries = get_session_replay(session_id)
    if not entries:
        return {"error": "No replay data found"}

    steps = []
    for i, e in enumerate(entries, 1):
        step = {
            "step": i,
            "tool": e.get("tool"),
            "params": e.get("params", {}),
        }
        steps.append(step)

    return {
        "name": f"Workflow from session {session_id[:12]}",
        "created_from": session_id,
        "steps": steps,
        "total_steps": len(steps),
    }
