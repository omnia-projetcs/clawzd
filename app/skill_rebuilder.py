"""
Clawzd — Skill Rebuilder (inspired by Hermes Agent Curator).

Provides lifecycle management, usage tracking, LLM-powered skill
improvement, and background maintenance for the dynamic skill system.
"""
import ast
import asyncio
import json
import logging
import os
import shutil
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

from config import DATA_DIR

logger = logging.getLogger("clawzd.rebuilder")

SKILLS_DIR = os.path.join(DATA_DIR, "skills")
ARCHIVE_DIR = os.path.join(SKILLS_DIR, ".archive")
BACKUPS_DIR = os.path.join(SKILLS_DIR, ".backups")
USAGE_FILE = os.path.join(DATA_DIR, "skill_usage.jsonl")

# Lifecycle thresholds (days)
STALE_AFTER_DAYS = 30
ARCHIVE_AFTER_DAYS = 90

# Background maintenance interval (seconds)
MAINTENANCE_INTERVAL = 6 * 3600  # 6 hours


# ── Usage Tracking ────────────────────────────────────────────────────────

def log_usage(skill_name: str, success: bool, execution_time: float = 0.0,
              error: str = "", session_id: str = "") -> None:
    """Append a usage record to the JSONL log."""
    entry = {
        "skill": skill_name,
        "success": success,
        "execution_time": round(execution_time, 3),
        "error": error[:500] if error else "",
        "session_id": session_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    try:
        os.makedirs(os.path.dirname(USAGE_FILE), exist_ok=True)
        with open(USAGE_FILE, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.debug("Failed to log skill usage: %s", e)


def get_usage_history(skill_name: str, limit: int = 50) -> list[dict]:
    """Read the last N usage records for a given skill."""
    if not os.path.exists(USAGE_FILE):
        return []
    records = []
    try:
        with open(USAGE_FILE) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if entry.get("skill") == skill_name:
                        records.append(entry)
                except json.JSONDecodeError:
                    continue
    except Exception:
        pass
    return records[-limit:]


def get_usage_stats(skill_name: str) -> dict:
    """Compute aggregate stats for a skill."""
    history = get_usage_history(skill_name, limit=200)
    if not history:
        return {"total": 0, "successes": 0, "failures": 0,
                "avg_time": 0, "failure_rate": 0, "last_used": None}
    successes = sum(1 for r in history if r.get("success"))
    failures = len(history) - successes
    times = [r.get("execution_time", 0) for r in history if r.get("success")]
    avg_time = round(sum(times) / max(len(times), 1), 3)
    last_used = history[-1].get("timestamp") if history else None
    return {
        "total": len(history),
        "successes": successes,
        "failures": failures,
        "avg_time": avg_time,
        "failure_rate": round(failures / max(len(history), 1), 2),
        "last_used": last_used,
    }


# ── Lifecycle State Machine ──────────────────────────────────────────────

_STATE_FILE = os.path.join(DATA_DIR, "skill_states.json")


def _load_states() -> dict[str, dict]:
    if not os.path.exists(_STATE_FILE):
        return {}
    try:
        with open(_STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_states(states: dict[str, dict]) -> None:
    os.makedirs(os.path.dirname(_STATE_FILE), exist_ok=True)
    with open(_STATE_FILE, "w") as f:
        json.dump(states, f, indent=2, ensure_ascii=False)


def get_skill_state(name: str) -> str:
    """Return the lifecycle state of a skill (active/stale/archived/pinned)."""
    states = _load_states()
    return states.get(name, {}).get("state", "active")


def set_skill_state(name: str, state: str) -> None:
    """Set the lifecycle state of a skill."""
    states = _load_states()
    if name not in states:
        states[name] = {}
    states[name]["state"] = state
    states[name]["updated_at"] = datetime.now(timezone.utc).isoformat()
    _save_states(states)


def pin_skill(name: str) -> bool:
    """Pin a skill to prevent auto-archiving."""
    set_skill_state(name, "pinned")
    return True


def unpin_skill(name: str) -> bool:
    """Unpin a skill, returning it to active state."""
    set_skill_state(name, "active")
    return True


def is_pinned(name: str) -> bool:
    return get_skill_state(name) == "pinned"


# ── Archive / Restore ────────────────────────────────────────────────────

def archive_skill(name: str) -> tuple[bool, str]:
    """Move a skill file to .archive/ and unregister it."""
    from app.skill_registry import get_registry
    registry = get_registry()
    filepath = registry._file_map.get(name)
    if not filepath or not os.path.exists(filepath):
        return False, f"Skill '{name}' file not found"

    if os.path.basename(filepath).startswith("builtin_"):
        return False, "Cannot archive built-in skills"

    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    dest = os.path.join(ARCHIVE_DIR, os.path.basename(filepath))
    shutil.move(filepath, dest)
    registry.unregister(name)
    set_skill_state(name, "archived")
    logger.info("Archived skill '%s' → %s", name, dest)
    return True, f"Skill '{name}' archived"


def restore_skill(name: str) -> tuple[bool, str]:
    """Restore a skill from .archive/ back to skills/."""
    from app.skill_registry import get_registry

    if not os.path.isdir(ARCHIVE_DIR):
        return False, "No archive directory found"

    # Find the file in archive
    candidates = [f for f in os.listdir(ARCHIVE_DIR) if f.endswith(".py")]
    target_file = None
    for fname in candidates:
        fpath = os.path.join(ARCHIVE_DIR, fname)
        try:
            with open(fpath) as f:
                content = f.read()
            if f'name = "{name}"' in content:
                target_file = fpath
                break
        except Exception:
            continue

    if not target_file:
        return False, f"Skill '{name}' not found in archive"

    dest = os.path.join(SKILLS_DIR, os.path.basename(target_file))
    shutil.move(target_file, dest)

    registry = get_registry()
    skill = registry.register_file(dest)
    if skill:
        set_skill_state(name, "active")
        logger.info("Restored skill '%s' from archive", name)
        return True, f"Skill '{name}' restored"
    return False, "File restored but failed to load into registry"


# ── Backup Management ────────────────────────────────────────────────────

def _create_backup(filepath: str, skill_name: str) -> str:
    """Create a timestamped backup of a skill file. Returns backup path."""
    os.makedirs(BACKUPS_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"{skill_name}_{timestamp}.py.bak"
    backup_path = os.path.join(BACKUPS_DIR, backup_name)
    shutil.copy2(filepath, backup_path)
    logger.info("Created backup: %s", backup_path)
    return backup_path


def _restore_from_backup(backup_path: str, original_path: str) -> bool:
    """Restore a skill from a backup file."""
    try:
        shutil.copy2(backup_path, original_path)
        return True
    except Exception as e:
        logger.error("Failed to restore backup: %s", e)
        return False


# ── Code Validation ──────────────────────────────────────────────────────

def validate_skill_code(code: str) -> tuple[bool, str]:
    """Validate that generated code is syntactically correct Python
    and contains a BaseSkill subclass."""
    # 1. Syntax check
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, f"Syntax error at line {e.lineno}: {e.msg}"

    # 2. Check for BaseSkill subclass
    has_baseskill = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for base in node.bases:
                base_name = ""
                if isinstance(base, ast.Name):
                    base_name = base.id
                elif isinstance(base, ast.Attribute):
                    base_name = base.attr
                if base_name == "BaseSkill":
                    has_baseskill = True
                    break
    if not has_baseskill:
        return False, "No BaseSkill subclass found in generated code"

    # 3. Check for required imports
    if "from app.skill_model import" not in code and "import app.skill_model" not in code:
        return False, "Missing 'from app.skill_model import BaseSkill' import"

    return True, "Valid"


# ── LLM-Powered Rebuild ─────────────────────────────────────────────────

REBUILD_SYSTEM_PROMPT = """You are a Python skill code optimizer for the Clawzd agent system.
You will receive the source code of an existing skill, its execution history, and an optional instruction.

Your task is to generate an IMPROVED version of the skill that:
1. Fixes any bugs revealed by the error history
2. Improves performance and reliability
3. Adds better error handling
4. Optimizes the logic based on usage patterns
5. Follows the instruction if one is provided

RULES:
- The skill MUST inherit from BaseSkill
- The skill MUST import from app.skill_model (BaseSkill, SkillContext, SkillResult)
- Keep the same `name` attribute (do not rename the skill)
- Output ONLY the complete Python file content — no markdown fences, no explanation
- Preserve existing parameters and triggers unless the instruction says to change them
"""

# Append dev best practices to the rebuild prompt
try:
    from app.preprompts import _load_dev_profile
    _dev_profile = _load_dev_profile()
    if _dev_profile:
        REBUILD_SYSTEM_PROMPT += f"\nCODING STANDARDS:\n{_dev_profile}\n"
except Exception:
    pass  # Profile injection is non-critical



async def rebuild_skill(
    skill_name: str,
    instruction: str = "",
    provider: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Use the LLM to generate an improved version of a skill.

    Returns a dict with status, backup_path, and details.
    """
    from app.skill_registry import get_registry
    from app.llm_provider import get_llm_provider
    from app.settings import load_settings

    registry = get_registry()
    filepath = registry._file_map.get(skill_name)
    if not filepath or not os.path.exists(filepath):
        return {"success": False, "error": f"Skill '{skill_name}' not found"}

    if os.path.basename(filepath).startswith("builtin_"):
        return {"success": False, "error": "Cannot rebuild built-in skills"}

    # Read current source
    with open(filepath) as f:
        current_code = f.read()

    # Get execution history
    stats = get_usage_stats(skill_name)
    recent_errors = [
        r for r in get_usage_history(skill_name, limit=20)
        if not r.get("success") and r.get("error")
    ]

    # Build the prompt
    user_prompt_parts = [
        f"## Current skill source code ({skill_name}):\n```python\n{current_code}\n```",
        f"\n## Execution statistics:\n{json.dumps(stats, indent=2)}",
    ]
    if recent_errors:
        error_summary = "\n".join(
            f"- {e['error'][:200]}" for e in recent_errors[-5:]
        )
        user_prompt_parts.append(f"\n## Recent errors:\n{error_summary}")

    if instruction:
        user_prompt_parts.append(f"\n## User instruction:\n{instruction}")

    user_prompt = "\n".join(user_prompt_parts)

    # Call LLM (non-streaming — collect full response)
    settings = load_settings()
    provider_name = provider or settings.get("provider", "ollama")
    model_name = model or settings.get("model", "")

    llm = get_llm_provider(provider_name)
    messages = [
        {"role": "system", "content": REBUILD_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    response_chunks = []
    try:
        async for chunk in llm.chat_stream(messages, model=model_name):
            response_chunks.append(chunk)
    except Exception as e:
        return {"success": False, "error": f"LLM call failed: {e}"}

    new_code = "".join(response_chunks).strip()

    # Strip markdown fences if present
    if new_code.startswith("```"):
        lines = new_code.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        new_code = "\n".join(lines)

    # Validate the generated code
    valid, reason = validate_skill_code(new_code)
    if not valid:
        return {"success": False, "error": f"Generated code validation failed: {reason}",
                "generated_code": new_code[:2000]}

    # Create backup
    backup_path = _create_backup(filepath, skill_name)

    # Write new code
    try:
        with open(filepath, "w") as f:
            f.write(new_code)
    except Exception as e:
        _restore_from_backup(backup_path, filepath)
        return {"success": False, "error": f"Failed to write file: {e}"}

    # Reload the skill
    reloaded = registry.reload_skill(skill_name)
    if not reloaded:
        logger.warning("Rebuild of '%s' failed to reload — restoring backup", skill_name)
        _restore_from_backup(backup_path, filepath)
        registry.reload_skill(skill_name)
        return {"success": False, "error": "New code failed to load — original restored",
                "backup_path": backup_path}

    logger.info("Successfully rebuilt skill '%s'", skill_name)
    return {
        "success": True,
        "message": f"Skill '{skill_name}' rebuilt successfully",
        "backup_path": backup_path,
        "stats_before": stats,
    }


# ── Health Report ────────────────────────────────────────────────────────

def get_health_report() -> dict:
    """Generate a health report for all skills."""
    from app.skill_registry import get_registry
    registry = get_registry()

    skills_health = []
    for skill in registry.get_all():
        stats = get_usage_stats(skill.name)
        state = get_skill_state(skill.name)
        is_builtin = os.path.basename(
            registry._file_map.get(skill.name, "")
        ).startswith("builtin_")

        skills_health.append({
            "name": skill.name,
            "category": skill.category,
            "enabled": skill.enabled,
            "state": state,
            "source": "builtin" if is_builtin else "user",
            "usage": stats,
        })

    # Archived skills
    archived = []
    if os.path.isdir(ARCHIVE_DIR):
        archived = [f for f in os.listdir(ARCHIVE_DIR) if f.endswith(".py")]

    return {
        "total_active": len(registry),
        "total_archived": len(archived),
        "skills": skills_health,
        "archived_files": archived,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# ── Automatic Lifecycle Transitions ─────────────────────────────────────

def apply_automatic_transitions() -> dict[str, int]:
    """Walk all skills and transition states based on usage timestamps."""
    from app.skill_registry import get_registry
    registry = get_registry()

    now = datetime.now(timezone.utc)
    stale_cutoff = now - timedelta(days=STALE_AFTER_DAYS)
    archive_cutoff = now - timedelta(days=ARCHIVE_AFTER_DAYS)

    counts = {"marked_stale": 0, "archived": 0, "reactivated": 0, "checked": 0}

    for skill in registry.get_all():
        counts["checked"] += 1
        filepath = registry._file_map.get(skill.name, "")

        # Skip built-in and pinned skills
        if os.path.basename(filepath).startswith("builtin_"):
            continue
        if is_pinned(skill.name):
            continue

        current_state = get_skill_state(skill.name)
        stats = get_usage_stats(skill.name)
        last_used_str = stats.get("last_used")

        if last_used_str:
            try:
                last_used = datetime.fromisoformat(last_used_str)
                if last_used.tzinfo is None:
                    last_used = last_used.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                last_used = now  # can't parse → treat as recent
        else:
            # Never used — use created_at as anchor
            last_used = datetime.fromisoformat(
                skill.created_at or now.isoformat()
            )
            if last_used.tzinfo is None:
                last_used = last_used.replace(tzinfo=timezone.utc)

        if last_used <= archive_cutoff and current_state != "archived":
            ok, _ = archive_skill(skill.name)
            if ok:
                counts["archived"] += 1
        elif last_used <= stale_cutoff and current_state == "active":
            set_skill_state(skill.name, "stale")
            counts["marked_stale"] += 1
        elif last_used > stale_cutoff and current_state == "stale":
            set_skill_state(skill.name, "active")
            counts["reactivated"] += 1

    return counts


# ── Background Maintenance Task ──────────────────────────────────────────

async def _maintenance_loop():
    """Periodic background task for skill lifecycle maintenance."""
    logger.info("Skill rebuilder maintenance loop started (interval=%ds)", MAINTENANCE_INTERVAL)
    while True:
        await asyncio.sleep(MAINTENANCE_INTERVAL)
        try:
            counts = apply_automatic_transitions()
            if any(v > 0 for k, v in counts.items() if k != "checked"):
                logger.info("Skill maintenance: %s", counts)
        except Exception as e:
            logger.error("Skill maintenance error: %s", e)


def start_maintenance_task():
    """Start the background maintenance loop (call from gateway startup)."""
    asyncio.create_task(_maintenance_loop())
