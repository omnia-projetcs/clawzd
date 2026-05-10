"""
Clawzd — My Clone engine.

AI agent that mimics the user's communication style using a personal
knowledge base. Manages profile, knowledge files, connectors, auto-reply
settings, interaction logs, and a test sandbox.

Knowledge files: profiles/clone/  (markdown profile & knowledge base)
Runtime data:    data/clone/      (logs, settings, connectors)
"""
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, UploadFile, File

from config import DATA_DIR, PROFILES_DIR

router = APIRouter()
logger = logging.getLogger("clawzd.clone")

CLONE_DIR = os.path.join(DATA_DIR, "clone")
KNOWLEDGE_DIR = os.path.join(PROFILES_DIR, "clone")
LOGS_DIR = os.path.join(CLONE_DIR, "logs")
CONNECTORS_FILE = os.path.join(CLONE_DIR, "connectors.json")
SETTINGS_FILE = os.path.join(CLONE_DIR, "settings.json")
ONBOARDING_FILE = os.path.join(CLONE_DIR, "onboarding.json")

for d in [CLONE_DIR, KNOWLEDGE_DIR, LOGS_DIR,
          os.path.join(KNOWLEDGE_DIR, "expertise"),
          os.path.join(KNOWLEDGE_DIR, "projects")]:
    os.makedirs(d, exist_ok=True)

DEFAULT_SETTINGS = {
    "auto_mode": False,
    "confidence_threshold": 0.85,
    "review_mode": "human-in-loop",
    "daily_limit": 50,
    "working_hours": {"timezone": "Europe/Paris", "from": "09:00", "to": "18:00"},
    "replies_today": 0,
    "last_reset": None,
}

INTENT_LABELS = ["question", "request", "feedback", "spam", "urgent", "unknown"]
SAFETY_KEYWORDS = re.compile(
    r"(urgent|payment|wire transfer|bank account|ssn|password|credit card"
    r"|medical advice|legal advice|financial advice)",
    re.IGNORECASE,
)


# ── Helpers ──

def _read_file(path: str) -> str:
    """Read a text file, return empty string if missing."""
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return ""


def _write_file(path: str, content: str):
    """Write text to file, creating parent dirs."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def _load_json(path: str, default=None):
    """Load JSON file or return default."""
    if os.path.isfile(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return default if default is not None else {}


def _save_json(path: str, data):
    """Save data as JSON."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _list_knowledge_tree(base: str, prefix: str = "") -> list:
    """Recursively list .md files in knowledge directory."""
    items = []
    try:
        for entry in sorted(os.listdir(base)):
            full = os.path.join(base, entry)
            rel = os.path.join(prefix, entry) if prefix else entry
            if os.path.isdir(full):
                children = _list_knowledge_tree(full, rel)
                items.append({"name": entry, "path": rel, "type": "dir",
                              "children": children})
            elif entry.endswith(".md"):
                size = os.path.getsize(full)
                items.append({"name": entry, "path": rel, "type": "file",
                              "size": size})
    except Exception as e:
        logger.error("Knowledge tree error: %s", e)
    return items


def _load_all_knowledge() -> str:
    """Load and concatenate all .md files for context injection."""
    parts = []
    for root, _dirs, files in os.walk(KNOWLEDGE_DIR):
        for fname in sorted(files):
            if fname.endswith(".md"):
                rel = os.path.relpath(os.path.join(root, fname), KNOWLEDGE_DIR)
                content = _read_file(os.path.join(root, fname))
                if content.strip():
                    parts.append(f"--- {rel} ---\n{content}")
    return "\n\n".join(parts)


def _get_settings() -> dict:
    """Load clone settings with defaults."""
    settings = dict(DEFAULT_SETTINGS)
    saved = _load_json(SETTINGS_FILE, {})
    settings.update(saved)
    # Reset daily counter if date changed
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if settings.get("last_reset") != today:
        settings["replies_today"] = 0
        settings["last_reset"] = today
        _save_json(SETTINGS_FILE, settings)
    return settings


def _log_interaction(entry: dict):
    """Append an interaction to today's log file."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    log_file = os.path.join(LOGS_DIR, f"{today}.json")
    logs = _load_json(log_file, [])
    if not isinstance(logs, list):
        logs = []
    entry["timestamp"] = datetime.now(timezone.utc).isoformat()
    logs.append(entry)
    _save_json(log_file, logs)


# ── Profile & Knowledge CRUD ──

@router.get("/profile")
async def get_profile():
    """Return all profile files."""
    return {
        "profile": _read_file(os.path.join(KNOWLEDGE_DIR, "profile.md")),
        "style": _read_file(os.path.join(KNOWLEDGE_DIR, "communication_style.md")),
        "rules": _read_file(os.path.join(KNOWLEDGE_DIR, "rules.md")),
        "faq": _read_file(os.path.join(KNOWLEDGE_DIR, "faq.md")),
    }


@router.post("/profile")
async def save_profile(request: Request):
    """Save profile files (partial update)."""
    data = await request.json()
    mapping = {
        "profile": "profile.md",
        "style": "communication_style.md",
        "rules": "rules.md",
        "faq": "faq.md",
    }
    for key, fname in mapping.items():
        if key in data:
            _write_file(os.path.join(KNOWLEDGE_DIR, fname), data[key])
    return {"status": "saved"}


@router.get("/knowledge")
async def list_knowledge():
    """List knowledge file tree."""
    return {"tree": _list_knowledge_tree(KNOWLEDGE_DIR)}


@router.get("/knowledge/{path:path}")
async def get_knowledge_file(path: str):
    """Read a specific knowledge file."""
    full = os.path.join(KNOWLEDGE_DIR, path)
    if not os.path.isfile(full) or not full.startswith(KNOWLEDGE_DIR):
        raise HTTPException(404, "File not found")
    return {"path": path, "content": _read_file(full)}


@router.put("/knowledge/{path:path}")
async def put_knowledge_file(path: str, request: Request):
    """Create or update a knowledge file."""
    data = await request.json()
    content = data.get("content", "")
    full = os.path.join(KNOWLEDGE_DIR, path)
    if not full.startswith(KNOWLEDGE_DIR):
        raise HTTPException(400, "Invalid path")
    _write_file(full, content)
    return {"status": "saved", "path": path}


@router.delete("/knowledge/{path:path}")
async def delete_knowledge_file(path: str):
    """Delete a knowledge file."""
    full = os.path.join(KNOWLEDGE_DIR, path)
    if not full.startswith(KNOWLEDGE_DIR) or not os.path.isfile(full):
        raise HTTPException(404, "File not found")
    # Protect core files from deletion
    protected = {"profile.md", "communication_style.md", "rules.md", "faq.md"}
    if path in protected:
        raise HTTPException(400, "Cannot delete core profile files")
    os.remove(full)
    return {"status": "deleted", "path": path}


# ── Connectors ──

# Communication/publish node types exposed to the Clone Studio
_CLONE_CONNECTOR_CATEGORIES = {"communication", "publish"}


def _get_automation_connectors() -> list:
    """Return connectors from Automation NODE_TYPES (communication + publish)."""
    try:
        from app.tools_automation import NODE_TYPES
        result = []
        for key, defn in NODE_TYPES.items():
            if defn.get("category") in _CLONE_CONNECTOR_CATEGORIES:
                result.append({
                    "key": key,
                    "label": defn.get("label", key),
                    "icon": defn.get("icon", "link"),
                    "color": defn.get("color", "#6b7280"),
                    "category": defn.get("category", "communication"),
                    "params": defn.get("params", []),
                })
        return result
    except Exception as e:
        logger.error("Failed to load automation connectors: %s", e)
        return []


@router.get("/available-connectors")
async def get_available_connectors():
    """Return all connectors available from the Automation engine."""
    return {"connectors": _get_automation_connectors()}


@router.get("/connectors")
async def get_connectors():
    """Return connector configurations merged with automation-discovered defaults."""
    # Build default structure from automation NODE_TYPES
    default: dict = {}
    for conn in _get_automation_connectors():
        key = conn["key"]
        default[key] = {
            "enabled": False,
            "params": {},          # user-configured param values
            "auto_reply": False,
            "allowed_senders": [],
            "last_activity": None,
        }
    # Fallback in case automation import fails
    if not default:
        for key in ("email_send", "whatsapp_send", "signal_send", "telegram_send"):
            default[key] = {"enabled": False, "params": {}, "auto_reply": False,
                            "allowed_senders": [], "last_activity": None}
    saved = _load_json(CONNECTORS_FILE, {})
    for ch in default:
        if ch in saved:
            default[ch].update(saved[ch])
    return {"connectors": default}


@router.post("/connectors")
async def save_connectors(request: Request):
    """Save connector configurations."""
    data = await request.json()
    connectors = data.get("connectors", {})
    _save_json(CONNECTORS_FILE, connectors)
    return {"status": "saved"}


@router.post("/connectors/{connector_key}/test")
async def test_connector(connector_key: str, request: Request):
    """Test a connector by sending a test message through the Automation engine."""
    data = await request.json()
    params = data.get("params", {})
    message = data.get("message", "🤖 Clone connector test message")

    # Load saved params and merge with provided ones
    saved = _load_json(CONNECTORS_FILE, {})
    saved_params = saved.get(connector_key, {}).get("params", {})
    merged_params = {**saved_params, **params}

    # Inject message into the right param key for each connector type
    msg_key_map = {
        "email_send": ("body", "subject"),
        "discord_send": ("message", None),
        "signal_send": ("message", None),
        "telegram_send": ("message", None),
        "whatsapp_send": ("message", None),
        "medium_publish": ("content", "title"),
        "twitter_publish": ("text", None),
        "linkedin_publish": ("text", None),
        "export_email": ("body", "subject"),
    }
    if connector_key in msg_key_map:
        body_key, title_key = msg_key_map[connector_key]
        if body_key and body_key not in merged_params:
            merged_params[body_key] = message
        if title_key and title_key not in merged_params:
            merged_params[title_key] = "Clone Test"

    try:
        from app.tools_automation import _exec_node
        node = {"id": "clone_test", "type": connector_key, "params": merged_params}
        result = await _exec_node(node, {}, {}, testing_mode=False)
        return {"status": "sent", "result": result}
    except Exception as e:
        logger.error("Connector test failed for %s: %s", connector_key, e)
        return {"status": "error", "error": str(e)}


# ── Settings ──

@router.get("/settings")
async def get_settings():
    """Return auto-mode settings."""
    return {"settings": _get_settings()}


@router.post("/settings")
async def save_settings(request: Request):
    """Save auto-mode settings."""
    data = await request.json()
    settings = _get_settings()
    for k in ("auto_mode", "confidence_threshold", "review_mode",
              "daily_limit", "working_hours"):
        if k in data:
            settings[k] = data[k]
    _save_json(SETTINGS_FILE, settings)
    return {"status": "saved", "settings": settings}


# ── Logs ──

@router.get("/logs")
async def get_logs(limit: int = 50):
    """Return recent interactions across all days."""
    all_logs = []
    try:
        files = sorted(os.listdir(LOGS_DIR), reverse=True)
        for fname in files:
            if not fname.endswith(".json"):
                continue
            entries = _load_json(os.path.join(LOGS_DIR, fname), [])
            if isinstance(entries, list):
                all_logs.extend(entries)
            if len(all_logs) >= limit:
                break
    except Exception:
        pass
    all_logs.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return {"logs": all_logs[:limit]}


@router.get("/stats")
async def get_stats():
    """Dashboard statistics."""
    settings = _get_settings()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today_logs = _load_json(os.path.join(LOGS_DIR, f"{today}.json"), [])
    if not isinstance(today_logs, list):
        today_logs = []
    confidences = [e.get("confidence", 0) for e in today_logs if "confidence" in e]
    return {
        "replies_today": settings.get("replies_today", 0),
        "daily_limit": settings.get("daily_limit", 50),
        "interactions_today": len(today_logs),
        "avg_confidence": round(sum(confidences) / len(confidences), 2) if confidences else 0,
        "auto_mode": settings.get("auto_mode", False),
    }


# ── Clone AI Engine ──

@router.post("/test")
async def test_clone_reply(request: Request):
    """Test sandbox: generate a clone reply for a sample message."""
    data = await request.json()
    message = data.get("message", "")
    channel = data.get("channel", "test")
    if not message.strip():
        raise HTTPException(400, "Message is required")

    knowledge = _load_all_knowledge()
    result = await _generate_reply(message, channel, knowledge)

    _log_interaction({
        "channel": channel, "direction": "test",
        "message": message, "reply": result["reply"],
        "intent": result["intent"], "confidence": result["confidence"],
        "flagged": result.get("flagged", False),
    })
    return result


async def _generate_reply(message: str, channel: str, knowledge: str) -> dict:
    """Core clone reply generation pipeline."""
    from app.llm_provider import get_llm_provider
    provider = get_llm_provider()

    # Step 1 — Classify intent
    intent = await _classify_intent(message, provider)

    # Step 2 — Check safety
    flagged = bool(SAFETY_KEYWORDS.search(message))

    # Step 3 — Generate reply
    system = (
        "You are a personal AI clone. You must reply EXACTLY as the person "
        "described in the profile below. Match their tone, vocabulary, "
        "formality, and style precisely.\n\n"
        f"=== KNOWLEDGE BASE ===\n{knowledge[:8000]}\n"
        "=== END KNOWLEDGE BASE ===\n\n"
        "Rules:\n"
        "- Reply naturally as this person would\n"
        "- If you don't have relevant knowledge, say so honestly\n"
        "- Never invent facts\n"
        "- Keep the reply concise unless the profile says otherwise\n"
        f"- The message arrived via: {channel}\n"
        f"- Detected intent: {intent}\n"
    )

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": message},
    ]

    reply = ""
    async for tok in provider.chat_stream(messages):
        reply += tok

    # Clean LLM artifacts
    reply = re.sub(r"<think>.*?</think>", "", reply, flags=re.DOTALL).strip()

    # Step 4 — Confidence scoring (simple heuristic)
    confidence = _compute_confidence(reply, knowledge, message)

    return {
        "reply": reply,
        "intent": intent,
        "confidence": round(confidence, 2),
        "channel": channel,
        "flagged": flagged,
        "auto_sendable": confidence >= _get_settings().get(
            "confidence_threshold", 0.85) and not flagged,
    }


async def _classify_intent(message: str, provider) -> str:
    """Classify message intent using LLM."""
    prompt = (
        f"Classify this message into ONE of: {', '.join(INTENT_LABELS)}.\n"
        f"Message: {message}\n"
        "Reply with ONLY the label, nothing else."
    )
    result = ""
    async for tok in provider.chat_stream([{"role": "user", "content": prompt}]):
        result += tok
    result = result.strip().lower()
    for label in INTENT_LABELS:
        if label in result:
            return label
    return "unknown"


def _compute_confidence(reply: str, knowledge: str, message: str) -> float:
    """Heuristic confidence score for the generated reply."""
    score = 0.5
    # Boost if knowledge base has content
    if len(knowledge) > 200:
        score += 0.15
    # Boost if reply is reasonably sized
    if 20 < len(reply) < 2000:
        score += 0.1
    # Boost if message words appear in knowledge
    words = set(message.lower().split())
    kb_lower = knowledge.lower()
    matches = sum(1 for w in words if len(w) > 3 and w in kb_lower)
    if matches > 2:
        score += 0.15
    # Penalize very short replies
    if len(reply) < 10:
        score -= 0.2
    # Penalize "I don't know" type replies
    if any(p in reply.lower() for p in ["i don't know", "je ne sais pas",
                                         "no relevant", "pas d'information"]):
        score -= 0.25
    return max(0.0, min(1.0, score))


# ── Onboarding ──

@router.get("/onboarding")
async def get_onboarding():
    """Return onboarding state."""
    default = {"completed": False, "current_step": 1, "steps_done": []}
    saved = _load_json(ONBOARDING_FILE, default)
    return {"onboarding": saved}


@router.post("/onboarding")
async def update_onboarding(request: Request):
    """Update onboarding state."""
    data = await request.json()
    state = _load_json(ONBOARDING_FILE, {"completed": False,
                                          "current_step": 1,
                                          "steps_done": []})
    if "current_step" in data:
        state["current_step"] = data["current_step"]
    if "step_done" in data:
        step = data["step_done"]
        if step not in state["steps_done"]:
            state["steps_done"].append(step)
    if len(state["steps_done"]) >= 5:
        state["completed"] = True
    _save_json(ONBOARDING_FILE, state)
    return {"onboarding": state}
