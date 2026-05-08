"""
Clawzd — Deep Research Engine.
Core functions for advanced research: perspective-guided question decomposition
(STORM), recursive deep research branches (GPT-Researcher), structured
multi-criteria evaluation, inter-iteration reflection, and citation-tracked
report generation. No external dependencies beyond the existing LLM provider.
"""
import json
import asyncio
import logging
from typing import Callable, Awaitable

logger = logging.getLogger("clawzd.research.engine")

# Type alias for the LLM call function passed in from tools_research
LLMCallFn = Callable[[list[dict], str, str], Awaitable[str]]


def _parse_json_block(text: str, fallback=None):
    """Safely extract a JSON object or array from LLM output."""
    # Try array first
    start_arr = text.find("[")
    end_arr = text.rfind("]")
    start_obj = text.find("{")
    end_obj = text.rfind("}")
    candidates = []
    if start_arr != -1 and end_arr > start_arr:
        candidates.append((start_arr, end_arr + 1))
    if start_obj != -1 and end_obj > start_obj:
        candidates.append((start_obj, end_obj + 1))
    for s, e in sorted(candidates, key=lambda x: x[0]):
        try:
            return json.loads(text[s:e])
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
                f"Given research on a topic, identify {breadth} specific "
                "sub-topics that need deeper investigation.\n"
                "Return a JSON array of short topic strings.\n"
                "Return ONLY valid JSON, no markdown."
            )},
            {"role": "user", "content": (
                f"Main query: {query}\n"
                f"Current topic: {topic}\n"
                f"Findings summary: {summary[:1000]}\n\n"
                f"Identify {breadth} sub-topics for deeper research."
            )},
        ]
        st_text = await llm_call(subtopics_prompt, provider, model)
        sub_topics = _parse_json_block(st_text, fallback=[])
        if not isinstance(sub_topics, list):
            sub_topics = []
        sub_topics = [t for t in sub_topics if isinstance(t, str)][:breadth]

        # Research sub-topics in parallel
        if sub_topics:
            sub_tasks = [
                deep_research_branch(
                    st, query, depth - 1, breadth,
                    search_fn, scrape_fn, llm_call,
                    provider, model, emit_fn,
                )
                for st in sub_topics
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
) -> str:
    """Generate a report with inline citations [1][2] and numbered bibliography."""
    # Build numbered source list
    seen_urls = set()
    numbered_sources = []
    for r in results:
        url = r.get("url", "")
        if url and url not in seen_urls and not url.startswith("rag://"):
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
            "Report structure:\n"
            "1. Table of Contents\n"
            "2. Executive Summary (with key metrics table)\n"
            "3. Introduction & Context (with concept mindmap)\n"
            "4. Analysis sections with evidence & diagrams\n"
            "5. Key Findings with proof & comparison tables\n"
            "6. Conclusion & Recommendations\n"
            "7. Bibliography [1]-[N]\n"
        )},
        {"role": "user", "content": (
            f"# Research Topic: {query}\n\n"
            f"## Research Perspectives\n{perspectives_text}\n\n"
            f"## Deep Research Summaries\n{branch_summaries[:6000]}\n\n"
            f"## Numbered Sources\n{sources_text[:8000]}\n\n"
            f"## Evidence & Experimental Data\n{evidence_text}\n\n"
            f"## Downloaded Assets\n{assets_text}\n\n"
            f"## Research Metrics\n"
            f"- Quality Score: {score:.0%}\n"
            f"- Iterations: {num_iterations}\n"
            f"- Sources collected: {len(numbered_sources)}\n\n"
            "Generate the full research report with inline citations, "
            "evidence blocks, and rich diagrams."
        )},
    ]
    report = await llm_call(prompt, provider, model)

    # Append bibliography if not already included
    if "## Bibliography" not in report and "## Bibliographie" not in report:
        bib = "\n\n---\n\n## Bibliography\n\n"
        for s in numbered_sources:
            bib += f"[{s['id']}] {s['title']} — {s['url']}\n\n"
        report += bib

    return report
