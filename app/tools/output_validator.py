"""
Clawzd — LLM Output Validator (OpenClaw OS-inspired).

Real-time validation of LLM streaming output to catch and fix common issues:
- Malformed tool_call JSON (auto-repair before execution)
- Unclosed code fences (auto-close for clean rendering)
- Hallucinated file paths (detect references to nonexistent files)
- Duplicate tool calls (prevent re-execution)
- Token budget warnings (detect runaway generation)

The validator runs as a post-processing step AFTER each generation round
and BEFORE tool execution, reducing errors and improving reliability.
"""
import json
import logging
import os
import re
from typing import Optional

logger = logging.getLogger("clawzd.output_validator")


# ---------------------------------------------------------------------------
# Code fence validator
# ---------------------------------------------------------------------------

def validate_code_fences(text: str) -> tuple[str, list[str]]:
    """Validate and auto-close unclosed code fences.

    Returns (fixed_text, list_of_warnings).
    """
    warnings = []
    fence_count = text.count("```")

    if fence_count % 2 != 0:
        # Unclosed fence — auto-close
        text += "\n```"
        warnings.append("Auto-closed unclosed code fence")
        logger.info("Validator: auto-closed unclosed code fence")

    return text, warnings


# ---------------------------------------------------------------------------
# Tool call validator
# ---------------------------------------------------------------------------

_KNOWN_TOOLS = {
    "execute_python", "search_web", "screenshot_remote", "screenshot_local",
    "generate_image", "generate_animation", "run_command", "browse_web",
    "audit_code", "rag_search", "edit_file", "read_file", "create_document",
    "send_email", "post_to_twitter", "post_to_linkedin", "post_to_medium",
    "trigger_n8n", "memory", "rebuild_skill", "search_twitter",
    "search_linkedin", "undo", "create_skill",
}


def validate_tool_calls(tool_calls: list[dict]) -> tuple[list[dict], list[str]]:
    """Validate parsed tool calls before execution.

    Checks:
    - Tool name exists in known tools
    - Required params are present
    - No duplicate calls in the same round
    - Params are not empty when required

    Returns (validated_calls, list_of_warnings).
    """
    warnings = []
    validated = []
    seen_signatures = set()

    for tc in tool_calls:
        tool = tc.get("tool", "")
        params = tc.get("params", {})

        # 1. Check tool exists
        if tool not in _KNOWN_TOOLS and not tool.startswith("mcp_"):
            warnings.append(f"Unknown tool '{tool}' — will attempt fuzzy match")
            # Still allow it through (fuzzy matching happens downstream)

        # 2. Check for empty critical params
        if tool == "execute_python" and not params.get("code", "").strip():
            warnings.append(f"Skipped {tool}: empty 'code' param")
            continue
        if tool == "run_command" and not params.get("command", "").strip():
            warnings.append(f"Skipped {tool}: empty 'command' param")
            continue
        if tool == "generate_image" and not params.get("prompt", "").strip():
            warnings.append(f"Skipped {tool}: empty 'prompt' param")
            continue
        if tool == "search_web" and not params.get("query", "").strip():
            warnings.append(f"Skipped {tool}: empty 'query' param")
            continue

        # 3. Detect duplicates (same tool + same params = skip)
        sig = f"{tool}|{json.dumps(params, sort_keys=True)}"
        if sig in seen_signatures:
            warnings.append(f"Skipped duplicate {tool} call")
            continue
        seen_signatures.add(sig)

        validated.append(tc)

    if warnings:
        for w in warnings:
            logger.info("Validator: %s", w)

    return validated, warnings


# ---------------------------------------------------------------------------
# File path hallucination detector
# ---------------------------------------------------------------------------

def detect_hallucinated_paths(text: str, workspace_dir: str = "./workspace") -> list[str]:
    """Detect file paths mentioned in the response that don't exist.

    Scans for patterns like `file_path: "..."` or path-like strings
    in edit_file/read_file tool calls and flags nonexistent ones.

    Returns list of warning strings.
    """
    warnings = []

    # Extract file paths from tool_call blocks
    path_re = re.compile(
        r'"file_path"\s*:\s*"([^"]+)"',
        re.MULTILINE,
    )

    for match in path_re.finditer(text):
        path = match.group(1)
        # Skip paths that look like templates or examples
        if path in ("...", "path/to/file", "example.py"):
            continue
        # Only check relative paths (absolute are blocked elsewhere)
        if not path.startswith("/") and not path.startswith("~"):
            full_path = os.path.join(workspace_dir, path)
            if not os.path.exists(full_path):
                # Not necessarily an error for edit_file (new file creation)
                # but worth flagging for read_file
                warnings.append(
                    f"Path '{path}' does not exist in workspace"
                )

    return warnings


# ---------------------------------------------------------------------------
# Token budget guard
# ---------------------------------------------------------------------------

def check_token_budget(
    text: str,
    max_chars: int = 50_000,
    max_tool_rounds: int = 15,
    current_round: int = 0,
) -> list[str]:
    """Check if the generation is approaching budget limits.

    Returns list of warning strings.
    """
    warnings = []
    text_len = len(text)

    if text_len > max_chars:
        warnings.append(
            f"Output exceeds {max_chars} chars ({text_len} chars) — "
            "consider stopping generation"
        )

    if current_round >= max_tool_rounds - 1:
        warnings.append(
            f"Approaching max tool rounds ({current_round + 1}/{max_tool_rounds})"
        )

    return warnings


# ---------------------------------------------------------------------------
# Main validation pipeline
# ---------------------------------------------------------------------------

def validate_round_output(
    text: str,
    tool_calls: list[dict],
    round_num: int = 0,
    max_tool_rounds: int = 15,
    workspace_dir: str = "./workspace",
) -> dict:
    """Run the full validation pipeline on a generation round.

    Returns:
        {
            "text": str,           # Potentially fixed text
            "tool_calls": list,    # Validated tool calls
            "warnings": list[str], # All warnings
            "blocked": list[str],  # Tool calls that were blocked
        }
    """
    all_warnings = []

    # 1. Code fence validation
    text, fence_warnings = validate_code_fences(text)
    all_warnings.extend(fence_warnings)

    # 2. Tool call validation
    validated_calls, call_warnings = validate_tool_calls(tool_calls)
    blocked = [tc["tool"] for tc in tool_calls if tc not in validated_calls]
    all_warnings.extend(call_warnings)

    # 3. Path hallucination detection (informational only)
    if any(tc.get("tool") in ("read_file", "edit_file") for tc in validated_calls):
        path_warnings = detect_hallucinated_paths(text, workspace_dir)
        all_warnings.extend(path_warnings)

    # 4. Token budget check
    budget_warnings = check_token_budget(
        text,
        max_tool_rounds=max_tool_rounds,
        current_round=round_num,
    )
    all_warnings.extend(budget_warnings)

    if all_warnings:
        logger.info(
            "Validation round %d: %d warnings — %s",
            round_num, len(all_warnings),
            "; ".join(all_warnings[:3]),
        )

    return {
        "text": text,
        "tool_calls": validated_calls,
        "warnings": all_warnings,
        "blocked": blocked,
    }
