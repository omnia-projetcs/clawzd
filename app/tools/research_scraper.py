"""
Clawzd — Research Smart Scraper.
Intelligent web scraping with LLM-guided content extraction
and parallel batch processing. Inspired by GPT-Researcher's
approach to maximizing content relevance from web sources.
"""
import asyncio
import logging

logger = logging.getLogger("clawzd.research.scraper")


async def smart_scrape(
    url: str,
    query: str,
    scrape_fn,
    llm_call,
    provider: str = "",
    model: str = "",
) -> dict:
    """
    Scrape a URL and use LLM to extract content relevant to the query.
    Returns a dict with url, raw_text, relevant_extract, and key_facts.
    """
    raw_text = await scrape_fn(url)
    if not raw_text or len(raw_text.strip()) < 100:
        return {"url": url, "raw_text": "", "relevant_extract": "", "key_facts": []}

    # Use LLM to extract relevant information
    extract = await extract_relevant_content(
        raw_text, query, llm_call, provider, model,
    )

    return {
        "url": url,
        "raw_text": raw_text[:5000],
        "relevant_extract": extract.get("extract", ""),
        "key_facts": extract.get("key_facts", []),
    }


async def extract_relevant_content(
    text: str,
    query: str,
    llm_call,
    provider: str = "",
    model: str = "",
) -> dict:
    """
    Use LLM to extract the most relevant content from scraped text
    relative to the research query. Inspired by GPT-Researcher's
    approach to source summarization.
    """
    import json

    prompt = [
        {"role": "system", "content": (
            "You are a research data extractor. Given raw web page content "
            "and a research query, extract ONLY the relevant information.\n\n"
            "Return JSON:\n"
            '{"extract": "Relevant text summary (300-500 words)", '
            '"key_facts": ["fact 1", "fact 2", ...], '
            '"relevance_score": 0.0-1.0}\n\n'
            "Rules:\n"
            "- Ignore navigation, ads, boilerplate\n"
            "- Focus on facts, data, statistics\n"
            "- Preserve exact numbers and dates\n"
            "- Note the author/source if visible\n"
            "Return ONLY valid JSON, no markdown."
        )},
        {"role": "user", "content": (
            f"Research query: {query}\n\n"
            f"Raw content (truncated):\n{text[:4000]}"
        )},
    ]
    result_text = await llm_call(prompt, provider, model)

    # Parse JSON response
    try:
        start = result_text.find("{")
        end = result_text.rfind("}")
        if start != -1 and end != -1:
            data = json.loads(result_text[start:end + 1])
            return {
                "extract": data.get("extract", text[:500]),
                "key_facts": data.get("key_facts", []),
                "relevance_score": data.get("relevance_score", 0.5),
            }
    except Exception:
        pass

    # Fallback: return truncated raw text
    return {"extract": text[:500], "key_facts": [], "relevance_score": 0.3}


async def batch_scrape(
    urls: list[str],
    query: str,
    scrape_fn,
    llm_call,
    provider: str = "",
    model: str = "",
    max_concurrent: int = 5,
) -> list[dict]:
    """
    Scrape multiple URLs in parallel with concurrency control.
    Each result is enriched with LLM-extracted relevant content.
    """
    semaphore = asyncio.Semaphore(max_concurrent)

    async def _bounded_scrape(url: str) -> dict:
        async with semaphore:
            try:
                return await smart_scrape(
                    url, query, scrape_fn, llm_call, provider, model,
                )
            except Exception as e:
                logger.warning("Batch scrape failed for %s: %s", url, e)
                return {
                    "url": url, "raw_text": "",
                    "relevant_extract": "", "key_facts": [],
                }

    tasks = [_bounded_scrape(u) for u in urls]
    results = await asyncio.gather(*tasks)
    # Filter out empty results
    return [r for r in results if r.get("relevant_extract")]
