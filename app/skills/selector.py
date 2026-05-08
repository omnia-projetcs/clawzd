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
        r"(?:take)\s+.*(?:screenshot|capture)",
    ],
    "screenshot_remote": [
        r"(?:screenshot|capture)\s+.*(?:url|website|page|site)",
        r"(?:show|display|preview|visuali[sz]e)\s+.*(?:page|site|website|url)",
        r"https?://\S+",
        r"\b\w+\.\w{2,}\b.*(?:look|show|page|site)",
    ],
    "generate_image": [
        r"(?:generate|create|make|draw)\s+.*(?:image|picture|illustration|photo)",
        r"(?:image of|picture of|illustration of)",
        r"(?:generate|create|make)\s+.*(?:svg|icon|logo|badge|vector)",
        r"(?:svg|icon|logo|badge|vector)\s+",
        r"(?:simple|flat|minimalist|geometric)\s+.*(?:image|drawing|illustration)",
    ],
    "browse_web": [
        r"(?:navigate|open|go to|browse)\s+.*(?:url|website|page|site|http)",
        r"(?:click|fill|type|extract)\s+.*(?:on|in|from)\s+(?:the|a)\s+(?:page|site)",
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
        r"(?:modifie|[ée]dite|change|mets [àa] jour)\s+.*(?:fichier|code)",
    ],
    "read_file": [
        r"(?:read|show|open|view|display)\s+.*(?:file|code|script|document)",
        r"(?:lis|montre|ouvre|affiche|voir)\s+.*(?:fichier|code)",
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
        "screenshot_remote": "Capture remote webpage screenshot",
        "generate_image": "Generate an image from text",
        "browse_web": "Control a web browser",
        "cron_schedule": "Schedule a recurring task",
        "create_skill": "Create a new custom skill",
        "rebuild_skill": "Rebuild and improve an existing skill using AI",
    }
    return descriptions.get(skill_name, skill_name)
