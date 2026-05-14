"""
Clawzd — Deep Research Engine.
Core functions for advanced research: perspective-guided question decomposition
(STORM), recursive deep research branches (GPT-Researcher), structured
multi-criteria evaluation, inter-iteration reflection, citation-tracked
report generation, self-referential process improvement (HyperAgents),
and score-proportional topic selection for open-ended exploration.
"""
import json
import math
import random
import asyncio
import logging
from typing import Callable, Awaitable

try:
    import json_repair as _json_repair
    _HAS_JSON_REPAIR = True
except ImportError:
    _HAS_JSON_REPAIR = False

logger = logging.getLogger("clawzd.research.engine")

# Type alias for the LLM call function passed in from tools_research
LLMCallFn = Callable[[list[dict], str, str], Awaitable[str]]


def _parse_json_block(text: str, fallback=None):
    """Safely extract a JSON object or array from LLM output.

    Uses json_repair (GPT-Researcher's approach) when available for ~20%
    better success rate on LLM outputs with minor JSON formatting errors.
    Falls back to manual bracket extraction for robustness.
    """
    if not text or not text.strip():
        return fallback

    # Strip markdown fences if present
    clean = text.strip()
    if clean.startswith("```"):
        lines = clean.split("\n")
        # Remove first and last fence lines
        inner = [l for l in lines[1:] if not l.strip().startswith("```")]
        clean = "\n".join(inner).strip()

    # Try json_repair first (handles trailing commas, missing quotes, etc.)
    if _HAS_JSON_REPAIR:
        try:
            result = _json_repair.loads(clean)
            if result is not None and result != "":
                return result
        except Exception:
            pass

    # Manual bracket extraction fallback
    start_arr = clean.find("[")
    end_arr = clean.rfind("]")
    start_obj = clean.find("{")
    end_obj = clean.rfind("}")
    candidates = []
    if start_arr != -1 and end_arr > start_arr:
        candidates.append((start_arr, end_arr + 1))
    if start_obj != -1 and end_obj > start_obj:
        candidates.append((start_obj, end_obj + 1))
    for s, e in sorted(candidates, key=lambda x: x[0]):
        try:
            return json.loads(clean[s:e])
        except Exception:
            continue
    return fallback


# ── 1. Perspective-Guided Question Decomposition (STORM-style) ──

async def generate_perspectives(
    query: str, llm_call: LLMCallFn,
    provider: str = "", model: str = "",
    num_perspectives: int = 5,
) -> list[dict]:
    """Generate multiple perspectives on a research topic (STORM-style)."""
    prompt = [
        {"role": "system", "content": (
            "You are a research strategist. Given a topic, identify distinct "
            "perspectives (angles/viewpoints) to explore it comprehensively.\n\n"
            "For each perspective, provide 2-3 specific sub-questions.\n\n"
            "Return a JSON array:\n"
            '[{"perspective": "Technical Analysis", '
            '"description": "Examine the technical mechanisms...", '
            '"sub_questions": ["How does X work?", "What are limitations?"]}]\n\n'
            f"Generate exactly {num_perspectives} perspectives.\n"
            "Return ONLY valid JSON, no markdown fences."
        )},
        {"role": "user", "content": f"Research topic: {query}"},
    ]
    text = await llm_call(prompt, provider, model)
    result = _parse_json_block(text, fallback=[])
    if not isinstance(result, list):
        result = []
    # Validate structure
    validated = []
    for p in result[:num_perspectives]:
        if isinstance(p, dict) and "perspective" in p:
            validated.append({
                "perspective": p.get("perspective", ""),
                "description": p.get("description", ""),
                "sub_questions": p.get("sub_questions", []),
                "covered": False,
            })
    return validated


async def generate_sub_questions(
    query: str, perspectives: list[dict],
    llm_call: LLMCallFn,
    provider: str = "", model: str = "",
) -> list[str]:
    """Flatten perspective sub-questions and add cross-cutting questions."""
    # Collect perspective sub-questions
    all_questions = []
    for p in perspectives:
        for sq in p.get("sub_questions", []):
            all_questions.append(sq)

    # Generate cross-cutting questions
    perspectives_text = "\n".join(
        f"- {p['perspective']}: {p['description']}"
        for p in perspectives
    )
    prompt = [
        {"role": "system", "content": (
            "Given a topic and its research perspectives, generate 3-5 "
            "cross-cutting questions that connect multiple perspectives.\n"
            "Return a JSON array of question strings.\n"
            "Return ONLY valid JSON, no markdown."
        )},
        {"role": "user", "content": (
            f"Topic: {query}\n\nPerspectives:\n{perspectives_text}\n\n"
            "Generate cross-cutting questions."
        )},
    ]
    text = await llm_call(prompt, provider, model)
    cross = _parse_json_block(text, fallback=[])
    if isinstance(cross, list):
        all_questions.extend(q for q in cross if isinstance(q, str))

    return all_questions


# ── 2. Deep Research Recursive Branches (GPT-Researcher-style) ──

async def deep_research_branch(
    topic: str,
    query: str,
    depth: int,
    breadth: int,
    search_fn,
    scrape_fn,
    llm_call: LLMCallFn,
    provider: str = "",
    model: str = "",
    emit_fn=None,
) -> dict:
    """Recursively research a sub-topic, generating sub-topics in parallel."""
    if emit_fn:
        await emit_fn(f"🌿 Deep dive (depth={depth}): {topic[:80]}")

    # Search for this topic
    results = await search_fn(f"{query} {topic}", max_results=15)

    # Scrape top 3 most relevant URLs for deeper content
    scraped_texts = []
    urls_to_scrape = [
        r["url"] for r in results[:5]
        if r.get("url") and not r["url"].startswith("rag://")
    ][:3]
    if urls_to_scrape:
        scrape_tasks = [scrape_fn(u) for u in urls_to_scrape]
        scrape_results = await asyncio.gather(*scrape_tasks, return_exceptions=True)
        for url, text in zip(urls_to_scrape, scrape_results):
            if isinstance(text, str) and text.strip():
                scraped_texts.append({"url": url, "text": text[:3000]})

    # Generate summary of findings at this level
    results_text = "\n".join(
        f"- {r.get('title', '')}: {r.get('snippet', '')[:150]}"
        for r in results[:10]
    )
    scraped_ctx = "\n\n".join(
        f"[Source: {s['url']}]\n{s['text'][:1500]}"
        for s in scraped_texts
    )
    summary_prompt = [
        {"role": "system", "content": (
            "Summarize the research findings concisely. "
            "Focus on key facts, data points, and insights. "
            "Return a 200-400 word summary in plain text."
        )},
        {"role": "user", "content": (
            f"Research topic: {topic}\n"
            f"Context query: {query}\n\n"
            f"Search results:\n{results_text}\n\n"
            f"Scraped content:\n{scraped_ctx[:3000]}"
        )},
    ]
    summary = await llm_call(summary_prompt, provider, model)

    branch = {
        "topic": topic,
        "results": results,
        "scraped": scraped_texts,
        "summary": summary,
        "sub_branches": [],
    }

    # Recurse if depth > 0
    if depth > 0:
        subtopics_prompt = [
            {"role": "system", "content": (
                f"Given research on a topic, identify {breadth * 2} specific "
                "sub-topics that need deeper investigation, ranked by importance.\n"
                "Return a JSON array of objects with 'topic' and 'importance' (0-1).\n"
                "Example: [{\"topic\": \"...\", \"importance\": 0.9}]\n"
                "Return ONLY valid JSON, no markdown."
            )},
            {"role": "user", "content": (
                f"Main query: {query}\n"
                f"Current topic: {topic}\n"
                f"Findings summary: {summary[:1000]}\n\n"
                f"Identify {breadth * 2} sub-topics with importance scores."
            )},
        ]
        st_text = await llm_call(subtopics_prompt, provider, model)
        raw_topics = _parse_json_block(st_text, fallback=[])

        # Support both [{topic, importance}] and plain string arrays
        if isinstance(raw_topics, list):
            topic_strings, topic_scores = [], []
            for item in raw_topics:
                if isinstance(item, dict) and "topic" in item:
                    topic_strings.append(str(item["topic"]))
                    topic_scores.append(float(item.get("importance", 0.5)))
                elif isinstance(item, str):
                    topic_strings.append(item)
                    topic_scores.append(0.5)
        else:
            topic_strings, topic_scores = [], []

        # HyperAgents-style: score-proportional selection for exploration diversity
        selected_topics = _score_proportional_selection(
            topic_strings, topic_scores, breadth
        )

        # Research sub-topics in parallel
        if selected_topics:
            sub_tasks = [
                deep_research_branch(
                    st, query, depth - 1, breadth,
                    search_fn, scrape_fn, llm_call,
                    provider, model, emit_fn,
                )
                for st in selected_topics
            ]
            sub_results = await asyncio.gather(
                *sub_tasks, return_exceptions=True,
            )
            for sr in sub_results:
                if isinstance(sr, dict):
                    branch["sub_branches"].append(sr)

    return branch


def flatten_branch_results(branch: dict) -> list[dict]:
    """Flatten all search results from a recursive branch tree."""
    results = list(branch.get("results", []))
    for sub in branch.get("sub_branches", []):
        results.extend(flatten_branch_results(sub))
    return results


def flatten_branch_summaries(branch: dict, level: int = 0) -> str:
    """Flatten all summaries from a branch tree into structured text."""
    indent = "  " * level
    parts = [f"{indent}## {branch.get('topic', 'Unknown')}\n{branch.get('summary', '')}"]
    for sub in branch.get("sub_branches", []):
        parts.append(flatten_branch_summaries(sub, level + 1))
    return "\n\n".join(parts)


# ── Parallel Perspective Research (DeepResearch Research-Synthesis style) ─────

async def research_by_perspectives_parallel(
    query: str,
    perspectives: list[dict],
    search_fn,
    scrape_fn,
    llm_call: LLMCallFn,
    provider: str = "",
    model: str = "",
    depth: int = 1,
    breadth: int = 2,
    emit_fn=None,
) -> list[dict]:
    """
    Launch one deep research branch per perspective in parallel.

    Inspired by DeepResearch's Research-Synthesis paradigm:
    multiple Research Agents explore the topic from different angles
    simultaneously, then a Synthesis Agent integrates their reports.

    Each perspective becomes the top-level topic of a deep_research_branch,
    allowing true parallel exploration vs. the sequential approach.

    Args:
        perspectives: List of perspective dicts (from generate_perspectives)
        depth / breadth: Recursion params for each branch
        emit_fn: Optional SSE emit for progress updates

    Returns:
        List of branch dicts, one per perspective.
    """
    if not perspectives:
        return []

    if emit_fn:
        await emit_fn(
            f"🔬 Parallel perspective research: launching {len(perspectives)} "
            f"branches simultaneously..."
        )

    async def _research_one_perspective(p: dict) -> dict:
        topic = p.get("perspective", "General")
        desc = p.get("description", "")
        if emit_fn:
            await emit_fn(f"  ↳ [{topic}] starting parallel branch...")
        try:
            branch = await deep_research_branch(
                topic=f"{topic}: {desc}" if desc else topic,
                query=query,
                depth=depth,
                breadth=breadth,
                search_fn=search_fn,
                scrape_fn=scrape_fn,
                llm_call=llm_call,
                provider=provider,
                model=model,
                emit_fn=None,  # Suppress sub-branch emit to avoid noise
            )
            branch["_perspective"] = p.get("perspective", topic)
            return branch
        except Exception as e:
            logger.warning("Perspective branch failed [%s]: %s", topic, e)
            return {
                "topic": topic,
                "results": [],
                "scraped": [],
                "summary": f"[Branch failed: {e}]",
                "sub_branches": [],
                "_perspective": topic,
            }

    tasks = [_research_one_perspective(p) for p in perspectives]
    branches = await asyncio.gather(*tasks, return_exceptions=True)

    valid_branches = []
    for b in branches:
        if isinstance(b, dict):
            valid_branches.append(b)
        elif isinstance(b, Exception):
            logger.warning("Perspective branch exception: %s", b)

    if emit_fn:
        total_results = sum(len(flatten_branch_results(b)) for b in valid_branches)
        await emit_fn(
            f"✅ Parallel research complete: {len(valid_branches)} perspectives, "
            f"~{total_results} total results"
        )

    logger.info(
        "Parallel perspective research: %d/%d branches succeeded",
        len(valid_branches), len(perspectives),
    )
    return valid_branches


async def synthesize_perspective_branches(
    query: str,
    branches: list[dict],
    perspectives: list[dict],
    llm_call: LLMCallFn,
    provider: str = "",
    model: str = "",
) -> str:
    """
    Synthesis Agent step: integrate reports from all parallel perspective branches.

    Produces a coherent synthesis that:
      - Identifies cross-perspective agreements and conflicts
      - Highlights unique findings from each perspective
      - Proposes an integrated narrative structure

    Returns a synthesis text that can seed the final report generation.
    """
    if not branches:
        return ""

    # Build a compact representation of each branch's findings
    branches_text = "\n\n".join(
        f"### Perspective: {b.get('_perspective', b.get('topic', 'Unknown'))}\n"
        f"{b.get('summary', 'No summary')[:800]}"
        for b in branches
    )

    perspectives_text = "\n".join(
        f"- {p['perspective']}: {p.get('description', '')}"
        for p in perspectives
    ) if perspectives else ""

    prompt = [
        {"role": "system", "content": (
            "You are a synthesis agent integrating reports from multiple "
            "parallel research streams. Your role is to:\n"
            "  1. Identify key agreements across perspectives\n"
            "  2. Surface unique insights from each angle\n"
            "  3. Flag contradictions or tensions between perspectives\n"
            "  4. Propose a unified narrative that weaves all perspectives together\n\n"
            "Write a structured synthesis (600-1000 words) with sections:\n"
            "## Cross-Perspective Agreements\n"
            "## Unique Insights by Perspective\n"
            "## Tensions & Contradictions\n"
            "## Unified Narrative\n\n"
            "Be analytical, not just descriptive. This synthesis will seed the final report."
        )},
        {"role": "user", "content": (
            f"Research topic: {query}\n\n"
            f"Target perspectives:\n{perspectives_text}\n\n"
            f"Parallel research findings:\n{branches_text}\n\n"
            "Synthesize these into a unified multi-perspective analysis."
        )},
    ]

    try:
        synthesis = await llm_call(prompt, provider, model)
        logger.info(
            "Perspective synthesis complete: %d branches → %d chars",
            len(branches), len(synthesis),
        )
        return synthesis
    except Exception as e:
        logger.warning("Perspective synthesis failed: %s", e)
        return "\n\n".join(
            f"## {b.get('_perspective', 'Unknown')}\n{b.get('summary', '')}"
            for b in branches
        )


# ── Dynamic Outline (WebWeaver-inspired) ─────────────────────────────────────

async def update_dynamic_outline(
    current_outline: dict,
    new_findings: list[dict],
    query: str,
    iteration_num: int,
    llm_call: LLMCallFn,
    provider: str = "",
    model: str = "",
) -> dict:
    """
    Dynamically restructure the report outline based on accumulated findings.

    Inspired by WebWeaver (https://arxiv.org/abs/2509.13312):
    instead of a fixed 7-section template, the outline evolves as new
    evidence is discovered. Each iteration may add, rename, or reorder
    sections to best represent the emerging knowledge structure.

    Args:
        current_outline: Current outline dict {sections: [{title, coverage, key_points}]}
        new_findings: Latest batch of search results
        query: Research query
        iteration_num: Current iteration number

    Returns:
        Updated outline dict with revised sections and coverage scores.
    """
    # Build current outline text
    if current_outline and current_outline.get("sections"):
        current_text = "\n".join(
            f"- [{s.get('coverage', 0):.0%}] {s['title']}: "
            f"{', '.join(s.get('key_points', [])[:3])}"
            for s in current_outline["sections"]
        )
    else:
        current_text = "No outline yet — create one from scratch."

    # Summarise new findings
    findings_text = "\n".join(
        f"- {r.get('title', '')}: {r.get('snippet', '')[:150]}"
        for r in new_findings[-20:]
    )

    prompt = [
        {"role": "system", "content": (
            "You are a research outline architect. Maintain and evolve a dynamic "
            "report outline as new evidence is discovered.\n\n"
            "Rules:\n"
            "  - Add new sections for topics with sufficient evidence (>2 sources)\n"
            "  - Update coverage scores based on how well each section is supported\n"
            "  - Rename sections to better reflect actual findings\n"
            "  - Merge sections that overlap significantly\n"
            "  - Keep 5-9 sections maximum\n\n"
            "Return JSON:\n"
            '{"sections": [{"title": "...", "coverage": 0.0-1.0, '
            '"key_points": ["..."], "needs_more": true|false}], '
            '"focus_next": ["topic to research next", ...]}\n\n'
            "Return ONLY valid JSON, no markdown."
        )},
        {"role": "user", "content": (
            f"Research topic: {query}\n"
            f"Iteration: {iteration_num}\n\n"
            f"Current outline:\n{current_text}\n\n"
            f"New findings ({len(new_findings)} results):\n{findings_text}\n\n"
            "Update the outline to reflect new evidence."
        )},
    ]

    try:
        text = await llm_call(prompt, provider, model)
        # Parse JSON
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            import json as _json
            data = _json.loads(text[start:end + 1])
            if isinstance(data, dict) and "sections" in data:
                logger.info(
                    "Dynamic outline updated: %d sections (iter %d)",
                    len(data["sections"]), iteration_num,
                )
                return data
    except Exception as e:
        logger.warning("Dynamic outline update failed: %s", e)

    # Return unchanged outline or minimal default
    if current_outline:
        return current_outline
    return {
        "sections": [
            {"title": query, "coverage": 0.0, "key_points": [], "needs_more": True}
        ],
        "focus_next": [],
    }


def outline_to_report_structure(outline: dict) -> str:
    """Convert a dynamic outline to a structured prompt for report generation."""
    if not outline or not outline.get("sections"):
        return ""

    lines = ["Report Structure (dynamic outline — follow this structure):"]
    for i, section in enumerate(outline["sections"], 1):
        coverage = section.get("coverage", 0)
        marker = "✅" if coverage >= 0.7 else ("⚠️" if coverage >= 0.4 else "❌")
        lines.append(
            f"{i}. {marker} {section['title']} "
            f"[{coverage:.0%} covered]"
        )
        for kp in section.get("key_points", [])[:3]:
            lines.append(f"   • {kp}")
    return "\n".join(lines)


# ── Helper: Score-Proportional Selection (HyperAgents-inspired) ─────────────

def _score_proportional_selection(
    items: list[str],
    scores: list[float],
    n: int,
    temperature: float = 0.4,
) -> list[str]:
    """
    Select n items with probability proportional to their scores (softmax).

    Directly inspired by HyperAgents' select_next_parent algorithm:
    the best items are favoured but not always chosen, maintaining
    open-ended exploratory diversity rather than pure greedy selection.

    Args:
        items: Candidate topic strings.
        scores: Importance scores [0-1] for each item.
        n: Number of items to select.
        temperature: Controls randomness (lower = more greedy).

    Returns:
        List of up to n selected items.
    """
    if not items:
        return []
    if len(items) <= n:
        return list(items)

    # Softmax normalisation
    max_s = max(scores) if scores else 1.0
    weights = [math.exp((s - max_s) / temperature) for s in scores]
    total = sum(weights)
    probs = [w / total for w in weights]

    selected: list[str] = []
    remaining_items = list(items)
    remaining_probs = list(probs)

    for _ in range(min(n, len(remaining_items))):
        r = random.random()
        cumsum = 0.0
        for i, p in enumerate(remaining_probs):
            cumsum += p
            if cumsum >= r:
                selected.append(remaining_items.pop(i))
                remaining_probs.pop(i)
                rem_total = sum(remaining_probs)
                if rem_total > 0:
                    remaining_probs = [p / rem_total for p in remaining_probs]
                break
        else:
            # Fallback: pick last item
            if remaining_items:
                selected.append(remaining_items.pop())
                remaining_probs = remaining_probs[:-1] if remaining_probs else []

    return selected


# ── Think Tool: Post-Search Reflection (open_deep_research-inspired) ─────────

async def reflect_after_search(
    query: str,
    new_results: list[dict],
    existing_findings: str,
    iteration_num: int,
    llm_call: LLMCallFn,
    provider: str = "",
    model: str = "",
) -> dict:
    """
    Strategic reflection after each search batch (open_deep_research think_tool).

    After every search, the LLM pauses to analyse:
      1. What key information was just found?
      2. What is still missing or unclear?
      3. Should we continue (or is the evidence already sufficient)?
      4. What specific query should be made next?

    This prevents "search spirals" (re-finding the same info) and enables
    confident early stopping — exactly what lifts open_deep_research to #6
    on Deep Research Bench despite a simpler overall architecture.

    Args:
        query: The original research query.
        new_results: Fresh search results from this iteration.
        existing_findings: Brief summary of what was already known.
        iteration_num: Current iteration number (for budget awareness).

    Returns:
        Dict with keys:
          - found: str — key facts just discovered
          - gaps: list[str] — what is still missing
          - continue: bool — whether more searching is warranted
          - stop_reason: str — reason if stopping early
          - next_query: str — the most targeted query for the next search
          - confidence: float — [0-1] confidence the question is answerable now
    """
    results_text = "\n".join(
        f"- [{r.get('source', 'web')}] {r.get('title', '')}: "
        f"{r.get('snippet', '')[:150]}"
        for r in new_results[:15]
    )
    findings_ctx = existing_findings[:1200] if existing_findings else "No prior findings yet."

    prompt = [
        {"role": "system", "content": (
            "You are a research strategist. After each search, reflect briefly:\n"
            "1. What KEY facts or data points were just found?\n"
            "2. What is still MISSING or unclear?\n"
            "3. Should we CONTINUE searching (consider diminishing returns)?\n"
            "4. If continuing, what is the BEST next query?\n\n"
            "Stop criteria (set continue=false if ANY holds):\n"
            "  - The last 2 searches returned very similar information\n"
            "  - You can already answer the question comprehensively (confidence >= 0.85)\n"
            "  - All major sub-questions are answered\n\n"
            "Return JSON:\n"
            '{"found": "key facts summary (1-3 sentences)", '
            '"gaps": ["gap 1", "gap 2"], '
            '"continue": true, '
            '"stop_reason": "", '
            '"next_query": "specific targeted query", '
            '"confidence": 0.0}'
            "\n\nReturn ONLY valid JSON, no markdown."
        )},
        {"role": "user", "content": (
            f"Original query: {query}\n"
            f"Iteration: {iteration_num}\n\n"
            f"Prior knowledge summary:\n{findings_ctx}\n\n"
            f"New results ({len(new_results)} found):\n{results_text}\n\n"
            "Reflect: what did we find, what's still missing, should we continue?"
        )},
    ]
    try:
        text = await llm_call(prompt, provider, model)
        data = _parse_json_block(text, fallback={})
        if not isinstance(data, dict):
            data = {}

        return {
            "found": data.get("found", ""),
            "gaps": data.get("gaps", []),
            "continue": bool(data.get("continue", True)),
            "stop_reason": data.get("stop_reason", ""),
            "next_query": data.get("next_query", query),
            "confidence": max(0.0, min(1.0, float(data.get("confidence", 0.5)))),
        }
    except Exception as e:
        logger.warning("reflect_after_search failed: %s", e)
        return {
            "found": "", "gaps": [], "continue": True,
            "stop_reason": "", "next_query": query, "confidence": 0.5,
        }


def should_stop_early(reflection: dict, min_confidence: float = 0.85) -> bool:
    """
    Decide whether to exit the research loop early based on reflection output.

    Stops if:
      - The think_tool says stop (continue=False)
      - Confidence in answer completeness exceeds the threshold
    """
    if not reflection.get("continue", True):
        return True
    if reflection.get("confidence", 0.0) >= min_confidence:
        return True
    return False


# ── 3. Structured Multi-Criteria Evaluation ──

async def evaluate_structured(
    query: str,
    perspectives: list[dict],
    results: list[dict],
    num_assets: int,
    llm_call: LLMCallFn,
    provider: str = "",
    model: str = "",
) -> dict:
    """Evaluate research on 5 axes: coverage, depth, reliability, coherence, recency."""
    perspectives_text = "\n".join(
        f"- {p['perspective']}: {p.get('description', '')}"
        for p in perspectives
    ) if perspectives else "No specific perspectives defined"

    results_summary = "\n".join(
        f"- [{r.get('source', 'web')}] {r.get('title', '')}: "
        f"{r.get('snippet', '')[:120]}"
        for r in results[-40:]
    )[:5000]

    prompt = [
        {"role": "system", "content": (
            "You are a research quality evaluator. Evaluate the collected "
            "research on 5 axes, each scored 0.0 to 1.0.\n\n"
            "Return JSON:\n"
            '{"coverage": 0.0, "depth": 0.0, "reliability": 0.0, '
            '"coherence": 0.0, "recency": 0.0, '
            '"gaps": ["missing topic 1", ...], '
            '"weakest_axis": "coverage", '
            '"evaluation": "Brief assessment", '
            '"suggestions": ["next step 1", ...]}\n\n'
            "Scoring guide per axis:\n"
            "- coverage: 1.0 = all perspectives well covered\n"
            "- depth: 1.0 = detailed analysis with supporting data\n"
            "- reliability: 1.0 = diverse, authoritative sources\n"
            "- coherence: 1.0 = no contradictions, logical flow\n"
            "- recency: 1.0 = mostly recent data (last 2 years)\n\n"
            "Return ONLY valid JSON, no markdown."
        )},
        {"role": "user", "content": (
            f"Topic: {query}\n\n"
            f"Target perspectives:\n{perspectives_text}\n\n"
            f"Collected results ({len(results)} total):\n{results_summary}\n\n"
            f"Assets downloaded: {num_assets}\n\n"
            "Evaluate research quality on all 5 axes."
        )},
    ]
    text = await llm_call(prompt, provider, model)
    data = _parse_json_block(text, fallback={})
    if not isinstance(data, dict):
        data = {}

    # Extract and validate scores
    axes = ["coverage", "depth", "reliability", "coherence", "recency"]
    scores = {}
    for ax in axes:
        try:
            scores[ax] = max(0.0, min(1.0, float(data.get(ax, 0.3))))
        except (ValueError, TypeError):
            scores[ax] = 0.3

    # Weighted overall score
    weights = {
        "coverage": 0.25, "depth": 0.25,
        "reliability": 0.20, "coherence": 0.15, "recency": 0.15,
    }
    overall = sum(scores[ax] * weights[ax] for ax in axes)

    return {
        "scores": scores,
        "overall": round(overall, 3),
        "gaps": data.get("gaps", []),
        "weakest_axis": data.get("weakest_axis", ""),
        "evaluation": data.get("evaluation", ""),
        "suggestions": data.get("suggestions", []),
    }


async def ensemble_evaluate(
    query: str,
    perspectives: list[dict],
    results: list[dict],
    num_assets: int,
    llm_call: LLMCallFn,
    llm_configs: list[dict],
) -> dict:
    """
    Evaluate research quality using multiple LLM judges (ensemble consensus).

    Inspired by HyperAgents' ensemble.py: runs N evaluators and averages
    their scores to produce a robust, bias-reduced quality estimate.

    Args:
        llm_configs: List of {"provider": str, "model": str} dicts.
                     Falls back to a single default call if empty.

    Returns:
        Consensus evaluation dict with an added 'ensemble_size' key.
    """
    if not llm_configs:
        return await evaluate_structured(
            query, perspectives, results, num_assets, llm_call
        )

    eval_tasks = [
        evaluate_structured(
            query, perspectives, results, num_assets, llm_call,
            cfg.get("provider", ""), cfg.get("model", ""),
        )
        for cfg in llm_configs
    ]
    evaluations = await asyncio.gather(*eval_tasks, return_exceptions=True)
    valid_evals = [e for e in evaluations if isinstance(e, dict)]

    if not valid_evals:
        return await evaluate_structured(
            query, perspectives, results, num_assets, llm_call
        )

    # Average scores across all judges
    axes = ["coverage", "depth", "reliability", "coherence", "recency"]
    consensus_scores: dict[str, float] = {}
    for ax in axes:
        vals = [e["scores"].get(ax, 0.3) for e in valid_evals]
        consensus_scores[ax] = round(sum(vals) / len(vals), 3)

    weights = {
        "coverage": 0.25, "depth": 0.25,
        "reliability": 0.20, "coherence": 0.15, "recency": 0.15,
    }
    overall = round(sum(consensus_scores[ax] * weights[ax] for ax in axes), 3)

    # Pick the evaluation closest to the consensus (most representative judge)
    best_eval = min(
        valid_evals,
        key=lambda e: abs(e.get("overall", 0) - overall),
    )

    return {
        **best_eval,
        "scores": consensus_scores,
        "overall": overall,
        "ensemble_size": len(valid_evals),
    }


# ── 4. Inter-Iteration Reflection (WebSeer/ReSearch-style) ──

async def reflect_on_iteration(
    query: str,
    iteration_num: int,
    max_iterations: int,
    eval_result: dict,
    uncovered_questions: list[str],
    llm_call: LLMCallFn,
    provider: str = "",
    model: str = "",
) -> dict:
    """Reflect on progress and produce a targeted correction plan."""
    gaps_text = "\n".join(f"- {g}" for g in eval_result.get("gaps", []))
    suggestions_text = "\n".join(
        f"- {s}" for s in eval_result.get("suggestions", [])
    )
    uncovered_text = "\n".join(
        f"- {q}" for q in uncovered_questions[:10]
    )
    scores = eval_result.get("scores", {})
    scores_text = "\n".join(
        f"- {ax}: {scores.get(ax, 0):.0%}" for ax in scores
    )

    prompt = [
        {"role": "system", "content": (
            "You are a research strategist reflecting on progress. "
            "Based on the evaluation, plan the next iteration.\n\n"
            "Return JSON:\n"
            '{"priority_actions": [{"action": "web_search", '
            '"params": {"query": "..."}, "reason": "..."}], '
            '"focus_queries": ["specific query 1", ...], '
            '"covered_questions": ["question already answered", ...]}\n\n'
            "Available actions: web_search, scrape_url, deep_dive, "
            "download_asset, query_rag, write_script\n"
            "Return ONLY valid JSON, no markdown."
        )},
        {"role": "user", "content": (
            f"Topic: {query}\n"
            f"Iteration: {iteration_num}/{max_iterations}\n\n"
            f"Current scores:\n{scores_text}\n"
            f"Overall: {eval_result.get('overall', 0):.0%}\n"
            f"Weakest axis: {eval_result.get('weakest_axis', 'unknown')}\n\n"
            f"Identified gaps:\n{gaps_text}\n\n"
            f"Suggestions:\n{suggestions_text}\n\n"
            f"Uncovered questions:\n{uncovered_text}\n\n"
            "Plan 3-5 targeted actions to improve the weakest areas."
        )},
    ]
    text = await llm_call(prompt, provider, model)
    data = _parse_json_block(text, fallback={})
    if not isinstance(data, dict):
        data = {}

    return {
        "priority_actions": data.get("priority_actions", []),
        "focus_queries": data.get("focus_queries", []),
        "covered_questions": data.get("covered_questions", []),
    }


# ── NEW: Self-Referential Process Improvement (HyperAgents-inspired) ─────────

async def improve_process_md(
    current_process: str,
    query: str,
    eval_result: dict,
    iteration_num: int,
    max_iterations: int,
    llm_call: LLMCallFn,
    provider: str = "",
    model: str = "",
) -> str | None:
    """
    Self-referentially improve the research process.md based on evaluation.

    This is the core HyperAgents concept adapted for research: the system
    modifies its own operational process to improve future iterations,
    rather than just modifying what it searches.

    Only triggers on iterations >= 2 and when score < 0.8 (room to improve).
    Returns the improved process text, or None if no improvement was made.
    """
    overall = eval_result.get("overall", 1.0)
    if overall >= 0.82 or iteration_num < 2:
        return None  # No need to self-improve — already good or too early

    weakest = eval_result.get("weakest_axis", "")
    gaps = eval_result.get("gaps", [])
    suggestions = eval_result.get("suggestions", [])
    scores = eval_result.get("scores", {})

    scores_text = " | ".join(
        f"{ax}: {v:.0%}" for ax, v in scores.items()
    )
    gaps_text = "\n".join(f"- {g}" for g in gaps[:4])
    suggestions_text = "\n".join(f"- {s}" for s in suggestions[:4])

    prompt = [
        {"role": "system", "content": (
            "You are a meta-research strategist. Your task is to improve a "
            "research process document based on mid-run evaluation results.\n\n"
            "The process.md is a Markdown document describing how the research "
            "agent should conduct its investigation. You can:\n"
            "  • Reorder or emphasise action types\n"
            "  • Add specific instructions for weak areas\n"
            "  • Adjust priority of sources (e.g. 'prioritise Scholar for depth')\n"
            "  • Insert targeted sub-queries to address identified gaps\n\n"
            "RULES:\n"
            "  - Make MINIMAL, TARGETED changes only\n"
            "  - Preserve the overall structure and Markdown format\n"
            "  - Do NOT change the header variables ({{query}}, {{model}}, etc.)\n"
            "  - Return the COMPLETE improved process.md, nothing else\n"
        )},
        {"role": "user", "content": (
            f"Research topic: {query}\n"
            f"Iteration: {iteration_num}/{max_iterations}\n"
            f"Current scores: {scores_text}\n"
            f"Overall: {overall:.0%} | Weakest axis: {weakest}\n\n"
            f"Identified gaps:\n{gaps_text}\n\n"
            f"Suggestions from evaluator:\n{suggestions_text}\n\n"
            f"Current process.md:\n{current_process}\n\n"
            "Return the improved process.md with targeted adjustments."
        )},
    ]
    try:
        improved = await llm_call(prompt, provider, model)
        # Sanity check: must be non-trivially different and contain structure
        if (
            improved
            and len(improved) > 200
            and improved != current_process
            and ("#" in improved or "-" in improved)
        ):
            return improved
    except Exception as e:
        logger.warning("process.md self-improvement failed: %s", e)
    return None


# ── 5. Report Generation with Inline Citations ──

async def generate_report_with_citations(
    query: str,
    results: list[dict],
    assets: list[dict],
    perspectives: list[dict],
    branch_summaries: str,
    score: float,
    num_iterations: int,
    llm_call: LLMCallFn,
    provider: str = "",
    model: str = "",
    dynamic_outline: dict | None = None,
    report_draft: str = "",
    perspective_synthesis: str = "",
) -> str:
    """Generate a report with inline citations [1][2] and numbered bibliography.

    Args:
        dynamic_outline: If provided (WebWeaver-style), uses it to structure
                         the report instead of the fixed 7-section template.
        report_draft: Evolving draft from IterResearch rounds — used as a
                      synthesis starting point rather than generating from scratch.
        perspective_synthesis: Cross-perspective synthesis from parallel branches.
    """
    # Build numbered source list (skip memory:// and rag:// synthetic entries)
    seen_urls = set()
    numbered_sources = []
    for r in results:
        url = r.get("url", "")
        if (
            url and url not in seen_urls
            and not url.startswith("rag://")
            and not url.startswith("memory://")
        ):
            seen_urls.add(url)
            numbered_sources.append({
                "id": len(numbered_sources) + 1,
                "title": r.get("title", "Untitled"),
                "url": url,
                "snippet": r.get("snippet", "")[:200],
                "source": r.get("source", "web"),
            })
        if len(numbered_sources) >= 50:
            break

    sources_text = "\n".join(
        f"[{s['id']}] {s['title']} — {s['url']}\n"
        f"    Excerpt: {s['snippet']}"
        for s in numbered_sources
    )

    perspectives_text = "\n".join(
        f"- {p['perspective']}: {p.get('description', '')}"
        for p in perspectives
    ) if perspectives else ""

    assets_text = "\n".join(
        f"- {a['name']} ({a['type']}) from {a.get('url', '')}"
        for a in assets
    )

    # Collect experimental evidence (script outputs, model knowledge)
    evidence_items = []
    for r in results:
        src = r.get("source", "")
        if src == "model_knowledge":
            evidence_items.append(f"[Model Expert] {r.get('snippet', '')[:300]}")
        elif src == "experiment":
            code = r.get("code", "")[:200]
            evidence_items.append(
                f"[Experiment] Code: {code}... → Output: {r.get('snippet', '')[:300]}"
            )
        if "key_facts" in r and r.get("key_facts"):
            facts = "; ".join(r["key_facts"][:5])
            evidence_items.append(f"[Extracted Facts] {facts}")
    evidence_text = "\n".join(evidence_items[:20]) if evidence_items else "None"

    # --- Build dynamic structure prompt ---
    if dynamic_outline and dynamic_outline.get("sections"):
        structure_prompt = outline_to_report_structure(dynamic_outline)
        structure_prompt += (
            "\n\nIMPORTANT: Follow this dynamic outline strictly. "
            "Sections marked ❌ need more evidence — synthesize what we have. "
            "Sections marked ✅ have strong evidence — be detailed and cite sources."
        )
    else:
        structure_prompt = (
            "Report structure:\n"
            "1. Table of Contents\n"
            "2. Executive Summary (with key metrics table)\n"
            "3. Introduction & Context (with concept mindmap)\n"
            "4. Analysis sections with evidence & diagrams\n"
            "5. Key Findings with proof & comparison tables\n"
            "6. Conclusion & Recommendations\n"
            "7. Bibliography [1]-[N]"
        )

    # --- Build user content parts ---
    user_parts = [f"# Research Topic: {query}\n\n"]

    if perspective_synthesis:
        user_parts.append(
            f"## Cross-Perspective Synthesis (DeepResearch multi-agent)\n"
            f"{perspective_synthesis[:3000]}\n\n"
        )

    if report_draft:
        user_parts.append(
            f"## Evolving Report Draft (IterResearch — integrate and expand this)\n"
            f"{report_draft[:4000]}\n\n"
        )

    user_parts += [
        f"## Research Perspectives\n{perspectives_text}\n\n",
        f"## Deep Research Summaries\n{branch_summaries[:4000]}\n\n",
        f"## Numbered Sources\n{sources_text[:8000]}\n\n",
        f"## Evidence & Experimental Data\n{evidence_text}\n\n",
        f"## Downloaded Assets\n{assets_text}\n\n",
        f"## Research Metrics\n"
        f"- Quality Score: {score:.0%}\n"
        f"- Iterations: {num_iterations}\n"
        f"- Sources collected: {len(numbered_sources)}\n\n",
        "Generate the full research report with inline citations, "
        "evidence blocks, and rich diagrams.",
    ]

    prompt = [
        {"role": "system", "content": (
            "You are an expert research report writer. Generate a "
            "comprehensive, analytical Markdown report.\n\n"
            "CRITICAL RULES:\n"
            "- Use inline citations like [1], [2][3] throughout the text\n"
            "- Every factual claim MUST have at least one citation\n"
            "- Include EVIDENCE sections: for each key finding, provide proof\n"
            "  using citations, data quotes, or experimental results\n"
            "- Use '> **Evidence:**' blockquotes for proof passages\n"
            "- Write 3000-6000 words minimum\n"
            "- Be analytical, not just descriptive\n\n"
            "VISUAL REQUIREMENTS:\n"
            "- Include 3-5 Mermaid diagrams (```mermaid blocks)\n"
            "- Use Markdown tables for data comparisons\n"
            "- Add flowcharts for processes, mindmaps for concepts\n"
            "- Use pie/bar charts in Mermaid where data supports it\n"
            "- Create timeline diagrams for chronological data\n\n"
            + structure_prompt
        )},
        {"role": "user", "content": "".join(user_parts)},
    ]
    report = await llm_call(prompt, provider, model)

    # Append bibliography if not already included
    if "## Bibliography" not in report and "## Bibliographie" not in report:
        bib = "\n\n---\n\n## Bibliography\n\n"
        for s in numbered_sources:
            bib += f"[{s['id']}] {s['title']} — {s['url']}\n\n"
        report += bib

    # --- Inject Structured UI Components ---
    # Prepend interactive research metrics (rendered by frontend)
    import json as _json

    # Executive summary metrics table
    metrics_table = {
        "title": "Research Metrics",
        "headers": ["Metric", "Value"],
        "rows": [
            ["Quality Score", f"{score:.0%}"],
            ["Iterations", str(num_iterations)],
            ["Total Sources", str(len(numbered_sources))],
            ["Perspectives", str(len(perspectives))],
            ["Assets Downloaded", str(len(assets))],
        ],
    }
    metrics_marker = f'__TABLE__{_json.dumps(metrics_table)}__TABLE__'

    # Source distribution chart
    source_counts = {}
    for r in results:
        src = r.get("source", "web")
        source_counts[src] = source_counts.get(src, 0) + 1

    if source_counts:
        source_chart = {
            "type": "pie",
            "title": "Source Distribution",
            "labels": list(source_counts.keys()),
            "datasets": [{
                "label": "Sources",
                "data": list(source_counts.values()),
            }],
        }
        chart_marker = f'__CHART__{_json.dumps(source_chart)}__CHART__'
    else:
        chart_marker = ""

    # Inject metrics right after the first H1 or at the top
    if "\n## " in report:
        # Insert after the first paragraph
        first_section = report.find("\n## ")
        report = (
            report[:first_section]
            + f"\n\n{metrics_marker}\n\n"
            + (f"{chart_marker}\n\n" if chart_marker else "")
            + report[first_section:]
        )
    else:
        report = f"{metrics_marker}\n\n{chart_marker}\n\n{report}"

    return report


# ── 6. Sectioned Report Generator (GPT-Researcher-style) ─────────────────────

async def generate_sectioned_report(
    query: str,
    sections: list[dict],
    sources: list[dict],
    branch_summaries: str,
    score: float,
    llm_call: LLMCallFn,
    provider: str = "",
    model: str = "",
    perspective_synthesis: str = "",
    emit_fn=None,
) -> str:
    """
    Generate a long-form report section-by-section (GPT-Researcher subtopic pattern).

    Instead of one monolithic LLM call (which causes the model to "forget"
    earlier sections), this generates each section sequentially:
      - Passes the last 2 completed sections as context for coherence
      - Each section is ~500-800 words with evidence and citations
      - A final assembly step weaves sections into a unified report

    This enables 5000-8000 word reports without quality degradation.
    """
    if not sections:
        logger.warning("generate_sectioned_report: no sections provided")
        return ""

    norm_sections: list[dict] = []
    for s in sections:
        if isinstance(s, str):
            norm_sections.append({"title": s, "coverage": 0.5, "key_points": []})
        elif isinstance(s, dict):
            norm_sections.append(s)

    seen_urls: set[str] = set()
    numbered_sources: list[dict] = []
    for r in sources:
        url = r.get("url", "")
        if url and url not in seen_urls and not url.startswith(("rag://", "memory://")):
            seen_urls.add(url)
            numbered_sources.append({
                "id": len(numbered_sources) + 1,
                "title": r.get("title", "Untitled"),
                "url": url,
                "snippet": r.get("snippet", "")[:200],
                "source": r.get("source", "web"),
            })
        if len(numbered_sources) >= 60:
            break

    sources_index = "\n".join(
        f"[{s['id']}] {s['title']} — {s['url']}\n    {s['snippet']}"
        for s in numbered_sources
    )

    system_prompt = (
        "You are an expert research report writer generating ONE section of a long report.\n\n"
        "CRITICAL RULES:\n"
        "- Write ONLY the requested section (do NOT write other sections)\n"
        "- Write 500-800 words for this section\n"
        "- Use inline citations like [1], [2][3] for every factual claim\n"
        "- Include evidence blockquotes: > **Evidence:** followed by quoted data\n"
        "- Include 1 Mermaid diagram where relevant (```mermaid blocks)\n"
        "- Use a Markdown table if comparing data\n"
        "- Be analytical and specific, not generic\n"
        "- Do NOT repeat information from the previous sections\n"
        "- End with a brief transition sentence to the next section\n\n"
        f"Source Index (use [N] citations):\n{sources_index[:4000]}"
    )

    completed_sections: list[str] = []

    for i, section in enumerate(norm_sections):
        title = section.get("title", f"Section {i + 1}")
        key_points = section.get("key_points", [])
        coverage = section.get("coverage", 0.5)

        if emit_fn:
            await emit_fn(f"✍️ Section {i + 1}/{len(norm_sections)}: {title[:60]}...")

        prior_ctx = ""
        if completed_sections:
            prior_sections = completed_sections[-2:]
            prior_ctx = (
                "## Previously Written Sections (DO NOT REPEAT):\n"
                + "\n\n---\n\n".join(
                    s[:600] + ("..." if len(s) > 600 else "")
                    for s in prior_sections
                )
            )

        section_evidence = _extract_section_evidence(
            title, key_points, branch_summaries, perspective_synthesis
        )

        user_content = (
            f"Research Topic: {query}\n\n"
            f"Overall Research Quality: {score:.0%}\n\n"
            + (f"{prior_ctx}\n\n" if prior_ctx else "")
            + f"## Section to Write Now:\n"
            f"**Title**: {title}\n"
            f"**Coverage**: {coverage:.0%} of evidence collected\n"
            + (f"**Key Points**: {', '.join(key_points[:5])}\n" if key_points else "")
            + f"\n## Relevant Research Evidence:\n{section_evidence[:3000]}\n\n"
            f"Write section '{title}' now (500-800 words, with citations and evidence):"
        )

        try:
            section_text = await llm_call(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                provider,
                model,
            )
            if not section_text.strip().startswith("#"):
                section_text = f"## {title}\n\n{section_text.strip()}"
            completed_sections.append(section_text)
        except Exception as e:
            logger.warning("Section '%s' generation failed: %s", title, e)
            completed_sections.append(
                f"## {title}\n\n*[Section generation failed: {e}]*\n"
            )

    if emit_fn:
        await emit_fn("📚 Assemblage du rapport final...")

    return await _assemble_sectioned_report(
        query=query,
        sections=completed_sections,
        section_titles=[s.get("title", "") for s in norm_sections],
        numbered_sources=numbered_sources,
        score=score,
        llm_call=llm_call,
        provider=provider,
        model=model,
    )


def _extract_section_evidence(
    title: str,
    key_points: list[str],
    branch_summaries: str,
    synthesis: str,
    max_chars: int = 2500,
) -> str:
    """Extract the most relevant research evidence for a section by keyword scoring."""
    if not branch_summaries and not synthesis:
        return "No research evidence available."

    keywords = title.lower().split()
    for kp in key_points[:3]:
        keywords.extend(kp.lower().split())
    keywords = [k for k in keywords if len(k) > 3]

    all_text = (synthesis + "\n\n" + branch_summaries) if synthesis else branch_summaries
    paragraphs = [p.strip() for p in all_text.split("\n\n") if p.strip()]

    scored: list[tuple[float, str]] = []
    for para in paragraphs:
        para_lower = para.lower()
        score = sum(1 for kw in keywords if kw in para_lower)
        if score > 0:
            scored.append((score, para))

    scored.sort(key=lambda x: x[0], reverse=True)
    selected = [p for _, p in scored[:6]]

    if not selected:
        return all_text[:max_chars]

    return "\n\n".join(selected)[:max_chars]


async def _assemble_sectioned_report(
    query: str,
    sections: list[str],
    section_titles: list[str],
    numbered_sources: list[dict],
    score: float,
    llm_call: LLMCallFn,
    provider: str = "",
    model: str = "",
) -> str:
    """Final assembly: ToC + executive summary + all sections + bibliography."""
    import json as _json

    toc_lines = ["## Table des Matières", ""]
    for i, title in enumerate(section_titles, 1):
        anchor = (
            title.lower()
            .replace(" ", "-").replace("'", "").replace("(", "").replace(")", "")
            .replace("&", "").replace(",", "").replace(".", "")
        )
        toc_lines.append(f"{i}. [{title}](#{anchor})")
    toc = "\n".join(toc_lines)

    bib_lines = ["## Bibliographie", ""]
    for s in numbered_sources:
        bib_lines.append(f"[{s['id']}] **{s['title']}** — [{s['url']}]({s['url']})")
        if s.get("snippet"):
            bib_lines.append(f"   > {s['snippet']}")
        bib_lines.append("")
    bibliography = "\n".join(bib_lines)

    sections_preview = "\n\n".join(s[:400] for s in sections[:4])
    exec_prompt = [
        {"role": "system", "content": (
            "Write a concise Executive Summary (200-300 words) for this research report. "
            "Highlight the 3-5 most important findings. Use bullet points. Be analytical. "
            "Return plain Markdown, starting with '## Résumé Exécutif'."
        )},
        {"role": "user", "content": (
            f"Research topic: {query}\n\n"
            f"Quality score: {score:.0%}\n\n"
            f"Report sections preview:\n{sections_preview}"
        )},
    ]
    try:
        exec_summary = await llm_call(exec_prompt, provider, model)
        if not exec_summary.strip().startswith("#"):
            exec_summary = f"## Résumé Exécutif\n\n{exec_summary.strip()}"
    except Exception as e:
        logger.warning("Executive summary generation failed: %s", e)
        exec_summary = f"## Résumé Exécutif\n\n*Rapport de recherche sur : {query}*"

    word_count = sum(len(s.split()) for s in sections)
    metrics_table = {
        "title": "Métriques de Recherche",
        "headers": ["Métrique", "Valeur"],
        "rows": [
            ["Score de qualité", f"{score:.0%}"],
            ["Sections générées", str(len(sections))],
            ["Sources collectées", str(len(numbered_sources))],
            ["Mots (~)", str(word_count)],
        ],
    }
    metrics_marker = f'__TABLE__{_json.dumps(metrics_table, ensure_ascii=False)}__TABLE__'

    report_parts = [
        f"# {query}",
        "",
        metrics_marker,
        "",
        toc,
        "",
        exec_summary,
        "",
        "---",
        "",
        "\n\n---\n\n".join(sections),
        "",
        "---",
        "",
        bibliography,
    ]
    return "\n".join(report_parts)


# ── 7. Mermaid Syntax Sanitizer ──────────────────────────────────────────────

import re as _re


def sanitize_mermaid_in_report(report_md: str) -> str:
    """Sanitize all mermaid code blocks in a report for valid syntax.

    Fixes common LLM generation issues:
    - HTML <br>, <br/> tags → spaces
    - Unquoted labels containing (), [], <>, / → quoted with ""
    - Invalid or unsupported diagram types → wrapped in warning
    """
    def _fix_block(match):
        code = match.group(1)
        # Strip HTML tags
        code = _re.sub(r'<br\s*/?>', ' ', code, flags=_re.IGNORECASE)
        code = _re.sub(r'</?[a-z][a-z0-9]*[^>]*>', '', code, flags=_re.IGNORECASE)
        # Auto-quote labels in square brackets with special chars
        code = _re.sub(
            r'(\w+)\[([^\]"]+[()/<>][^\]"]*)\]',
            lambda m: f'{m.group(1)}["{m.group(2).strip()}"]',
            code,
        )
        # Auto-quote labels in parentheses with special chars
        code = _re.sub(
            r'(\w+)\(([^)"]+[\[\]/<>][^)"]*)\)',
            lambda m: f'{m.group(1)}("{m.group(2).strip()}")',
            code,
        )
        # Remove self-referencing arrows
        code = _re.sub(
            r'^(\s*)(\w+)\s*(?:-->|==>|---|-.->)\s*\2\s*$',
            '', code, flags=_re.MULTILINE,
        )
        # Remove empty lines that resulted from cleanup
        code = _re.sub(r'\n{3,}', '\n\n', code)
        return f"```mermaid\n{code.strip()}\n```"

    return _re.sub(r'```mermaid\s*\n([\s\S]*?)```', _fix_block, report_md)


# ── 8. Iteration Merging (Cumulative Research) ──────────────────────────────

async def merge_iteration_findings(
    cumulative_findings: str,
    new_results: list[dict],
    new_branch_summaries: str,
    query: str,
    iteration_num: int,
    llm_call: LLMCallFn,
    provider: str = "",
    model: str = "",
) -> str:
    """Merge new iteration findings with existing cumulative knowledge.

    Instead of each iteration being independent, this function:
    1. Identifies what's genuinely NEW in the latest iteration
    2. Merges valuable new insights with existing findings
    3. Resolves contradictions between old and new data
    4. Produces an updated cumulative findings summary

    This ensures that each iteration BUILDS ON previous work rather than
    replacing it, leading to progressively better research output.
    """
    new_results_text = "\n".join(
        f"- [{r.get('source', 'web')}] {r.get('title', '')}: {r.get('snippet', '')[:200]}"
        for r in new_results[-30:]
    )[:3000]

    prompt = [
        {"role": "system", "content": (
            "You are a research synthesis specialist. Your task is to MERGE "
            "new research findings with existing accumulated knowledge.\n\n"
            "Rules:\n"
            "  1. KEEP everything valuable from the previous findings\n"
            "  2. ADD genuinely new insights from the latest iteration\n"
            "  3. RESOLVE contradictions — prefer the more recent/better-sourced info\n"
            "  4. REMOVE redundant/duplicate information\n"
            "  5. ORGANIZE by topic clusters for clarity\n"
            "  6. Maintain source attribution where possible\n\n"
            "Return a structured synthesis (800-1500 words) that represents "
            "the BEST of ALL iterations combined.\n"
            "Use clear headings (##) to organize topics."
        )},
        {"role": "user", "content": (
            f"Research topic: {query}\n"
            f"Iteration: {iteration_num}\n\n"
            f"=== EXISTING CUMULATIVE FINDINGS ===\n"
            f"{cumulative_findings[:4000]}\n\n"
            f"=== NEW RESEARCH (iteration {iteration_num}) ===\n"
            f"Branch summaries:\n{new_branch_summaries[:2000]}\n\n"
            f"New results:\n{new_results_text}\n\n"
            "Produce the MERGED cumulative findings, keeping the best of both."
        )},
    ]

    try:
        merged = await llm_call(prompt, provider, model)
        if merged and len(merged) > 100:
            logger.info(
                "Iteration %d findings merged: %d → %d chars",
                iteration_num, len(cumulative_findings), len(merged),
            )
            return merged
    except Exception as e:
        logger.warning("merge_iteration_findings failed: %s", e)

    # Fallback: concatenate
    return (
        cumulative_findings
        + f"\n\n---\n\n## Iteration {iteration_num} Findings\n\n"
        + new_branch_summaries[:2000]
    )

