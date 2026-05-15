"""
Clawzd — Research Brief Generator.
Inspired by open_deep_research's `write_research_brief` step (#6 on Deep Research Bench).

Before launching any search, transforms the raw user query into a structured
research brief that guides ALL subsequent steps with:
  - A reformulated, detailed research question
  - Key dimensions to cover
  - Preferred source types (academic, news, official docs, etc.)
  - Output language detection
  - Scope and time sensitivity assessment

This "brief-first" approach improves the relevance of perspective decomposition,
search queries, and the final report by providing a clear contract of what needs
to be researched.
"""
import logging
from typing import Callable, Awaitable

logger = logging.getLogger("clawzd.research.brief")

LLMCallFn = Callable[[list[dict], str, str], Awaitable[str]]


def _parse_json_block(text: str, fallback=None):
    """Safely extract a JSON object from LLM output."""
    import json
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except Exception:
            pass
    return fallback


async def generate_research_brief(
    query: str,
    llm_call: LLMCallFn,
    provider: str = "",
    model: str = "",
    context_messages: list[dict] | None = None,
) -> dict:
    """
    Transform a raw user query into a structured research brief.

    Inspired by open_deep_research's `transform_messages_into_research_topic_prompt`
    and `write_research_brief` node — the #1 lever for improving the relevance of
    ALL downstream research steps.

    Args:
        query: Raw user query or question.
        llm_call: Async LLM call function.
        provider / model: LLM routing parameters.
        context_messages: Optional prior conversation messages for context.

    Returns:
        Dict with:
          - research_brief: str — detailed, specific reformulation of the query
          - key_dimensions: list[str] — critical aspects to cover
          - preferred_sources: list[str] — source types to prioritise
          - output_language: str — detected language code (fr / en / etc.)
          - scope: str — "narrow" | "medium" | "broad"
          - time_sensitivity: str — "recent" | "historical" | "both"
          - specific_constraints: list[str] — explicit user constraints to respect
          - avoid: list[str] — topics/angles to avoid per user intent
    """
    context_text = ""
    if context_messages:
        context_text = "\n".join(
            f"{m.get('role', 'user').capitalize()}: {m.get('content', '')[:300]}"
            for m in context_messages[-5:]
        )

    prompt = [
        {"role": "system", "content": (
            "You are a research planning expert. Transform the user's query into "
            "a structured research brief that will guide an autonomous research agent.\n\n"
            "IMPORTANT GUIDELINES:\n"
            "1. Maximise SPECIFICITY — include all known user preferences and dimensions\n"
            "2. Fill UNSTATED dimensions as open-ended (don't invent constraints)\n"
            "3. Avoid UNWARRANTED assumptions — if unspecified, say so explicitly\n"
            "4. Detect the OUTPUT LANGUAGE from the query (fr, en, es, de, zh, etc.)\n"
            "5. For academic/scientific topics: prefer direct paper links, DOIs\n"
            "6. For product/travel: prefer official sites over aggregators\n"
            "7. For people: prefer LinkedIn, personal sites\n\n"
            "Return JSON:\n"
            '{"research_brief": "Detailed, specific reformulation of the query (2-4 sentences)", '
            '"key_dimensions": ["dimension 1", "dimension 2", ...], '
            '"preferred_sources": ["source type 1", ...], '
            '"output_language": "fr", '
            '"scope": "narrow|medium|broad", '
            '"time_sensitivity": "recent|historical|both", '
            '"specific_constraints": ["constraint 1", ...], '
            '"avoid": ["topic to avoid 1", ...]}\n\n'
            "Return ONLY valid JSON, no markdown fences."
        )},
        {"role": "user", "content": (
            f"User query: {query}\n"
            + (f"\nConversation context:\n{context_text}" if context_text else "")
            + "\n\nGenerate the structured research brief."
        )},
    ]

    try:
        text = await llm_call(prompt, provider, model)
        data = _parse_json_block(text, fallback={})
        if not isinstance(data, dict):
            data = {}

        # Detect language from query if LLM didn't provide it
        output_language = data.get("output_language", "")
        if not output_language:
            output_language = _detect_language_heuristic(query)

        brief = {
            "research_brief": data.get("research_brief", query),
            "key_dimensions": data.get("key_dimensions", []),
            "preferred_sources": data.get("preferred_sources", []),
            "output_language": output_language,
            "scope": data.get("scope", "medium"),
            "time_sensitivity": data.get("time_sensitivity", "both"),
            "specific_constraints": data.get("specific_constraints", []),
            "avoid": data.get("avoid", []),
            "_original_query": query,
        }

        logger.info(
            "Research brief generated: scope=%s lang=%s dims=%d",
            brief["scope"], brief["output_language"], len(brief["key_dimensions"]),
        )
        return brief

    except Exception as e:
        logger.warning("generate_research_brief failed: %s", e)
        return {
            "research_brief": query,
            "key_dimensions": [],
            "preferred_sources": [],
            "output_language": _detect_language_heuristic(query),
            "scope": "medium",
            "time_sensitivity": "both",
            "specific_constraints": [],
            "avoid": [],
            "_original_query": query,
        }


def _detect_language_heuristic(text: str) -> str:
    """
    Simple language detection heuristic based on common function words.
    Falls back to 'en' for unknown languages.
    """
    text_lower = text.lower()
    lang_indicators = {
        "fr": ["le ", "la ", "les ", "un ", "une ", "des ", "est ", "que ", "qui ",
               "pour ", "dans ", "avec ", "sur ", "comment ", "quoi ", "quel "],
        "es": ["el ", "la ", "los ", "las ", "un ", "una ", "es ", "que ", "para ",
               "con ", "en ", "como ", "cual ", "del "],
        "de": ["der ", "die ", "das ", "ein ", "eine ", "ist ", "mit ", "von ",
               "wie ", "was ", "und ", "oder ", "für "],
        "zh": ["的", "是", "在", "有", "和", "了", "不", "就"],
        "ja": ["の", "は", "が", "に", "を", "で", "と", "も"],
        "pt": ["de ", "da ", "do ", "um ", "uma ", "é ", "para ", "com ", "não "],
        "it": ["il ", "la ", "i ", "le ", "un ", "una ", "è ", "per ", "con "],
        "ar": ["في ", "من ", "على ", "إلى ", "عن ", "هذا ", "التي "],
    }
    scores = {lang: 0 for lang in lang_indicators}
    for lang, indicators in lang_indicators.items():
        scores[lang] = sum(text_lower.count(ind) for ind in indicators)

    best_lang = max(scores, key=lambda l: scores[l])
    if scores[best_lang] >= 2:
        return best_lang
    return "en"  # Default to English


def brief_to_planning_context(brief: dict) -> str:
    """
    Convert a research brief into a planning context string suitable for
    injection into the planning prompt of the research loop.

    This replaces the raw query in the planner's user message, providing
    richer context for action selection.
    """
    parts = [
        f"Research Brief: {brief.get('research_brief', '')}",
    ]
    if brief.get("key_dimensions"):
        dims = ", ".join(brief["key_dimensions"][:5])
        parts.append(f"Key Dimensions: {dims}")
    if brief.get("preferred_sources"):
        srcs = ", ".join(brief["preferred_sources"][:4])
        parts.append(f"Preferred Sources: {srcs}")
    if brief.get("time_sensitivity") and brief["time_sensitivity"] != "both":
        parts.append(f"Time Focus: {brief['time_sensitivity']} data")
    if brief.get("specific_constraints"):
        constraints = "; ".join(brief["specific_constraints"][:3])
        parts.append(f"Constraints: {constraints}")
    if brief.get("avoid"):
        avoid_list = ", ".join(brief["avoid"][:3])
        parts.append(f"Avoid: {avoid_list}")
    return "\n".join(parts)


async def check_research_clarity(
    query: str,
    llm_call: LLMCallFn,
    provider: str = "",
    model: str = "",
    allow_clarification: bool = True,
) -> dict:
    """
    Check whether a research query needs clarification before starting.

    Inspired by open_deep_research's `clarify_with_user` step. Returns
    a clarification question if the query is ambiguous, or a verification
    message if research can start immediately.

    Args:
        query: The raw user query.
        allow_clarification: If False, always returns needs_clarification=False.

    Returns:
        Dict with:
          - needs_clarification: bool
          - question: str — clarifying question to show the user (if needed)
          - verification: str — "starting research..." message (if not needed)
    """
    if not allow_clarification:
        return {
            "needs_clarification": False,
            "question": "",
            "verification": f"Lancement de la recherche sur : {query[:80]}...",
        }

    prompt = [
        {"role": "system", "content": (
            "Analyse whether this research query needs clarification before starting.\n\n"
            "ASK for clarification ONLY if:\n"
            "  - There are unexplained acronyms or highly ambiguous terms\n"
            "  - The scope is too vague to conduct meaningful research\n"
            "  - Multiple very different interpretations are equally likely\n\n"
            "Do NOT ask if the query is reasonably clear, even if imperfect.\n"
            "Do NOT ask a second time if a clarification was already provided.\n\n"
            "Return JSON:\n"
            '{"needs_clarification": false, '
            '"question": "", '
            '"verification": "I will now research: ..."}\n\n'
            "Return ONLY valid JSON, no markdown."
        )},
        {"role": "user", "content": f"Query: {query}"},
    ]

    try:
        text = await llm_call(prompt, provider, model)
        data = _parse_json_block(text, fallback={})
        if not isinstance(data, dict):
            data = {}

        return {
            "needs_clarification": bool(data.get("needs_clarification", False)),
            "question": data.get("question", ""),
            "verification": data.get(
                "verification",
                f"Starting research on: {query[:80]}...",
            ),
        }
    except Exception as e:
        logger.warning("check_research_clarity failed: %s", e)
        return {
            "needs_clarification": False,
            "question": "",
            "verification": f"Starting research on: {query[:80]}...",
        }
