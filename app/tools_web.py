"""
Clawzd — Web search tool using DuckDuckGo and Google Scholar.
"""
import asyncio
import urllib.request
import urllib.parse
from bs4 import BeautifulSoup
from fastapi import APIRouter

router = APIRouter()

def _scrape_scholar(query: str, max_results: int, base_url: str = "https://scholar.google.com/scholar") -> list:
    results = []
    try:
        url = f"{base_url}?hl=fr&q=" + urllib.parse.quote(query)
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })
        html = urllib.request.urlopen(req, timeout=10).read()
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
            })
    except Exception as e:
        print(f"Scholar scrape error for {base_url}: {e}")
    return results

def _do_search(query: str, max_results: int):
    results = []
    
    # Google Scholar normal
    scholar_res = _scrape_scholar(query, max_results)
    results.extend(scholar_res)
    
    # Google Scholar Labs
    labs_res = _scrape_scholar(query, max_results, base_url="https://scholar.google.com/scholar_labs/search")
    results.extend(labs_res)

    # DuckDuckGo fallback/general
    try:
        from ddgs import DDGS
        with DDGS() as ddgs:
            # We fetch up to max_results from DDG
            for r in ddgs.text(query, max_results=max_results):
                results.append({
                    "title": r.get("title", ""),
                    "snippet": r.get("body", ""),
                    "url": r.get("href", ""),
                })
    except Exception as e:
        print(f"DDGS error: {e}")
        
    return results[:max_results]

@router.get("/search")
async def search_web(query: str, max_results: int = 50):
    """Search the web using DuckDuckGo and Google Scholar, returning formatted results."""
    try:
        # Run blocking I/O in a separate thread to avoid blocking the event loop
        results = await asyncio.to_thread(_do_search, query, max_results)
    except Exception as e: # pylint: disable=broad-exception-caught
        return {"error": str(e), "results": []}
    return {"results": results}
