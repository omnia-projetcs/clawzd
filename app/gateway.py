"""
Clawzd — FastAPI application gateway.
Main router that wires all modules together and handles chat streaming.

STATUS: Historical monolith under migration (see REFACTOR_PLAN.md).
- New routers go in app/routers/
- Legacy tool routers (app/tools_*.py) still wired for compatibility
- Middleware and core app setup remain here for now
"""
import asyncio
import logging
import os
import time
import uuid
import warnings

# Suppress Hugging Face transformers Siglip2ImageProcessorFast deprecation warnings
warnings.filterwarnings("ignore", message=".*Siglip2ImageProcessor.*")

from fastapi import FastAPI, Request, HTTPException, Form, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from jinja2 import Environment, FileSystemLoader
from fastapi.templating import Jinja2Templates
from sse_starlette.sse import EventSourceResponse
from datetime import datetime, timezone

from app.core.database import (
    init_db, create_session, get_session, add_message, get_messages,
    auto_title,
)
from app.core.llm_provider import get_llm_provider, _get_provider_models
from app.core.preprompts import get_preprompt, get_jailbreak_wrapper
from app.chat import router as chat_router
from app.profiles import router as profiles_router
from app.routers.code import router as code_router, executor
from app.routers.web import router as web_router
from app.routers.local import router as local_router
from app.routers.quality import router as quality_router
from app.ai_models.rag import router as rag_router
from app.improvement import router as improvement_router
from app.routers.agent import router as agent_router
from app.routers.home import router as home_router
from app.core.settings import router as settings_router
from app.routers.screenshot import router as screenshot_router
from app.routers.image import router as image_router
from app.routers.audio import router as audio_router
from app.routers.audio_lab import router as audio_lab_router
from app.routers.voice_rtvi import router as voice_rtvi_router
from app.routers.system import router as system_router
from app.routers.arena import router as arena_router
from app.routers.chat import router as chat_extra_router
from app.routers.browser import router as browser_router
from app.routers.cron import router as cron_router
from app.routers.skills import router as skills_router
from app.routers.document import router as document_router
from app.integrations_telegram import router as telegram_router
from app.skills.selector import select_skills
from app.skills.registry import get_registry
from app.ai_models.manager import router as models_router
from app.core.compression import optimize_for_provider
from app.routers.presentation import router as presentation_router
from app.routers.presentation_video import router as presentation_video_router
from app.routers.automation import router as automation_router
from app.routers.clone import router as clone_router
from app.routers.docgen import router as docgen_router
from app.routers.studio_editor import router as studio_editor_router
from app.tools.executor import parse_tool_calls, execute_tool, format_tool_result, resolve_tool_name
from app.core.tool_permissions import (
    get_tool_permission, request_approval,
)
from app.core.metrics import get_metrics
from app.cache import cache_stats
from app.core.tokens import count_tokens, count_message_tokens
from config import STATIC_DIR, TEMPLATES_DIR, DATA_DIR, CORS_ORIGINS, RATE_LIMIT, APP_VERSION, OLLAMA_VERIFY_SSL, API_SECRET_TOKEN

import re as _re
import json as _json
import base64 as _b64
import httpx
import uuid as _uuid

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("websockets").setLevel(logging.WARNING)
logging.getLogger("websockets.server").setLevel(logging.WARNING)

class PollingEndpointFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        if "/image/download-status" in msg or "/notifications" in msg or "/api/tasks/active" in msg:
            return False
        return True

logging.getLogger("uvicorn.access").addFilter(PollingEndpointFilter())

logger = logging.getLogger("clawzd.gateway")

# Regex to strip base64 data URIs from text (images bloat LLM context)
_BASE64_RE = _re.compile(r'!\[[^\]]*\]\(data:image/[^)]+\)', _re.DOTALL)

# Regex to strip HTML tags from user input (XSS prevention)
_HTML_TAG_RE = _re.compile(r'<[^>]+>', _re.DOTALL | _re.IGNORECASE)


def _strip_base64(text: str) -> str:
    """Remove inline base64 image data from text to reduce LLM context size."""
    return _BASE64_RE.sub('[image displayed to user]', text)


def _sanitize_input(text: str) -> str:
    """Sanitize user input by removing all HTML tags.
    
    Note: We keep angle brackets for code generation (LLMs need <tag> syntax)
    but strip actual HTML tags to prevent stored XSS.
    """
    # Remove HTML tags but preserve angle brackets used in code
    # This prevents XSS while allowing LLMs to generate code with <html> tags
    return _HTML_TAG_RE.sub('', text)


# --- App Setup ---
app = FastAPI(title="Clawzd", version="2.0")

# --- CORS Middleware ---
# SECURITY: Never use allow_origins=["*"] with allow_credentials=True.
# FastAPI will reject this combination, so we default to localhost only.
_cors_origins = CORS_ORIGINS if CORS_ORIGINS else ["http://localhost:3000", "http://localhost:5173"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Rate Limiting ---
try:
    from slowapi import Limiter
    from slowapi.util import get_remote_address
    from slowapi.errors import RateLimitExceeded

    limiter = Limiter(key_func=get_remote_address, default_limits=[RATE_LIMIT])
    app.state.limiter = limiter

    @app.exception_handler(RateLimitExceeded)
    async def _rate_limit_handler(request: Request, exc: RateLimitExceeded):
        return JSONResponse(
            status_code=429,
            content={"error": "Rate limit exceeded. Please slow down."},
        )
    logger.info("Rate limiting enabled: %s", RATE_LIMIT)
except ImportError:
    limiter = None
    logger.warning("slowapi not installed — rate limiting disabled")

# --- Authentication Middleware (SEC-2 fix) ---
_PUBLIC_PATHS = {"/", "/health", "/docs", "/openapi.json", "/redoc"}
_PUBLIC_PREFIXES = ("/static/", "/data/", "/stream/")

@app.middleware("http")
async def _auth_middleware(request: Request, call_next):
    """Enforce Bearer token auth on API endpoints when API_SECRET_TOKEN is set."""
    if API_SECRET_TOKEN:
        path = request.url.path
        # Skip auth for public routes, static files, and SSE streams
        if path not in _PUBLIC_PATHS and not any(path.startswith(p) for p in _PUBLIC_PREFIXES):
            auth_header = request.headers.get("Authorization", "")
            token = ""
            if auth_header.startswith("Bearer "):
                token = auth_header[7:]
            else:
                token = request.cookies.get("api_secret_token", "")
            
            if token != API_SECRET_TOKEN:
                return JSONResponse(status_code=401, content={"error": "Unauthorized — set Authorization: Bearer <token>"})
    return await call_next(request)

# --- Request Timing, Tracing & Security Middleware ---
@app.middleware("http")
async def _timing_middleware(request: Request, call_next):
    """Record request latency, inject tracing request-id and COOP/COEP headers."""
    # FEAT-8: Inject request-id for traceability
    request_id = request.headers.get("X-Request-ID", _uuid.uuid4().hex[:12])
    t0 = time.perf_counter()
    response = await call_next(request)
    latency = time.perf_counter() - t0
    get_metrics().record_request(
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        latency_s=latency,
    )
    # Enable SharedArrayBuffers for StackBlitz WebContainer API
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Cross-Origin-Embedder-Policy"] = "require-corp"
    response.headers["X-Request-ID"] = request_id
    return response
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Serve screenshots and generated images as static files
import os as _os
_screenshots_dir = _os.path.join(DATA_DIR, "screenshots")
_images_dir = _os.path.join(DATA_DIR, "images")
_documents_dir = _os.path.join(DATA_DIR, "documents")
_os.makedirs(_screenshots_dir, exist_ok=True)
_os.makedirs(_images_dir, exist_ok=True)
_audio_dir = _os.path.join(DATA_DIR, "audio")
_os.makedirs(_documents_dir, exist_ok=True)
_os.makedirs(_audio_dir, exist_ok=True)
app.mount("/data/screenshots", StaticFiles(directory=_screenshots_dir), name="screenshots")
app.mount("/data/images", StaticFiles(directory=_images_dir), name="images")
app.mount("/data/documents", StaticFiles(directory=_documents_dir), name="documents")
app.mount("/data/audio", StaticFiles(directory=_audio_dir), name="audio")
_audio_lab_dir = _os.path.join(DATA_DIR, "audio_lab")
_os.makedirs(_audio_lab_dir, exist_ok=True)
app.mount("/data/audio-lab", StaticFiles(directory=_audio_lab_dir), name="audio_lab")
_video_dir = _os.path.join(DATA_DIR, "media", "video")
_os.makedirs(_video_dir, exist_ok=True)
app.mount("/data/media/video", StaticFiles(directory=_video_dir), name="video")
_research_dir = _os.path.join(DATA_DIR, "research")
_os.makedirs(_research_dir, exist_ok=True)
app.mount("/data/research", StaticFiles(directory=_research_dir), name="research")

jinja_env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), cache_size=0)
templates = Jinja2Templates(env=jinja_env)

# --- Track background tasks for graceful shutdown (BUG-4) ---
_background_tasks: list[asyncio.Task] = []

# --- Initialize database and skill registry on startup ---
@app.on_event("startup")
async def startup():
    init_db()

    # Auto-discover and register plugins
    try:
        from app.core.plugin_system import discover_plugins, run_hook_register_routes
        n = discover_plugins("app/plugins")
        if n:
            run_hook_register_routes(app)
            logger.info("Plugin system: %d plugin(s) loaded", n)
    except Exception as exc:
        logger.warning("Plugin discovery failed: %s", exc)

    # Initialize upload store
    try:
        from app.core.upload_store import init_store
        init_store(DATA_DIR)
        logger.info("Upload store initialized")
    except Exception as exc:
        logger.warning("Upload store init failed: %s", exc)

    # Load dynamic skills from data/skills/
    registry = get_registry()
    count = registry.load_all()
    logger.info("Clawzd v2.0 started — %d dynamic skill(s) loaded", count)

    from app.mcp_tool import mcp_manager
    _background_tasks.append(asyncio.create_task(mcp_manager.connect_all()))

    # Start Discord bot if configured
    import os
    if os.getenv("DISCORD_BOT_TOKEN"):
        from app.integrations_discord import start_discord_bot
        _background_tasks.append(asyncio.create_task(start_discord_bot()))
        logger.info("Discord bot starting...")

    # Start automation background listeners (Discord/Telegram/Cron triggers)
    from app.tools_automation import start_automation_listeners
    _background_tasks.append(asyncio.create_task(start_automation_listeners()))
    logger.info("Automation listeners starting...")

    # Start skill rebuilder background maintenance (lifecycle transitions)
    from app.skills.rebuilder import start_maintenance_task
    start_maintenance_task()
    logger.info("Skill rebuilder maintenance loop started")

    # Scan RAG folder for documents to index
    try:
        from app.ai_models.rag import scan_rag_folder
        rag_report = await asyncio.to_thread(scan_rag_folder)
        added = len(rag_report.get('added', []))
        updated = len(rag_report.get('updated', []))
        if added or updated:
            logger.info("RAG folder scan: %d new, %d updated documents indexed", added, updated)
        else:
            logger.info("RAG folder scan: no new documents")
    except Exception as e:
        logger.warning("RAG folder scan skipped: %s", e)

    # Start daily memory optimization loop
    async def run_daily_optimization():
        from app.core.memory import optimize_memory_files
        while True:
            await asyncio.sleep(24 * 3600)
            try:
                await optimize_memory_files()
            except Exception as e:
                logger.error("Daily memory optimization failed: %s", e)

    _background_tasks.append(asyncio.create_task(run_daily_optimization()))

    # FEAT-6: Daily database backup with rotation
    async def run_daily_backup():
        from app.core.database import backup_database
        # Run initial backup on startup (deferred by 60s to avoid startup congestion)
        await asyncio.sleep(60)
        try:
            result = await asyncio.to_thread(backup_database)
            if result.get("status") == "ok":
                logger.info("Startup DB backup: %s", result["backup_path"])
        except Exception as e:
            logger.warning("Startup DB backup failed: %s", e)
        # Then repeat daily
        while True:
            await asyncio.sleep(24 * 3600)
            try:
                result = await asyncio.to_thread(backup_database)
                if result.get("status") == "ok":
                    logger.info("Daily DB backup: %s", result["backup_path"])
            except Exception as e:
                logger.error("Daily DB backup failed: %s", e)

    _background_tasks.append(asyncio.create_task(run_daily_backup()))

    # PERF-3: Periodic cleanup of stale SSE sessions (every 5 minutes)
    async def _cleanup_stale_sessions():
        while True:
            await asyncio.sleep(300)
            stale_count = 0
            for sid in list(_cancelled_sessions):
                _cancelled_sessions.discard(sid)
                stale_count += 1
            if stale_count:
                logger.debug("Cleaned up %d stale cancelled session(s)", stale_count)

    _background_tasks.append(asyncio.create_task(_cleanup_stale_sessions()))


# --- Graceful shutdown (BUG-4 fix) ---
@app.on_event("shutdown")
async def shutdown():
    """Cancel background tasks and cleanup resources on server shutdown."""
    logger.info("Shutting down — cancelling %d background task(s)...", len(_background_tasks))
    for task in _background_tasks:
        if not task.done():
            task.cancel()
    # Wait for generation tasks to complete (max 10s)
    for sid, task in list(_generation_tasks.items()):
        if not task.done():
            logger.info("Waiting for generation %s to complete...", sid)
            try:
                await asyncio.wait_for(task, timeout=10)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                logger.warning("Generation %s timed out during shutdown", sid)
    # Cleanup SSE queues
    _sse_queues.clear()
    _arena_queues.clear()
    _active_generations.clear()
    _cancelled_sessions.clear()
    _generation_tasks.clear()
    logger.info("Shutdown complete")

# --- Include sub-routers ---
app.include_router(chat_router, prefix="/chat")
app.include_router(profiles_router, prefix="/profile")
app.include_router(code_router, prefix="/code")
app.include_router(web_router, prefix="/web")
app.include_router(local_router, prefix="/local")
app.include_router(quality_router, prefix="/quality")
app.include_router(rag_router, prefix="/rag")
app.include_router(improvement_router, prefix="/improve")
app.include_router(agent_router, prefix="/agent")
app.include_router(settings_router, prefix="/api")
from app.core.memory import router as memory_router
app.include_router(memory_router, prefix="/api")
app.include_router(screenshot_router, prefix="/screenshot")
app.include_router(image_router, prefix="/image")
app.include_router(audio_router, prefix="/audio")
app.include_router(audio_lab_router, prefix="/audio-lab")
app.include_router(voice_rtvi_router)
app.include_router(system_router)  # health, metrics, token-usage, tokenize (extracted from gateway)
app.include_router(arena_router)  # arena/send, arena/stream, arena/evaluate (extracted)
app.include_router(chat_extra_router, prefix="")  # /chat/upload-image, /chat/humanize (extracted; paths preserved)
app.include_router(home_router)  # home page extracted


app.include_router(browser_router, prefix="/browser")
app.include_router(cron_router, prefix="/cron")
app.include_router(skills_router, prefix="/skills")
app.include_router(document_router, prefix="/document")
app.include_router(telegram_router, prefix="/telegram")
app.include_router(models_router, prefix="/models")
app.include_router(presentation_router, prefix="/presentation")
app.include_router(presentation_video_router, prefix="/presentation")
app.include_router(automation_router, prefix="/automation")
app.include_router(clone_router, prefix="/clone")
app.include_router(docgen_router, prefix="/docgen")
app.include_router(studio_editor_router, prefix="/studio")

from app.routers.research import router as research_router
app.include_router(research_router, prefix="/research")

from app.routers.workspace import router as workspace_router
app.include_router(workspace_router, prefix="/workspace")

from app.routers.workspace_git import router as workspace_git_router
from app.routers.files import router as files_router
app.include_router(workspace_git_router, prefix="/workspace")
app.include_router(files_router)  # preview + export-zip (extracted from monolithic gateway)

from app.routers.autocomplete import router as autocomplete_router
app.include_router(autocomplete_router, prefix="/api")

from app.routers.artifacts_api import router as artifacts_api_router
app.include_router(artifacts_api_router)

from app.routers.apps_api import router as apps_api_router
app.include_router(apps_api_router, prefix="/apps")

from app.routers.misc_api import router as misc_api_router
app.include_router(misc_api_router, prefix="/api")
# local/run needs its own mount (no /api prefix)
from fastapi import APIRouter as _MiscLocalRouter
_local_router = _MiscLocalRouter()
@_local_router.post("/local/run")
async def _local_run_proxy(request: Request):
    from app.routers.misc_api import local_run
    return await local_run(request)
app.include_router(_local_router)

from app.tools.task_manager import router as task_manager_router
app.include_router(task_manager_router, prefix="/api")

from app.routers.twitter import router as twitter_router
app.include_router(twitter_router, prefix="/twitter")

from app.routers.project import router as project_router
app.include_router(project_router, prefix="/project")

from app.routers.spec import router as spec_router
app.include_router(spec_router, prefix="/spec")

# Agent dispatch (multi-agent orchestration)
from app.routers.agent_dispatch import router as agent_dispatch_router
app.include_router(agent_dispatch_router, prefix="/agents")

# Playbook engine (multi-step workflow automation)
from app.playbook_engine import router as playbook_router
app.include_router(playbook_router, prefix="/playbook")

# Enhance Prompt (Roo Code-inspired prompt refinement)
from app.routers.enhance import router as enhance_router
app.include_router(enhance_router, prefix="/api")

# OpenAI-Compatible API (inference endpoint for external tools)
from app.routers.openai_api import router as openai_api_router
app.include_router(openai_api_router, prefix="/v1")

# Analytics Dashboard (fleet overview + charts)
from app.routers.dashboard import router as dashboard_analytics_router
app.include_router(dashboard_analytics_router, prefix="/dashboard")

# WebDev Studio Workspace Sync
from app.routers.webdev_sync import router as webdev_sync_router
app.include_router(webdev_sync_router, prefix="/api/webdev")

# --- In-memory SSE queues per session ---
_sse_queues: dict[str, asyncio.Queue] = {}
# _arena_queues moved to app/routers/arena.py
_active_generations: dict[str, str] = {}
_cancelled_sessions: set[str] = set()
_generation_tasks: dict[str, asyncio.Task] = {}


# NOTE: home page moved to app/routers/home.py


# --- Health Check ---
# NOTE: /health, /api/metrics, /api/token-usage, /api/tokenize/prefetch
# have been extracted to app/routers/system.py (included above).
# --- SSE streaming endpoint ---
@app.get("/stream/{session_id}")
async def chat_stream(session_id: str):
    """Server-Sent Events endpoint for streaming LLM responses."""
    if session_id not in _sse_queues:
        _sse_queues[session_id] = asyncio.Queue()

    async def event_generator():
        queue = _sse_queues[session_id]
        while True:
            token = await queue.get()
            if token is None:
                yield {"data": "[DONE]"}
                break
            yield {"data": token}

    return EventSourceResponse(event_generator())


# --- Stop generation endpoint ---
@app.post("/stop/{session_id}")
async def stop_generation(session_id: str):
    """Cancel an active generation for a session."""
    _cancelled_sessions.add(session_id)
    # Force-close the SSE queue to signal [DONE]
    if session_id in _sse_queues:
        try:
            await _sse_queues[session_id].put(None)
        except Exception:
            pass
    return {"status": "stopped", "session_id": session_id}


# ---------------------------------------------------------------------------
# Suggested Responses (Roo Code-inspired follow-up chips)
# ---------------------------------------------------------------------------

_SUGGESTION_SYSTEM = (
    "You generate 2-3 SHORT follow-up questions/actions the user might want next, "
    "based on the assistant's last response. "
    "Reply with ONLY a JSON array of strings, nothing else. "
    "Each suggestion must be under 60 characters, actionable, and in the SAME language as the response. "
    "Example: [\"Explain this in more detail\",\"Show me an example\",\"How do I test this?\"]"
)


async def _generate_suggestions(
    assistant_response: str, provider_key: str, model_key: str = ""
) -> list[str]:
    """Generate 2-3 follow-up suggestion chips from the assistant's response."""
    # Only suggest for substantial responses (skip short/error ones)
    if len(assistant_response.strip()) < 80:
        return []

    # Use the tail of the response to stay within token limits
    tail = assistant_response[-1500:] if len(assistant_response) > 1500 else assistant_response

    try:
        provider = get_llm_provider(provider_key)
        messages = [
            {"role": "system", "content": _SUGGESTION_SYSTEM},
            {"role": "user", "content": f"Generate follow-up suggestions for this response:\n\n{tail}"},
        ]
        kwargs = {}
        if model_key:
            kwargs["model"] = model_key

        raw = await provider.chat(messages, **kwargs)
        raw = raw.strip()

        # Extract JSON array
        import json as _json
        # Handle cases where model wraps in markdown code block
        if "```" in raw:
            import re
            match = re.search(r'\[.*?\]', raw, re.DOTALL)
            if match:
                raw = match.group(0)

        suggestions = _json.loads(raw)
        if isinstance(suggestions, list) and all(isinstance(s, str) for s in suggestions):
            return suggestions[:3]
    except Exception:
        pass
    return []


# --- Send message (shared logic) ---
async def _process_chat(session_id: str, data: dict) -> dict:
    """Core chat processing shared by HTTP POST and WebSocket handlers."""
    user_msg = _sanitize_input(data.get("message", "").strip())
    if not user_msg:
        raise HTTPException(400, "Message is required")

    # Per-request provider/model/preprompt override
    provider_key = data.get("provider")
    model_key = data.get("model")
    preprompt_key = data.get("preprompt")
    active_project = data.get("active_project", ".")
    active_file = data.get("active_file")
    rag_mode = data.get("rag_mode", False)

    # Vision chat: extract uploaded images (data URLs)
    chat_images = data.get("images", [])  # list of data URLs

    # Ensure session exists
    session = get_session(session_id)
    if not session:
        # Auto-create if missing
        create_session(
            session_id,
            provider=provider_key or "local",
            model=model_key or "",
            preprompt=preprompt_key or "none",
        )
        session = get_session(session_id)

        # --- Plugin hook: on_session_create ---
        try:
            from app.core.plugin_system import run_hook
            run_hook("on_session_create", {
                "session_id": session_id,
                "provider": provider_key or "local",
                "model": model_key or "",
            })
        except Exception:
            pass  # Plugin hooks are non-critical

    # Use session defaults if not overridden per-request
    provider_key = provider_key or session.get("provider", "local")
    model_key = model_key or session.get("model", "")
    preprompt_key = preprompt_key or session.get("preprompt", "none")

    # Save user message (text only in DB — images are transient per-request)
    add_message(session_id, "user", user_msg)

    # Auto-title from first message
    messages = get_messages(session_id)
    user_messages = [m for m in messages if m["role"] == "user"]
    if len(user_messages) == 1:
        auto_title(session_id, user_msg)

    # Build messages for the LLM
    llm_messages = []
    system_prompt = get_preprompt(preprompt_key, model=model_key, user_query=user_msg)
    
    # Inject dynamic setting for autonomy
    if system_prompt:
        from app.settings import load_settings
        settings = load_settings()
        req_confirm = settings.get("require_command_confirmation", True)

        # Handle action_mode (auto / step-by-step)
        action_mode = data.get("action_mode", "none")
        if action_mode == "auto":
            system_prompt += "\n\nCRITICAL: AUTO MODE is active. You MUST be extremely proactive and autonomous. DO NOT ask the user for permission. DO NOT present plans or numbered lists. JUST DO IT. Execute tools directly and deliver results immediately."
        elif action_mode == "step-by-step":
            system_prompt += "\n\nCRITICAL: STEP-BY-STEP MODE is active. Before executing anything, you MUST first present a clear, numbered plan of all steps you will take. Then STOP and wait for the user to confirm (e.g., 'OK', 'go ahead', 'proceed'). Only after confirmation should you execute the plan step by step, reporting progress at each step."
        elif not req_confirm:
            system_prompt += "\n\nCRITICAL: The user has DISABLED command confirmation in settings. You MUST be extremely proactive and autonomous. DO NOT ask the user for permission to proceed. DO NOT output numbered lists of steps you plan to take. JUST DO IT. Use tools directly to create files and run commands."
        else:
            system_prompt += "\n\nCRITICAL: The user has ENABLED command confirmation in settings. While you should still use tools, if an operation is highly destructive or risky, you must ask the user for permission before proceeding."

        context_str = f"\n\nCURRENT EDITOR CONTEXT:\n- Active Project Path: {active_project}\n"
        if active_file:
            context_str += f"- Active File: {active_file}\n"
        context_str += "- IMPORTANT: When using tools (edit_file, read_file, run_command, etc.) for this project, always prefix file paths with the Active Project Path if it's not '.'! (e.g. use edit_file with file_path='project_name/file.py' or run_command with 'cat project_name/TODO.md')\n"
        system_prompt += context_str

    if system_prompt:
        llm_messages.append({"role": "system", "content": system_prompt})
    for i, m in enumerate(messages):
        is_last_user_msg = (i == len(messages) - 1 and m["role"] == "user")

        # Apply L1B3RT4S jailbreak wrapper to the last user message if jailbreak mode is active
        if preprompt_key == "jailbreak" and is_last_user_msg:
            wrapped_content = get_jailbreak_wrapper(model_key, m["content"], provider_key)
            llm_messages.append({"role": m["role"], "content": wrapped_content})
        elif is_last_user_msg and chat_images:
            # Vision chat: build multimodal content with text + images
            content_parts = [{"type": "text", "text": m["content"]}]
            for img_url in chat_images:
                if isinstance(img_url, str) and img_url.startswith("data:"):
                    content_parts.append({
                        "type": "image_url",
                        "image_url": {"url": img_url},
                    })
            llm_messages.append({"role": m["role"], "content": content_parts})
        else:
            llm_messages.append({"role": m["role"], "content": m["content"]})

    # --- Agent dispatch: detect and inject specialized agent prompt ---
    active_agent = "none"
    try:
        from app.agent_dispatch import detect_agent, get_agent_system_prompt, get_max_tool_rounds, is_tool_allowed
        agent_key = data.get("agent") or detect_agent(user_msg)
        agent_prompt = get_agent_system_prompt(agent_key)
        if agent_prompt and agent_key != "orchestrator":
            active_agent = agent_key
            # Merge agent prompt into system prompt
            if llm_messages and llm_messages[0]["role"] == "system":
                llm_messages[0]["content"] += "\n\n" + agent_prompt
            else:
                llm_messages.insert(0, {"role": "system", "content": agent_prompt})
    except Exception:
        pass  # Agent dispatch is non-critical

    # --- RAG: explicit mode or auto-inject knowledge base context ---
    try:
        if rag_mode:
            # Explicit RAG mode — user wants to search the knowledge base
            from app.ai_models.rag import explicit_rag_search
            # Strip @rag prefix if present
            rag_query = user_msg
            if rag_query.lower().startswith("@rag"):
                rag_query = rag_query[4:].strip()
            rag_context = explicit_rag_search(rag_query, k=5)
            if rag_context:
                llm_messages.insert(-1, {"role": "system", "content": rag_context})
        else:
            # Auto-RAG: silently inject if relevant context exists
            from app.ai_models.rag import auto_rag_context
            rag_context = auto_rag_context(user_msg)
            if rag_context:
                llm_messages.insert(-1, {"role": "system", "content": rag_context})
    except Exception:
        pass  # RAG injection is non-critical

    # --- Plugin hook: before_prompt_build ---
    try:
        from app.core.plugin_system import run_hook
        _sys_content = llm_messages[0]["content"] if llm_messages and llm_messages[0]["role"] == "system" else ""
        hook_ctx = run_hook("before_prompt_build", {
            "system_prompt": _sys_content,
            "user_message": user_msg,
            "session_id": session_id,
            "provider": provider_key,
            "model": model_key,
            "detected_skills": [],
        })
        if hook_ctx.get("system_prompt") != _sys_content and llm_messages and llm_messages[0]["role"] == "system":
            llm_messages[0]["content"] = hook_ctx["system_prompt"]
    except Exception:
        pass  # Plugin hooks are non-critical

    # Inject Structured UI component schemas (cloud providers only — local models
    # have limited context and can't handle the extra instructions well)
    if provider_key not in ("local", "ollama"):
        try:
            from app.core.structured_ui import get_component_prompt
            _ui_prompt = get_component_prompt()
            if llm_messages and llm_messages[0]["role"] == "system":
                llm_messages[0]["content"] += "\n\n" + _ui_prompt
        except Exception:
            pass  # Non-critical

    # Auto-detect relevant skills (builtin + dynamic) and inject hint.
    # Only skills above the confidence threshold are injected — we never
    # pollute the prompt with hundreds of irrelevant skills.
    detected = []
    if preprompt_key != "jailbreak":
        detected = select_skills(user_msg, top_k=5, min_confidence=0.25)

        # --- Semantic intent classification (language-agnostic) ---
        # Use a fast LLM call to detect which tools are genuinely needed,
        # regardless of the user's language. This replaces brittle keyword lists.
        try:
            from app.skills.intent_classifier import classify_intent
            semantic_tools = await asyncio.wait_for(classify_intent(user_msg), timeout=3.0)
            detected_names = {d["skill"] for d in detected}
            for tool_name in semantic_tools:
                if tool_name not in detected_names:
                    detected.insert(0, {"skill": tool_name, "confidence": 0.95, "source": "semantic"})
                    detected_names.add(tool_name)
        except asyncio.TimeoutError:
            logger.warning("Intent classifier timed out (3s) — skipping semantic routing")
        except Exception as _ic_err:
            logger.debug("Intent classifier unavailable: %s", _ic_err)


        # Merge manually activated skills from the catalog (always injected)
        try:
            from app.skills.registry import load_active_skills
            pinned_names = load_active_skills()
            detected_names = {d["skill"] for d in detected}
            for pname in pinned_names:
                if pname not in detected_names:
                    detected.append({"skill": pname, "confidence": 1.0, "source": "catalog"})
        except Exception:
            pass  # Catalog injection is non-critical

        # --- Plugin hook: after_skill_detect ---
        try:
            from app.core.plugin_system import run_hook
            _skill_ctx = run_hook("after_skill_detect", {
                "detected_skills": detected,
                "user_message": user_msg,
                "session_id": session_id,
            })
            detected = _skill_ctx.get("detected_skills", detected)
        except Exception:
            pass  # Plugin hooks are non-critical
            
    if detected:
        from app.skills.selector import get_skill_catalog_entry, get_skill_full_instructions

        # For local provider with small ctx, use fewer tools
        is_local = (provider_key in ("local", "ollama"))
        if is_local:
            detected = detected[:2]  # max 2 tools for small context

        if is_local:
            # --- LOCAL PROVIDERS: Direct full injection (small models need it) ---
            # Keep full tool_call examples so 7B-9B models can use them correctly.
            parts = []
            for d in detected:
                parts.append(get_skill_full_instructions(d["skill"]))

            hint = (
                "## Tools\n"
                "Use ```tool_call blocks when relevant. Do NOT refuse if a tool can help.\n\n"
                + "\n".join(parts)
            )
        else:
            # --- CLOUD PROVIDERS: Lightweight catalog (lazy skill loading) ---
            # Only inject names + short descriptions (~80 tokens vs ~750).
            # The LLM already knows the tool_call format from the system prompt
            # and can emit correct calls from the name alone.
            catalog_lines = [get_skill_catalog_entry(d["skill"]) for d in detected]

            hint = (
                "## Available Tools\n"
                "When a tool is needed, emit a tool_call block:\n"
                '```tool_call\n{"tool":"<name>","params":{...}}\n```\n\n'
                + "\n".join(catalog_lines)
            )

            logger.debug(
                "Lazy skill loading: injected %d catalog entries (%d chars) instead of full instructions",
                len(catalog_lines), len(hint),
            )

        # Merge into existing system prompt (Mixtral only supports one system message)
        if llm_messages and llm_messages[0]["role"] == "system":
            llm_messages[0]["content"] += "\n\n" + hint
        else:
            llm_messages.insert(0, {"role": "system", "content": hint})

        # Inject compact typed schemas for detected tools (cloud providers only).
        # This gives the LLM exact parameter names/types/defaults so it emits
        # correct tool_call JSON on the first try.
        if not is_local and detected:
            try:
                from app.tools.contracts import get_compact_schemas
                detected_names = [d["skill"] for d in detected]
                compact = get_compact_schemas(detected_names)
                if compact:
                    if llm_messages and llm_messages[0]["role"] == "system":
                        llm_messages[0]["content"] += "\n\n## Tool Schemas\n" + compact
            except Exception:
                pass  # Schema injection is non-critical

    # Apply context compression for long conversations (AFTER tool hints so they get compressed too)
    llm_messages = await optimize_for_provider(llm_messages, provider_key)

    # Detect if user is asking to continue a previous response
    _continue_words = {"continue", "continuer", "continues", "suite", "go on", "keep going", "poursuit", "poursuis"}
    if user_msg.lower().strip().rstrip(".!") in _continue_words:
        # Find the last assistant message and inject it as context
        assistant_msgs = [m for m in messages if m["role"] == "assistant"]
        if assistant_msgs:
            last_resp = assistant_msgs[-1]["content"]
            # Take the last 2000 chars to give the LLM context of where it stopped
            tail = last_resp[-2000:] if len(last_resp) > 2000 else last_resp
            # Replace the user message in llm_messages with a continuation prompt
            for i in range(len(llm_messages) - 1, -1, -1):
                if llm_messages[i]["role"] == "user" and llm_messages[i]["content"].lower().strip().rstrip(".!") in _continue_words:
                    llm_messages[i]["content"] = (
                        f"Your previous response was cut off. Here is how it ended:\n\n"
                        f"```\n...{tail[-800:]}\n```\n\n"
                        f"Please continue EXACTLY from where you stopped. "
                        f"Do NOT repeat what was already written. "
                        f"Start your response with the continuation of the code or text."
                    )
                    break

    # Ensure SSE queue exists
    if session_id not in _sse_queues:
        _sse_queues[session_id] = asyncio.Queue()

    # Maximum number of tool-call rounds to avoid infinite loops
    # Dynamically adjusted per-agent via get_max_tool_rounds()
    try:
        _agent_max_rounds = get_max_tool_rounds(active_agent)
    except Exception:
        _agent_max_rounds = 15
    MAX_TOOL_ROUNDS = _agent_max_rounds
    # Maximum auto-continuation rounds for truncated responses
    # IDE mode needs more rounds for complex multi-step coding tasks
    MAX_CONTINUATION_ROUNDS = 10 if preprompt_key in ("ide_developer", "ide_planner") else 5
    # Maximum total output characters to prevent runaway generation
    MAX_TOTAL_OUTPUT = 250_000

    def _is_truncated(text: str) -> bool:
        """Detect if a response was truncated mid-output.

        Checks for unclosed code fences (odd number of ```) which indicates
        the LLM hit its token limit while generating code.
        Also detects IDE-specific truncation: unclosed <thought> tags,
        unclosed XML tool blocks, and interrupted tool_call JSON.
        """
        stripped = text.rstrip()
        if not stripped:
            return False

        # If the response contains LLM stop tokens, it completed normally
        stop_markers = ["<|endoftext|>", "<|im_start|>", "<|im_end|>",
                        "<|eot_id|>", "</s>", "<|end|>"]
        tail = stripped[-200:]
        if any(marker in tail for marker in stop_markers):
            return False

        # Unclosed code fences (odd ```) — always truncated
        fence_count = text.count("```")
        if fence_count % 2 != 0:
            return True

        # IDE-specific: unclosed <thought> or <antThinking> tags
        import re as _trunc_re
        for tag in ['thought', 'antThinking']:
            opens = len(_trunc_re.findall(rf'<{tag}>', stripped, _trunc_re.IGNORECASE))
            closes = len(_trunc_re.findall(rf'</{tag}>', stripped, _trunc_re.IGNORECASE))
            if opens > closes:
                return True

        # IDE-specific: unclosed tool_call JSON block (opening { without closing })
        # Pattern: ```tool_call\n{"tool":... without closing ``` 
        tool_fence_re = _trunc_re.compile(
            r'```(?:tool_call|tool|json)\s*\n', _trunc_re.IGNORECASE
        )
        tool_fences = list(tool_fence_re.finditer(stripped))
        if tool_fences:
            last_tool_start = tool_fences[-1].end()
            after_last = stripped[last_tool_start:]
            if '```' not in after_last:
                # Unclosed tool_call fence
                return True

        # IDE-specific: unclosed XML tool blocks (e.g. <edit_file> without </edit_file>)
        xml_tools = ['edit_file', 'write_file', 'read_file', 'run_command',
                     'execute_python', 'grep_code', 'list_files', 'apply_patch']
        for tool in xml_tools:
            opens_t = stripped.count(f'<{tool}>')
            closes_t = stripped.count(f'</{tool}>')
            if opens_t > closes_t:
                return True

        if len(stripped) < 200:
            return False

        # Trailing blank lines with no other signals indicate natural end
        if text.endswith("\n\n") or text.endswith("\n"):
            return False

        # Mid-sentence check — conservative to avoid false positives.
        # Only trigger for longer responses that clearly end mid-word.
        if len(stripped) > 4000:
            last_char = stripped[-1]
            # Allow letters, digits, punctuation, markdown, emoji, etc.
            if last_char not in '.!?\n`>)]}"\':;-—…*#|0123456789':
                # Double-check: if last line is short, it's likely a natural end
                last_line = stripped.split("\n")[-1]
                if len(last_line.strip()) > 40:
                    return True
        return False

    # --- Doom-loop detection (inspired by OpenMonoAgent) ---
    # Track the last 3 tool call sequences; if all 3 are identical, abort.
    _recent_tool_sequences: list[str] = []

    # Launch background generation task
    async def generate():
        queue = _sse_queues[session_id]
        current_messages = list(llm_messages)  # mutable copy
        full_conversation = ""  # everything sent to the user across all rounds
        _active_generations[session_id] = full_conversation
        round_num = 0

        try:
            provider = get_llm_provider(provider_key)
            kwargs = {}
            if model_key:
                kwargs["model"] = model_key

            while round_num < MAX_TOOL_ROUNDS:
                round_num += 1
                round_response = ""
                _finished_normally = False  # True when provider signals finish_reason=stop

                t0_llm = time.perf_counter()

                # Import the sentinel from the provider module
                from app.core.llm_provider import FINISH_STOP_SENTINEL

                # Stream the LLM response for this round
                async for token in provider.chat_stream(current_messages, **kwargs):
                    # Check for cancellation
                    if session_id in _cancelled_sessions:
                        _cancelled_sessions.discard(session_id)
                        logger.info("Generation cancelled by user for session %s", session_id)
                        full_conversation += "\n\n*⏹️ Generation stopped by user.*"
                        await queue.put(None)
                        return
                    # Intercept the finish sentinel (not a real token)
                    if token == FINISH_STOP_SENTINEL:
                        _finished_normally = True
                        continue
                    # Filter out LLM stop/control tokens
                    if any(m in token for m in ["<|endoftext|>", "<|im_start|>", "<|im_end|>",
                                                 "<|eot_id|>", "</s>", "<|end|>"]):
                        for m in ["<|endoftext|>", "<|im_start|>", "<|im_end|>",
                                  "<|eot_id|>", "</s>", "<|end|>"]:
                            token = token.replace(m, "")
                        if not token:
                            continue
                    round_response += token
                    await queue.put(token)

                latency_s = time.perf_counter() - t0_llm
                input_tokens = count_message_tokens(current_messages, model=model_key or "")
                output_tokens = count_tokens(round_response, model=model_key or "")
                get_metrics().record_llm_call(
                    provider=provider_key,
                    model=model_key or getattr(provider, "default_model", "unknown"),
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    latency_s=latency_s,
                    session_id=session_id,
                )

                full_conversation += round_response
                _active_generations[session_id] = full_conversation

                # Check for truncation REGARDLESS of tool calls
                # BUT skip if the provider explicitly signaled finish_reason=stop
                if _finished_normally and _is_truncated(round_response):
                    logger.debug(
                        "Skipping continuation: _is_truncated=True but provider "
                        "signaled finish_reason=stop (model completed normally)"
                    )
                continuation_round = 0
                while (not _finished_normally and _is_truncated(round_response)
                       and continuation_round < MAX_CONTINUATION_ROUNDS):
                    continuation_round += 1
                    logger.info("Response truncated, auto-continuing (round %d)...", continuation_round)

                    # Notify the user (only if not inside a code block, to keep code seamless)
                    # Build continuation context — detect if we were inside a code block
                    # Count code fences to detect if truncated mid-code
                    fence_count = round_response.count("```")
                    in_code_block = fence_count % 2 != 0

                    if not in_code_block:
                        # Use a single-line notice that won't break Markdown context
                        cont_notice = "\n\n---\n⏳ *Continuation...*\n\n"
                        await queue.put(cont_notice)
                        full_conversation += cont_notice
                        _active_generations[session_id] = full_conversation
                    # Try to detect the language of the open code block
                    code_lang = ""
                    if in_code_block:
                        import re as _cont_re
                        # Find the last opening fence
                        fences = list(_cont_re.finditer(r'```(\w*(?::\S+)?)', round_response))
                        if fences:
                            code_lang = fences[-1].group(1) or ""

                    # Strip LLM stop tokens from the response before re-injecting
                    clean_round = round_response
                    for marker in ["<|endoftext|>", "<|im_start|>", "<|im_end|>",
                                   "<|eot_id|>", "</s>", "<|end|>"]:
                        clean_round = clean_round.replace(marker, "")
                    clean_round = clean_round.rstrip()

                    current_messages.append({
                        "role": "assistant",
                        "content": clean_round,
                    })

                    # Detect the user's language for the continuation prompt
                    _user_lang = ""
                    for m in messages:
                        if m["role"] == "user":
                            _umsg = m["content"].lower()
                            if any(w in _umsg for w in ["write", "hello", "thanks", "tell", "story", "book"]):
                                _user_lang = " You MUST continue in English."
                                break

                    # Build context-aware continuation instructions
                    if in_code_block and code_lang:
                        cont_instruction = (
                            "Your response was cut off INSIDE a code block. "
                            f"Continue EXACTLY from where you stopped. "
                            f"You MUST start your response with the continuation of the code "
                            f"inside a ```{code_lang} fence. "
                            "Do NOT repeat any previously written code or text. "
                            "Do NOT add introductory text before the code."
                            + _user_lang
                        )
                    elif in_code_block:
                        cont_instruction = (
                            "Your response was cut off INSIDE a code block. "
                            "Continue EXACTLY from where you stopped. "
                            "You MUST start your response with the continuation of the code "
                            "inside a ``` code fence. "
                            "Do NOT repeat any previously written code or text. "
                            "Do NOT add introductory text before the code."
                            + _user_lang
                        )
                    else:
                        cont_instruction = (
                            "Your response was cut off. Continue EXACTLY from where you stopped. "
                            "Do NOT repeat any previously written code or text. "
                            "Do NOT add introductory text. "
                            "Start immediately with the continuation."
                            + _user_lang
                        )

                    current_messages.append({
                        "role": "user",
                        "content": cont_instruction,
                    })

                    # Compress to fit context
                    current_messages = await optimize_for_provider(current_messages, provider_key)

                    # Stream continuation
                    cont_round_response = ""
                    _found_code_start = not in_code_block
                    
                    t0_cont = time.perf_counter()
                    async for token in provider.chat_stream(current_messages, **kwargs):
                        # Check for cancellation
                        if session_id in _cancelled_sessions:
                            _cancelled_sessions.discard(session_id)
                            logger.info("Generation cancelled by user for session %s", session_id)
                            full_conversation += "\n\n*\u23f9\ufe0f Generation stopped by user.*"
                            await queue.put(None)
                            return
                        # Intercept the finish sentinel
                        if token == FINISH_STOP_SENTINEL:
                            _finished_normally = True
                            continue
                        # Filter out LLM stop/control tokens
                        if any(m in token for m in ["<|endoftext|>", "<|im_start|>", "<|im_end|>",
                                                     "<|eot_id|>", "</s>", "<|end|>"]):
                            for m in ["<|endoftext|>", "<|im_start|>", "<|im_end|>",
                                      "<|eot_id|>", "</s>", "<|end|>"]:
                                token = token.replace(m, "")
                            if not token:
                                continue
                                
                        cont_round_response += token
                        
                        if not _found_code_start:
                            # Wait until we see the first \n after ```
                            import re as _cont_re
                            match = _cont_re.search(r"```[^\n]*\n([\s\S]*)", cont_round_response)
                            if match:
                                _found_code_start = True
                                # Stream only the part AFTER the newline
                                await queue.put(match.group(1))
                            elif len(cont_round_response) > 200:
                                # Fallback: LLM forgot the fence — strip introductory
                                # fluff ("Voici la suite", "Here is the continuation", etc.)
                                _found_code_start = True
                                _clean = cont_round_response.lstrip()
                                # Remove common intro patterns before streaming
                                import re as _strip_re
                                _clean = _strip_re.sub(
                                    r'^(?:(?:Voici|Here is|Continuing|Suite|I\'ll continue)[^\n]*\n)+',
                                    '', _clean, flags=_strip_re.IGNORECASE
                                ).lstrip()
                                if _clean:
                                    await queue.put(_clean)
                        else:
                            await queue.put(token)
                            
                    if not _found_code_start and cont_round_response:
                        # Flush remaining buffer — strip intro text
                        _clean = cont_round_response.lstrip()
                        import re as _strip_re
                        _clean = _strip_re.sub(
                            r'^(?:(?:Voici|Here is|Continuing|Suite|I\'ll continue)[^\n]*\n)+',
                            '', _clean, flags=_strip_re.IGNORECASE
                        ).lstrip()
                        if _clean:
                            await queue.put(_clean)

                    latency_s = time.perf_counter() - t0_cont
                    input_tokens = count_message_tokens(current_messages, model=model_key or "")
                    output_tokens = count_tokens(cont_round_response, model=model_key or "")
                    get_metrics().record_llm_call(
                        provider=provider_key,
                        model=model_key or getattr(provider, "default_model", "unknown"),
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        latency_s=latency_s,
                        session_id=session_id,
                    )

                    # Accumulate the continuation to the total round response
                    if in_code_block:
                        import re as _cont_re
                        match = _cont_re.search(r"```[^\n]*\n([\s\S]*)", cont_round_response)
                        if match:
                            cont_round_response = match.group(1)
                        else:
                            # If it forgot the fence, we still might need to strip introductory text.
                            # Just append as-is if no fence was found.
                            pass
                            
                    round_response += cont_round_response
                    full_conversation += cont_round_response

                # NOW check for tool_call blocks in the fully-completed response
                tool_calls = parse_tool_calls(round_response)

                # --- LLM Output Validation (OpenClaw OS-inspired) ---
                # Validate tool calls before execution: catch empty params,
                # duplicates, hallucinated paths, and budget overruns.
                try:
                    from app.tools.output_validator import validate_round_output
                    validation = validate_round_output(
                        text=round_response,
                        tool_calls=tool_calls,
                        round_num=round_num,
                        max_tool_rounds=MAX_TOOL_ROUNDS,
                    )
                    tool_calls = validation["tool_calls"]
                    if validation["blocked"]:
                        logger.info(
                            "Validator blocked %d tool call(s): %s",
                            len(validation["blocked"]),
                            ", ".join(validation["blocked"]),
                        )
                except Exception:
                    pass  # Validation is non-critical — never block generation

                if not tool_calls:
                    break  # Done (no tool calls)

                # Check total output cap
                if len(full_conversation) > MAX_TOTAL_OUTPUT:
                    cap_msg = "\n\n⚠️ **Output limit reached** — response capped at ~250K characters to prevent excessive generation.\n\n"
                    await queue.put(cap_msg)
                    full_conversation += cap_msg
                    break

                # --- Doom-loop detection ---
                # Build a fingerprint of this round's tool calls, including parameters
                import json as _dl_json
                _round_sig_parts = []
                for tc in tool_calls:
                    _param_str = _dl_json.dumps(tc.get("params", {}), sort_keys=True)
                    _round_sig_parts.append(f"{tc['tool']}::{_param_str}")
                _round_sig = "|".join(sorted(_round_sig_parts))
                _recent_tool_sequences.append(_round_sig)
                if len(_recent_tool_sequences) >= 3:
                    _last3 = _recent_tool_sequences[-3:]
                    if _last3[0] == _last3[1] == _last3[2]:
                        _sig_display = _round_sig if len(_round_sig) < 200 else _round_sig[:197] + "..."
                        doom_msg = (
                            "\n\n⚠️ **Doom-loop detected** — the same tools "
                            f"(`{_sig_display}`) were called 3 times in a row. "
                            "Aborting to prevent infinite looping.\n\n"
                        )
                        await queue.put(doom_msg)
                        full_conversation += doom_msg
                        logger.warning("Doom-loop detected: %s", _sig_display)
                        break

                # Execute each tool call
                tool_results = []
                for tc in tool_calls:
                    tool_name = tc["tool"]
                    params = tc["params"]
                    resolved = resolve_tool_name(tool_name)

                    # --- Agent tool isolation check ---
                    effective_tool = resolved or tool_name
                    try:
                        if active_agent != "none" and not is_tool_allowed(active_agent, effective_tool):
                            blocked_msg = (
                                f"\n\n🚫 *Tool `{effective_tool}` blocked — "
                                f"agent `{active_agent}` does not have permission.*\n\n"
                            )
                            await queue.put(blocked_msg)
                            full_conversation += blocked_msg
                            tool_results.append({
                                "tool": effective_tool,
                                "original": tool_name,
                                "result": f"Tool '{effective_tool}' blocked by agent policy for '{active_agent}'.",
                            })
                            continue
                    except Exception:
                        pass  # Tool isolation is non-critical

                    # --- Mode-level tool restriction ---
                    try:
                        from app.core.agent_modes import is_tool_allowed as mode_tool_allowed
                        if not mode_tool_allowed(preprompt_key, effective_tool):
                            mode_msg = (
                                f"\n\n🔒 *Tool `{effective_tool}` is not available in "
                                f"**{preprompt_key}** mode. Switch mode to use this tool.*\n\n"
                            )
                            await queue.put(mode_msg)
                            full_conversation += mode_msg
                            tool_results.append({
                                "tool": effective_tool,
                                "original": tool_name,
                                "result": f"Tool '{effective_tool}' blocked by mode '{preprompt_key}'.",
                            })
                            continue
                    except Exception:
                        pass  # Mode restrictions are non-critical

                    # Notify the user about tool execution
                    status_prefix = ""
                    if resolved and resolved != tool_name:
                        status_prefix = f"\n\n⚡ *`{tool_name}` → `{resolved}`* — "
                    elif resolved:
                        status_prefix = f"\n\n⚡ *Executing `{resolved}`...* "
                    else:
                        status_prefix = f"\n\n⚠️ *Unknown tool `{tool_name}`, trying best match...* "

                    await queue.put(status_prefix)
                    full_conversation += status_prefix
                    _active_generations[session_id] = full_conversation

                    # --- Plugin hook: before_tool_execute ---
                    _skip_tool = False
                    try:
                        from app.core.plugin_system import run_hook
                        _pre_ctx = run_hook("before_tool_execute", {
                            "tool_name": resolved or tool_name,
                            "params": params,
                            "session_id": session_id,
                            "skip": False,
                        })
                        params = _pre_ctx.get("params", params)
                        _skip_tool = _pre_ctx.get("skip", False)
                    except Exception:
                        pass

                    # --- Pipeline Step: Per-tool permission check (HITL) ---
                    # Only enforced when "require_command_confirmation" is enabled in settings
                    # Note: _hitl_enabled is checked per-tool but the import is cached by Python
                    if not hasattr(generate, '_hitl_cache_ts') or (time.time() - generate._hitl_cache_ts > 5):
                        from app.settings import load_settings as _load_hitl_settings
                        generate._hitl_enabled = _load_hitl_settings().get("require_command_confirmation", True)
                        generate._hitl_cache_ts = time.time()
                    _tool_perm = get_tool_permission(resolved or tool_name) if generate._hitl_enabled else "always"
                    if _tool_perm == "deny":
                        _deny_msg = (
                            f"\n\n🚫 *Tool `{resolved or tool_name}` is **denied** by permission policy. "
                            "Change in Settings → Tool Permissions.*\n\n"
                        )
                        await queue.put(_deny_msg)
                        full_conversation += _deny_msg
                        tool_results.append({
                            "tool": resolved or tool_name,
                            "original": tool_name,
                            "result": f"Tool '{resolved or tool_name}' denied by permission policy.",
                        })
                        continue
                    elif _tool_perm == "ask" and not _skip_tool:
                        _ask_msg = (
                            f"\n\n⏳ *Waiting for approval to execute `{resolved or tool_name}`...*\n\n"
                        )
                        await queue.put(_ask_msg)
                        full_conversation += _ask_msg
                        _approved = await request_approval(
                            session_id, resolved or tool_name, params, queue,
                        )
                        if not _approved:
                            _denied_msg = (
                                f"\n\n❌ *Tool `{resolved or tool_name}` execution **denied** by user.*\n\n"
                            )
                            await queue.put(_denied_msg)
                            full_conversation += _denied_msg
                            tool_results.append({
                                "tool": resolved or tool_name,
                                "original": tool_name,
                                "result": f"Tool '{resolved or tool_name}' denied by user.",
                            })
                            continue
                        else:
                            _ok_msg = f"\n\n✅ *Approved — executing `{resolved or tool_name}`...*\n\n"
                            await queue.put(_ok_msg)
                            full_conversation += _ok_msg

                    # Execute the tool
                    _exec_start = time.time()
                    if _skip_tool:
                        result = {"output": "Tool execution skipped by plugin."}
                    else:
                        result = await execute_tool(tool_name, params, {"active_project": active_project})

                    # --- Autonomous Self-Healing / Auto-Correction Loop ---
                    if (resolved or tool_name) in ("edit_file", "write_file", "apply_patch") and "error" not in result and result.get("status") != "error":
                        try:
                            from app.tools_code import run_workspace_tests
                            # Run tests asynchronously to keep the gateway responsive
                            test_res = await asyncio.to_thread(run_workspace_tests, None, active_project)
                            if not test_res.get("success", False):
                                # Increment correction attempts counter
                                if not hasattr(generate, '_correction_counts'):
                                    generate._correction_counts = {}
                                file_key = params.get("file_path") or params.get("path") or "global_tests"
                                attempt_num = generate._correction_counts.get(file_key, 0) + 1
                                generate._correction_counts[file_key] = attempt_num
                                
                                # Visual indicator in UI SSE queue
                                test_warn_msg = (
                                    f"\n\n⚠️ **[Self-Healing] Test suite failed on '{file_key}'!** "
                                    f"Starting autonomous auto-correction (Attempt {attempt_num}/10)... \n"
                                )
                                await queue.put(test_warn_msg)
                                full_conversation += test_warn_msg
                                _active_generations[session_id] = full_conversation

                                test_output = (test_res.get("stdout", "") + "\n" + test_res.get("stderr", "")).strip()
                                test_output = test_output[-3000:]  # Limit to save token budget

                                if attempt_num <= 10:
                                    result = {
                                        "status": "error",
                                        "error": (
                                            f"The changes were written, but the automated test suite failed (Attempt {attempt_num}/10).\n"
                                            "You MUST correct this immediately. Analyze the test output below and propose another surgical edit (edit_file) or patch to fix the code.\n\n"
                                            f"Test Suite Command: {test_res.get('command')}\n"
                                            f"Test Output:\n{test_output}"
                                        )
                                    }
                                else:
                                    result = {
                                        "status": "error",
                                        "error": (
                                            f"The changes were written, but the automated test suite failed. "
                                            "Maximum self-healing attempts (10) reached. Stopping auto-correction loop.\n\n"
                                            f"Test Output:\n{test_output}"
                                        )
                                    }
                        except Exception as _sh_err:
                            logger.error("Error in autonomous self-healing loop: %s", _sh_err)

                    # Push notification for long-running tools (OpenClaw OS-inspired)
                    try:
                        from app.core.notifications import notify_tool_complete
                        _long_tools = {"generate_image", "generate_animation", "audit_code",
                                       "screenshot_remote", "search_web"}
                        if (resolved or tool_name) in _long_tools:
                            success = "error" not in result
                            notify_tool_complete(
                                resolved or tool_name, session_id,
                                success=success,
                                detail=result.get("error", "")[:100] if not success else "",
                            )
                    except Exception:
                        pass  # Notifications are non-critical

                    # Record tool call for replay (debugging & workflow export)
                    try:
                        from app.core.tool_replay import record_tool_call
                        _exec_end = time.time()
                        record_tool_call(
                            session_id, resolved or tool_name, params, result,
                            duration_ms=(_exec_end - _exec_start) * 1000,
                            round_num=round_num,
                        )
                    except Exception:
                        pass  # Replay recording is non-critical

                    # --- Plugin hook: after_tool_execute ---
                    try:
                        from app.core.plugin_system import run_hook
                        _post_ctx = run_hook("after_tool_execute", {
                            "tool_name": resolved or tool_name,
                            "params": params,
                            "result": result,
                            "session_id": session_id,
                        })
                        # Plugins can modify the result
                        result = _post_ctx.get("result", result)
                    except Exception:
                        pass  # Plugin hooks are non-critical

                    # Measure raw result size for token savings analytics
                    import json as _json_metrics
                    try:
                        raw_result_text = _json_metrics.dumps(result, ensure_ascii=False)
                    except (TypeError, ValueError):
                        raw_result_text = str(result)
                    raw_size = len(raw_result_text)

                    result_text = format_tool_result(resolved or tool_name, result)

                    # Track token savings (RTK-style analytics)
                    compressed_size = len(result_text)
                    if raw_size > 50:  # Only track meaningful compressions
                        get_metrics().record_token_savings(
                            resolved or tool_name, raw_size, compressed_size
                        )

                    # Stream the result preview to the user
                    if (resolved or tool_name) in ("execute_python", "run_command"):
                        # Format terminal output in a special marker to be parsed by frontend
                        result_preview = f"\n\n__DETAILS__{result_text}__DETAILS__\n\n"
                        await queue.put(result_preview)
                        full_conversation += result_preview
                        _active_generations[session_id] = full_conversation
                    elif (resolved or tool_name) == "search_web" and isinstance(result, dict) and result.get("results"):
                        # Stream search results as a visible collapsible block
                        search_items = result["results"]
                        search_lines = []
                        for idx, sr in enumerate(search_items[:10], 1):
                            title = sr.get("title", "N/A")[:120]
                            url = sr.get("url", "")
                            snippet = sr.get("snippet", "")[:200]
                            search_lines.append(f"**{idx}. [{title}]({url})**")
                            if snippet:
                                search_lines.append(f"   {snippet}")
                        search_md = "\n".join(search_lines)
                        search_preview = f"\n\n✅ **{len(search_items)} result(s) found:**\n\n{search_md}\n\n"
                        await queue.put(search_preview)
                        full_conversation += search_preview
                        _active_generations[session_id] = full_conversation
                    else:
                        # For other tools, do not stream raw text to avoid double results
                        status_done = "✅ *Done.*\n\n"
                        await queue.put(status_done)
                        full_conversation += status_done

                    # Stream images inline if the tool returned any
                    if isinstance(result, dict):
                        # Matplotlib plots (multiple images) — save to disk
                        if result.get("images"):
                            import base64 as _b64_dec
                            import uuid as _uuid_plot
                            for idx, b64 in enumerate(result["images"], 1):
                                plot_fname = f"plot_{_uuid_plot.uuid4().hex[:10]}.png"
                                plot_path = _os.path.join(_images_dir, plot_fname)
                                try:
                                    with open(plot_path, "wb") as _pf:
                                        _pf.write(_b64_dec.b64decode(b64))
                                    file_url = f"/data/images/{plot_fname}"
                                    img_md = f"\n\n__IMG__{file_url}|Plot {idx}|{plot_fname}__IMG__\n\n"
                                except Exception as _plot_err:
                                    logger.warning("Failed to save plot %d: %s", idx, _plot_err)
                                    img_md = f"\n\n⚠️ *Plot {idx} could not be saved.*\n\n"
                                await queue.put(img_md)
                                full_conversation += img_md
                        # SVG images (inline SVG content)
                        elif result.get("svg"):
                            label = resolved or tool_name
                            fname = result.get('filename', '')
                            if fname:
                                file_url = f"/data/images/{fname}"
                                # Use __SVG__ marker for frontend to render inline
                                svg_md = f"\n\n__SVG__{file_url}|{label}|{fname}__SVG__\n\n"
                                await queue.put(svg_md)
                                full_conversation += svg_md
                            else:
                                # Fallback: render SVG inline as image
                                svg_content = result['svg']
                                svg_md = f"\n\n{svg_content}\n\n"
                                await queue.put(svg_md)
                                full_conversation += svg_md
                        # Screenshots and generated images (single base64)
                        elif result.get("base64"):
                            label = resolved or tool_name
                            fname = result.get('filename', '')
                            if fname:
                                if 'screenshot' in (resolved or tool_name):
                                    file_url = f"/data/screenshots/{fname}"
                                else:
                                    file_url = f"/data/images/{fname}"
                                # Use static URL instead of base64 to avoid
                                # SSE/markdown parsing issues with huge payloads
                                img_md = f"\n\n__IMG__{file_url}|{label}|{fname}__IMG__\n\n"
                                await queue.put(img_md)
                                full_conversation += img_md
                            else:
                                # Fallback: inline base64 (no filename)
                                img_md = f"\n\n![{label}](data:image/png;base64,{result['base64']})\n\n"
                                await queue.put(img_md)
                                full_conversation += img_md
                                
                        # Code editor file updates (trigger frontend file refresh and diff highlight)
                        if (resolved or tool_name) == "edit_file" and result.get("status") == "success" and result.get("file_path"):
                            import json as _json
                            edit_data = {
                                "path": result.get("file_path"),
                                "diff": result.get("diff", ""),
                                "lines_added": result.get("lines_added", 0),
                                "lines_removed": result.get("lines_removed", 0),
                                "lines_changed": result.get("lines_changed", 0),
                                "show_diff": result.get("show_diff", False),
                            }
                            edit_marker = f"\n\n__FILE_EDIT__{_json.dumps(edit_data)}__\n\n"
                            await queue.put(edit_marker)
                            full_conversation += edit_marker

                        # If an apply_patch tool modified files, emit file edit markers
                        # so the frontend IDE can refresh and open the modified files.
                        if (resolved or tool_name) == "apply_patch" and result.get("success"):
                            try:
                                import json as _json
                                ops = result.get("operations") or []
                                for op in ops:
                                    # prefer 'target' (new path) then 'path'
                                    p = op.get('target') or op.get('path') or op.get('file')
                                    if not p:
                                        continue
                                    edit_data = {
                                        "path": p,
                                        "diff": op.get("diff", ""),
                                        "lines_added": op.get("lines_added", 0),
                                        "lines_removed": op.get("lines_removed", 0),
                                        "lines_changed": op.get("lines_changed", 0),
                                        "show_diff": False,
                                    }
                                    edit_marker = f"\n\n__FILE_EDIT__{_json.dumps(edit_data)}__\n\n"
                                    await queue.put(edit_marker)
                                    full_conversation += edit_marker
                            except Exception:
                                pass

                        # write_file: emit file edit marker so the frontend IDE refreshes
                        if (resolved or tool_name) == "write_file" and result.get("status") == "success" and result.get("file_path"):
                            import json as _json
                            edit_data = {
                                "path": result.get("file_path"),
                                "diff": "",
                                "lines_added": result.get("lines", 0),
                                "lines_removed": 0,
                                "lines_changed": 0,
                                "show_diff": False,
                            }
                            edit_marker = f"\n\n__FILE_EDIT__{_json.dumps(edit_data)}__\n\n"
                            await queue.put(edit_marker)
                            full_conversation += edit_marker

                        # TodoWrite: broadcast plan update to frontend in real-time.
                        # NOTE: The marker is SSE-only — do NOT add to full_conversation
                        # to prevent it from being persisted in chat history.
                        if (resolved or tool_name) == "todo_write" and result.get("__todo_update__"):
                            import json as _json
                            todo_data = {
                                "todos": result.get("todos", []),
                                "session_id": session_id,
                                "action": result.get("status", "written"),
                            }
                            todo_marker = f"\n\n__TODO_UPDATE__{_json.dumps(todo_data)}__TODO_UPDATE__\n\n"
                            await queue.put(todo_marker)
                            # Intentionally NOT added to full_conversation (SSE-only transport marker)

                        # App Builder: stream an inline preview card with iframe link
                        if (resolved or tool_name) in ("create_app", "update_app") and result.get("id"):
                            app_id = result["id"]
                            app_name = result.get("name", "App")
                            preview_url = result.get("preview_url", f"/apps/{app_id}/index.html")
                            icon_emoji = result.get("icon", "📱")
                            action_label = "Created" if (resolved or tool_name) == "create_app" else "Updated"
                            app_card = (
                                f"\n\n**{icon_emoji} {action_label}: {app_name}**\n"
                                f"[🔗 Open Preview]({preview_url})\n\n"
                            )
                            await queue.put(app_card)
                            full_conversation += app_card


                    tool_results.append({
                        "tool": resolved or tool_name,
                        "original": tool_name,
                        "result": result_text,
                    })

                    logger.info("Tool executed: %s → %s (%d chars)",
                                tool_name, resolved, len(result_text))

                # If we got results, feed them back to the LLM for a final answer
                if tool_results:
                    # Strip base64 data from round_response before adding to context
                    # (images are already displayed to the user via SSE)
                    clean_response = _strip_base64(round_response)
                    # Also truncate if the response is too long
                    if len(clean_response) > 4000:
                        clean_response = clean_response[:4000] + "\n... (truncated)"

                    current_messages.append({
                        "role": "assistant",
                        "content": clean_response,
                    })

                    # Build compact tool results (strip base64 from results too)
                    # File content (read_file) needs more context than other tools
                    _result_parts = []
                    for tr in tool_results:
                        _max_chars = 12000 if tr['tool'] in ('read_file', 'grep_code', 'webfetch') else 3000
                        _result_parts.append(
                            f"[Tool result: {tr['tool']}]\n{tr['result'][:_max_chars]}"
                        )
                    results_text = "\n\n".join(_result_parts)
                    instruction = "The tools have been executed and here are the results. "
                    if round_num >= MAX_TOOL_ROUNDS:
                        instruction += "You MUST now present a clear, complete answer based on these results. Do NOT use any tool_call blocks. Do NOT ask the user to run code. Directly present the answer or analysis."
                    else:
                        instruction += (
                            "Analyze these results. If you need to modify a file, use a ```tool_call block with edit_file. "
                            "If you need more information, use another tool. "
                            "If you have all the information you need, directly present the final answer without any tool calls."
                        )

                    current_messages.append({
                        "role": "user",
                        "content": f"{instruction}\n\n{results_text}",
                    })

                    # Aggressively compress to fit context window
                    current_messages = await optimize_for_provider(current_messages, provider_key)

                    # Log context size for debugging
                    ctx_chars = sum(len(m.get('content', '')) for m in current_messages)
                    logger.info("Context after tool round %d: %d messages, %d chars",
                                round_num, len(current_messages), ctx_chars)

                    # Separator before the final answer
                    separator = "\n\n---\n\n"
                    await queue.put(separator)
                    full_conversation += separator
                    _active_generations[session_id] = full_conversation
                else:
                    break

        except Exception as e:
            error_msg = f"\n\n❌ **LLM Error**: {type(e).__name__} — {e}"
            full_conversation += error_msg
            _active_generations[session_id] = full_conversation
            await queue.put(error_msg)
            logger.error("LLM error: %s", e)
        finally:
            # Generate follow-up suggestion chips (Roo Code-inspired)
            # Only if explicitly enabled in settings (disabled by default for performance)
            from app.settings import load_settings
            if load_settings().get("enable_suggestions", False) and \
               full_conversation.strip() and session_id not in _cancelled_sessions:
                try:
                    suggestions = await _generate_suggestions(
                        full_conversation, provider_key, model_key
                    )
                    if suggestions:
                        import json as _json
                        suggestion_token = f"__SUGGESTIONS__{_json.dumps(suggestions)}__SUGGESTIONS__"
                        await queue.put(suggestion_token)
                except Exception as sg_err:
                    logger.debug("Suggestion generation skipped: %s", sg_err)

            await queue.put(None)  # Signal end of stream
            # Save the complete conversation (all rounds) as the assistant response
            if full_conversation.strip():
                add_message(session_id, "assistant", full_conversation, metadata={
                    "provider": provider_key,
                    "model": model_key,
                    "preprompt": preprompt_key,
                })
                # Auto-save substantial code blocks as persistent artifacts
                try:
                    from app.core.artifacts import extract_and_save_artifacts
                    extract_and_save_artifacts(full_conversation, session_id)
                except Exception:
                    pass  # Artifact extraction is non-critical

                # --- Plugin hook: after_generation ---
                try:
                    from app.core.plugin_system import run_hook
                    run_hook("after_generation", {
                        "response": full_conversation,
                        "session_id": session_id,
                        "provider": provider_key,
                        "model": model_key,
                    })
                except Exception:
                    pass  # Plugin hooks are non-critical

                # --- Auto-populate memory files (background) ---
                try:
                    from app.core.memory import auto_extract_memory, auto_summarize_session
                    conv_messages = get_messages(session_id)
                    asyncio.create_task(auto_extract_memory(conv_messages))
                    asyncio.create_task(auto_summarize_session(session_id))
                except Exception:
                    pass  # Memory extraction/summarization is non-critical

            _active_generations.pop(session_id, None)
            _sse_queues.pop(session_id, None)
            _generation_tasks.pop(session_id, None)

    task = asyncio.create_task(generate())
    _generation_tasks[session_id] = task
    return {"status": "processing", "session_id": session_id}


@app.post("/send/{session_id}")
async def send_message(session_id: str, request: Request):
    """Send a user message and trigger LLM response generation (HTTP)."""
    data = await request.json()
    return await _process_chat(session_id, data)


# NOTE: /chat/upload-image and /chat/humanize moved to app/routers/chat.py (included with prefix="")

# --- WebSocket chat endpoint ---
@app.websocket("/ws/{session_id}")
async def ws_chat(websocket: WebSocket, session_id: str):
    """Bidirectional WebSocket endpoint for chat streaming.

    Replaces the POST /send/ + GET /stream/ pair with a single
    persistent connection.  Supports:
      - {"type":"message", "message":"...", ...} → triggers generation
      - {"type":"stop"}   → cancels active generation
      - {"type":"ping"}   → keepalive, returns {"type":"pong"}
    """
    if API_SECRET_TOKEN:
        token = websocket.query_params.get("token") or websocket.cookies.get("api_secret_token")
        if token != API_SECRET_TOKEN:
            await websocket.close(code=4001, reason="Unauthorized")
            return
    await websocket.accept()
    await websocket.send_json({"type": "connected", "session_id": session_id})
    logger.info("WebSocket connected: %s", session_id)

    # Subscribe to push notifications
    try:
        from app.core.notifications import subscribe, get_recent
        subscribe(session_id)
        # Send any recent unread notifications
        for n in get_recent(limit=5, session_id=session_id):
            await websocket.send_json(n)
    except Exception:
        pass

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type", "message")

            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})
                continue

            if msg_type == "stop":
                _cancelled_sessions.add(session_id)
                if session_id in _sse_queues:
                    try:
                        await _sse_queues[session_id].put(None)
                    except Exception:
                        pass
                await websocket.send_json({"type": "stopped"})
                continue

            if msg_type == "message":
                # Ensure queue exists
                if session_id not in _sse_queues:
                    _sse_queues[session_id] = asyncio.Queue()

                # Trigger generation (reuses the exact same logic as POST /send/)
                try:
                    result = await _process_chat(session_id, data)
                    await websocket.send_json({"type": "processing", **result})
                except HTTPException as exc:
                    await websocket.send_json({"type": "error", "detail": exc.detail})
                    continue
                except Exception as exc:
                    await websocket.send_json({"type": "error", "detail": str(exc)})
                    continue

                # Stream tokens from queue to WebSocket
                queue = _sse_queues[session_id]

                async def _stream_tokens():
                    """Read tokens from the generation queue and send over WS."""
                    while True:
                        token = await queue.get()
                        if token is None:
                            break
                        await websocket.send_json({"type": "token", "data": token})
                    await websocket.send_json({"type": "done"})

                async def _listen_for_stop():
                    """Listen for stop signals while streaming."""
                    while True:
                        try:
                            msg = await websocket.receive_json()
                            if msg.get("type") == "stop":
                                _cancelled_sessions.add(session_id)
                                await queue.put(None)
                                return
                            elif msg.get("type") == "ping":
                                await websocket.send_json({"type": "pong"})
                        except (WebSocketDisconnect, Exception):
                            return

                # Run streaming and stop-listener concurrently
                stream_task = asyncio.create_task(_stream_tokens())
                listen_task = asyncio.create_task(_listen_for_stop())

                done, pending = await asyncio.wait(
                    [stream_task, listen_task],
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()
                    try:
                        await task
                    except (asyncio.CancelledError, Exception):
                        pass

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected: %s", session_id)
    except Exception as exc:
        logger.error("WebSocket error for %s: %s", session_id, exc)
    finally:
        # Unsubscribe from notifications
        try:
            from app.core.notifications import unsubscribe
            unsubscribe(session_id)
        except Exception:
            pass


# NOTE: /notifications moved to app/routers/system.py


# NOTE: Arena code fully extracted to app/routers/arena.py (see include above)


# --- Preview route (serves workspace files for web preview) ---
from config import WORKSPACE_DIR as _WORKSPACE_DIR

# NOTE: /preview/* and /api/export-zip have been extracted to app/routers/files.py
# (see files_router include above). Legacy definitions removed to avoid duplication.
