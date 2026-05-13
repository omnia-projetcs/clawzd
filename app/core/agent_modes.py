"""
Clawzd — Structured Agent Modes (OpenSwarm-inspired).

Extends the preprompt system with tool restrictions, UI hints,
and mode-specific behavior.

Each mode defines:
  - allowed_tools: list of tool names this mode can access (None = all)
  - blocked_tools: list of tools explicitly denied in this mode
  - ui_hints: dict with studio panel auto-open, header color, etc.
"""
import json
import os
import logging
from typing import Optional
from config import DATA_DIR

logger = logging.getLogger("clawzd.agent_modes")

CUSTOM_MODES_DIR = os.path.join(DATA_DIR, "modes")


# ---------------------------------------------------------------------------
# Built-in mode definitions (extending preprompts with tool restrictions)
# ---------------------------------------------------------------------------

AGENT_MODES: dict[str, dict] = {
    "none": {
        "label": "Chat",
        "icon": "💬",
        "allowed_tools": None,  # All tools available
        "blocked_tools": [],
        "ui_hints": {},
    },
    "developer": {
        "label": "Code",
        "icon": "💻",
        "allowed_tools": None,  # Full tool access
        "blocked_tools": [],
        "ui_hints": {
            "auto_open": "editor",
            "accent": "#7c5cfc",
        },
    },
    "architect": {
        "label": "Architect",
        "icon": "🏗️",
        "allowed_tools": [
            "search_web", "read_file", "list_files", "run_command",
            "screenshot_remote", "rag_search", "graphify_query",
            "graphify_explain", "graphify_path",
        ],
        "blocked_tools": ["edit_file", "execute_python", "create_app"],
        "ui_hints": {
            "read_only": True,
            "accent": "#f59e0b",
        },
    },
    "writer": {
        "label": "Write",
        "icon": "✍️",
        "allowed_tools": [
            "search_web", "read_file", "rag_search", "screenshot_remote",
            "create_document", "edit_file",
        ],
        "blocked_tools": ["execute_python", "run_command"],
        "ui_hints": {
            "accent": "#10b981",
        },
    },
    "auditor": {
        "label": "Audit",
        "icon": "🔍",
        "allowed_tools": [
            "audit_code", "read_file", "list_files", "run_command",
            "search_web", "rag_search", "execute_python",
        ],
        "blocked_tools": ["edit_file", "send_email", "post_to_twitter"],
        "ui_hints": {
            "accent": "#ef4444",
        },
    },
    "designer": {
        "label": "Design",
        "icon": "🎨",
        "allowed_tools": [
            "search_web", "screenshot_remote", "generate_image",
            "generate_animation", "create_app", "update_app",
            "edit_file", "read_file",
        ],
        "blocked_tools": ["run_command", "execute_python"],
        "ui_hints": {
            "auto_open": "media",
            "accent": "#ec4899",
        },
    },
    "auto": {
        "label": "Auto",
        "icon": "🤖",
        "allowed_tools": None,
        "blocked_tools": [],
        "ui_hints": {
            "accent": "#8b5cf6",
        },
    },
    "jailbreak": {
        "label": "Jailbreak",
        "icon": "🔓",
        "allowed_tools": None,
        "blocked_tools": [],
        "ui_hints": {
            "accent": "#f97316",
        },
    },
}


# ---------------------------------------------------------------------------
# Mode lookup
# ---------------------------------------------------------------------------

def get_mode(mode_key: str) -> dict:
    """Get a mode definition by key, including custom modes."""
    # Built-in modes
    if mode_key in AGENT_MODES:
        return AGENT_MODES[mode_key]

    # Custom modes from data/modes/
    custom = _load_custom_mode(mode_key)
    if custom:
        return custom

    # Fallback: unrestricted
    return {
        "label": mode_key,
        "icon": "💬",
        "allowed_tools": None,
        "blocked_tools": [],
        "ui_hints": {},
    }


def is_tool_allowed(mode_key: str, tool_name: str) -> bool:
    """Check if a tool is allowed in the given mode."""
    mode = get_mode(mode_key)

    # Explicitly blocked
    blocked = mode.get("blocked_tools", [])
    if tool_name in blocked:
        return False

    # Allowed list (None = all allowed)
    allowed = mode.get("allowed_tools")
    if allowed is None:
        return True

    return tool_name in allowed


def get_mode_ui_hints(mode_key: str) -> dict:
    """Get UI hints for a mode (for frontend)."""
    mode = get_mode(mode_key)
    return mode.get("ui_hints", {})


def list_modes() -> list[dict]:
    """List all available modes (built-in + custom)."""
    modes = []
    for key, mode in AGENT_MODES.items():
        modes.append({
            "key": key,
            "label": mode["label"],
            "icon": mode["icon"],
            "has_tool_restrictions": mode.get("allowed_tools") is not None,
            "ui_hints": mode.get("ui_hints", {}),
        })

    # Add custom modes
    for custom in _load_all_custom_modes():
        modes.append({
            "key": custom["key"],
            "label": custom.get("label", custom["key"]),
            "icon": custom.get("icon", "⚙️"),
            "has_tool_restrictions": custom.get("allowed_tools") is not None,
            "ui_hints": custom.get("ui_hints", {}),
            "custom": True,
        })

    return modes


# ---------------------------------------------------------------------------
# Custom modes (user-defined, stored in data/modes/)
# ---------------------------------------------------------------------------

def _load_custom_mode(key: str) -> Optional[dict]:
    """Load a custom mode from data/modes/<key>.json."""
    path = os.path.join(CUSTOM_MODES_DIR, f"{key}.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            mode = json.load(f)
        mode["key"] = key
        return mode
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load custom mode '%s': %s", key, e)
        return None


def _load_all_custom_modes() -> list[dict]:
    """Load all custom modes from data/modes/."""
    if not os.path.isdir(CUSTOM_MODES_DIR):
        return []
    modes = []
    for fname in os.listdir(CUSTOM_MODES_DIR):
        if fname.endswith(".json"):
            key = fname[:-5]
            mode = _load_custom_mode(key)
            if mode:
                modes.append(mode)
    return modes


def save_custom_mode(key: str, mode: dict):
    """Save a custom mode to data/modes/."""
    os.makedirs(CUSTOM_MODES_DIR, exist_ok=True)
    path = os.path.join(CUSTOM_MODES_DIR, f"{key}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(mode, f, indent=2)
    logger.info("Saved custom mode: %s", key)


def delete_custom_mode(key: str) -> bool:
    """Delete a custom mode."""
    path = os.path.join(CUSTOM_MODES_DIR, f"{key}.json")
    if os.path.isfile(path):
        os.remove(path)
        return True
    return False
