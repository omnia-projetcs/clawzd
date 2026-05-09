"""
Clawzd — Simulated browser fallback (web_browser_simul).

Used when Playwright is not installed or the real browser fails.
Provides HTTP-based browsing using requests + BeautifulSoup to:
- Fetch and parse web pages
- Extract text, links, forms, tables
- Simulate form submissions
- Follow links

This is a *degraded* mode — no JavaScript execution, no real clicking,
no screenshots. But it allows browse_web to still function on servers
without a display or without Playwright/Chromium installed.
"""
import asyncio
import logging
import re
from typing import Optional
from urllib.parse import urljoin, urlparse

logger = logging.getLogger("clawzd.browser_simul")

_MAX_TEXT = 8_000
_MAX_ACTIONS = 20
_TIMEOUT = 15


# ---------------------------------------------------------------------------
# HTTP session (reusable across calls)
# ---------------------------------------------------------------------------

_session = None


def _get_session():
    """Get or create a requests Session with browser-like headers."""
    global _session
    if _session is None:
        import requests
        _session = requests.Session()
        _session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;"
                "q=0.9,image/webp,*/*;q=0.8"
            ),
            "Accept-Language": "en-US,en;q=0.9,fr;q=0.8",
        })
    return _session


# ---------------------------------------------------------------------------
# Page parser
# ---------------------------------------------------------------------------

class SimulatedPage:
    """Represents a fetched and parsed web page."""

    def __init__(self, url: str, html: str, status_code: int):
        from bs4 import BeautifulSoup

        self.url = url
        self.status_code = status_code
        self.html = html
        self.soup = BeautifulSoup(html, "html.parser")

    @property
    def title(self) -> str:
        tag = self.soup.find("title")
        return tag.get_text(strip=True) if tag else ""

    def extract_text(self, selector: str = "body") -> str:
        """Extract visible text from a CSS selector."""
        # Remove script and style elements for cleaner text
        for tag in self.soup.find_all(["script", "style", "noscript"]):
            tag.decompose()

        if selector == "body":
            el = self.soup.find("body")
        else:
            el = self.soup.select_one(selector)

        if not el:
            return ""

        text = el.get_text(separator="\n", strip=True)
        # Collapse excessive whitespace
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text[:_MAX_TEXT]

    def extract_links(self, limit: int = 20) -> list[dict]:
        """Extract links from the page."""
        links = []
        for a in self.soup.find_all("a", href=True)[:limit]:
            href = a["href"]
            if href.startswith("#") or href.startswith("javascript:"):
                continue
            full_url = urljoin(self.url, href)
            text = a.get_text(strip=True)[:100]
            links.append({"text": text, "url": full_url})
        return links

    def extract_forms(self) -> list[dict]:
        """Extract form structures from the page."""
        forms = []
        for form in self.soup.find_all("form")[:5]:
            fields = []
            for inp in form.find_all(["input", "textarea", "select"]):
                field = {
                    "tag": inp.name,
                    "type": inp.get("type", "text"),
                    "name": inp.get("name", ""),
                    "id": inp.get("id", ""),
                    "placeholder": inp.get("placeholder", ""),
                }
                if inp.name == "select":
                    field["options"] = [
                        opt.get("value", opt.get_text(strip=True))
                        for opt in inp.find_all("option")[:10]
                    ]
                fields.append(field)

            forms.append({
                "action": urljoin(self.url, form.get("action", "")),
                "method": form.get("method", "GET").upper(),
                "fields": fields,
            })
        return forms

    def extract_tables(self, limit: int = 3) -> list[dict]:
        """Extract HTML tables as structured data."""
        tables = []
        for table in self.soup.find_all("table")[:limit]:
            headers = []
            for th in table.find_all("th"):
                headers.append(th.get_text(strip=True))

            rows = []
            for tr in table.find_all("tr")[1:20]:  # Skip header row
                cells = [td.get_text(strip=True) for td in tr.find_all("td")]
                if cells:
                    rows.append(cells)

            if headers or rows:
                tables.append({"headers": headers, "rows": rows})
        return tables

    def extract_attribute(self, selector: str, attribute: str) -> str:
        """Extract an attribute from a CSS-selected element."""
        el = self.soup.select_one(selector)
        if not el:
            return ""
        return str(el.get(attribute, ""))[:_MAX_TEXT]

    def extract_html(self, selector: str) -> str:
        """Extract innerHTML of a CSS-selected element."""
        el = self.soup.select_one(selector)
        if not el:
            return ""
        return str(el)[:_MAX_TEXT]

    def find_link(self, text_or_selector: str) -> Optional[str]:
        """Find a link by partial text match or CSS selector."""
        # Try CSS selector first
        el = self.soup.select_one(text_or_selector)
        if el and el.get("href"):
            return urljoin(self.url, el["href"])

        # Try text match
        text_lower = text_or_selector.lower()
        for a in self.soup.find_all("a", href=True):
            if text_lower in a.get_text(strip=True).lower():
                return urljoin(self.url, a["href"])

        return None


# ---------------------------------------------------------------------------
# Main API — simul_browse (fallback for execute_actions)
# ---------------------------------------------------------------------------

async def simul_browse(
    url: str,
    actions: list[dict] | None = None,
) -> dict:
    """Simulated browsing via HTTP requests — fallback when Playwright unavailable.

    Supports a subset of browse_web actions:
    - navigate   → HTTP GET
    - extract    → BeautifulSoup text/html/attribute extraction
    - click      → follow link (if selector matches an <a>)
    - type/select → tracked for form submission simulation
    - wait       → asyncio.sleep

    Actions that require real JS (evaluate, screenshot, hover) return
    a degraded result with an explanation.
    """
    results = []
    page = None

    # 1. Fetch the initial URL
    if url:
        page = await _fetch_page(url)
        if not page:
            return {"error": f"Failed to fetch {url}", "simulated": True}

    # 2. Process actions
    if actions and page:
        form_data = {}  # Accumulate form fills for submission

        for i, action in enumerate(actions[:_MAX_ACTIONS]):
            action_type = action.get("action", "").lower()
            step = {"step": i + 1, "action": action_type, "simulated": True}

            try:
                if action_type == "navigate":
                    nav_url = action.get("url", "")
                    if nav_url:
                        page = await _fetch_page(nav_url)
                        step["status"] = "ok" if page else "error"

                elif action_type == "click":
                    sel = action.get("selector", "")
                    link = page.find_link(sel) if page else None
                    if link:
                        page = await _fetch_page(link)
                        step["status"] = "ok"
                        step["navigated_to"] = link
                    else:
                        step["status"] = "simulated"
                        step["note"] = (
                            "Click simulated — no matching link found. "
                            "JavaScript-dependent clicks require Playwright."
                        )

                elif action_type == "type":
                    sel = action.get("selector", "")
                    text = action.get("text", "")
                    name = action.get("name", sel)
                    form_data[name] = text
                    step["status"] = "ok"
                    step["note"] = "Value stored for form submission"

                elif action_type == "select":
                    sel = action.get("selector", "")
                    val = action.get("value", "")
                    form_data[sel] = val
                    step["status"] = "ok"

                elif action_type == "extract":
                    sel = action.get("selector", "body")
                    attr = action.get("attribute", "")
                    if attr == "html" or attr == "innerHTML":
                        content = page.extract_html(sel) if page else ""
                    elif attr:
                        content = page.extract_attribute(sel, attr)
                    else:
                        content = page.extract_text(sel) if page else ""
                    step["status"] = "ok"
                    step["content"] = content

                elif action_type == "wait":
                    wait_time = min(float(action.get("time", 1)), 5)
                    await asyncio.sleep(wait_time)
                    step["status"] = "ok"

                elif action_type in ("screenshot", "evaluate", "hover", "press"):
                    step["status"] = "unsupported"
                    step["note"] = (
                        f"'{action_type}' requires Playwright (real browser). "
                        "Install: pip install playwright && "
                        "playwright install chromium"
                    )

                elif action_type == "go_back":
                    step["status"] = "unsupported"
                    step["note"] = "Navigation history not available in simulated mode"

                else:
                    step["status"] = "unknown_action"

            except Exception as e:
                step["status"] = "error"
                step["error"] = str(e)[:300]

            results.append(step)

    # 3. Build response
    text = page.extract_text() if page else ""
    links = page.extract_links() if page else []
    forms = page.extract_forms() if page else []
    tables = page.extract_tables() if page else []

    response = {
        "status": "ok",
        "simulated": True,
        "url": page.url if page else url,
        "title": page.title if page else "",
        "text": text,
        "screenshots": [],  # Not available in simulated mode
        "action_results": results,
        "actions_executed": len(results),
        # Extra structured data (bonus of HTML parsing)
        "links": links[:15],
        "forms": forms,
        "tables": tables,
    }

    if not page:
        response["status"] = "error"
        response["error"] = "Failed to fetch page"

    return response


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _fetch_page(url: str) -> Optional[SimulatedPage]:
    """Fetch a URL and return a SimulatedPage, or None on failure."""

    def _do_fetch():
        try:
            session = _get_session()
            resp = session.get(url, timeout=_TIMEOUT, allow_redirects=True)
            return SimulatedPage(
                url=str(resp.url),
                html=resp.text,
                status_code=resp.status_code,
            )
        except Exception as e:
            logger.warning("simul_browse fetch failed for %s: %s", url, e)
            return None

    return await asyncio.to_thread(_do_fetch)
