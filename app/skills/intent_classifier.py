"""
Clawzd — Semantic intent classifier for tool routing.

Replaces brittle keyword lists with a fast LLM call that understands
the user's intent regardless of the language they write in.

The classifier outputs a compact JSON array of tool names that should be
injected into the system prompt for this turn.  It runs in parallel with
the main generation pipeline so it adds minimal latency (~100-200 ms on
a local 3-7B model).
"""
import json
import logging
import re

logger = logging.getLogger("clawzd.intent_classifier")

# ---------------------------------------------------------------------------
# Tool catalog shown to the classifier LLM
# ---------------------------------------------------------------------------
# Each entry: (tool_name, one-line description in English)
# Keep descriptions short — they must fit in a tiny context window.
_TOOL_CATALOG = [
    ("generate_image",    "User wants to generate, create, or draw an image, photo, illustration, logo, icon, avatar, banner, wallpaper, or any visual artwork."),
    ("generate_animation","User wants to generate a video, animation, GIF, or moving image."),
    ("search_web",        "User wants to search the internet or find recent/live information."),
    ("execute_python",    "User wants to run, execute, or test Python/code in a sandbox."),
    ("audit_code",        "User wants a security audit, code review, or vulnerability scan."),
    ("run_command",       "User wants to run a shell/terminal command on their machine."),
    ("screenshot_local",  "User wants to capture a screenshot of their local desktop/screen."),
    ("screenshot_remote", "User wants a screenshot of a remote webpage or URL."),
    ("browse_web",        "User wants to navigate, interact with, or automate a website."),
    ("create_document",   "User wants to create a Word document, PDF, spreadsheet, or markdown report."),
    ("rag_search",        "User wants to search their private knowledge base or uploaded documents."),
    ("memory",            "User wants to save, remember, or recall information about themselves."),
    ("edit_file",         "User wants to edit or modify a specific file in their project."),
    ("read_file",         "User wants to read or view the content of a specific file."),
    ("cron_schedule",     "User wants to schedule a recurring task or automation."),
    ("create_skill",      "User wants to create a new custom AI skill or tool."),
]

# Cache tool catalog string (built once)
_CATALOG_STR = "\n".join(f'- "{name}": {desc}' for name, desc in _TOOL_CATALOG)

_SYSTEM_PROMPT = f"""\
You are a request intent classifier. Your ONLY job is to output a JSON array \
of tool names that match what the user is asking for.

Available tools:
{_CATALOG_STR}

Rules:
1. Output ONLY a valid JSON array, example: ["generate_image"] or [] or ["search_web","execute_python"]
2. Only include tools the user EXPLICITLY needs. When in doubt, output [].
3. "generate_image" means the user wants a VISUAL IMAGE OUTPUT — not code, not HTML, not a diagram.
4. Writing code (HTML, CSS, JS, Python…) or designing a UI layout = [] (no special tool needed).
5. The user may write in any language — classify the INTENT, not the language.
6. Output [] for general questions, explanations, or conversational messages.
"""

# ---------------------------------------------------------------------------
# Fast LLM model for classification (non-reasoning, low token budget)
# ---------------------------------------------------------------------------
# Use the configured OLLAMA_MODEL as primary (it's always installed).
# Fallback to mistral-nemo which is a reliable fast instruction model.
# Both are resolved at call time so config changes take effect immediately.
_FALLBACK_MODEL = "mistral-nemo:12b-instruct-2407-q4_K_M"  # always available
_MAX_TOKENS     = 40   # JSON array fits in ~15 tokens
_TEMPERATURE    = 0.0  # deterministic


def _get_classifier_models() -> list[str]:
    """Return ordered list of models to try for classification.

    Primary = OLLAMA_MODEL from config (guaranteed installed).
    Fallback = mistral-nemo (fast instruction model, also installed).
    """
    try:
        from config import OLLAMA_MODEL
        primary = OLLAMA_MODEL
    except Exception:
        primary = _FALLBACK_MODEL
    models = [primary]
    if primary != _FALLBACK_MODEL:
        models.append(_FALLBACK_MODEL)
    return models


def _parse_tool_array(raw: str) -> list[str]:
    """Extract the JSON array from the LLM response, tolerating noise."""
    raw = raw.strip()
    # Remove <think>…</think> blocks if the model leaks reasoning
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    # Find the first JSON array
    match = re.search(r"\[.*?\]", raw, re.DOTALL)
    if not match:
        return []
    try:
        result = json.loads(match.group(0))
        if isinstance(result, list):
            # Filter to known tool names only
            known = {name for name, _ in _TOOL_CATALOG}
            return [t for t in result if isinstance(t, str) and t in known]
    except (json.JSONDecodeError, ValueError):
        pass
    return []


async def classify_intent(message: str) -> list[str]:
    """Classify user intent and return a list of relevant tool names.

    Uses a fast local LLM to understand the request in any language.
    Falls back to an empty list if the model is unavailable or returns garbage.

    Args:
        message: The raw user message (any language).

    Returns:
        List of tool name strings (subset of _TOOL_CATALOG keys).
        Empty list = no special tools needed (general chat/code answer).
    """
    if not message or not message.strip():
        return []

    # Truncate very long messages — classifier only needs the intent
    text = message.strip()
    if len(text) > 400:
        text = text[:400]

    from app.llm_provider import get_llm_provider

    llm = get_llm_provider("ollama")
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user",   "content": text},
    ]

    raw = ""
    for model in _get_classifier_models():
        try:
            raw = await llm.chat(
                messages,
                model=model,
                max_tokens=_MAX_TOKENS,
                temperature=_TEMPERATURE,
            )
            if raw and raw.strip():
                break
        except Exception as e:
            logger.debug("Classifier model %s failed: %s", model, e)
            continue

    tools = _parse_tool_array(raw)
    logger.info("Intent classifier [%s…] -> %s (raw: %r)", text[:60], tools, raw[:80])
    return tools
