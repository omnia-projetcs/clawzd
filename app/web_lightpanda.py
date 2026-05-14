"""
Clawzd — Lightpanda headless browser fallback.

Inspired by https://github.com/lightpanda-io/browser

Lightpanda is an ultra-lightweight headless browser designed for AI
and automation.  It is used here as a **third-level fallback** when
both the DuckDuckGo API (ddgs) and Tavily fail to return results.

Capabilities:
  • Fetch any URL and dump it as Markdown (JS-rendered)
  • Scrape Bing search results via headless browser
  • Content-extract a page for downstream LLM consumption

The binary is auto-installed on first use from GitHub nightly releases.
"""
import asyncio
import logging
import os
import platform
import re
import stat
import subprocess
from urllib.parse import quote_plus, unquote

from config import DATA_DIR

logger = logging.getLogger("clawzd.lightpanda")

# ---------------------------------------------------------------------------
# Binary management
# ---------------------------------------------------------------------------

_BIN_DIR = os.path.join(DATA_DIR, "bin")
_BIN_PATH = os.path.join(_BIN_DIR, "lightpanda")

# Nightly release URLs by arch
_RELEASE_MAP = {
    ("Linux", "x86_64"): (
        "https://github.com/lightpanda-io/browser/releases"
        "/download/nightly/lightpanda-x86_64-linux"
    ),
    ("Linux", "aarch64"): (
        "https://github.com/lightpanda-io/browser/releases"
        "/download/nightly/lightpanda-aarch64-linux"
    ),
    ("Darwin", "arm64"): (
        "https://github.com/lightpanda-io/browser/releases"
        "/download/nightly/lightpanda-aarch64-macos"
    ),
    ("Darwin", "x86_64"): (
        "https://github.com/lightpanda-io/browser/releases"
        "/download/nightly/lightpanda-x86_64-macos"
    ),
}

# Subprocess timeout for fetch operations
_FETCH_TIMEOUT = 30
# Max text size for page content dumps
_MAX_TEXT = 12_000
# Larger limit for search result pages (need full HTML)
_MAX_TEXT_SEARCH = 50_000


def _resolve_download_url() -> str:
    """Pick the right nightly binary for the current OS/arch."""
    system = platform.system()        # Linux, Darwin
    machine = platform.machine()      # x86_64, aarch64, arm64
    key = (system, machine)
    url = _RELEASE_MAP.get(key)
    if not url:
        raise RuntimeError(
            f"No Lightpanda binary available for {system}/{machine}. "
            f"Supported: {list(_RELEASE_MAP.keys())}"
        )
    return url


async def _ensure_lightpanda_binary() -> str:
    """Download the Lightpanda binary if not already present.

    Returns the absolute path to the binary.  Thread-safe via
    asyncio.to_thread for the blocking download.
    """
    if os.path.isfile(_BIN_PATH) and os.access(_BIN_PATH, os.X_OK):
        return _BIN_PATH

    os.makedirs(_BIN_DIR, exist_ok=True)
    url = _resolve_download_url()
    logger.info("Downloading Lightpanda binary from %s …", url)

    def _download():
        import urllib.request
        urllib.request.urlretrieve(url, _BIN_PATH)
        # Make executable
        st = os.stat(_BIN_PATH)
        os.chmod(_BIN_PATH, st.st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        logger.info("Lightpanda binary installed at %s", _BIN_PATH)

    await asyncio.to_thread(_download)
    return _BIN_PATH


# ---------------------------------------------------------------------------
# Core fetch — runs `lightpanda fetch` as a subprocess
# ---------------------------------------------------------------------------

async def lightpanda_fetch(
    url: str,
    dump_format: str = "markdown",
    timeout: int = _FETCH_TIMEOUT,
    max_text: int = _MAX_TEXT,
) -> str:
    """Fetch a URL through Lightpanda and return the dumped content.

    Args:
        url: The page to fetch.
        dump_format: 'markdown' or 'html'.
        timeout: Max seconds to wait for the subprocess.
        max_text: Maximum characters to return.

    Returns:
        Extracted page content as a string, or empty on failure.
    """
    try:
        binary = await _ensure_lightpanda_binary()
    except Exception as e:
        logger.error("Lightpanda binary not available: %s", e)
        return ""

    cmd = [
        binary, "fetch",
        "--dump", dump_format,
        "--wait-until", "load",
        "--wait-ms", "3000",
        url,
    ]

    # Disable telemetry
    env = os.environ.copy()
    env["LIGHTPANDA_DISABLE_TELEMETRY"] = "true"

    try:
        proc = await asyncio.to_thread(
            subprocess.run,
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        if proc.returncode != 0:
            logger.warning(
                "Lightpanda fetch failed (rc=%d) for %s: %s",
                proc.returncode, url, (proc.stderr or "")[:300],
            )
            return ""
        return (proc.stdout or "")[:max_text]
    except subprocess.TimeoutExpired:
        logger.warning("Lightpanda fetch timed out for %s", url)
        return ""
    except Exception as e:
        logger.warning("Lightpanda fetch error for %s: %s", url, e)
        return ""


# ---------------------------------------------------------------------------
# Search — scrape Bing results via Lightpanda headless browser
# ---------------------------------------------------------------------------

def _parse_bing_markdown(md: str, max_results: int = 10) -> list[dict]:
    """Parse Bing search results from Lightpanda's markdown dump.

    Bing markdown structure per result:
      [domain.com](redirect_url)          ← domain link (skip)
      ## [Title](redirect_url)            ← real title (keep)
      description text line               ← snippet

    We target the ## heading links and extract the next paragraph as snippet.
    Results are deduplicated by resolved URL.
    """
    results = []
    seen_urls: set[str] = set()
    if not md:
        return results

    # Filter out Bing internal/navigation links
    _SKIP_DOMAINS = {
        "bing.com", "microsoft.com", "go.microsoft.com",
        "login.live.com", "account.live.com", "th.bing.com",
    }

    lines = md.split("\n")
    i = 0
    while i < len(lines) and len(results) < max_results:
        line = lines[i].strip()

        # Look specifically for ## [Title](url) headings
        heading_match = re.match(
            r'^##\s*\[([^\]]{3,})\]\((https?://[^\)]+)\)', line
        )
        if heading_match:
            title = heading_match.group(1).strip()
            raw_url = heading_match.group(2).strip()

            # Bing wraps URLs in redirect — extract the real URL
            real_url = _extract_bing_real_url(raw_url)

            # Skip Bing internal links
            try:
                from urllib.parse import urlparse
                domain = urlparse(real_url).netloc.lower()
                if any(skip in domain for skip in _SKIP_DOMAINS):
                    i += 1
                    continue
            except Exception:
                pass

            # Deduplicate by URL
            if real_url in seen_urls:
                i += 1
                continue
            seen_urls.add(real_url)

            # Clean up title: remove markdown bold markers
            title = title.replace("\\*\\*", "").replace("**", "")
            title = title.replace("\\(", "(").replace("\\)", ")")
            title = title.replace("\\-", "-").replace("\\!", "!")

            # Collect snippet from the next non-empty, non-link lines
            snippet_parts = []
            j = i + 1
            while j < len(lines) and j < i + 5:
                next_line = lines[j].strip()
                if not next_line:
                    j += 1
                    continue
                # Stop at next result or heading
                if next_line.startswith("#") or next_line.startswith("!["):
                    break
                if re.match(r'^\d+\.\s*$', next_line):  # Numbered list item
                    break
                # Skip lines that are just links or very short
                if next_line.startswith("[") and next_line.endswith(")"):
                    j += 1
                    continue
                if not next_line.startswith("http") and len(next_line) > 15:
                    # Clean markdown formatting
                    cleaned = next_line.replace("\\*\\*", "").replace("**", "")
                    cleaned = cleaned.replace("\\-", "-").replace("\\!", "!")
                    snippet_parts.append(cleaned)
                    break  # Take just the first real text line
                j += 1

            snippet = " ".join(snippet_parts)[:300]

            results.append({
                "title": title[:200],
                "snippet": snippet,
                "url": real_url,
                "source": "lightpanda_bing",
            })

        i += 1

    return results


def _parse_bing_html(html: str, max_results: int = 10) -> list[dict]:
    """Parse Bing search results from raw HTML using BeautifulSoup.

    Bing uses <li class="b_algo"> for organic results, each containing
    an <h2><a href="...">Title</a></h2> and a <p class="b_lineclamp*">
    for the snippet.
    """
    results = []
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")

        for block in soup.select("li.b_algo"):
            title_tag = block.select_one("h2 a")
            if not title_tag:
                continue

            href = title_tag.get("href", "")
            if not href or href.startswith("javascript:"):
                continue

            # Extract real URL from Bing redirect
            real_url = _extract_bing_real_url(href)

            title = title_tag.get_text(strip=True)

            # Find snippet
            snippet = ""
            for snippet_sel in [
                "p.b_lineclamp2", "p.b_lineclamp3", "p.b_lineclamp4",
                ".b_caption p", "p",
            ]:
                snippet_tag = block.select_one(snippet_sel)
                if snippet_tag:
                    snippet = snippet_tag.get_text(strip=True)
                    break

            results.append({
                "title": title[:200],
                "snippet": snippet[:300],
                "url": real_url,
                "source": "lightpanda_bing",
            })
            if len(results) >= max_results:
                break

    except Exception as e:
        logger.warning("Bing HTML parse error: %s", e)

    return results


def _extract_bing_real_url(url: str) -> str:
    """Extract the real URL from a Bing redirect wrapper."""
    if "bing.com/ck/a" in url:
        # Bing wraps URLs in base64-encoded redirect: &u=a1<base64>
        m = re.search(r"[&?]u=a1([^&]+)", url)
        if m:
            try:
                import base64
                decoded = base64.b64decode(m.group(1) + "==").decode(
                    "utf-8", errors="ignore"
                )
                if decoded.startswith("http"):
                    return decoded
            except Exception:
                pass
    return url


async def lightpanda_search(
    query: str,
    max_results: int = 10,
) -> list[dict]:
    """Search using Lightpanda to scrape Bing search results.

    This bypasses API-based search entirely — useful when the ddgs
    library and Tavily both fail.  Lightpanda renders the Bing results
    page (which is the most scraper-friendly major search engine).

    Returns a list of result dicts: {title, snippet, url, source}.
    """
    encoded_q = quote_plus(query)
    bing_url = f"https://www.bing.com/search?q={encoded_q}&mkt=en-US"

    # Strategy 1: Try markdown dump (faster, simpler parsing)
    raw_md = await lightpanda_fetch(
        bing_url, dump_format="markdown", max_text=_MAX_TEXT_SEARCH,
    )
    if raw_md:
        results = _parse_bing_markdown(raw_md, max_results)
        if results:
            logger.info(
                "Lightpanda Bing search (md): %d results for '%s'",
                len(results), query[:60],
            )
            return results

    # Strategy 2: Fallback to HTML dump (more reliable structure)
    raw_html = await lightpanda_fetch(
        bing_url, dump_format="html", max_text=_MAX_TEXT_SEARCH,
    )
    if raw_html:
        results = _parse_bing_html(raw_html, max_results)
        if results:
            logger.info(
                "Lightpanda Bing search (html): %d results for '%s'",
                len(results), query[:60],
            )
            return results

    logger.warning(
        "Lightpanda Bing scrape returned nothing for '%s'", query[:60]
    )
    return []


# ---------------------------------------------------------------------------
# Page content scraping — Lightpanda-based URL scraper
# ---------------------------------------------------------------------------

async def lightpanda_scrape(url: str) -> str:
    """Scrape a URL using Lightpanda, returning clean markdown text.

    This is a fallback for httpx-based scraping — Lightpanda executes
    JavaScript, so it works on SPAs and JS-heavy pages.
    """
    text = await lightpanda_fetch(url, dump_format="markdown")
    if not text:
        return ""

    # Light cleanup: remove excessive blank lines
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text.strip()[:8000]
