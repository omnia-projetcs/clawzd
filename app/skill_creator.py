import os
import re
import logging
from fastapi import HTTPException
from app.skill_model import generate_skill_template, SKILL_CATEGORIES
from app.skill_registry import get_registry, SKILLS_DIR

logger = logging.getLogger("clawzd.skills_creator")

async def create_skill_core(name: str, description: str, category: str = "other", code: str = "", parameters: list = None, triggers: list = None) -> dict:
    name = name.strip().replace(" ", "_").lower()
    description = description.strip()
    category = category.strip()

    if not name or not description:
        return {"error": "name and description are required"}

    if category not in SKILL_CATEGORIES:
        return {"error": f"Invalid category. Valid: {list(SKILL_CATEGORIES.keys())}"}

    registry = get_registry()
    if registry.get(name):
        return {"error": f"Skill '{name}' already exists"}

    # Build the Python source
    code = code.strip()
    if not code:
        param_names = parameters or ["input"]
        code = generate_skill_template(name, description, category, param_names)

    # Inject custom triggers if provided
    custom_triggers = triggers or []
    if custom_triggers and "triggers = [" in code:
        triggers_str = ",\n        ".join(f'r"{t}"' for t in custom_triggers)
        code = re.sub(
            r"triggers = \[.*?\]",
            f"triggers = [\n        {triggers_str},\n    ]",
            code,
            flags=re.DOTALL,
        )

    # Create subdirectory for skill
    skill_dir = os.path.join(SKILLS_DIR, name)
    os.makedirs(skill_dir, exist_ok=True)

    # Write skill file
    filename = f"{name}.py"
    filepath = os.path.join(skill_dir, filename)
    if os.path.exists(filepath):
        return {"error": f"File '{filename}' already exists in skills directory"}

    with open(filepath, "w") as f:
        f.write(code)

    # Load into registry
    skill = registry.register_file(filepath)
    if not skill:
        # Cleanup if loading failed
        try:
            os.unlink(filepath)
            os.rmdir(skill_dir)
        except OSError:
            import shutil
            shutil.rmtree(skill_dir, ignore_errors=True)
        return {"error": "Skill file was created but failed to load. Check the code syntax."}

    logger.info("Created skill '%s' [%s]", name, category)
    return {
        "status": "created",
        "skill": skill.to_dict(),
        "file": filepath,
    }
