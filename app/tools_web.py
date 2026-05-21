"""
Clawzd — Web search tool using DuckDuckGo and Google Scholar.

Priority order:
  1. DuckDuckGo (general / news / current results)
  2. Google Scholar (academic complement)

Results are deduplicated by URL and returned in a unified format.
"""
import asyncio
import logging
import urllib.request
import urllib.parse
from bs4 import BeautifulSoup
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

logger = logging.getLogger("clawzd.web")

router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic model for POST body
# ---------------------------------------------------------------------------

class SearchRequest(BaseModel):
    query: str
    max_results: int = 10


# ---------------------------------------------------------------------------
# DuckDuckGo search (primary — general / news)
# ---------------------------------------------------------------------------

def _search_ddg(query: str, max_results: int) -> list:
    """Search DuckDuckGo for general web results."""
    results = []
    try:
        from ddgs import DDGS
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                results.append({
                    "title": r.get("title", ""),
                    "snippet": r.get("body", ""),
                    "url": r.get("href", ""),
                    "source": "ddg",
                })
    except Exception as e:
        logger.warning("DuckDuckGo search error: %s", e)
    return results


# ---------------------------------------------------------------------------
# Google Scholar scraping (secondary — academic)
# ---------------------------------------------------------------------------

def _scrape_scholar(
    query: str,
    max_results: int,
    base_url: str = "https://scholar.google.com/scholar",
) -> list:
    """Scrape Google Scholar for academic results."""
    results = []
    try:
        url = f"{base_url}?hl=fr&q=" + urllib.parse.quote(query)
        req = urllib.request.Request(url, headers={
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/120.0.0.0 Safari/537.36'
            ),
        })
        html = urllib.request.urlopen(req, timeout=8).read()
        soup = BeautifulSoup(html, "html.parser")

        for r in soup.find_all('div', class_='gs_ri')[:max_results]:
            title_tag = r.find('h3')
            title = title_tag.text if title_tag else "No title"
            link_tag = title_tag.find('a') if title_tag else None
            link = link_tag['href'] if link_tag and 'href' in link_tag.attrs else url
            snippet_tag = r.find('div', class_='gs_rs')
            snippet = snippet_tag.text if snippet_tag else ""

            results.append({
                "title": f"[Scholar] {title}",
                "snippet": snippet,
                "url": link,
                "source": "scholar",
            })
    except Exception as e:
        logger.warning("Scholar scrape error for %s: %s", base_url, e)
    return results


# ---------------------------------------------------------------------------
# Unified search (DDG first, Scholar complement, dedup)
# ---------------------------------------------------------------------------

def _do_search(query: str, max_results: int) -> list:
    """Execute a web search across multiple engines.

    Order: DuckDuckGo (general) → Google Scholar (academic complement).
    Results are deduplicated by URL.
    """
    seen_urls: set[str] = set()
    results: list[dict] = []

    def _add_unique(items: list[dict]):
        for item in items:
            url = item.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                results.append(item)

    # 1. DuckDuckGo — primary source (general, news, current)
    ddg_results = _search_ddg(query, max_results)
    _add_unique(ddg_results)
    logger.info("DDG returned %d results for '%s'", len(ddg_results), query[:60])

    # 2. Lightpanda headless browser — fallback if DDG returned nothing
    if not ddg_results:
        try:
            from app.web_lightpanda import lightpanda_search
            logger.info("DDG empty → trying Lightpanda headless fallback for '%s'", query[:60])
            lp_results = await lightpanda_search(query, max_results)
            _add_unique(lp_results)
            logger.info("Lightpanda returned %d results", len(lp_results))
        except Exception as e:
            logger.warning("Lightpanda fallback failed: %s", e)

    # 3. Google Scholar — complement (academic)
    #    Only fetch a small number to avoid overwhelming general results
    scholar_limit = min(max_results // 3, 5)
    if scholar_limit > 0:
        scholar_res = _scrape_scholar(query, scholar_limit)
        _add_unique(scholar_res)
        logger.info("Scholar returned %d results", len(scholar_res))

    if not results:
        logger.warning("No results from any search engine for: %s", query[:80])

    return results[:max_results]


# ---------------------------------------------------------------------------
# API endpoints (GET + POST for compatibility)
# ---------------------------------------------------------------------------

@router.get("/search")
async def search_web(query: str, max_results: int = 10):
    """Search the web using DuckDuckGo + Google Scholar (GET)."""
    try:
        results = await asyncio.to_thread(_do_search, query, max_results)
    except Exception as e:
        logger.error("search_web GET error: %s", e)
        return {"error": str(e), "results": []}
    return {"results": results}


@router.post("/search")
async def search_web_post(req: SearchRequest):
    """Search the web using DuckDuckGo + Google Scholar (POST)."""
    try:
        results = await asyncio.to_thread(_do_search, req.query, req.max_results)
    except Exception as e:
        logger.error("search_web POST error: %s", e)
        return {"error": str(e), "results": []}
    return {"results": results}
