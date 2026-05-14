"""
Clawzd — IterResearch Context Condensation.

Inspired by Tongyi DeepResearch's "Heavy Mode" / IterResearch paradigm:
instead of letting the research context grow unboundedly (causing
"cognitive suffocation"), each round reconstructs a streamlined workspace
containing only the essential outputs from previous rounds.

Key mechanisms:
  1. Context size estimation (token budget)
  2. Relevance-ranked result pruning (keep top-k by relevance_score)
  3. LLM-guided findings compression into a "core findings" block
  4. Evolving central report draft update (WriteResearch step)

References:
  - Tongyi DeepResearch blog: https://tongyi-agent.github.io/blog/introducing-tongyi-deep-research/
  - ReSum paper: https://arxiv.org/abs/2509.13313 (context summarisation)
"""
import asyncio
import logging
from typing import Callable, Awaitable

logger = logging.getLogger("clawzd.research.condensation")

# Type alias for the LLM call function
LLMCallFn = Callable[[list[dict], str, str], Awaitable[str]]

# Heuristic: average chars per token for English text
_CHARS_PER_TOKEN = 4

# Thresholds (configurable)
CONDENSE_TRIGGER_RESULTS = 35   # Condense when accumulated results exceed this
CONDENSE_TRIGGER_ITER = 3       # Start condensing from iteration N
CONTEXT_BUDGET_TOKENS = 60_000  # Target context window ceiling
MAX_CORE_FINDINGS_CHARS = 6_000  # Compressed findings block size limit


# ── Token Budget Estimation ─────────────────────────────────────────────────

def estimate_tokens(text: str) -> int:
    """Rough token count estimate (chars / 4)."""
    return len(text) // _CHARS_PER_TOKEN


def estimate_context_size(
    results: list[dict],
    report_draft: str = "",
    branch_summaries: str = "",
) -> int:
    """Estimate total token consumption of the current research context."""
    results_text = " ".join(
        f"{r.get('title', '')} {r.get('snippet', '')}"
        for r in results
    )
    return estimate_tokens(results_text + report_draft + branch_summaries)


def should_condense(
    iteration_num: int,
    results: list[dict],
    report_draft: str = "",
    branch_summaries: str = "",
) -> bool:
    """
    Determine whether context condensation should be triggered.

    Triggers when EITHER:
      - We have accumulated too many results (breadth explosion)
      - The estimated token count exceeds the budget
      - We are past the warm-up phase (iter >= CONDENSE_TRIGGER_ITER)
    """
    if iteration_num < CONDENSE_TRIGGER_ITER:
        return False

    too_many_results = len(results) > CONDENSE_TRIGGER_RESULTS
    over_budget = estimate_context_size(
        results, report_draft, branch_summaries
    ) > CONTEXT_BUDGET_TOKENS

    return too_many_results or over_budget


# ── Relevance-Ranked Result Pruning ─────────────────────────────────────────

def prune_results(
    results: list[dict],
    max_keep: int = 25,
) -> list[dict]:
    """
    Keep only the top-k most relevant results using relevance_score.

    Falls back to recency order (last seen = highest index) when the score
    is unavailable, which matches the web-search assumption: more recent
    results were retrieved because they better match the evolving query.
    """
    if len(results) <= max_keep:
        return results

    # Sort by relevance_score descending, preserving insertion order as tie-break
    scored = [
        (i, r, float(r.get("relevance_score", 0.5)))
        for i, r in enumerate(results)
    ]
    scored.sort(key=lambda x: (x[2], x[0]), reverse=True)

    kept_indices = sorted(i for i, _, _ in scored[:max_keep])
    pruned = [results[i] for i in kept_indices]

    logger.info(
        "Context pruned: %d → %d results (relevance-ranked)",
        len(results), len(pruned),
    )
    return pruned


# ── LLM-Guided Findings Compression ─────────────────────────────────────────

async def compress_findings(
    results: list[dict],
    query: str,
    current_report_draft: str,
    iteration_num: int,
    llm_call: LLMCallFn,
    provider: str = "",
    model: str = "",
) -> str:
    """
    IterResearch WriteResearch step: compress accumulated findings into a
    dense, structured "core findings" block that replaces the raw result list
    as the research workspace for subsequent iterations.

    The compression preserves:
      - Key facts with source URLs
      - Identified gaps (for the next iteration to fill)
      - Emerging themes / hypotheses
      - Conflicting data points (important for reliability score)
    """
    # Build compact result summary for the LLM
    results_text = "\n".join(
        f"[{i+1}] ({r.get('source', 'web')}) {r.get('title', 'No title')}: "
        f"{r.get('snippet', '')[:200]}"
        f"{' [score=' + str(round(r.get('relevance_score', 0.5), 2)) + ']' if 'relevance_score' in r else ''}"
        for i, r in enumerate(results[-40:])
    )

    report_excerpt = current_report_draft[:2000] if current_report_draft else "No report draft yet."

    prompt = [
        {"role": "system", "content": (
            "You are a research synthesis expert. Your task is to compress a set of "
            "research findings into a dense, high-value core findings block.\n\n"
            "This block will serve as the reconstructed workspace for the next iteration — "
            "it REPLACES the raw result list to prevent context overflow.\n\n"
            "The output must be structured plain text (no JSON) containing:\n"
            "## KEY FACTS\n"
            "- Numbered list of the most important factual findings with source references\n"
            "## EMERGING THEMES\n"
            "- Key patterns and themes identified across sources\n"
            "## CONFLICTING DATA\n"
            "- Any contradictions or inconsistencies found (critical for reliability)\n"
            "## OPEN GAPS\n"
            "- What is still missing or uncertain — prioritise these for the next iteration\n"
            "## DRAFT PROGRESS\n"
            "- Brief note on what sections of the final report are now well-supported\n\n"
            f"Keep the total output under {MAX_CORE_FINDINGS_CHARS} characters.\n"
            "Be dense and specific. Preserve exact numbers, dates, and proper nouns."
        )},
        {"role": "user", "content": (
            f"Research query: {query}\n"
            f"Current iteration: {iteration_num}\n\n"
            f"Current report draft (excerpt):\n{report_excerpt}\n\n"
            f"Accumulated results ({len(results)} total, showing last 40):\n{results_text}\n\n"
            "Compress these findings into the core findings block."
        )},
    ]

    try:
        compressed = await llm_call(prompt, provider, model)
        if compressed and len(compressed) > 200:
            logger.info(
                "Findings compressed: %d results → %d chars core block",
                len(results), len(compressed),
            )
            return compressed[:MAX_CORE_FINDINGS_CHARS]
    except Exception as e:
        logger.warning("Findings compression failed: %s", e)

    # Fallback: simple concatenation of snippets
    return "\n".join(
        f"- {r.get('title', '')}: {r.get('snippet', '')[:150]}"
        for r in results[-20:]
    )


# ── Central Report Draft Update (IterResearch WriteResearch) ─────────────────

async def update_report_draft(
    query: str,
    core_findings: str,
    current_draft: str,
    iteration_num: int,
    eval_scores: dict,
    llm_call: LLMCallFn,
    provider: str = "",
    model: str = "",
) -> str:
    """
    Update the evolving central report draft with new findings.

    In IterResearch, the report draft grows incrementally — each iteration
    adds new sections or enriches existing ones, rather than regenerating
    everything from scratch at the end.
    """
    scores_text = " | ".join(
        f"{k}: {v:.0%}" for k, v in eval_scores.items()
    ) if eval_scores else "not yet evaluated"

    # Keep draft brief for context efficiency
    draft_excerpt = current_draft[-3000:] if len(current_draft) > 3000 else current_draft

    prompt = [
        {"role": "system", "content": (
            "You are a research report writer updating a living document.\n\n"
            "Based on new findings, update the evolving report draft:\n"
            "  • Add or enrich sections supported by new evidence\n"
            "  • Mark [NEEDS EVIDENCE] for claims that still lack support\n"
            "  • Integrate key facts naturally with [Source N] markers\n"
            "  • Do NOT rewrite sections that are already well-supported\n"
            "  • Keep the draft structured with ## headings\n"
            "  • Aim for 800-1500 words total\n\n"
            "Return the COMPLETE updated draft (not just the changes)."
        )},
        {"role": "user", "content": (
            f"Topic: {query}\n"
            f"Iteration: {iteration_num}\n"
            f"Quality scores: {scores_text}\n\n"
            f"New core findings:\n{core_findings}\n\n"
            f"Current draft (last section):\n{draft_excerpt}\n\n"
            "Update the report draft with the new findings."
        )},
    ]

    try:
        updated = await llm_call(prompt, provider, model)
        if updated and len(updated) > 300:
            logger.info(
                "Report draft updated: %d → %d chars (iter %d)",
                len(current_draft), len(updated), iteration_num,
            )
            return updated
    except Exception as e:
        logger.warning("Report draft update failed: %s", e)

    return current_draft  # Keep existing draft on failure


# ── Main Condensation Orchestrator ───────────────────────────────────────────

async def condense_research_context(
    results: list[dict],
    report_draft: str,
    query: str,
    iteration_num: int,
    eval_scores: dict,
    llm_call: LLMCallFn,
    provider: str = "",
    model: str = "",
    emit_fn=None,
) -> tuple[list[dict], str, str]:
    """
    IterResearch-style workspace reconstruction.

    Steps:
      1. Prune results (keep top-k by relevance_score)
      2. Compress findings into a dense core block (LLM WriteResearch step)
      3. Update the evolving report draft with new findings
      4. Return (pruned_results, core_findings_block, updated_draft)

    The core_findings_block is injected into the next iteration's context
    as a synthetic "previous findings" result, enabling the agent to maintain
    high reasoning quality without accumulating a bloated raw context.

    Args:
        results: All accumulated search results
        report_draft: Current evolving report draft (may be empty)
        query: Original research query
        iteration_num: Current iteration number
        eval_scores: Latest quality evaluation scores per axis
        llm_call: Async LLM call function
        provider / model: LLM routing params
        emit_fn: Optional SSE emit function for progress updates

    Returns:
        (pruned_results, core_findings_block, updated_report_draft)
    """
    if emit_fn:
        await emit_fn(
            f"🗜️ IterResearch condensation (iter {iteration_num}): "
            f"compressing {len(results)} results into core workspace..."
        )

    # Step 1: Prune results
    pruned = prune_results(results, max_keep=20)

    # Step 2: Compress findings
    try:
        core_findings = await compress_findings(
            results, query, report_draft, iteration_num,
            llm_call, provider, model,
        )
    except Exception as e:
        logger.warning("Compression task failed: %s", e)
        core_findings = "\n".join(
            f"- {r.get('title', '')}: {r.get('snippet', '')[:150]}"
            for r in pruned
        )

    # Step 3: Update draft sequentially using new core findings
    try:
        updated_draft = await update_report_draft(
            query, core_findings, report_draft, iteration_num, eval_scores,
            llm_call, provider, model,
        )
    except Exception as e:
        logger.warning("Draft update task failed: %s", e)
        updated_draft = report_draft

    # Inject core findings as a synthetic "memory" result at the front
    memory_result = {
        "title": f"[Core Findings — Iteration {iteration_num} Workspace]",
        "snippet": core_findings[:500],
        "url": "memory://core_findings",
        "source": "memory",
        "relevance_score": 1.0,  # Always keep the core findings block
        "_full_core_findings": core_findings,
    }

    condensed_results = [memory_result] + pruned

    if emit_fn:
        await emit_fn(
            f"✅ Context condensed: {len(results)} → {len(condensed_results)} "
            f"results, draft updated ({len(updated_draft)} chars)"
        )

    logger.info(
        "IterResearch condensation complete: %d→%d results, "
        "core block %d chars, draft %d chars",
        len(results), len(condensed_results),
        len(core_findings), len(updated_draft),
    )

    return condensed_results, core_findings, updated_draft
