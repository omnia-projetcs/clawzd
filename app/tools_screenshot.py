"""
Clawzd — Screenshot tool.
Captures local desktop or remote web pages via Playwright.
"""
import os
import uuid
import base64
import subprocess
from datetime import datetime
from fastapi import APIRouter, Request, HTTPException
from config import DATA_DIR

router = APIRouter()

SCREENSHOTS_DIR = os.path.join(DATA_DIR, "screenshots")
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)


@router.post("/local")
async def screenshot_local(request: Request):
    """Take a screenshot of the local desktop using scrot or gnome-screenshot."""
    filename = f"local_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.png"
    filepath = os.path.join(SCREENSHOTS_DIR, filename)
    # Try multiple screenshot tools
    for cmd in [
        ["scrot", filepath],
        ["gnome-screenshot", "-f", filepath],
        ["xfce4-screenshooter", "-f", "-s", filepath],
        ["import", "-window", "root", filepath],  # ImageMagick
    ]:
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=10)
            if result.returncode == 0 and os.path.exists(filepath):
                with open(filepath, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode()
                return {
                    "status": "ok",
                    "filename": filename,
                    "path": filepath,
                    "base64": b64,
                    "tool": cmd[0],
                }
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    raise HTTPException(500, "No screenshot tool available (install scrot, gnome-screenshot, or ImageMagick)")


@router.post("/remote")
async def screenshot_remote(request: Request):
    """Take a screenshot of a remote URL using Playwright."""
    data = await request.json()
    url = data.get("url", "")
    if not url:
        raise HTTPException(400, "URL is required")

    filename = f"remote_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.png"
    filepath = os.path.join(SCREENSHOTS_DIR, filename)

    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            page = await browser.new_page(viewport={"width": 1920, "height": 1080})
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await page.screenshot(path=filepath, full_page=data.get("full_page", False))
            await browser.close()

        with open(filepath, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        return {
            "status": "ok",
            "filename": filename,
            "path": filepath,
            "base64": b64,
            "url": url,
        }
    except ImportError:
        raise HTTPException(500, "Playwright not installed. Run: pip install playwright && playwright install chromium")
    except Exception as e:
        raise HTTPException(500, f"Screenshot failed: {e}")
