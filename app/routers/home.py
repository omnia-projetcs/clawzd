"""
Clawzd — Home / index route.
Extracted from gateway.
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from config import TEMPLATES_DIR, HUGGINGFACE_API_KEY, OPENAI_API_KEY, APP_VERSION, API_SECRET_TOKEN

router = APIRouter()
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Serve the main application page."""
    has_hf_token = bool(HUGGINGFACE_API_KEY)
    has_openai_key = bool(OPENAI_API_KEY)
    
    context = {
        "request": request,
        "has_hf_token": has_hf_token,
        "has_openai_key": has_openai_key,
        "has_cloud_media_api": has_hf_token or has_openai_key,
        "app_version": APP_VERSION,
    }
    response = templates.TemplateResponse(request=request, name="index.html", context=context)
    if API_SECRET_TOKEN:
        response.set_cookie(
            key="api_secret_token",
            value=API_SECRET_TOKEN,
            httponly=True,
            samesite="lax",
            secure=False,
        )
    return response
