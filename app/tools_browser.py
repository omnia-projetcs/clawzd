"""
Clawzd — Chrome/Playwright browser automation skill.
Provides headless browser control: navigate, click, type, extract text, fill forms.
"""
import logging
from fastapi import APIRouter, Request, HTTPException

router = APIRouter()
logger = logging.getLogger("clawzd.browser")

_browser = None
_page = None


async def _ensure_browser():
    """Lazy-initialize a persistent Playwright browser + page."""
    global _browser, _page
    if _browser is not None and _page is not None:
        return _page
    try:
        from playwright.async_api import async_playwright
        pw = await async_playwright().start()
        _browser = await pw.chromium.launch(headless=True)
        context = await _browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080}
        )
        _page = await context.new_page()
        logger.info("Playwright browser started")
        return _page
    except ImportError:
        raise HTTPException(500, "Playwright not installed. Run: pip install playwright && playwright install chromium")


@router.post("/navigate")
async def navigate(request: Request):
    """Navigate to a URL and return page info."""
    data = await request.json()
    url = data.get("url", "")
    if not url:
        raise HTTPException(400, "URL is required")
    page = await _ensure_browser()
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    title = await page.title()
    return {"status": "ok", "url": page.url, "title": title}


@router.post("/click")
async def click(request: Request):
    """Click an element by CSS selector."""
    data = await request.json()
    selector = data.get("selector", "")
    if not selector:
        raise HTTPException(400, "Selector is required")
    page = await _ensure_browser()
    try:
        await page.click(selector, timeout=5000)
        return {"status": "ok", "selector": selector}
    except Exception as e:
        raise HTTPException(400, f"Click failed: {e}")


@router.post("/type")
async def type_text(request: Request):
    """Type text into an element by CSS selector."""
    data = await request.json()
    selector = data.get("selector", "")
    text = data.get("text", "")
    if not selector or not text:
        raise HTTPException(400, "Selector and text are required")
    page = await _ensure_browser()
    try:
        await page.fill(selector, text, timeout=5000)
        return {"status": "ok", "selector": selector}
    except Exception as e:
        raise HTTPException(400, f"Type failed: {e}")


@router.post("/extract")
async def extract_text(request: Request):
    """Extract text content from the current page or a specific selector."""
    data = await request.json()
    selector = data.get("selector", "body")
    page = await _ensure_browser()
    try:
        text = await page.inner_text(selector, timeout=5000)
        return {"status": "ok", "text": text[:10000]}
    except Exception as e:
        raise HTTPException(400, f"Extract failed: {e}")


@router.post("/evaluate")
async def evaluate_js(request: Request):
    """Execute JavaScript on the current page and return the result."""
    data = await request.json()
    script = data.get("script", "")
    if not script:
        raise HTTPException(400, "Script is required")
    page = await _ensure_browser()
    try:
        result = await page.evaluate(script)
        return {"status": "ok", "result": str(result)[:5000]}
    except Exception as e:
        raise HTTPException(400, f"Evaluate failed: {e}")


@router.post("/screenshot")
async def page_screenshot(request: Request):
    """Take a screenshot of the current browser page."""
    import base64, os, uuid
    from config import DATA_DIR
    page = await _ensure_browser()
    filepath = os.path.join(DATA_DIR, "screenshots", f"browser_{uuid.uuid4().hex[:8]}.png")
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    await page.screenshot(path=filepath)
    with open(filepath, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    return {"status": "ok", "path": filepath, "base64": b64}


@router.post("/close")
async def close_browser():
    """Close the browser instance."""
    global _browser, _page
    if _browser:
        await _browser.close()
        _browser = None
        _page = None
    return {"status": "closed"}
