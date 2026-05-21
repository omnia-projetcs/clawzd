"""
Clawzd — Chrome/Playwright browser automation engine.

Provides headless browser control for LLM-driven automation:
- Navigate to URLs
- Click elements, fill forms, scroll
- Extract text, attributes, HTML
- Take screenshots
- Wait for elements or network idle
- Execute JavaScript
- Run multi-step action sequences from a single tool call

The `execute_actions` function is the core entry point used by the
`browse_web` tool — it accepts a URL and a list of action dicts.
"""
import base64
import logging
import os
import uuid
from typing import Optional

from fastapi import APIRouter, Request, HTTPException

router = APIRouter()
logger = logging.getLogger("clawzd.browser")

_browser = None
_page = None
_playwright_instance = None  # Track Playwright instance for proper cleanup

# Maximum text size returned per action to avoid LLM context overflow
_MAX_TEXT = 8_000
# Maximum actions per sequence to prevent infinite loops
_MAX_ACTIONS = 20


# ---------------------------------------------------------------------------
# Browser lifecycle
# ---------------------------------------------------------------------------

async def _ensure_browser():
    """Lazy-initialize a persistent Playwright browser + page."""
    global _browser, _page, _playwright_instance
    if _browser is not None and _page is not None:
        return _page
    try:
        from playwright.async_api import async_playwright
        if _playwright_instance is None:
            _playwright_instance = await async_playwright().start()
        pw = _playwright_instance
        _browser = await pw.chromium.launch(headless=True)
        context = await _browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1920, "height": 1080},
        )
        _page = await context.new_page()
        logger.info("Playwright browser started")
        return _page
    except ImportError:
        raise HTTPException(
            500,
            "Playwright not installed. "
            "Run: pip install playwright && playwright install chromium",
        )


async def close_browser_instance():
    """Close the browser instance and free resources."""
    global _browser, _page, _playwright_instance
    if _page:
        try:
            await _page.close()
        except Exception:
            pass
        _page = None
    if _browser:
        try:
            await _browser.close()
        except Exception:
            pass
        _browser = None
    if _playwright_instance:
        try:
            await _playwright_instance.stop()
        except Exception:
            pass
        _playwright_instance = None


# ---------------------------------------------------------------------------
# Action execution engine — heart of the browser automation
# ---------------------------------------------------------------------------

async def execute_actions(
    url: str,
    actions: list[dict] | None = None,
    take_final_screenshot: bool = True,
) -> dict:
    """Execute a sequence of browser actions and return results.

    This is the main entry point for the `browse_web` tool.
    The LLM sends a URL and an optional list of action dicts.

    Supported action types:
        navigate    — Go to a URL                {action: "navigate", url: "..."}
        click       — Click an element           {action: "click", selector: "..."}
        type        — Type into a field           {action: "type", selector: "...", text: "..."}
        select      — Select dropdown option      {action: "select", selector: "...", value: "..."}
        scroll      — Scroll the page             {action: "scroll", direction: "down", amount: 500}
        wait        — Wait for element/time       {action: "wait", selector: "..." | time: 2}
        extract     — Extract text/HTML/attribute {action: "extract", selector: "...", attribute: "..."}
        screenshot  — Take a screenshot           {action: "screenshot"}
        evaluate    — Run JavaScript              {action: "evaluate", script: "..."}
        hover       — Hover over element          {action: "hover", selector: "..."}
        press       — Press a keyboard key        {action: "press", key: "Enter"}
        go_back     — Navigate back               {action: "go_back"}

    Returns:
        Dict with keys: url, title, text, screenshots, action_results.
    """
    from playwright.async_api import TimeoutError as PwTimeout

    page = await _ensure_browser()
    results = []
    screenshots = []

    # 1. Navigate to the URL
    if url:
        try:
            await page.goto(
                url, wait_until="domcontentloaded", timeout=25_000,
            )
        except PwTimeout:
            logger.warning("Navigation timeout for %s — continuing", url)

    # 2. Execute each action in sequence
    if actions:
        for i, action in enumerate(actions[:_MAX_ACTIONS]):
            action_type = action.get("action", "").lower()
            step_result = {"step": i + 1, "action": action_type}

            try:
                if action_type == "click":
                    sel = action.get("selector", "")
                    await page.click(sel, timeout=8_000)
                    step_result["status"] = "ok"
                    step_result["selector"] = sel

                elif action_type == "type":
                    sel = action.get("selector", "")
                    text = action.get("text", "")
                    clear = action.get("clear", True)
                    if clear:
                        await page.fill(sel, text, timeout=8_000)
                    else:
                        await page.type(sel, text, timeout=8_000)
                    step_result["status"] = "ok"
                    step_result["selector"] = sel

                elif action_type == "select":
                    sel = action.get("selector", "")
                    val = action.get("value", "")
                    await page.select_option(sel, val, timeout=8_000)
                    step_result["status"] = "ok"

                elif action_type == "scroll":
                    direction = action.get("direction", "down")
                    amount = int(action.get("amount", 500))
                    delta = amount if direction == "down" else -amount
                    await page.evaluate(f"window.scrollBy(0, {delta})")
                    step_result["status"] = "ok"

                elif action_type == "wait":
                    sel = action.get("selector", "")
                    wait_time = action.get("time", 0)
                    if sel:
                        await page.wait_for_selector(
                            sel, timeout=int(wait_time or 10) * 1_000,
                        )
                        step_result["status"] = "ok"
                        step_result["found"] = True
                    elif wait_time:
                        import asyncio
                        await asyncio.sleep(min(float(wait_time), 10))
                        step_result["status"] = "ok"

                elif action_type == "extract":
                    sel = action.get("selector", "body")
                    attr = action.get("attribute", "")
                    if attr == "html" or attr == "innerHTML":
                        content = await page.inner_html(
                            sel, timeout=5_000,
                        )
                    elif attr == "href" or attr:
                        content = await page.get_attribute(
                            sel, attr, timeout=5_000,
                        )
                    else:
                        content = await page.inner_text(
                            sel, timeout=5_000,
                        )
                    step_result["status"] = "ok"
                    step_result["content"] = (
                        str(content)[:_MAX_TEXT] if content else ""
                    )

                elif action_type == "screenshot":
                    sc = await _take_screenshot(page)
                    screenshots.append(sc)
                    step_result["status"] = "ok"
                    step_result["screenshot"] = sc["filename"]

                elif action_type == "evaluate":
                    script = action.get("script", "")
                    result = await page.evaluate(script)
                    step_result["status"] = "ok"
                    step_result["result"] = str(result)[:_MAX_TEXT]

                elif action_type == "hover":
                    sel = action.get("selector", "")
                    await page.hover(sel, timeout=5_000)
                    step_result["status"] = "ok"

                elif action_type == "press":
                    key = action.get("key", "Enter")
                    await page.keyboard.press(key)
                    step_result["status"] = "ok"

                elif action_type == "go_back":
                    await page.go_back(timeout=10_000)
                    step_result["status"] = "ok"

                elif action_type == "navigate":
                    nav_url = action.get("url", "")
                    if nav_url:
                        await page.goto(
                            nav_url,
                            wait_until="domcontentloaded",
                            timeout=25_000,
                        )
                    step_result["status"] = "ok"

                else:
                    step_result["status"] = "unknown_action"
                    step_result["error"] = (
                        f"Unknown action: {action_type}. "
                        "Supported: click, type, select, scroll, wait, "
                        "extract, screenshot, evaluate, hover, press, "
                        "go_back, navigate."
                    )

            except PwTimeout:
                step_result["status"] = "timeout"
                step_result["error"] = f"Timeout on {action_type}"
            except Exception as e:
                step_result["status"] = "error"
                step_result["error"] = str(e)[:500]

            results.append(step_result)

    # 3. Collect final page state
    try:
        title = await page.title()
    except Exception:
        title = ""

    try:
        text = await page.inner_text("body", timeout=5_000)
        text = text[:_MAX_TEXT]
    except Exception:
        text = ""

    # 4. Take a final screenshot if requested and no screenshot was taken
    if take_final_screenshot and not screenshots:
        try:
            sc = await _take_screenshot(page)
            screenshots.append(sc)
        except Exception as e:
            logger.warning("Final screenshot failed: %s", e)

    return {
        "status": "ok",
        "url": page.url,
        "title": title,
        "text": text,
        "screenshots": screenshots,
        "action_results": results,
        "actions_executed": len(results),
    }


async def _take_screenshot(page) -> dict:
    """Take a page screenshot and return path + base64."""
    from config import DATA_DIR

    sc_dir = os.path.join(DATA_DIR, "screenshots")
    os.makedirs(sc_dir, exist_ok=True)

    filename = f"browser_{uuid.uuid4().hex[:8]}.png"
    filepath = os.path.join(sc_dir, filename)

    await page.screenshot(path=filepath)

    with open(filepath, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()

    return {
        "filename": filename,
        "path": f"/data/screenshots/{filename}",
        "base64": b64[:200] + "..." if len(b64) > 200 else b64,
    }


# ---------------------------------------------------------------------------
# REST API endpoints (for direct calls from frontend / automation studio)
# ---------------------------------------------------------------------------

@router.post("/navigate")
async def api_navigate(request: Request):
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
async def api_click(request: Request):
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
async def api_type_text(request: Request):
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
async def api_extract_text(request: Request):
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
async def api_evaluate_js(request: Request):
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
async def api_page_screenshot(request: Request):
    """Take a screenshot of the current browser page."""
    page = await _ensure_browser()
    sc = await _take_screenshot(page)
    return {"status": "ok", **sc}


@router.post("/execute")
async def api_execute_actions(request: Request):
    """Execute a multi-step browser automation sequence.

    Body: { url: "...", actions: [...], screenshot: true }
    This is the REST equivalent of the browse_web tool.
    """
    data = await request.json()
    url = data.get("url", "")
    actions = data.get("actions", [])
    screenshot = data.get("screenshot", True)
    return await execute_actions(url, actions, take_final_screenshot=screenshot)


@router.post("/close")
async def api_close_browser():
    """Close the browser instance."""
    await close_browser_instance()
    return {"status": "closed"}
