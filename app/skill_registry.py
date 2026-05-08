"""
Clawzd — Skill Registry.
Dynamically discovers, loads, and manages skill modules from the filesystem.
"""
import os
import sys
import time
import logging
import importlib
import importlib.util
import inspect
from datetime import datetime, timezone
from typing import Optional

from app.skill_model import BaseSkill, SkillContext, SkillResult, SKILL_CATEGORIES
from config import DATA_DIR

logger = logging.getLogger("clawzd.registry")

SKILLS_DIR = os.path.join(DATA_DIR, "skills")
os.makedirs(SKILLS_DIR, exist_ok=True)


class SkillRegistry:
    """Singleton registry that discovers, loads, and caches skill instances.

    Skills are Python files placed in ``data/skills/`` that contain at least
    one class inheriting from :class:`BaseSkill`.  The registry scans this
    directory, imports each module via ``importlib``, and instantiates every
    ``BaseSkill`` subclass it finds.

    Provides hot-reload: call ``reload()`` or ``reload_skill(name)`` to pick
    up changes without restarting the application.
    """

    _instance: Optional["SkillRegistry"] = None

    def __new__(cls) -> "SkillRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialised = False
        return cls._instance

    def __init__(self):
        if getattr(self, '_initialised', False):
            return
        self._skills: dict[str, BaseSkill] = {}
        self._modules: dict[str, object] = {}
        self._file_map: dict[str, str] = {}  # name → filepath
        self._initialised = True

    # ------------------------------------------------------------------
    # Discovery & loading
    # ------------------------------------------------------------------

    def load_all(self) -> int:
        """Scan ``SKILLS_DIR`` and load every ``.py`` skill module.
        Also traverses one level deep for skills organized in subdirectories.

        Returns:
            Number of skills successfully loaded.
        """
        loaded = 0
        if not os.path.isdir(SKILLS_DIR):
            logger.warning("Skills directory does not exist: %s", SKILLS_DIR)
            return 0

        def process_dir(directory, level=0):
            nonlocal loaded
            for filename in sorted(os.listdir(directory)):
                if filename.startswith("__"):
                    continue
                filepath = os.path.join(directory, filename)

                if os.path.isdir(filepath) and level == 0:
                    process_dir(filepath, level + 1)
                elif os.path.isfile(filepath) and filename.endswith(".py"):
                    try:
                        skills = self._load_module(filepath)
                        loaded += len(skills)
                    except Exception as e:
                        logger.error("Failed to load skill from %s: %s", filename, e)

        process_dir(SKILLS_DIR)

        logger.info("Skill registry: %d skill(s) loaded from %s", loaded, SKILLS_DIR)
        return loaded

    def _load_module(self, filepath: str) -> list[BaseSkill]:
        """Import a single ``.py`` file and register every BaseSkill subclass."""
        module_name = f"skill_{os.path.basename(filepath).removesuffix('.py')}"

        # Remove previously loaded version to allow hot-reload
        if module_name in sys.modules:
            del sys.modules[module_name]

        spec = importlib.util.spec_from_file_location(module_name, filepath)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot create module spec for {filepath}")

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        found: list[BaseSkill] = []

        for _attr_name, obj in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(obj, BaseSkill)
                and obj is not BaseSkill
                and getattr(obj, "name", "")
            ):
                instance = obj()
                if not instance.created_at:
                    instance.created_at = datetime.now(timezone.utc).isoformat()

                # Auto-detect source based on filename
                if os.path.basename(filepath).startswith("builtin_"):
                    instance.source = "builtin"

                # Preserve usage stats from a previous load
                prev = self._skills.get(instance.name)
                if prev:
                    instance.usage_count = prev.usage_count
                    instance.created_at = prev.created_at
                    instance.error_count = prev.error_count
                    instance.last_error = prev.last_error
                    instance.state = prev.state
                    instance.source = prev.source

                self._skills[instance.name] = instance
                self._modules[instance.name] = module
                self._file_map[instance.name] = filepath
                found.append(instance)
                logger.info("  ✓ Loaded skill: %s [%s]", instance.name, instance.category)

        return found

    # ------------------------------------------------------------------
    # Hot-reload
    # ------------------------------------------------------------------

    def reload(self) -> int:
        """Reload **all** skills from disk (hot-reload)."""
        self._skills.clear()
        self._modules.clear()
        self._file_map.clear()
        return self.load_all()

    def reload_skill(self, name: str) -> Optional[BaseSkill]:
        """Reload a single skill by name."""
        filepath = self._file_map.get(name)
        if not filepath or not os.path.exists(filepath):
            logger.warning("Cannot reload skill '%s': file not found", name)
            return None
        try:
            skills = self._load_module(filepath)
            return skills[0] if skills else None
        except Exception as e:
            logger.error("Failed to reload skill '%s': %s", name, e)
            return None

    # ------------------------------------------------------------------
    # Registration (for skills created at runtime via API)
    # ------------------------------------------------------------------

    def register_file(self, filepath: str) -> Optional[BaseSkill]:
        """Load and register a skill from a new file.

        Returns:
            The loaded ``BaseSkill`` instance, or ``None`` on failure.
        """
        try:
            skills = self._load_module(filepath)
            return skills[0] if skills else None
        except Exception as e:
            logger.error("Failed to register skill from %s: %s", filepath, e)
            return None

    def unregister(self, name: str) -> bool:
        """Remove a skill from the registry (and optionally delete file)."""
        if name not in self._skills:
            return False
        filepath = self._file_map.get(name)
        del self._skills[name]
        self._modules.pop(name, None)
        self._file_map.pop(name, None)
        return True

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get(self, name: str) -> Optional[BaseSkill]:
        """Get a skill by name."""
        return self._skills.get(name)

    def get_all(self) -> list[BaseSkill]:
        """Return all registered skills."""
        return list(self._skills.values())

    def get_enabled(self) -> list[BaseSkill]:
        """Return only enabled skills."""
        return [s for s in self._skills.values() if s.enabled]

    def get_by_category(self, category: str) -> list[BaseSkill]:
        """Return all skills in a given category."""
        return [s for s in self._skills.values() if s.category == category]

    def get_names(self) -> list[str]:
        """Return all registered skill names."""
        return list(self._skills.keys())

    def get_categories(self) -> dict[str, int]:
        """Return category names with skill counts."""
        counts: dict[str, int] = {}
        for s in self._skills.values():
            counts[s.category] = counts.get(s.category, 0) + 1
        return counts

    def get_tool_definitions(self) -> list[dict]:
        """Export all enabled skills as OpenAI function-calling tool definitions."""
        return [s.to_tool_definition() for s in self.get_enabled()]

    def get_trigger_map(self) -> dict[str, list[str]]:
        """Return a mapping of skill_name → trigger patterns for the selector."""
        return {
            s.name: s.triggers
            for s in self.get_enabled()
            if s.triggers
        }

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def execute(self, name: str, params: dict, context: SkillContext) -> SkillResult:
        """Execute a skill by name with the given parameters.

        Handles validation, execution, stats tracking, and error handling.
        """
        skill = self._skills.get(name)
        if not skill:
            return SkillResult(success=False, error=f"Skill '{name}' not found")

        if not skill.enabled:
            return SkillResult(success=False, error=f"Skill '{name}' is disabled")

        # Validate parameters
        valid, reason = skill.validate_params(params)
        if not valid:
            return SkillResult(success=False, error=f"Validation failed: {reason}")

        # Execute
        t0 = time.perf_counter()
        try:
            result = await skill.execute(params, context)
            skill.usage_count += 1
            skill.last_used_at = datetime.now(timezone.utc).isoformat()
            if not result.execution_time:
                result.execution_time = time.perf_counter() - t0

            # Log usage for the rebuilder
            try:
                from app.skill_rebuilder import log_usage
                log_usage(
                    skill_name=name,
                    success=result.success,
                    execution_time=result.execution_time,
                    error=result.error,
                    session_id=context.session_id,
                )
            except Exception:
                pass  # Non-critical

            # Track errors on the skill instance
            if not result.success and result.error:
                skill.error_count += 1
                skill.last_error = result.error[:500]

            return result
        except Exception as e:
            logger.error("Skill '%s' execution failed: %s", name, e, exc_info=True)
            skill.error_count += 1
            skill.last_error = str(e)[:500]

            # Log failure
            try:
                from app.skill_rebuilder import log_usage
                log_usage(name, False, time.perf_counter() - t0, str(e), context.session_id)
            except Exception:
                pass

            return SkillResult(
                success=False,
                error=f"Execution error: {e}",
                execution_time=time.perf_counter() - t0,
            )

    # ------------------------------------------------------------------
    # Info
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._skills)

    def __repr__(self) -> str:
        return f"<SkillRegistry: {len(self._skills)} skill(s)>"


# Module-level singleton accessor
_registry: Optional[SkillRegistry] = None


def get_registry() -> SkillRegistry:
    """Return the global SkillRegistry singleton."""
    global _registry
    if _registry is None:
        _registry = SkillRegistry()
    return _registry


# ------------------------------------------------------------------
# Active skills persistence (catalog activation / deactivation)
# ------------------------------------------------------------------

import json

_ACTIVE_SKILLS_FILE = os.path.join(DATA_DIR, "active_skills.json")

# Hardcoded builtin tools from tool_executor.py — always available,
# listed in the catalog for reference but cannot be deactivated.
HARDCODED_TOOLS: list[dict] = [
    {"name": "search_web",         "description": "Search the internet",                                       "category": "web"},
    {"name": "execute_python",     "description": "Execute Python code in sandbox",                            "category": "code"},
    {"name": "run_command",        "description": "Run a local shell command",                                 "category": "code"},
    {"name": "screenshot_remote",  "description": "Capture a remote webpage screenshot",                       "category": "web"},
    {"name": "screenshot_local",   "description": "Capture local desktop screenshot",                          "category": "media"},
    {"name": "generate_image",     "description": "Generate an image from text (SVG / Stable Diffusion)",      "category": "media"},
    {"name": "generate_animation", "description": "Generate an animation / video from text",                   "category": "media"},
    {"name": "browse_web",         "description": "Navigate and interact with a web page",                     "category": "web"},
    {"name": "audit_code",         "description": "Audit code for security & quality",                         "category": "code"},
    {"name": "rag_search",         "description": "Search knowledge base (RAG)",                               "category": "data"},
    {"name": "edit_file",          "description": "Edit a file in the workspace",                              "category": "code"},
    {"name": "read_file",          "description": "Read a file from the workspace",                            "category": "code"},
    {"name": "create_document",    "description": "Create a document (PDF, DOCX, MD…)",                        "category": "automation"},
    {"name": "send_email",         "description": "Send an email via SMTP",                                    "category": "integration"},
    {"name": "memory",             "description": "Save/recall persistent memory notes",                       "category": "other"},
    {"name": "rebuild_skill",      "description": "Rebuild and improve an existing skill using AI",             "category": "other"},
    {"name": "create_skill",       "description": "Create a new custom skill",                                 "category": "other"},
]


def load_active_skills() -> list[str]:
    """Return the list of manually activated skill names."""
    if not os.path.exists(_ACTIVE_SKILLS_FILE):
        return []
    try:
        with open(_ACTIVE_SKILLS_FILE) as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_active_skills(names: list[str]) -> None:
    """Persist the list of manually activated skill names."""
    os.makedirs(os.path.dirname(_ACTIVE_SKILLS_FILE), exist_ok=True)
    with open(_ACTIVE_SKILLS_FILE, "w") as f:
        json.dump(sorted(set(names)), f, indent=2)


def activate_skill(name: str) -> bool:
    """Add a skill to the active list. Returns True if newly added."""
    active = load_active_skills()
    if name in active:
        return False
    active.append(name)
    save_active_skills(active)
    return True


def deactivate_skill(name: str) -> bool:
    """Remove a skill from the active list. Returns True if removed."""
    active = load_active_skills()
    if name not in active:
        return False
    active.remove(name)
    save_active_skills(active)
    return True


def get_full_catalog() -> list[dict]:
    """Build the full skill catalog merging hardcoded tools + dynamic skills.

    Each entry has: name, description, category, source, activatable, active.
    """
    active = set(load_active_skills())
    catalog: list[dict] = []

    # 1. Hardcoded builtins (always on, not toggleable)
    for tool in HARDCODED_TOOLS:
        catalog.append({
            "name": tool["name"],
            "description": tool["description"],
            "category": tool["category"],
            "version": "—",
            "source": "core",
            "activatable": False,
            "active": True,  # always on
            "usage_count": 0,
            "state": "active",
            "enabled": True,
        })

    # 2. Dynamic skills from registry (toggleable)
    registry = get_registry()
    seen = {t["name"] for t in HARDCODED_TOOLS}
    for skill in registry.get_all():
        if skill.name in seen:
            continue  # skip if overridden by hardcoded
        catalog.append({
            "name": skill.name,
            "description": skill.description,
            "category": skill.category,
            "version": skill.version,
            "source": skill.source,
            "activatable": True,
            "active": skill.name in active,
            "usage_count": skill.usage_count,
            "state": skill.state,
            "enabled": skill.enabled,
            "triggers": skill.triggers,
        })

    return catalog
