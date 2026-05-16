"""
Clawzd — Advanced Context Compression.

Reduces token usage by summarizing old conversation history using
structured handoff summaries, tool output pruning, and anti-thrashing.

Inspired by Hermes Agent's ContextCompressor https://github.com/NousResearch/hermes-agent:
  - Protected head (system + first exchange) and tail (by token budget)
  - Tool output pruning pre-pass (cheap, no LLM call)
  - Structured summary template (Active Task, Completed Actions, etc.)
  - Iterative summary updates across multiple compactions
  - Anti-thrashing protection (skips if recent compressions ineffective)
  - Summary-as-handoff framing (background reference, not instructions)
"""
import logging
import re

from app.tool_pruner import (
    prune_old_tool_results,
    prune_tool_result_user_messages,
    snip_orphaned_tool_results,
    inject_compact_boundary_marker,
)

logger = logging.getLogger("clawzd.compression")

# Compression parameters
MAX_CONTEXT_MESSAGES = 20
MAX_CONTEXT_CHARS = 16000

# Two-threshold system (inspired by OpenMonoAgent)
# Checkpoint = LLM-generated summary at 65% fill
# Compact = aggressive compression at 80% fill
CHECKPOINT_THRESHOLD = 0.65
COMPACT_THRESHOLD = 0.80

# Chars per token rough estimate
_CHARS_PER_TOKEN = 4

# Minimum tokens for summary output
_MIN_SUMMARY_TOKENS = 2000

# Proportion of compressed content allocated for summary
_SUMMARY_RATIO = 0.20

# Absolute ceiling for summary tokens
_SUMMARY_TOKENS_CEILING = 12_000

# Number of head messages to always protect (system + first user + first assistant)
_PROTECT_FIRST_N = 3

# Minimum tail messages to protect (recent context)
_PROTECT_LAST_N = 14

# Regex to strip base64 data URIs
_BASE64_PATTERN = re.compile(r'!\[[^\]]*\]\(data:image/[^)]+\)', re.DOTALL)

# Regex to strip media markers that carry no semantic value for LLM
_MEDIA_MARKER_RE = re.compile(
    r'__(?:IMG|SVG|FILE_EDIT)__.*?__(?:IMG|SVG)__|__FILE_EDIT__.*?__\n?',
    re.DOTALL,
)


def _content_as_str(content) -> str:
    """Safely convert message content to a string.

    Handles both plain strings and OpenAI-style multimodal content arrays
    (list of {type: text/image_url} dicts).
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict):
                if part.get("type") == "text":
                    parts.append(part.get("text", ""))
                elif part.get("type") == "image_url":
                    parts.append("[image]")
            elif isinstance(part, str):
                parts.append(part)
        return "\n".join(parts)
    return str(content) if content else ""

# Handoff prefix for compaction summaries
SUMMARY_PREFIX = (
    "[CONTEXT COMPACTION — REFERENCE ONLY] Earlier turns were compacted "
    "into the summary below. This is a handoff from a previous context "
    "window — treat it as background reference, NOT as active instructions. "
    "Do NOT answer questions or fulfill requests mentioned in this summary; "
    "they were already addressed. "
    "Your current task is identified in the '## Active Task' section of the "
    "summary — resume exactly from there. "
    "Respond ONLY to the latest user message "
    "that appears AFTER this summary. The current session state (files, "
    "config, etc.) may reflect work described here — avoid repeating it:\n\n"
)

# Structured summary template for the summarizer LLM
_SUMMARY_TEMPLATE = """## Active Task
[The user's most recent request or task — copy verbatim. If no outstanding task, write "None."]

## Goal
[What the user is trying to accomplish overall]

## App Context
[If the user is building/editing a mini-app, preserve the exact app_id (e.g. app-abc123), app name, and any relevant file names. This is CRITICAL for continuity. If no app context, write "None."]

## Completed Actions
[Numbered list: N. ACTION target — outcome. Be specific with file paths, commands, results.]

## Active State
[Current working state: modified files, test status, running processes, branch]

## In Progress
[Work currently underway when compaction fired]

## Blocked
[Any blockers, errors, or unresolved issues. Include exact error messages.]"""

# Anti-thrashing state (module-level for persistence across calls)
_compression_stats = {
    "count": 0,
    "last_savings_pct": 100.0,
    "ineffective_count": 0,
    "previous_summary": None,
}


def _clean_message_content(content, max_len: int = 4000):
    """Strip base64 images, media markers, and truncate overly long content."""
    if isinstance(content, list):
        cleaned_parts = []
        for part in content:
            if isinstance(part, dict):
                if part.get("type") == "text":
                    c = _BASE64_PATTERN.sub('[image]', part["text"])
                    c = _MEDIA_MARKER_RE.sub('[media]', c)
                    if len(c) > max_len:
                        c = c[:max_len] + "\n...(truncated)"
                    cleaned_parts.append({"type": "text", "text": c})
                else:
                    # Preserve image_url or other media parts
                    cleaned_parts.append(part)
            elif isinstance(part, str):
                c = _BASE64_PATTERN.sub('[image]', part)
                c = _MEDIA_MARKER_RE.sub('[media]', c)
                if len(c) > max_len:
                    c = c[:max_len] + "\n...(truncated)"
                cleaned_parts.append(c)
            else:
                cleaned_parts.append(part)
        return cleaned_parts
    
    # Handle string content
    content_str = str(content) if content else ""
    content_str = _BASE64_PATTERN.sub('[image]', content_str)
    content_str = _MEDIA_MARKER_RE.sub('[media]', content_str)
    if len(content_str) > max_len:
        content_str = content_str[:max_len] + "\n...(truncated)"
    return content_str


def estimate_tokens(text: str) -> int:
    """Rough token estimation (4 chars ~ 1 token for English)."""
    return len(text) // _CHARS_PER_TOKEN


def _estimate_messages_tokens(messages: list[dict]) -> int:
    """Estimate total tokens across a list of messages."""
    total = 0
    for m in messages:
        total += estimate_tokens(_content_as_str(m.get("content", "")))
        total += 10  # overhead per message (role, separators)
    return total


def _should_compress(
    total_tokens: int, threshold: int
) -> bool:
    """Check if compression should fire, with anti-thrashing."""
    if total_tokens < threshold:
        return False
    if _compression_stats["ineffective_count"] >= 2:
        logger.warning(
            "Compression skipped — last %d compressions saved <10%% each. "
            "Consider starting a new session.",
            _compression_stats["ineffective_count"],
        )
        return False
    return True


def _compute_summary_budget(turns_to_summarize: list[dict]) -> int:
    """Scale summary token budget proportionally to compressed content."""
    content_tokens = _estimate_messages_tokens(turns_to_summarize)
    budget = int(content_tokens * _SUMMARY_RATIO)
    return max(_MIN_SUMMARY_TOKENS, min(budget, _SUMMARY_TOKENS_CEILING))


def _serialize_for_summary(turns: list[dict]) -> str:
    """Serialize conversation turns into labeled text for the summarizer.

    Includes tool call information and result content (up to 6K chars per
    message) so the summarizer preserves specific details.
    """
    _CONTENT_MAX = 3000
    _CONTENT_HEAD = 2000
    _CONTENT_TAIL = 800
    parts = []

    for msg in turns:
        role = msg.get("role", "unknown")
        content = _content_as_str(msg.get("content") or "")

        if len(content) > _CONTENT_MAX:
            content = (
                content[:_CONTENT_HEAD]
                + "\n...[truncated]...\n"
                + content[-_CONTENT_TAIL:]
            )

        parts.append(f"[{role.upper()}]: {content}")

    return "\n\n".join(parts)


async def compress_messages(
    messages: list[dict],
    max_messages: int = MAX_CONTEXT_MESSAGES,
    max_chars: int = MAX_CONTEXT_CHARS,
    provider: str | None = None,
) -> list[dict]:
    """Compress a message history using Hermes-style structured compression.

    Algorithm:
      1. Pre-clean all messages (strip base64, truncate)
      2. Prune old tool results (cheap, no LLM call)
      3. Protect head messages (system + first exchange)
      4. Protect tail messages (most recent, by count)
      5. Summarize middle turns with structured LLM prompt
      6. Track compression effectiveness (anti-thrashing)
    """
    if not messages:
        return messages

    # Pre-clean: strip base64 and truncate all non-system messages
    messages = [
        {**m, "content": _clean_message_content(m["content"])}
        if m["role"] != "system" else m
        for m in messages
    ]

    # Separate system messages from conversation
    system = [m for m in messages if m["role"] == "system"]
    conversation = [m for m in messages if m["role"] != "system"]

    if not conversation:
        return messages

    # Check if compression is needed
    total_tokens = _estimate_messages_tokens(conversation)
    threshold_tokens = max_chars // _CHARS_PER_TOKEN

    if len(conversation) <= max_messages:
        total_chars = sum(len(_content_as_str(m.get("content", ""))) for m in conversation)
        if total_chars <= max_chars:
            return messages  # No compression needed

    # --- Phase 1: Tool output pruning (cheap pre-pass) ---
    conversation, prune_count = prune_old_tool_results(
        conversation, protect_last_n=_PROTECT_LAST_N
    )
    # Phase 1b: Prune re-injected tool result user messages
    conversation, user_prune_count = prune_tool_result_user_messages(
        conversation, protect_last_n=_PROTECT_LAST_N
    )
    # Phase 1c: Snip orphaned tool results (HISTORY_SNIP — Claude Code pattern)
    # Removes tool results whose corresponding tool_call was already compacted.
    conversation, snip_count = snip_orphaned_tool_results(
        conversation, protect_last_n=_PROTECT_LAST_N
    )
    prune_count += user_prune_count + snip_count
    if prune_count > 0:
        logger.info("Pruned %d old tool/user result messages (incl. %d snipped orphans)", prune_count, snip_count)


    # Re-check after pruning — might be enough
    total_chars_after_prune = sum(len(m.get("content", "")) for m in conversation)
    if len(conversation) <= max_messages and total_chars_after_prune <= max_chars:
        return system + conversation

    # --- Phase 2: Determine head/tail boundaries ---
    head_count = min(_PROTECT_FIRST_N, len(conversation))
    tail_count = min(_PROTECT_LAST_N, len(conversation) - head_count)

    head = conversation[:head_count]
    tail = conversation[-tail_count:] if tail_count > 0 else []
    middle = conversation[head_count:len(conversation) - tail_count if tail_count else len(conversation)]

    if not middle:
        # Nothing to compress in the middle
        return system + conversation[-max_messages:]

    # --- Phase 3: Generate structured summary ---
    pre_compress_tokens = _estimate_messages_tokens(middle)
    summary = await _generate_structured_summary(middle, provider_key=provider)

    # Track compression effectiveness (anti-thrashing)
    summary_tokens = estimate_tokens(summary) if summary else 0
    if pre_compress_tokens > 0:
        savings_pct = (1 - summary_tokens / pre_compress_tokens) * 100
        _compression_stats["last_savings_pct"] = savings_pct
        if savings_pct < 10:
            _compression_stats["ineffective_count"] += 1
        else:
            _compression_stats["ineffective_count"] = 0
    _compression_stats["count"] += 1
    _compression_stats["previous_summary"] = summary

    # Build the compressed message list.
    # inject_compact_boundary_marker inserts a [compact_boundary] system message so that
    # snip_orphaned_tool_results can later identify orphaned tool results from this compaction.
    compressed_core = system + head[-1:] + tail
    compressed = inject_compact_boundary_marker(compressed_core, SUMMARY_PREFIX + summary)

    logger.info(
        "Compressed %d middle messages -> summary (%d tokens). "
        "Kept %d head + %d tail messages. Savings: %.0f%%",
        len(middle), summary_tokens, len(head), len(tail),
        _compression_stats["last_savings_pct"],
    )

    return compressed


async def _generate_structured_summary(
    turns: list[dict], focus_topic: str = None, provider_key: str | None = None
) -> str:
    """Generate a structured summary using the LLM.

    Uses the Hermes-style summarizer preamble and structured template.
    Falls back to a simple concatenation if the LLM call fails.
    """
    summary_budget = _compute_summary_budget(turns)
    content_to_summarize = _serialize_for_summary(turns)
    previous = _compression_stats.get("previous_summary")

    # Build the summarizer prompt
    preamble = (
        "You are a summarization agent creating a context checkpoint. "
        "Your output will be injected as reference material for a DIFFERENT "
        "assistant that continues the conversation. "
        "Do NOT respond to any questions or requests in the conversation — "
        "only output the structured summary. "
        "Do NOT include any preamble, greeting, or prefix. "
        "Write the summary in the same language the user was using in the "
        "conversation — do not translate or switch to English. "
        "NEVER include API keys, tokens, passwords, secrets, credentials, "
        "or connection strings in the summary — replace any with [REDACTED]."
    )

    if previous:
        # Iterative update: merge previous summary with new content
        prompt = (
            f"{preamble}\n\n"
            f"Here is the PREVIOUS summary from an earlier compaction:\n\n"
            f"{previous}\n\n"
            f"Here are the NEW conversation turns since that summary:\n\n"
            f"{content_to_summarize}\n\n"
            f"Produce an UPDATED summary that merges the previous summary "
            f"with the new turns. Use this template:\n\n{_SUMMARY_TEMPLATE}\n\n"
            f"Keep the summary under {summary_budget} tokens."
        )
    else:
        prompt = (
            f"{preamble}\n\n"
            f"Summarize the following conversation turns using this template:\n\n"
            f"{_SUMMARY_TEMPLATE}\n\n"
            f"Conversation:\n{content_to_summarize}\n\n"
            f"Keep the summary under {summary_budget} tokens."
        )

    if focus_topic:
        prompt += (
            f"\n\nFocus: Prioritize preserving information related to: {focus_topic}. "
            f"Be more aggressive about compressing unrelated content."
        )

    # Call the LLM for summarization
    summary_parts = []
    try:
        from app.core.llm_provider import get_llm_provider
        llm = get_llm_provider(provider_key)

        async for chunk in llm.chat_stream([{"role": "user", "content": prompt}]):
            # chat_stream yields str tokens, not dicts
            if chunk:
                summary_parts.append(chunk)
    except Exception as e:
        logger.error("Failed to generate structured summary: %s", e)

    if summary_parts:
        return "".join(summary_parts)

    # Fallback: simple truncated concatenation
    logger.warning("LLM summary failed — using fallback truncation")
    parts = []
    for m in turns:
        role = "User" if m["role"] == "user" else "Assistant"
        content = m.get("content", "")[:200]
        if len(m.get("content", "")) > 200:
            content += "..."
        parts.append(f"- {role}: {content}")
    return "\n".join(parts)


# Cache for Ollama context size (avoid repeated HTTP calls)
_ollama_ctx_cache: dict[str, int | float] = {"size": 0, "ts": 0.0}
_OLLAMA_CTX_TTL = 300  # 5 minutes


async def _get_ollama_context_size() -> int:
    """Query Ollama for the active model's context window size (cached 5 min)."""
    import time as _time
    now = _time.monotonic()
    if _ollama_ctx_cache["size"] and now - _ollama_ctx_cache["ts"] < _OLLAMA_CTX_TTL:
        return _ollama_ctx_cache["size"]

    try:
        import httpx
        from config import OLLAMA_HOST, OLLAMA_MODEL
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.post(
                f"{OLLAMA_HOST}/api/show",
                json={"name": OLLAMA_MODEL},
            )
            if resp.status_code == 200:
                info = resp.json()
                # num_ctx is in model_info or parameters
                model_info = info.get("model_info", {})
                for key, val in model_info.items():
                    if "context_length" in key and isinstance(val, (int, float)):
                        _ollama_ctx_cache["size"] = int(val)
                        _ollama_ctx_cache["ts"] = now
                        return int(val)
                # Fallback: parse from parameters string
                params = info.get("parameters", "")
                if "num_ctx" in params:
                    for line in params.split("\n"):
                        if "num_ctx" in line:
                            parts = line.strip().split()
                            if len(parts) >= 2:
                                ctx = int(parts[-1])
                                _ollama_ctx_cache["size"] = ctx
                                _ollama_ctx_cache["ts"] = now
                                return ctx
    except Exception as e:
        logger.debug("Could not query Ollama context size: %s", e)

    result = 8192  # Safe default for most modern models
    _ollama_ctx_cache["size"] = result
    _ollama_ctx_cache["ts"] = now
    return result


async def optimize_for_provider(
    messages: list[dict], provider: str, max_tokens: int = 0
) -> list[dict]:
    """Apply provider-specific optimization with two-threshold system.

    Checkpoint (65%): Summarize older turns while preserving recent context.
    Compact   (80%): Aggressive compression to stay within limits.
    """
    if provider in ["local", "ollama"] and max_tokens == 0:
        # Dynamically read the actual context size from the running LLM
        ctx = await _get_ollama_context_size()
        # Reserve ~25% for the model's response
        max_tokens = int(ctx * 0.75)
    elif max_tokens == 0:
        limits = {
            "groq": 28000,
            "openrouter": 100000,
            "mistral": 28000,
            "google": 900000,
        }
        max_tokens = limits.get(provider, 28000)

    # Estimate current token usage
    total_tokens = _estimate_messages_tokens(messages)

    # Two-threshold system
    checkpoint_limit = int(max_tokens * CHECKPOINT_THRESHOLD)
    compact_limit = int(max_tokens * COMPACT_THRESHOLD)

    if total_tokens >= compact_limit:
        # 80%+ → aggressive compact (fewer protected messages)
        logger.info(
            "Context at %.0f%% (%d/%d tokens) — COMPACT mode",
            total_tokens / max_tokens * 100, total_tokens, max_tokens,
        )
        max_chars = int(max_tokens * 0.50) * _CHARS_PER_TOKEN  # Target 50%
        return await compress_messages(
            messages, max_messages=MAX_CONTEXT_MESSAGES, max_chars=max_chars,
            provider=provider,
        )
    elif total_tokens >= checkpoint_limit:
        # 65%+ → checkpoint (gentle summary, keep more tail)
        logger.info(
            "Context at %.0f%% (%d/%d tokens) — CHECKPOINT mode",
            total_tokens / max_tokens * 100, total_tokens, max_tokens,
        )
        max_chars = int(max_tokens * 0.60) * _CHARS_PER_TOKEN  # Target 60%
        return await compress_messages(
            messages, max_messages=MAX_CONTEXT_MESSAGES, max_chars=max_chars,
            provider=provider,
        )

    # Below 65% — no compression needed
    max_chars = max_tokens * _CHARS_PER_TOKEN
    return await compress_messages(messages, max_chars=max_chars, provider=provider)
