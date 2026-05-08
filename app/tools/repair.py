"""
Clawzd — Tool Call Argument Repair & Coercion.

Multi-pass JSON repair for malformed LLM tool calls and type coercion
to match tool schemas.  Inspired by Hermes Agent's robust repair logic https://github.com/NousResearch/hermes-agent.
"""
import json
import logging
import re
from typing import Any, Optional

logger = logging.getLogger("clawzd.tool_repair")


# ---------------------------------------------------------------------------
# JSON repair
# ---------------------------------------------------------------------------

def _escape_invalid_chars_in_json_strings(raw: str) -> str:
    """Escape unescaped control chars inside JSON string values.

    Walks the raw JSON character-by-character, tracking whether we are
    inside a double-quoted string.  Inside strings, replaces literal
    control characters (0x00-0x1F) with their ``\\uXXXX`` equivalents.
    """
    out: list[str] = []
    in_string = False
    i = 0
    n = len(raw)
    while i < n:
        ch = raw[i]
        if in_string:
            if ch == "\\" and i + 1 < n:
                out.append(ch)
                out.append(raw[i + 1])
                i += 2
                continue
            if ch == '"':
                in_string = False
                out.append(ch)
            elif ord(ch) < 0x20:
                out.append(f"\\u{ord(ch):04x}")
            else:
                out.append(ch)
        else:
            if ch == '"':
                in_string = True
            out.append(ch)
        i += 1
    return "".join(out)


def repair_tool_call_arguments(raw_args: str, tool_name: str = "?") -> str:
    """Attempt to repair malformed tool_call argument JSON.

    Models (especially local ones via Ollama) can produce truncated JSON,
    trailing commas, Python ``None``, etc.  This function applies common
    repairs; if all fail it returns ``"{}"`` so the request can continue.

    Repair passes:
      0. ``json.loads(strict=False)`` for literal control chars
      1. Strip trailing commas before ``}`` or ``]``
      2. Close unclosed structures (``{``, ``[``)
      3. Remove excess closing braces/brackets
      4. Escape unescaped control chars inside JSON strings
      Fallback: Return ``"{}"`` with a warning log
    """
    raw_stripped = raw_args.strip() if isinstance(raw_args, str) else ""

    # Fast-path: empty / whitespace-only → empty object
    if not raw_stripped:
        logger.warning("Repaired empty tool_call arguments for %s", tool_name)
        return "{}"

    # Python-literal None → normalise to {}
    if raw_stripped == "None":
        logger.warning("Repaired Python-None tool_call arguments for %s", tool_name)
        return "{}"

    # Pass 0: json.loads with strict=False (handles literal tabs, newlines)
    try:
        parsed = json.loads(raw_stripped, strict=False)
        reserialised = json.dumps(parsed, separators=(",", ":"), ensure_ascii=False)
        if reserialised != raw_stripped:
            logger.info(
                "Repaired unescaped control chars in tool_call arguments for %s",
                tool_name,
            )
        return reserialised
    except (json.JSONDecodeError, TypeError, ValueError):
        pass

    # Attempt common JSON repairs
    fixed = raw_stripped

    # 1. Strip trailing commas before } or ]
    fixed = re.sub(r',\s*([}\]])', r'\1', fixed)

    # 2. Close unclosed structures
    open_curly = fixed.count('{') - fixed.count('}')
    open_bracket = fixed.count('[') - fixed.count(']')
    if open_curly > 0:
        fixed += '}' * open_curly
    if open_bracket > 0:
        fixed += ']' * open_bracket

    # 3. Remove excess closing braces/brackets (bounded to 50 iterations)
    for _ in range(50):
        try:
            json.loads(fixed)
            break
        except json.JSONDecodeError:
            if fixed.endswith('}') and fixed.count('}') > fixed.count('{'):
                fixed = fixed[:-1]
            elif fixed.endswith(']') and fixed.count(']') > fixed.count('['):
                fixed = fixed[:-1]
            else:
                break

    try:
        json.loads(fixed)
        logger.warning(
            "Repaired malformed tool_call arguments for %s: %s → %s",
            tool_name, raw_stripped[:80], fixed[:80],
        )
        return fixed
    except json.JSONDecodeError:
        pass

    # Pass 4: escape unescaped control chars then retry
    try:
        escaped = _escape_invalid_chars_in_json_strings(fixed)
        if escaped != fixed:
            json.loads(escaped)
            logger.warning(
                "Repaired control-char-laced tool_call arguments for %s",
                tool_name,
            )
            return escaped
    except (json.JSONDecodeError, TypeError, ValueError):
        pass

    # Last resort: replace with empty object
    logger.warning(
        "Unrepairable tool_call arguments for %s — "
        "replaced with empty object (was: %s)",
        tool_name, raw_stripped[:80],
    )
    return "{}"


# ---------------------------------------------------------------------------
# Type coercion
# ---------------------------------------------------------------------------

_KNOWN_PARAM_TYPES: dict[str, dict[str, str]] = {
    "execute_python": {"confirmed": "boolean"},
    "run_command": {"confirmed": "boolean"},
    "screenshot_remote": {"full_page": "boolean"},
    "generate_animation": {"duration": "number"},
    "read_file": {"start_line": "integer", "end_line": "integer"},
    "edit_file": {"replace_all": "boolean"},
    "search_web": {"max_results": "integer"},
    "rag_search": {"k": "integer"},
    "audit_code": {},
    "create_document": {},
    "memory": {},
}


def coerce_tool_args(tool_name: str, args: dict, schema: Optional[dict] = None) -> dict:
    """Coerce tool call arguments to match their JSON Schema types.

    LLMs frequently return numbers as strings (``"42"`` instead of ``42``)
    and booleans as strings (``"true"`` instead of ``true``).  This compares
    each argument value against the schema and attempts safe coercion.

    When no explicit schema is provided, uses a built-in registry of known
    parameter types per tool to perform heuristic coercion.

    Args:
        tool_name: Name of the tool (for logging).
        args: The parsed argument dictionary.
        schema: Optional JSON Schema ``parameters`` object for the tool.

    Returns:
        The args dict with coerced values (mutated in place).
    """
    if not args or not isinstance(args, dict):
        return args

    # Build properties from schema or built-in registry
    properties: dict[str, dict] = {}
    if schema:
        properties = schema.get("properties", {})
    else:
        # Use known param types for the tool
        known = _KNOWN_PARAM_TYPES.get(tool_name, {})
        properties = {k: {"type": v} for k, v in known.items()}

    if not properties:
        return args

    for key, value in args.items():
        if not isinstance(value, str):
            continue
        prop_schema = properties.get(key)
        if not prop_schema:
            continue
        expected = prop_schema.get("type")
        if not expected:
            continue
        coerced = _coerce_value(value, expected)
        if coerced is not value:
            args[key] = coerced

    return args


def _coerce_value(value: str, expected_type) -> Any:
    """Attempt to coerce a string *value* to *expected_type*.

    Returns the original string when coercion is not applicable or fails.
    """
    if isinstance(expected_type, list):
        for t in expected_type:
            result = _coerce_value(value, t)
            if result is not value:
                return result
        return value

    if expected_type in ("integer", "number"):
        return _coerce_number(value, integer_only=(expected_type == "integer"))
    if expected_type == "boolean":
        return _coerce_boolean(value)
    if expected_type == "array":
        return _coerce_json(value, list)
    if expected_type == "object":
        return _coerce_json(value, dict)
    if expected_type == "null" and value.strip().lower() == "null":
        return None
    return value


def _coerce_number(value: str, integer_only: bool = False) -> Any:
    """Try to parse *value* as a number."""
    try:
        f = float(value)
    except (ValueError, OverflowError):
        return value
    if f != f or f == float("inf") or f == float("-inf"):
        return value
    if f == int(f):
        return int(f)
    if integer_only:
        return value
    return f


def _coerce_boolean(value: str) -> Any:
    """Try to parse *value* as a boolean."""
    low = value.strip().lower()
    if low == "true":
        return True
    if low == "false":
        return False
    return value


def _coerce_json(value: str, expected_python_type: type) -> Any:
    """Parse *value* as JSON when the schema expects an array or object."""
    try:
        parsed = json.loads(value)
    except (ValueError, TypeError):
        return value
    if isinstance(parsed, expected_python_type):
        return parsed
    return value
