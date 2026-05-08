"""
Clawzd — Skill Model.
Defines the base class, context, and result types for all dynamic skills.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Skill categories — used for filtering and UI grouping
# ---------------------------------------------------------------------------
SKILL_CATEGORIES = {
    "code":        "Code analysis, generation, and execution",
    "data":        "Data processing, analysis, and transformation",
    "web":         "Web scraping, browsing, and API interactions",
    "media":       "Image, audio, and video processing",
    "automation":  "File operations, scheduling, and workflows",
    "integration": "External service connectors (Discord, Slack, …)",
    "other":       "Uncategorized skills",
}


# ---------------------------------------------------------------------------
# SkillContext — runtime context passed to every skill execution
# ---------------------------------------------------------------------------
@dataclass
class SkillContext:
    """Runtime context available to every skill during execution."""
    session_id: str = ""
    user_message: str = ""
    provider: str = "local"
    model: str = ""
    workspace_dir: str = ""
    data_dir: str = ""
    extra: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# SkillResult — standardised return value from skill execution
# ---------------------------------------------------------------------------
@dataclass
class SkillResult:
    """Standardised result returned by every skill execution."""
    success: bool
    data: Any = None
    message: str = ""
    error: str = ""
    execution_time: float = 0.0
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "data": self.data,
            "message": self.message,
            "error": self.error,
            "execution_time": round(self.execution_time, 3),
            "metadata": self.metadata,
        }


# ---------------------------------------------------------------------------
# BaseSkill — abstract base class that every skill must implement
# ---------------------------------------------------------------------------
class BaseSkill(ABC):
    """Abstract base class for all Clawzd skills.

    Subclasses must set the class-level attributes and implement ``execute``.
    """

    # --- Required metadata (override in subclass) ---
    name: str = ""
    description: str = ""
    category: str = "other"
    version: str = "1.0.0"

    # Regex patterns that trigger auto-detection for this skill.
    # These are merged into ``skill_selector`` at runtime.
    triggers: list[str] = []

    # JSON-Schema-style parameter definition for the skill.
    # Used to build OpenAI function-calling tool definitions.
    parameters: dict = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    # Whether this skill is currently enabled.
    enabled: bool = True

    # Runtime stats (managed by the registry, not the skill itself)
    usage_count: int = 0
    created_at: str = ""
    last_used_at: Optional[str] = None

    # Lifecycle state: active, stale, archived, pinned
    state: str = "active"
    # Error tracking for health monitoring
    error_count: int = 0
    last_error: str = ""
    # Origin: builtin, user, agent
    source: str = "user"

    # --- Abstract execution method ---
    @abstractmethod
    async def execute(self, params: dict, context: SkillContext) -> SkillResult:
        """Execute the skill with the given parameters and context.

        Args:
            params: Validated input parameters matching ``self.parameters``.
            context: Runtime context (session, provider, workspace, …).

        Returns:
            A ``SkillResult`` with success status and data.
        """
        ...

    # --- Helpers ---
    def to_tool_definition(self) -> dict:
        """Export this skill as an OpenAI function-calling tool definition."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "metadata": {
                "category": self.category,
                "version": self.version,
                "dynamic": True,
            },
        }

    def to_dict(self) -> dict:
        """Serialise the skill metadata to a JSON-friendly dictionary."""
        return {
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "version": self.version,
            "triggers": self.triggers,
            "parameters": self.parameters,
            "enabled": self.enabled,
            "usage_count": self.usage_count,
            "created_at": self.created_at,
            "last_used_at": self.last_used_at,
            "state": self.state,
            "error_count": self.error_count,
            "last_error": self.last_error,
            "source": self.source,
        }

    def validate_params(self, params: dict) -> tuple[bool, str]:
        """Basic validation against the parameter schema.

        Returns:
            ``(True, "")`` on success, ``(False, reason)`` on failure.
        """
        required = self.parameters.get("required", [])
        properties = self.parameters.get("properties", {})
        for key in required:
            if key not in params:
                return False, f"Missing required parameter: {key}"
        for key in params:
            if key not in properties:
                return False, f"Unknown parameter: {key}"
        return True, ""

    def __repr__(self) -> str:
        return f"<Skill:{self.name} [{self.category}] v{self.version}>"


# ---------------------------------------------------------------------------
# Skill template generator — produces a starter .py file for new skills
# ---------------------------------------------------------------------------
def generate_skill_template(
    name: str,
    description: str,
    category: str = "other",
    param_names: list[str] | None = None,
) -> str:
    """Return a Python source string for a new skill module.

    The generated code defines a subclass of ``BaseSkill`` with stub
    ``execute`` method and correct metadata.
    """
    safe_class = "".join(w.capitalize() for w in name.replace("-", "_").split("_")) + "Skill"
    param_names = param_names or ["input"]
    props = "\n".join(
        f'            "{p}": {{"type": "string", "description": "{p} value"}},'
        for p in param_names
    )
    req = ", ".join(f'"{p}"' for p in param_names)

    return f'''"""
Clawzd — Custom Skill: {name}
{description}
"""
import time
from app.skill_model import BaseSkill, SkillContext, SkillResult


class {safe_class}(BaseSkill):
    name = "{name}"
    description = "{description}"
    category = "{category}"
    version = "1.0.0"

    triggers = [
        r"(?i)\\b{name.replace("_", "|")}\\b",
    ]

    parameters = {{
        "type": "object",
        "properties": {{
{props}
        }},
        "required": [{req}],
    }}

    async def execute(self, params: dict, context: SkillContext) -> SkillResult:
        t0 = time.perf_counter()
        try:
            # --- Your skill logic here ---
            result_data = {{"echo": params}}
            return SkillResult(
                success=True,
                data=result_data,
                message="Skill executed successfully",
                execution_time=time.perf_counter() - t0,
            )
        except Exception as e:
            return SkillResult(
                success=False,
                error=str(e),
                execution_time=time.perf_counter() - t0,
            )
'''
