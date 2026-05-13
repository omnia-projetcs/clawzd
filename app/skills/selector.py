"""
Clawzd — MCP skill auto-selector.
Analyzes user messages to automatically select relevant skills/tools.
Combines static built-in patterns with dynamic custom skill triggers.
"""
import re
import logging

logger = logging.getLogger("clawzd.selector")

# ---------------------------------------------------------------------------
# Static patterns for built-in tools (always available)
# ---------------------------------------------------------------------------
BUILTIN_PATTERNS = {
    "execute_python": [
        r"(?:run|execute|launch)\s+(?:this|the)?\s*(?:code|script|python)",
        r"```python", r"```py",
        r"(?:write|create|build)\s+.*(?:script|program|code)",
    ],
    "search_web": [
        r"(?:search|find|look up|google)\s+",
        r"(?:what is|who is|how to|where)\s+",
        r"(?:latest|news|current|recent)\s+",
    ],
    "audit_code": [
        r"(?:audit|review|check|analyse|analyze)\s+.*(?:code|security|quality)",
        r"(?:vulnerability|bug|issue|flaw)\s+",
        r"(?:owasp|trivy|semgrep|bandit|pylint)\s*",
        r"(?:full|complete|deep|complet)\s+(?:audit|scan|analysis)",
        r"(?:security)\s+(?:scan|audit|check)",
        r"(?:dependency)\s+(?:check|scan|audit)",
        r"(?:scan|scanner)\s+.*(?:code|project|repo)",
        r"(?:detect|find)\s+.*(?:secret|vulnerability|flaw)",
    ],
    "run_command": [
        r"(?:run|execute|launch)\s+(?:command|cmd|terminal|shell)",
        r"(?:ls|cat|grep|find|git|docker|pip)\s+",
    ],
    "rag_search": [
        r"(?:search|find|look)\s+.*(?:knowledge|document|base|rag)",
        r"(?:in my)\s+(?:documents|files)",
    ],
    "screenshot_local": [
        r"(?:screenshot|capture|screen)\s+(?:local|desktop)",
        r"(?:take)\s+(?:a\s+)?(?:screenshot|capture)(?!.*\b\w+\.(?:com|org|net|io|dev|fr|de|uk|co|app|ai)\b)(?!.*https?://)",
    ],
    "screenshot_remote": [
        r"(?:screenshot|capture)\s+.*(?:url|website|page|site)",
        r"(?:show|display|preview|visuali[sz]e)\s+.*(?:page|site|website|url)",
        r"https?://\S+",
        r"\b\w+\.\w{2,}\b.*(?:look|show|page|site)",
        r"(?:take|capture|screenshot).*(?:https?://\S+|\b\w+\.(?:com|org|net|io|dev|fr|de|uk|co|app|ai)\b)",
        r"(?:navigate|open|go to|browse|surf|visit|montre|voir|regarde|ressemble)\s+.*(?:url|website|page|site|http)",
        r"(?:montre|voir|regarde).*(?:page|site)\b",
        r"\b\w+\.(?:com|org|net|io|dev|fr|de|uk|co|app|ai)\b",
    ],
    "generate_image": [
        r"(?:generate|create|make|draw)\s+.*(?:image|picture|illustration|photo)(?!.*(?:mermaid|diagram|schéma|schema|flowchart))",
        r"(?:image of|picture of|illustration of)",
        r"(?:generate|create|make)\s+.*(?:svg|icon|logo|badge|vector)(?!.*(?:mermaid|diagram|schéma|schema))",
        r"(?:svg|icon|logo|badge|vector)\s+",
        r"(?:simple|flat|minimalist|geometric)\s+.*(?:image|drawing|illustration)",
    ],
    "cron_schedule": [
        r"(?:schedule|cron|every)\s+",
        r"(?:daily|hourly|weekly|monthly)",
    ],
    "create_skill": [
        r"(?:create|make|build|define)\s+.*(?:skill|tool|plugin)",
        r"(?:new skill|nouveau skill|new tool)",
    ],
    "rebuild_skill": [
        r"(?:rebuild|improve|optimize|fix|repair|upgrade)\s+.*(?:skill|tool|plugin)",
        r"(?:skill)\s+(?:rebuild|improvement|optimization|repair)",
    ],
    "memory": [
        r"(?:remember|memorize|save|note|keep in mind)\s+",
        r"(?:my profile|my name|about me|my preference)",
        r"(?:update|add to|save to)\s+(?:memory|profile)",
        r"(?:oublie pas|retiens|m[ée]morise|enregistre|note [çc]a|garde en m[ée]moire)",
        r"(?:mon profil|mon nom|mes pr[ée]f[ée]rences)",
    ],
    "edit_file": [
        r"(?:edit|modify|update|change|rewrite)\s+.*(?:file|code|script|document)",
    ],
    "read_file": [
        r"(?:read|show|open|view|display)\s+.*(?:file|code|script|document)",
    ],
}


def _get_dynamic_patterns() -> dict[str, list[str]]:
    """Fetch trigger patterns from all dynamically loaded custom skills.

    Returns an empty dict if the registry is not yet initialised to avoid
    circular import issues during startup.
    """
    try:
        from app.skills.registry import get_registry
        registry = get_registry()
        return registry.get_trigger_map()
    except Exception:
        return {}


def _build_pattern_map() -> dict[str, list[str]]:
    """Merge built-in and dynamic patterns into a single map."""
    merged = dict(BUILTIN_PATTERNS)
    dynamic = _get_dynamic_patterns()
    for name, triggers in dynamic.items():
        if name in merged:
            # Extend existing built-in patterns with dynamic ones
            merged[name] = merged[name] + triggers
        else:
            merged[name] = triggers
    return merged


def select_skills(message: str, top_k: int = 5, min_confidence: float = 0.0) -> list[dict]:
    """Analyze a user message and return the most relevant skills.

    Only skills whose confidence score is >= ``min_confidence`` are returned.
    This prevents polluting the LLM prompt with irrelevant skills when
    hundreds of custom skills are registered.

    Returns a list of ``{skill, confidence, source}`` dicts ordered by
    confidence descending.  ``source`` is ``"builtin"`` or ``"dynamic"``.
    """
    msg = message.lower()
    scores: dict[str, float] = {}
    sources: dict[str, str] = {}

    pattern_map = _build_pattern_map()
    dynamic_names = set(_get_dynamic_patterns().keys())

    for skill, patterns in pattern_map.items():
        score = 0
        for pattern in patterns:
            try:
                matches = re.findall(pattern, msg, re.IGNORECASE)
                score += len(matches) * 2
            except re.error:
                continue
        if score > 0:
            scores[skill] = min(score / 6.0, 1.0)  # Normalize to 0-1
            sources[skill] = "dynamic" if skill in dynamic_names else "builtin"

    # Filter by minimum confidence, then sort descending and limit to top_k
    ranked = sorted(
        ((s, c) for s, c in scores.items() if c >= min_confidence),
        key=lambda x: x[1],
        reverse=True,
    )[:top_k]
    return [
        {"skill": s, "confidence": round(c, 2), "source": sources.get(s, "builtin")}
        for s, c in ranked
    ]


def get_skill_description(skill_name: str) -> str:
    """Return a human-readable description for a skill.

    Checks dynamic skills first, then falls back to built-in descriptions.
    """
    # Try dynamic skills first
    try:
        from app.skills.registry import get_registry
        registry = get_registry()
        skill = registry.get(skill_name)
        if skill:
            return skill.description
    except Exception:
        pass

    # Fall back to static descriptions
    descriptions = {
        "execute_python": "Execute Python code in sandbox",
        "search_web": "Search the internet",
        "audit_code": "Audit code quality & security (Semgrep, Trivy, detect-secrets, pylint, bandit)",
        "run_command": "Run a local shell command",
        "rag_search": "Search knowledge base",
        "screenshot_local": "Capture local desktop screenshot",
        "screenshot_remote": "Capture and view a remote webpage (screenshot + text extract)",
        "generate_image": "Generate an image from text",
        "cron_schedule": "Schedule a recurring task",
        "create_skill": "Create a new custom skill",
        "rebuild_skill": "Rebuild and improve an existing skill using AI",
    }
    return descriptions.get(skill_name, skill_name)


def get_skill_catalog_entry(skill_name: str) -> str:
    """Return a compact one-liner for the lightweight skill catalog.

    Used by the lazy skill loading system: only names + short descriptions
    are injected into the initial prompt to reduce context size.
    """
    desc = get_skill_description(skill_name)
    return f"- {skill_name}: {desc[:60]}"


# ---------------------------------------------------------------------------
# Full tool instructions (loaded on demand for cloud providers)
# ---------------------------------------------------------------------------

_TOOL_FULL_INSTRUCTIONS: dict[str, str] = {
    "screenshot_remote": (
        "screenshot_remote — take a visual screenshot of any website/URL and extract its text content. "
        "ALWAYS use this when the user asks to SEE, VIEW, SHOW, VISIT, or LOOK AT a website/page. "
        "Do NOT use search_web for this — screenshot_remote gives a real visual capture.\n"
        '```tool_call\n{"tool":"screenshot_remote","params":{"url":"https://example.com"}}\n```'
    ),
    "screenshot_local": (
        "screenshot_local — capture local desktop.\n"
        '```tool_call\n{"tool":"screenshot_local","params":{}}\n```'
    ),
    "generate_image": (
        "generate_image — generate image from text (format: auto/svg/png/transparent_png, "
        "style: none/photorealistic/anime/cinematic/digital_art/3d_render/pixel_art/neon_punk/logo).\n"
        '```tool_call\n{"tool":"generate_image","params":{"prompt":"desc","format":"auto","style":"none"}}\n```'
    ),
    "generate_animation": (
        "generate_animation — generate GIF/MP4 animation.\n"
        '```tool_call\n{"tool":"generate_animation","params":{"prompt":"desc","format":"gif"}}\n```'
    ),
    "execute_python": (
        'execute_python — run Python code (risky SQL needs "confirmed":true).\n'
        '```tool_call\n{"tool":"execute_python","params":{"code":"print(42)"}}\n```'
    ),
    "search_web": (
        "search_web — search the internet.\n"
        '```tool_call\n{"tool":"search_web","params":{"query":"..."}}\n```'
    ),
    "audit_code": (
        "audit_code — audit code quality/security (mode: quick/full).\n"
        '```tool_call\n{"tool":"audit_code","params":{"mode":"quick","code":"..."}}\n```'
    ),
    "run_command": (
        'run_command — shell command in workspace (risky cmds need "confirmed":true).\n'
        '```tool_call\n{"tool":"run_command","params":{"command":"ls -la"}}\n```'
    ),
    "edit_file": (
        "edit_file — modify file content.\n"
        '```tool_call\n{"tool":"edit_file","params":{"file_path":"...","old_string":"...","new_string":"..."}}\n```'
    ),
    "read_file": (
        "read_file — read file content.\n"
        '```tool_call\n{"tool":"read_file","params":{"file_path":"..."}}\n```'
    ),
    "memory": (
        "memory — save/update persistent memory (action: add/replace/remove, target: memory/user).\n"
        '```tool_call\n{"tool":"memory","params":{"action":"add","content":"..."}}\n```'
    ),
    "create_document": (
        "create_document — create document (markdown/word/excel/pdf).\n"
        '```tool_call\n{"tool":"create_document","params":{"format_type":"markdown","content":"...","title":"..."}}\n```'
    ),
    "search_twitter": (
        "search_twitter — search tweets/X posts or get user timeline.\n"
        '```tool_call\n{"tool":"search_twitter","params":{"query":"...","username":""}}\n```'
    ),
    "search_linkedin": (
        "search_linkedin — search LinkedIn profiles (CV) or articles.\n"
        '```tool_call\n{"tool":"search_linkedin","params":{"query":"...","type":"profiles"}}\n```'
    ),
}


def get_skill_full_instructions(skill_name: str) -> str:
    """Return the full tool_call instructions for a skill.

    Used for on-demand loading (cloud providers) and direct injection
    (local providers).  Falls back to a simple one-liner if no detailed
    instructions are registered.
    """
    if skill_name in _TOOL_FULL_INSTRUCTIONS:
        return _TOOL_FULL_INSTRUCTIONS[skill_name]
    desc = get_skill_description(skill_name)
    return f"{skill_name} -- {desc[:80]}"
