"""
Clawzd — Dynamic skill management API.
CRUD operations for skills + execution via the SkillRegistry.
"""
import os
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Request, HTTPException

from app.skill_model import (
    BaseSkill,
    SkillContext,
    SkillResult,
    SKILL_CATEGORIES,
    generate_skill_template,
)
from app.skill_registry import (
    get_registry, SKILLS_DIR,
    get_full_catalog, load_active_skills, activate_skill, deactivate_skill,
)
from config import DATA_DIR, WORKSPACE_DIR

router = APIRouter()
logger = logging.getLogger("clawzd.skills")


# ---------------------------------------------------------------------------
# Catalog (unified view of all skills with activation state)
# ---------------------------------------------------------------------------

@router.get("/catalog")
async def skill_catalog():
    """Return the full skill catalog (hardcoded + dynamic) with activation state."""
    catalog = get_full_catalog()
    active = load_active_skills()
    return {
        "skills": catalog,
        "total": len(catalog),
        "active_count": len(active),
        "active_names": active,
    }


@router.get("/active")
async def active_skills():
    """Return the list of currently activated skill names."""
    active = load_active_skills()
    return {"active": active, "count": len(active)}


@router.post("/activate/{skill_name}")
async def activate_skill_endpoint(skill_name: str):
    """Activate a skill (add to the user's active list)."""
    added = activate_skill(skill_name)
    active = load_active_skills()
    return {
        "status": "activated" if added else "already_active",
        "name": skill_name,
        "active_count": len(active),
    }


@router.post("/deactivate/{skill_name}")
async def deactivate_skill_endpoint(skill_name: str):
    """Deactivate a skill (remove from the user's active list)."""
    removed = deactivate_skill(skill_name)
    active = load_active_skills()
    return {
        "status": "deactivated" if removed else "not_active",
        "name": skill_name,
        "active_count": len(active),
    }


# ---------------------------------------------------------------------------
# List & discovery
# ---------------------------------------------------------------------------

@router.get("/list")
async def list_skills():
    """Return all registered skills with metadata."""
    registry = get_registry()
    return {
        "skills": [s.to_dict() for s in registry.get_all()],
        "total": len(registry),
    }


@router.get("/categories")
async def list_categories():
    """Return available skill categories with descriptions and counts."""
    registry = get_registry()
    counts = registry.get_categories()
    return {
        "categories": [
            {
                "id": cat_id,
                "description": cat_desc,
                "skill_count": counts.get(cat_id, 0),
            }
            for cat_id, cat_desc in SKILL_CATEGORIES.items()
        ]
    }


@router.get("/by-category/{category}")
async def skills_by_category(category: str):
    """Return skills filtered by category."""
    if category not in SKILL_CATEGORIES:
        raise HTTPException(400, f"Unknown category: {category}. Valid: {list(SKILL_CATEGORIES.keys())}")
    registry = get_registry()
    skills = registry.get_by_category(category)
    return {
        "category": category,
        "skills": [s.to_dict() for s in skills],
    }


@router.get("/detail/{skill_name}")
async def skill_detail(skill_name: str):
    """Return detailed information about a specific skill."""
    registry = get_registry()
    skill = registry.get(skill_name)
    if not skill:
        raise HTTPException(404, f"Skill '{skill_name}' not found")
    return {
        "skill": skill.to_dict(),
        "tool_definition": skill.to_tool_definition(),
    }


# ---------------------------------------------------------------------------
# Creation
# ---------------------------------------------------------------------------

@router.post("/create")
async def create_skill(request: Request):
    """Create a new skill from parameters or from a code template.

    Body JSON:
        name (str): Unique skill identifier (snake_case)
        description (str): What the skill does
        category (str): One of SKILL_CATEGORIES keys
        code (str, optional): Full Python source code. If omitted, a template is generated.
        parameters (list[str], optional): Parameter names for the template generator.
        triggers (list[str], optional): Regex patterns for auto-detection.
    """
    data = await request.json()
    name = data.get("name", "").strip().replace(" ", "_").lower()
    description = data.get("description", "").strip()
    category = data.get("category", "other").strip()

    if not name or not description:
        raise HTTPException(400, "name and description are required")

    if category not in SKILL_CATEGORIES:
        raise HTTPException(400, f"Invalid category. Valid: {list(SKILL_CATEGORIES.keys())}")

    registry = get_registry()
    if registry.get(name):
        raise HTTPException(409, f"Skill '{name}' already exists")

    # Build the Python source
    code = data.get("code", "").strip()
    if not code:
        param_names = data.get("parameters", ["input"])
        code = generate_skill_template(name, description, category, param_names)

    # Inject custom triggers if provided
    custom_triggers = data.get("triggers", [])
    if custom_triggers and "triggers = [" in code:
        import re
        triggers_str = ",\n        ".join(f'r"{t}"' for t in custom_triggers)
        code = re.sub(
            r"triggers = \[.*?\]",
            f"triggers = [\n        {triggers_str},\n    ]",
            code,
            flags=re.DOTALL,
        )

    # Write skill file
    filename = f"{name}.py"
    filepath = os.path.join(SKILLS_DIR, filename)
    if os.path.exists(filepath):
        raise HTTPException(409, f"File '{filename}' already exists in skills directory")

    with open(filepath, "w") as f:
        f.write(code)

    # Load into registry
    skill = registry.register_file(filepath)
    if not skill:
        # Cleanup if loading failed
        os.unlink(filepath)
        raise HTTPException(500, "Skill file was created but failed to load. Check the code syntax.")

    logger.info("Created skill '%s' [%s]", name, category)
    return {
        "status": "created",
        "skill": skill.to_dict(),
        "file": filepath,
    }


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

@router.post("/execute/{skill_name}")
async def execute_skill(skill_name: str, request: Request):
    """Execute a skill by name with the given parameters.

    Body JSON:
        params (dict): Parameters matching the skill's schema.
        session_id (str, optional): Current session ID for context.
        provider (str, optional): LLM provider for context.
        model (str, optional): LLM model for context.
    """
    data = await request.json()
    params = data.get("params", {})

    context = SkillContext(
        session_id=data.get("session_id", ""),
        user_message=data.get("user_message", ""),
        provider=data.get("provider", "local"),
        model=data.get("model", ""),
        workspace_dir=WORKSPACE_DIR,
        data_dir=DATA_DIR,
    )

    registry = get_registry()
    result = await registry.execute(skill_name, params, context)
    return result.to_dict()


# ---------------------------------------------------------------------------
# Management
# ---------------------------------------------------------------------------

@router.post("/toggle/{skill_name}")
async def toggle_skill(skill_name: str):
    """Enable or disable a skill."""
    registry = get_registry()
    skill = registry.get(skill_name)
    if not skill:
        raise HTTPException(404, f"Skill '{skill_name}' not found")
    skill.enabled = not skill.enabled
    return {"status": "toggled", "name": skill_name, "enabled": skill.enabled}


@router.delete("/{skill_name}")
async def delete_skill(skill_name: str):
    """Delete a skill by name (removes file and unregisters)."""
    registry = get_registry()
    skill = registry.get(skill_name)
    if not skill:
        raise HTTPException(404, f"Skill '{skill_name}' not found")

    # Prevent deleting built-in skills
    filepath = registry._file_map.get(skill_name, "")
    if os.path.basename(filepath).startswith("builtin_"):
        raise HTTPException(403, "Cannot delete built-in skills")

    registry.unregister(skill_name)

    if filepath and os.path.exists(filepath):
        os.unlink(filepath)

    logger.info("Deleted skill '%s'", skill_name)
    return {"status": "deleted", "name": skill_name}


@router.post("/reload")
async def reload_skills():
    """Hot-reload all skills from disk without restarting the application."""
    registry = get_registry()
    count = registry.reload()
    return {"status": "reloaded", "skills_loaded": count}


@router.post("/reload/{skill_name}")
async def reload_single_skill(skill_name: str):
    """Hot-reload a single skill by name."""
    registry = get_registry()
    skill = registry.reload_skill(skill_name)
    if not skill:
        raise HTTPException(404, f"Skill '{skill_name}' not found or failed to reload")
    return {"status": "reloaded", "skill": skill.to_dict()}


@router.get("/template")
async def get_skill_template(
    name: str = "my_skill",
    description: str = "A custom skill",
    category: str = "other",
):
    """Generate a skill template file content for reference or download."""
    code = generate_skill_template(name, description, category)
    return {"template": code, "filename": f"{name}.py"}


# ---------------------------------------------------------------------------
# Skill Rebuilder endpoints (Hermes-inspired lifecycle management)
# ---------------------------------------------------------------------------

@router.post("/rebuild/{skill_name}")
async def rebuild_skill_endpoint(skill_name: str, request: Request):
    """Trigger LLM-powered rebuild of a skill.

    Body JSON (all optional):
        instruction (str): Specific improvement instruction for the LLM.
        provider (str): LLM provider override.
        model (str): LLM model override.
    """
    from app.skill_rebuilder import rebuild_skill

    data = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    instruction = data.get("instruction", "")
    provider = data.get("provider")
    model = data.get("model")

    result = await rebuild_skill(skill_name, instruction, provider, model)
    if not result.get("success"):
        raise HTTPException(400, result.get("error", "Rebuild failed"))
    return result


@router.get("/health")
async def skill_health():
    """Return a health report for all skills (usage stats, states)."""
    from app.skill_rebuilder import get_health_report
    return get_health_report()


@router.post("/pin/{skill_name}")
async def pin_skill_endpoint(skill_name: str):
    """Pin a skill to prevent auto-archiving."""
    from app.skill_rebuilder import pin_skill
    registry = get_registry()
    if not registry.get(skill_name):
        raise HTTPException(404, f"Skill '{skill_name}' not found")
    pin_skill(skill_name)
    return {"status": "pinned", "name": skill_name}


@router.post("/unpin/{skill_name}")
async def unpin_skill_endpoint(skill_name: str):
    """Unpin a skill, returning it to active state."""
    from app.skill_rebuilder import unpin_skill
    registry = get_registry()
    if not registry.get(skill_name):
        raise HTTPException(404, f"Skill '{skill_name}' not found")
    unpin_skill(skill_name)
    return {"status": "unpinned", "name": skill_name}


@router.post("/archive/{skill_name}")
async def archive_skill_endpoint(skill_name: str):
    """Manually archive a skill (moves to .archive/, unregisters)."""
    from app.skill_rebuilder import archive_skill
    ok, msg = archive_skill(skill_name)
    if not ok:
        raise HTTPException(400, msg)
    return {"status": "archived", "message": msg}


@router.post("/restore/{skill_name}")
async def restore_skill_endpoint(skill_name: str):
    """Restore a skill from the .archive/ directory."""
    from app.skill_rebuilder import restore_skill
    ok, msg = restore_skill(skill_name)
    if not ok:
        raise HTTPException(400, msg)
    return {"status": "restored", "message": msg}


@router.get("/usage/{skill_name}")
async def skill_usage(skill_name: str):
    """Return usage history and stats for a skill."""
    from app.skill_rebuilder import get_usage_stats, get_usage_history
    return {
        "skill": skill_name,
        "stats": get_usage_stats(skill_name),
        "history": get_usage_history(skill_name, limit=20),
    }

