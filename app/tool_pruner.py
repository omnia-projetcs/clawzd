"""
Clawzd — Tool Output Pruning Engine.

Cheap pre-pass (no LLM call) that replaces old tool results with informative
1-line summaries.  Saves 50-80% of context space on long conversations.
Inspired by Hermes Agent's ContextCompressor tool output pruning https://github.com/NousResearch/hermes-agent.
"""
import hashlib
import json
import logging
import re
from typing import Any

logger = logging.getLogger("clawzd.tool_pruner")

PRUNED_TOOL_PLACEHOLDER = "[Old tool output cleared to save context space]"
_MIN_PRUNE_LENGTH = 100


def summarize_tool_result(tool_name: str, params: dict, result_text: str) -> str:
    """Create an informative 1-line summary of a tool call + result."""
    content = result_text or ""
    cl = len(content)
    lc = content.count("\n") + 1 if content.strip() else 0

    if tool_name == "search_web":
        q = params.get("query", "?")
        return f"[search_web] query='{q[:57]}' ({cl:,} chars)"
    if tool_name == "execute_python":
        code = params.get("code", "")[:60].replace("\n", " ")
        return f"[execute_python] ran '{code}' ({lc} lines output)"
    if tool_name == "run_command":
        cmd = params.get("command", "?")[:77]
        em = re.search(r'"returncode"\s*:\s*(-?\d+)', content)
        ec = em.group(1) if em else "?"
        return f"[run_command] `{cmd}` -> exit {ec}, {lc} lines"
    if tool_name == "screenshot_remote":
        return f"[screenshot_remote] {params.get('url', '?')} ({cl:,} chars)"
    if tool_name == "generate_image":
        return f"[generate_image] prompt='{params.get('prompt', '?')[:47]}' ({cl:,} chars)"
    if tool_name == "audit_code":
        return f"[audit_code] mode={params.get('mode', 'quick')} ({cl:,} chars)"
    if tool_name == "rag_search":
        return f"[rag_search] query='{params.get('query', '?')}' ({cl:,} chars)"
    if tool_name == "browse_web":
        return f"[browse_web] {params.get('url', '?')} ({cl:,} chars)"
    if tool_name == "edit_file":
        return f"[edit_file] {params.get('file_path', '?')} ({cl:,} chars)"
    if tool_name == "read_file":
        return f"[read_file] {params.get('file_path', '?')} ({cl:,} chars)"
    if tool_name == "memory":
        return f"[memory] {params.get('action', '?')} on {params.get('target', '?')}"
    # Generic
    fa = " ".join(f"{k}={str(v)[:30]}" for k, v in list(params.items())[:2])
    return f"[{tool_name}] {fa} ({cl:,} chars)"


def prune_old_tool_results(
    messages: list[dict], protect_last_n: int = 10,
) -> tuple[list[dict], int]:
    """Replace old tool result contents with informative 1-line summaries.

    Protects the most recent N messages. Only prunes tool results with
    content longer than _MIN_PRUNE_LENGTH.

    Returns (pruned_messages, pruned_count).
    """
    if not messages:
        return messages, 0

    result = [m.copy() for m in messages]
    pruned = 0
    boundary = max(0, len(result) - protect_last_n)

    # Pass 1: Deduplicate identical large content
    hashes: dict[str, int] = {}
    for i in range(len(result) - 1, -1, -1):
        c = result[i].get("content", "")
        if not isinstance(c, str) or len(c) < _MIN_PRUNE_LENGTH:
            continue
        h = hashlib.md5(c.encode("utf-8", errors="replace")).hexdigest()[:12]
        if h in hashes:
            result[i] = {**result[i], "content": "[Duplicate output — same as a more recent message]"}
            pruned += 1
        else:
            hashes[h] = i

    # Pass 2: Replace old large results with summaries
    _RESULT_PREFIXES = ("⚠️ Tool", "🔍 ", "✅ ", "❌ ", "📋 Result:", "📚 ", "📊 ")
    for i in range(boundary):
        c = result[i].get("content", "")
        if not isinstance(c, str) or len(c) <= _MIN_PRUNE_LENGTH:
            continue
        if c.startswith("[Duplicate") or c == PRUNED_TOOL_PLACEHOLDER:
            continue
        if any(c.startswith(p) for p in _RESULT_PREFIXES):
            tn, pr = _guess_tool_from_result(c)
            if tn:
                result[i] = {**result[i], "content": summarize_tool_result(tn, pr, c)}
                pruned += 1

    return result, pruned


def prune_tool_result_user_messages(
    messages: list[dict], protect_last_n: int = 6,
) -> tuple[list[dict], int]:
    """Prune user messages that contain re-injected tool results.

    When tools are executed in multi-round conversations, their results are
    re-injected as user messages with '[Tool result: ...]' content. These
    grow rapidly and bloat context. This pass replaces them with compact
    1-line summaries.
    """
    if not messages:
        return messages, 0

    result = [m.copy() for m in messages]
    pruned = 0
    boundary = max(0, len(result) - protect_last_n)

    for i in range(boundary):
        m = result[i]
        if m.get("role") != "user":
            continue
        content = m.get("content", "")
        if not isinstance(content, str):
            continue
        # Detect tool result re-injection
        if "[Tool result:" in content and len(content) > _MIN_PRUNE_LENGTH:
            # Extract tool name from the marker
            import re as _re
            tool_match = _re.search(r'\[Tool result:\s*(\w+)\]', content)
            tool_name = tool_match.group(1) if tool_match else "unknown"
            result[i] = {
                **m,
                "content": f"[Previous tool result from {tool_name} — pruned to save context]"
            }
            pruned += 1

    return result, pruned


def _guess_tool_from_result(content: str) -> tuple[str, dict]:
    """Heuristic extraction of tool name from formatted tool result text."""
    if "Search results" in content:
        return "search_web", {}
    if "Output:" in content or "Code executed" in content:
        return "execute_python", {}
    if "Knowledge base" in content:
        return "rag_search", {}
    if "Audit complete" in content:
        return "audit_code", {}
    m = re.match(r"⚠️ Tool '(\w+)'", content)
    if m:
        return m.group(1), {}
    return "", {}
