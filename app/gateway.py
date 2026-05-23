"""
Clawzd — FastAPI application gateway.
Main router that wires all modules together and handles chat streaming.
"""
import asyncio
import io
import logging
import os
import time
import zipfile
import uuid

from fastapi import FastAPI, Request, HTTPException, UploadFile, File, Form, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from jinja2 import Environment, FileSystemLoader
from fastapi.templating import Jinja2Templates
from sse_starlette.sse import EventSourceResponse
from datetime import datetime, timezone

from app.database import (
    init_db, create_session, get_session, add_message, get_messages,
    auto_title, fork_at_message, list_branches, delete_branch,
)
from app.llm_provider import get_llm_provider, _get_provider_models
from app.preprompts import get_preprompt, list_preprompts, get_jailbreak_wrapper
from app.chat import router as chat_router
from app.profiles import router as profiles_router
from app.tools_code import router as code_router, executor
from app.tools_web import router as web_router
from app.tools_local import router as local_router
from app.tools_quality import router as quality_router
from app.rag import router as rag_router
from app.improvement import router as improvement_router
from app.agent_core import router as agent_router
from app.settings import router as settings_router
from app.tools_screenshot import router as screenshot_router
from app.tools_image import router as image_router
from app.tools_audio import router as audio_router
from app.routers.voice_rtvi import router as voice_rtvi_router
from app.tools_browser import router as browser_router
from app.tools_cron import router as cron_router
from app.tools_skills import router as skills_router
from app.tools_document import router as document_router
from app.integrations_telegram import router as telegram_router
from app.skill_selector import select_skills
from app.skill_registry import get_registry
from app.model_manager import router as models_router
from app.compression import optimize_for_provider
from app.tools_presentation import router as presentation_router
from app.routers.presentation_video import router as presentation_video_router
from app.tools_automation import router as automation_router
from app.tools_clone import router as clone_router
from app.tools_document_gen import router as docgen_router
from app.tools_studio_editor import router as studio_editor_router
from app.tool_executor import parse_tool_calls, execute_tool, format_tool_result, resolve_tool_name
from app.core.tool_permissions import (
    get_tool_permission, set_tool_permission, load_permissions,
    request_approval, resolve_approval, list_pending_approvals,
)
from app.metrics import get_metrics
from app.cache import cache_stats
from app.core.tokens import count_tokens, count_message_tokens
from config import STATIC_DIR, TEMPLATES_DIR, DATA_DIR, CORS_ORIGINS, RATE_LIMIT, APP_VERSION, OLLAMA_VERIFY_SSL

import re as _re
import httpx

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

# --- Request Timing Middleware ---
@app.middleware("http")
async def _timing_middleware(request: Request, call_next):
    """Record request latency for metrics."""
    t0 = time.perf_counter()
    response = await call_next(request)
    latency = time.perf_counter() - t0
    get_metrics().record_request(
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        latency_s=latency,
    )
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
_video_dir = _os.path.join(DATA_DIR, "media", "video")
_os.makedirs(_video_dir, exist_ok=True)
app.mount("/data/media/video", StaticFiles(directory=_video_dir), name="video")
_research_dir = _os.path.join(DATA_DIR, "research")
_os.makedirs(_research_dir, exist_ok=True)
app.mount("/data/research", StaticFiles(directory=_research_dir), name="research")

jinja_env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), cache_size=0)
templates = Jinja2Templates(env=jinja_env)

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
    import asyncio
    asyncio.create_task(mcp_manager.connect_all())

    # Start Discord bot if configured
    import os
    if os.getenv("DISCORD_BOT_TOKEN"):
        from app.integrations_discord import start_discord_bot
        asyncio.create_task(start_discord_bot())
        logger.info("Discord bot starting...")

    # Start automation background listeners (Discord/Telegram/Cron triggers)
    from app.tools_automation import start_automation_listeners
    asyncio.create_task(start_automation_listeners())
    logger.info("Automation listeners starting...")

    # Start skill rebuilder background maintenance (lifecycle transitions)
    from app.skill_rebuilder import start_maintenance_task
    start_maintenance_task()
    logger.info("Skill rebuilder maintenance loop started")

    # Scan RAG folder for documents to index
    try:
        from app.rag import scan_rag_folder
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
        from app.memory import optimize_memory_files
        while True:
            # wait 24 hours
            await asyncio.sleep(24 * 3600)
            try:
                await optimize_memory_files()
            except Exception as e:
                logger.error("Daily memory optimization failed: %s", e)

    asyncio.create_task(run_daily_optimization())

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
from app.memory import router as memory_router
app.include_router(memory_router, prefix="/api")
app.include_router(screenshot_router, prefix="/screenshot")
app.include_router(image_router, prefix="/image")
app.include_router(audio_router, prefix="/audio")
app.include_router(voice_rtvi_router)
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

from app.tools_research import router as research_router
app.include_router(research_router, prefix="/research")

from app.tools.task_manager import router as task_manager_router
app.include_router(task_manager_router, prefix="/api")

from app.tools_twitter import router as twitter_router
app.include_router(twitter_router, prefix="/twitter")

from app.tools_project import router as project_router
app.include_router(project_router, prefix="/project")

from app.tools_spec import router as spec_router
app.include_router(spec_router, prefix="/spec")

# Agent dispatch (multi-agent orchestration)
from app.agent_dispatch import router as agent_dispatch_router
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

# --- Tool Permissions API (HITL approval) ---

@app.get("/api/tool-permissions")
async def get_tool_permissions():
    """Return all tool permissions."""
    return {"permissions": load_permissions()}


@app.post("/api/tool-permissions")
async def update_tool_permissions(request: Request):
    """Update one or more tool permissions."""
    body = await request.json()
    for tool_name, level in body.items():
        if level in ("always", "ask", "deny"):
            set_tool_permission(tool_name, level)
    return {"status": "ok", "permissions": load_permissions()}


@app.post("/api/tool-approval")
async def handle_tool_approval(request: Request):
    """Approve or deny a pending tool execution."""
    body = await request.json()
    approval_id = body.get("approval_id", "")
    approved = body.get("approved", False)
    always_allow = body.get("always_allow", False)
    if not approval_id:
        raise HTTPException(400, "approval_id required")
    found = resolve_approval(approval_id, approved, always_allow)
    if not found:
        raise HTTPException(404, "Approval not found or already resolved")
    return {"status": "resolved", "approved": approved}


@app.get("/api/tool-approvals")
async def get_pending_approvals(session_id: str = ""):
    """List pending tool approvals."""
    return {"approvals": list_pending_approvals(session_id)}


# --- Conversation Branching API ---

@app.post("/api/branch/fork")
async def fork_conversation(request: Request):
    """Fork a conversation at a specific message."""
    body = await request.json()
    session_id = body.get("session_id", "")
    message_id = body.get("message_id", 0)
    branch_name = body.get("branch_name", "")
    if not session_id or not message_id:
        raise HTTPException(400, "session_id and message_id required")
    result = fork_at_message(session_id, int(message_id), branch_name)
    if "error" in result:
        raise HTTPException(404, result["error"])
    return result


@app.get("/api/branch/{session_id}")
async def get_branches(session_id: str):
    """List all branches for a session."""
    return {"branches": list_branches(session_id)}


@app.get("/api/branch/{session_id}/{branch_id}")
async def get_branch_messages(session_id: str, branch_id: str):
    """Get messages for a specific branch."""
    messages = get_messages(session_id, branch_id=branch_id)
    return {"branch_id": branch_id, "messages": messages}


@app.delete("/api/branch/{session_id}/{branch_id}")
async def remove_branch(session_id: str, branch_id: str):
    """Delete a branch (cannot delete 'main')."""
    if branch_id == "main":
        raise HTTPException(400, "Cannot delete the main branch")
    ok = delete_branch(session_id, branch_id)
    if not ok:
        raise HTTPException(400, "Could not delete branch")
    return {"status": "deleted", "branch_id": branch_id}


# --- Agent Modes API ---

@app.get("/api/modes")
async def get_agent_modes():
    """Return all available agent modes with tool restrictions."""
    from app.core.agent_modes import list_modes
    return {"modes": list_modes()}


@app.get("/api/modes/{mode_key}")
async def get_mode_detail(mode_key: str):
    """Return detailed mode definition including allowed/blocked tools."""
    from app.core.agent_modes import get_mode
    mode = get_mode(mode_key)
    return {
        "key": mode_key,
        "label": mode.get("label", mode_key),
        "icon": mode.get("icon", "💬"),
        "allowed_tools": mode.get("allowed_tools"),
        "blocked_tools": mode.get("blocked_tools", []),
        "ui_hints": mode.get("ui_hints", {}),
    }


# --- Diff Viewer API ---

@app.get("/api/diff")
async def get_diff_endpoint(project: str = ""):
    """Get git diff for a project or the workspace."""
    from app.core.diff_viewer import get_diff
    path = project or os.path.join(os.path.dirname(os.path.dirname(__file__)), "workspace")
    staged = False  # Can be extended later
    return get_diff(path, staged=staged)


@app.post("/api/diff/stage")
async def stage_file_endpoint(request: Request):
    """Stage a file in the git index."""
    from app.core.diff_viewer import stage_file
    body = await request.json()
    project = body.get("project", "")
    file_path = body.get("file", "")
    if not file_path:
        raise HTTPException(400, "file is required")
    path = project or os.path.join(os.path.dirname(os.path.dirname(__file__)), "workspace")
    return stage_file(path, file_path)


@app.post("/api/diff/revert")
async def revert_file_endpoint(request: Request):
    """Revert a file to its last committed state."""
    from app.core.diff_viewer import revert_file
    body = await request.json()
    project = body.get("project", "")
    file_path = body.get("file", "")
    if not file_path:
        raise HTTPException(400, "file is required")
    path = project or os.path.join(os.path.dirname(os.path.dirname(__file__)), "workspace")
    return revert_file(path, file_path)


# --- System Health API ---

@app.get("/api/system/health")
async def system_health():
    """Return system resource usage and service status."""
    from app.core.metrics import MetricsCollector
    resources = MetricsCollector.get_system_resources()

    # Check Ollama status (resolve host dynamically so remote servers are checked)
    ollama_status = "unknown"
    try:
        import httpx
        from app.core.llm_provider import _resolve_ollama_host, _resolve_ollama_api_key
        _ollama_host = _resolve_ollama_host()
        _ollama_key = _resolve_ollama_api_key()
        _headers = {"Authorization": f"Bearer {_ollama_key}"} if _ollama_key else {}
        async with httpx.AsyncClient(timeout=3) as client:
            resp = await client.get(f"{_ollama_host}/api/version", headers=_headers)
            ollama_status = "running" if resp.status_code == 200 else "error"
    except Exception:
        ollama_status = "offline"

    return {**resources, "ollama_status": ollama_status}

# --- In-memory SSE queues per session ---
_sse_queues: dict[str, asyncio.Queue] = {}
_arena_queues: dict[str, asyncio.Queue] = {}
_active_generations: dict[str, str] = {}
_cancelled_sessions: set[str] = set()
_generation_tasks: dict[str, asyncio.Task] = {}


# --- Main page ---
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Serve the main application page."""
    from config import HUGGINGFACE_API_KEY
    
    # We check if HUGGINGFACE_API_KEY is truthy (exists and not empty)
    has_hf_token = bool(HUGGINGFACE_API_KEY)
    
    context = {
        "request": request,
        "has_hf_token": has_hf_token,
        "app_version": APP_VERSION,
    }
    return templates.TemplateResponse(request=request, name="index.html", context=context)


# --- Health Check ---
@app.get("/health")
async def health_check():
    """Health check with dependency status."""
    import httpx as _httpx
    from config import OLLAMA_HOST, DB_PATH, CHROMA_DB_PATH

    status = {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}
    deps = {}

    # Check Ollama
    try:
        async with _httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{OLLAMA_HOST}/api/tags")
            deps["ollama"] = "ok" if resp.status_code == 200 else "degraded"
    except Exception:
        deps["ollama"] = "unavailable"

    # Check SQLite
    try:
        def check_sqlite():
            import sqlite3
            conn = sqlite3.connect(DB_PATH, timeout=2)
            conn.execute("SELECT 1")
            conn.close()
        await asyncio.to_thread(check_sqlite)
        deps["sqlite"] = "ok"
    except Exception:
        deps["sqlite"] = "error"

    # Check ChromaDB directory
    deps["chromadb"] = "ok" if await asyncio.to_thread(_os.path.isdir, CHROMA_DB_PATH) else "missing"

    status["dependencies"] = deps
    if any(v == "error" for v in deps.values()):
        status["status"] = "degraded"
    return status


# --- Metrics ---
@app.get("/api/metrics")
async def metrics_endpoint():
    """Return system and application metrics."""
    metrics = get_metrics().get_summary()
    metrics["cache"] = cache_stats()
    return metrics


@app.get("/api/token-usage")
async def token_usage_endpoint():
    """Return lightweight token consumption data for the header counter."""
    m = get_metrics()
    with m._lock:
        calls = list(m._llm_calls)
    total_input = sum(c.get("input_tokens", 0) for c in calls)
    total_output = sum(c.get("output_tokens", 0) for c in calls)
    total_calls = len(calls)
    return {
        "input_tokens": total_input,
        "output_tokens": total_output,
        "total_tokens": total_input + total_output,
        "total_calls": total_calls,
    }


# --- Tokenization Prefetch ---
@app.post("/api/tokenize/prefetch")
async def prefetch_tokens(request: Request):
    """Trigger background tokenization for the given text to eliminate latency during generation."""
    body = await request.json()
    text = body.get("text", "")
    model = body.get("model", "gpt-4o")
    if text:
        from app.core.tokens import shadow_tokenizer
        shadow_tokenizer.prefetch(text, model)
    return {"status": "accepted"}
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
        agent_key = detect_agent(user_msg)
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
            from app.rag import explicit_rag_search
            # Strip @rag prefix if present
            rag_query = user_msg
            if rag_query.lower().startswith("@rag"):
                rag_query = rag_query[4:].strip()
            rag_context = explicit_rag_search(rag_query, k=5)
            if rag_context:
                llm_messages.insert(-1, {"role": "system", "content": rag_context})
        else:
            # Auto-RAG: silently inject if relevant context exists
            from app.rag import auto_rag_context
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
            from app.skill_registry import load_active_skills
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
        from app.skill_selector import get_skill_catalog_entry, get_skill_full_instructions

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
                    results_text = "\n\n".join(
                        f"[Tool result: {tr['tool']}]\n{tr['result'][:2000]}"
                        for tr in tool_results
                    )
                    instruction = "The tools have been executed and here are the results. "
                    if round_num >= MAX_TOOL_ROUNDS:
                        instruction += "You MUST now present a clear, complete answer based on these results. Do NOT use any tool_call blocks. Do NOT ask the user to run code. Directly present the answer or analysis."
                    else:
                        instruction += "You may analyze these results and output another ```tool_call block if you need to run more tools to complete the user's request. If you have all the information you need, directly present the final answer without any tool calls."

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
                    from app.memory import auto_extract_memory, auto_summarize_session
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


@app.post("/chat/upload-image")
async def chat_upload_image(file: UploadFile = File(...)):
    """Upload an image for use in vision chat.

    Returns a base64 data URL that can be embedded in a multimodal message.
    """
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(400, "Only image files are accepted")

    import base64
    content = await file.read()

    # Limit image size to 10 MB
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(413, "Image too large (max 10 MB)")

    b64 = base64.b64encode(content).decode("utf-8")
    data_url = f"data:{file.content_type};base64,{b64}"

    return {
        "data_url": data_url,
        "filename": file.filename,
        "content_type": file.content_type,
        "size_bytes": len(content),
    }


@app.post("/chat/humanize")
async def humanize_text(request: Request):
    """Rewrite AI-generated text to sound more natural and human.

    Inspired by Abacus.ai's Humanize Text feature.
    Uses the dedicated humanizer preprompt to reformulate text
    while preserving meaning, code blocks, and technical accuracy.
    """
    data = await request.json()
    text = data.get("text", "")
    if not text.strip():
        raise HTTPException(400, "No text provided")

    # Cap input to avoid excessive token usage
    if len(text) > 20_000:
        text = text[:20_000] + "\n\n... (truncated)"

    provider_key = data.get("provider", "")
    model_key = data.get("model", "")
    provider = get_llm_provider(provider_key or None)

    from app.core.preprompts import PREPROMPTS
    humanizer_prompt = PREPROMPTS["humanizer"]["system_prompt"]

    messages = [
        {"role": "system", "content": humanizer_prompt},
        {"role": "user", "content": f"Humanize this text:\n\n{text}"},
    ]

    kwargs = {}
    if model_key:
        kwargs["model"] = model_key

    import time as _time
    t0 = _time.time()
    result = ""
    async for chunk in provider.chat_stream(messages, **kwargs):
        result += chunk
    elapsed = _time.time() - t0

    # Record metrics
    input_tokens = count_tokens(text, model=model_key or "")
    output_tokens = count_tokens(result, model=model_key or "")
    get_metrics().record_llm_call(
        provider=provider_key or "default",
        model=model_key or "default",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_s=elapsed,
        session_id="humanize",
    )

    return {
        "humanized": result,
        "original_length": len(text),
        "humanized_length": len(result),
        "latency_s": round(elapsed, 2),
    }


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


@app.get("/notifications")
async def get_notifications(session_id: str = "", limit: int = 20):
    """Get recent notifications (REST fallback for non-WebSocket clients)."""
    try:
        from app.core.notifications import get_recent
        return get_recent(limit=limit, session_id=session_id or None)
    except Exception:
        return []


# --- Persistent Artifacts API (OpenClaw OS-inspired) ---

@app.get("/artifacts")
async def list_artifacts_endpoint(session_id: str = "", kind: str = "", pinned: bool = False, limit: int = 50):
    """List artifacts, optionally filtered by session/kind/pinned."""
    from app.core.artifacts import list_artifacts
    return list_artifacts(
        session_id=session_id or None,
        kind=kind or None,
        pinned_only=pinned,
        limit=limit,
    )


@app.get("/artifacts/{artifact_id}")
async def get_artifact_endpoint(artifact_id: str):
    """Get a single artifact by ID."""
    from app.core.artifacts import get_artifact
    artifact = get_artifact(artifact_id)
    if not artifact:
        raise HTTPException(404, "Artifact not found")
    return artifact


@app.post("/artifacts")
async def create_artifact_endpoint(request: Request):
    """Create a new artifact."""
    from app.core.artifacts import create_artifact
    data = await request.json()
    return create_artifact(
        title=data.get("title", "Untitled"),
        content=data.get("content", ""),
        session_id=data.get("session_id"),
        language=data.get("language", ""),
        kind=data.get("kind", "code"),
        parent_id=data.get("parent_id"),
    )


@app.put("/artifacts/{artifact_id}")
async def update_artifact_endpoint(artifact_id: str, request: Request):
    """Update an artifact. Set version: true to create a new version."""
    from app.core.artifacts import update_artifact, get_artifact, create_artifact
    data = await request.json()

    if data.get("version") and "content" in data:
        parent = get_artifact(artifact_id)
        if not parent:
            raise HTTPException(404, "Artifact not found")
        return create_artifact(
            title=data.get("title", parent["title"]),
            content=data["content"],
            session_id=parent.get("session_id"),
            language=data.get("language", parent.get("language", "")),
            kind=parent.get("kind", "code"),
            parent_id=artifact_id,
        )

    result = update_artifact(
        artifact_id,
        title=data.get("title"),
        content=data.get("content"),
        pinned=data.get("pinned"),
    )
    if not result:
        raise HTTPException(404, "Artifact not found")
    return result


@app.delete("/artifacts/{artifact_id}")
async def delete_artifact_endpoint(artifact_id: str):
    """Delete an artifact."""
    from app.core.artifacts import delete_artifact
    delete_artifact(artifact_id)
    return {"status": "deleted", "id": artifact_id}


@app.get("/artifacts/{artifact_id}/history")
async def artifact_history_endpoint(artifact_id: str):
    """Get the version history of an artifact."""
    from app.core.artifacts import get_artifact_history
    return get_artifact_history(artifact_id)


# --- Plugin Management API ---

@app.get("/plugins")
async def list_plugins_endpoint():
    """List all registered plugins."""
    from app.core.plugin_system import list_plugins
    return list_plugins()


@app.post("/plugins/{plugin_name}/toggle")
async def toggle_plugin_endpoint(plugin_name: str):
    """Enable or disable a plugin."""
    from app.core.plugin_system import get_plugin
    plugin = get_plugin(plugin_name)
    if not plugin:
        raise HTTPException(404, f"Plugin '{plugin_name}' not found")
    plugin.enabled = not plugin.enabled
    return {"name": plugin.name, "enabled": plugin.enabled}


# --- Upload Store API (OpenClaw OS-inspired) ---

@app.get("/uploads")
async def list_uploads(category: str = "", session_id: str = "", limit: int = 50):
    """List files in the upload store."""
    from app.core.upload_store import list_files
    return list_files(
        category=category or None,
        session_id=session_id or None,
        limit=limit,
    )


@app.get("/uploads/stats")
async def upload_stats():
    """Get upload store statistics."""
    from app.core.upload_store import get_store_stats
    return get_store_stats()


@app.get("/uploads/{file_id}")
async def get_upload(file_id: str):
    """Get file metadata by ID."""
    from app.core.upload_store import get_file
    meta = get_file(file_id)
    if not meta:
        raise HTTPException(404, "File not found")
    return meta


@app.delete("/uploads/{file_id}")
async def delete_upload(file_id: str):
    """Remove a file from the upload store."""
    from app.core.upload_store import delete_file
    deleted = delete_file(file_id)
    if not deleted:
        raise HTTPException(404, "File not found")
    return {"status": "deleted", "id": file_id}


# --- Structured UI API ---

@app.get("/ui/components")
async def get_ui_components():
    """Get available structured UI component schemas."""
    from app.core.structured_ui import COMPONENT_SCHEMAS
    return COMPONENT_SCHEMAS


# --- Tool Replay API (OpenClaw OS-inspired) ---

@app.get("/replays")
async def list_replays_endpoint(limit: int = 20):
    """List all available replay sessions."""
    from app.core.tool_replay import list_replays
    return list_replays(limit=limit)


@app.get("/replays/{session_id}")
async def get_replay_endpoint(session_id: str):
    """Get the full tool replay log for a session."""
    from app.core.tool_replay import get_session_replay
    return get_session_replay(session_id)


@app.get("/replays/{session_id}/summary")
async def replay_summary_endpoint(session_id: str):
    """Get a summary of a session's tool replay."""
    from app.core.tool_replay import get_replay_summary
    return get_replay_summary(session_id)


@app.get("/replays/{session_id}/workflow")
async def replay_workflow_endpoint(session_id: str):
    """Export a replay as a reusable workflow definition."""
    from app.core.tool_replay import export_as_workflow
    return export_as_workflow(session_id)


@app.delete("/replays/{session_id}")
async def delete_replay_endpoint(session_id: str):
    """Delete a replay log."""
    from app.core.tool_replay import delete_replay
    deleted = delete_replay(session_id)
    if not deleted:
        raise HTTPException(404, "Replay not found")
    return {"status": "deleted", "session_id": session_id}


# --- Performance Dashboard API ---

@app.get("/dashboard/metrics")
async def dashboard_metrics():
    """Get aggregated system performance metrics."""
    from app.core.dashboard import get_system_metrics
    return get_system_metrics()


# --- App Builder API (OpenClaw OS-inspired) ---

@app.post("/apps")
async def create_app_endpoint(request: Request):
    """Create a new mini web application."""
    from app.core.app_builder import create_app
    data = await request.json()
    name = data.get("name", "Untitled App")
    files = data.get("files", {})
    session_id = data.get("session_id")
    template = data.get("template")
    icon = data.get("icon")
    visual = data.get("visual")

    if not files and not template:
        raise HTTPException(400, "Provide 'files' or 'template'")

    result = create_app(name, files, session_id=session_id, template=template, icon=icon, visual=visual)
    return result


@app.get("/apps")
async def list_apps_endpoint(limit: int = 20):
    """List all created mini-apps."""
    from app.core.app_builder import list_apps
    return list_apps(limit=limit)


@app.post("/apps/import-from-workspace")
async def import_app_from_workspace(request: Request):
    """Import a workspace project folder as a mini-app."""
    from app.core.app_builder import import_from_workspace
    data = await request.json()
    project = data.get("project", "").strip()
    name = data.get("name", "").strip()
    session_id = data.get("session_id")
    icon = data.get("icon")

    if not project:
        raise HTTPException(400, "'project' is required")
    if not name:
        name = project.split("/")[-1] or project

    try:
        from config import WORKSPACE_DIR
        result = import_from_workspace(
            project_path=project,
            name=name,
            workspace_dir=WORKSPACE_DIR,
            session_id=session_id,
            icon=icon,
        )
        return result
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/apps/templates")
async def list_templates():
    """List available starter templates."""
    from app.core.app_builder import STARTER_TEMPLATES
    return {k: {"name": v["name"], "description": v["description"]}
            for k, v in STARTER_TEMPLATES.items()}


@app.get("/apps/{app_id}/meta")
async def get_app_meta(app_id: str):
    """Get app metadata."""
    from app.core.app_builder import get_app
    meta = get_app(app_id)
    if not meta:
        raise HTTPException(404, "App not found")
    return meta


@app.put("/apps/{app_id}")
async def update_app_endpoint(app_id: str, request: Request):
    """Update an app's files or metadata."""
    from app.core.app_builder import update_app
    data = await request.json()
    files = data.get("files", None)
    name = data.get("name")
    icon = data.get("icon")
    visual = data.get("visual")
    result = update_app(app_id, files=files, name=name, icon=icon, visual=visual)
    if not result:
        raise HTTPException(404, "App not found")
    return result


@app.delete("/apps/{app_id}")
async def delete_app_endpoint(app_id: str):
    """Delete an app."""
    from app.core.app_builder import delete_app
    deleted = delete_app(app_id)
    if not deleted:
        raise HTTPException(404, "App not found")
    return {"status": "deleted", "id": app_id}


# Serve app static files (HTML/CSS/JS)
from fastapi.responses import FileResponse as _AppFileResponse


@app.get("/apps/{app_id}/preview")
async def preview_app(app_id: str):
    """Serve the app's index.html for preview."""
    from app.core.app_builder import APPS_DIR
    filepath = _os.path.join(APPS_DIR, app_id, "index.html")
    if not _os.path.exists(filepath):
        raise HTTPException(404, "App not found or has no index.html")
    return _AppFileResponse(filepath, media_type="text/html")


@app.get("/apps/{app_id}/files")
async def get_app_files(app_id: str):
    """Return all file contents for a mini-app (for inline code editor)."""
    from app.core.app_builder import get_app, get_app_file
    meta = get_app(app_id)
    if not meta:
        raise HTTPException(404, "App not found")
    files = {}
    for fname in meta.get("files", []):
        content = get_app_file(app_id, fname)
        if content is not None:
            files[fname] = content
    return {"id": app_id, "name": meta.get("name", ""), "files": files}


@app.delete("/apps/{app_id}/files/{filename}")
async def delete_app_file_endpoint(app_id: str, filename: str):
    """Delete a single file from a mini-app."""
    from app.core.app_builder import delete_app_file
    deleted = delete_app_file(app_id, filename)
    if not deleted:
        raise HTTPException(404, "File not found")
    return {"status": "deleted", "app_id": app_id, "filename": filename}


# --- App Secrets API ---

@app.get("/apps/{app_id}/secrets")
async def list_app_secrets(app_id: str):
    """List all secrets for an app (values masked)."""
    from app.core.app_services import get_secrets
    return {"app_id": app_id, "secrets": get_secrets(app_id)}


@app.post("/apps/{app_id}/secrets")
async def set_app_secret(app_id: str, request: Request):
    """Create or update a secret."""
    from app.core.app_services import set_secret
    data = await request.json()
    key = data.get("key", "").strip()
    value = data.get("value", "")
    if not key:
        raise HTTPException(400, "Secret key is required")
    return set_secret(app_id, key, value)


@app.delete("/apps/{app_id}/secrets/{key}")
async def delete_app_secret(app_id: str, key: str):
    """Delete a secret."""
    from app.core.app_services import delete_secret
    if not delete_secret(app_id, key):
        raise HTTPException(404, "Secret not found")
    return {"status": "deleted", "key": key}


# --- App Secrets Runtime (accessible from app iframe) ---

@app.get("/apps/{app_id}/api/secrets/{key}")
async def get_app_secret_runtime(app_id: str, key: str):
    """Return raw secret value (for runtime use by the app)."""
    from app.core.app_services import get_secret_value
    value = get_secret_value(app_id, key)
    if value is None:
        raise HTTPException(404, "Secret not found")
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(value)


# --- App Database API ---

@app.get("/apps/{app_id}/api/db/tables")
async def list_app_db_tables(app_id: str):
    """List tables in an app's database."""
    from app.core.app_services import list_tables
    return {"app_id": app_id, "tables": list_tables(app_id)}


@app.post("/apps/{app_id}/api/db/query")
async def app_db_query(app_id: str, request: Request):
    """Execute a SQL query against an app's database."""
    from app.core.app_services import execute_query
    data = await request.json()
    sql = data.get("sql", "").strip()
    params = data.get("params", [])
    if not sql:
        raise HTTPException(400, "SQL query is required")
    result = execute_query(app_id, sql, params)
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


@app.get("/apps/{app_id}/api/db/tables/{table}/schema")
async def app_db_table_schema(app_id: str, table: str):
    """Get column schema for a table."""
    from app.core.app_services import get_table_schema
    schema = get_table_schema(app_id, table)
    return {"table": table, "columns": schema}


# --- App ZIP Export ---

@app.get("/apps/{app_id}/export")
async def export_app_zip(app_id: str):
    """Export an app as a downloadable ZIP file."""
    import io
    import zipfile
    from app.core.app_builder import get_app, APPS_DIR
    from app.core.app_services import INTERNAL_FILES
    from fastapi.responses import StreamingResponse

    meta = get_app(app_id)
    if not meta:
        raise HTTPException(404, "App not found")

    app_dir = _os.path.join(APPS_DIR, app_id)
    buf = io.BytesIO()
    app_name = meta.get("name", app_id).replace(" ", "_")

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname in _os.listdir(app_dir):
            if fname in INTERNAL_FILES:
                continue
            fpath = _os.path.join(app_dir, fname)
            if _os.path.isfile(fpath):
                zf.write(fpath, f"{app_name}/{fname}")

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{app_name}.zip"'},
    )


@app.post("/apps/{app_id}/export-to-workspace")
async def export_app_to_workspace(app_id: str, request: Request):
    """Export app files into the workspace as an editable project folder."""
    from app.core.app_builder import get_app, APPS_DIR
    from app.core.app_services import INTERNAL_FILES

    meta = get_app(app_id)
    if not meta:
        raise HTTPException(404, "App not found")

    data = await request.json()
    project_name = data.get("project", "").strip()
    if not project_name:
        # Default to app name, sanitized
        project_name = (meta.get("name") or app_id).replace(" ", "_").replace("..", "")
        project_name = project_name.replace("/", "_").replace("\\", "_").strip("._")

    from config import WORKSPACE_DIR
    ws_base = _os.path.realpath(WORKSPACE_DIR)
    project_dir = _os.path.realpath(_os.path.join(ws_base, project_name))
    if not project_dir.startswith(ws_base):
        raise HTTPException(403, "Invalid project path")

    app_dir = _os.path.join(APPS_DIR, app_id)
    written = 0
    errors = []

    for root, dirs, files in _os.walk(app_dir):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for fname in sorted(files):
            if fname in INTERNAL_FILES or fname.startswith('.'):
                continue
            src = _os.path.join(root, fname)
            rel = _os.path.relpath(src, app_dir)
            dst = _os.path.join(project_dir, rel)
            try:
                _os.makedirs(_os.path.dirname(dst), exist_ok=True)
                with open(src, "rb") as fsrc:
                    with open(dst, "wb") as fdst:
                        fdst.write(fsrc.read())
                written += 1
            except Exception as e:
                errors.append(f"{rel}: {e}")

    return {
        "status": "ok",
        "project": project_name,
        "app_id": app_id,
        "written": written,
        "errors": errors,
    }


@app.get("/apps/{app_id}/{filename:path}")
async def serve_app_file(app_id: str, filename: str):
    """Serve a file from a mini-app (blocks internal files, supports subdirs)."""
    from app.core.app_builder import APPS_DIR
    from app.core.app_services import INTERNAL_FILES
    base = _os.path.basename(filename)
    if base in INTERNAL_FILES:
        raise HTTPException(403, "Access denied")
    # Support subdirectory paths — sanitize to prevent traversal
    clean = filename.replace("..", "").lstrip("/")
    filepath = _os.path.realpath(_os.path.join(APPS_DIR, app_id, clean))
    app_root = _os.path.realpath(_os.path.join(APPS_DIR, app_id))
    if not filepath.startswith(app_root):
        raise HTTPException(403, "Path traversal not allowed")
    if not _os.path.exists(filepath):
        raise HTTPException(404, "File not found")
    return _AppFileResponse(filepath)


# --- Battle Arena API ---

# Per-model timeout for Arena generation (seconds)
_ARENA_MODEL_TIMEOUT = 300  # 5 minutes max per model


@app.post("/arena/send")
async def arena_send(request: Request):
    """Start generation for multiple models in the Arena.

    Ollama/local models are executed **sequentially** in a single coordinator
    task to prevent VRAM saturation on remote servers (DGx10).  Each Ollama
    model is unloaded after completion with a pause to let VRAM flush.

    Cloud providers run in parallel since they don't share GPU resources.
    """
    data = await request.json()
    user_msg = _sanitize_input(data.get("message", "").strip())
    models = data.get("models", [])

    if not user_msg:
        raise HTTPException(400, "Message is required")
    if not models or len(models) > 10:
        raise HTTPException(400, "1 to 10 models required")

    streams = []
    # Separate Ollama models from cloud providers
    ollama_entries: list[dict] = []
    cloud_entries: list[dict] = []

    for m in models:
        provider_key = m.get("provider", "local")
        model_key = m.get("model", "")
        stream_id = str(uuid.uuid4())
        _arena_queues[stream_id] = asyncio.Queue()
        entry = {
            "stream_id": stream_id,
            "provider": provider_key,
            "model": model_key,
        }
        streams.append(entry)
        if provider_key in ("ollama", "local"):
            ollama_entries.append(entry)
        else:
            cloud_entries.append(entry)

    # ------------------------------------------------------------------
    # Shared per-model generation coroutine (no unload — caller handles)
    # ------------------------------------------------------------------
    async def _generate_single(s_id: str, p_key: str, m_key: str):
        """Generate tokens for one model and push them into its queue."""
        queue = _arena_queues.get(s_id)
        if queue is None:
            return
        try:
            import time as _t
            t0 = _t.perf_counter()
            tokens_count = 0

            provider = get_llm_provider(p_key)
            kwargs: dict = {}
            if m_key:
                kwargs["model"] = m_key
            kwargs["max_tokens"] = 8192

            messages = [
                {"role": "system", "content": "You are a helpful and detailed AI assistant. Provide complete and comprehensive answers. Do NOT truncate your response."},
                {"role": "user", "content": user_msg},
            ]

            async for token in provider.chat_stream(messages, **kwargs):
                # Strip special tokens from local models
                if any(marker in token for marker in ["<|endoftext|>", "<|im_start|>", "<|im_end|>", "<|eot_id|>", "</s>", "<|end|>"]):
                    for marker in ["<|endoftext|>", "<|im_start|>", "<|im_end|>", "<|eot_id|>", "</s>", "<|end|>"]:
                        token = token.replace(marker, "")
                    if not token:
                        continue
                tokens_count += 1
                await queue.put(token)

            total_time = _t.perf_counter() - t0
            tps = tokens_count / total_time if total_time > 0 else 0
            import json as _json
            stats_msg = f'\n\n__STATS__{_json.dumps({"time": round(total_time, 2), "tokens": tokens_count, "tps": round(tps, 1)})}__STATS__\n\n'
            await queue.put(stats_msg)

            # Track metrics
            input_tokens = count_tokens(user_msg, model=m_key or "")
            from app.metrics import get_metrics
            get_metrics().record_llm_call(
                provider=p_key,
                model=m_key or getattr(provider, "default_model", "unknown"),
                input_tokens=input_tokens,
                output_tokens=tokens_count,
                latency_s=total_time,
                session_id="arena",
            )
        except Exception as e:
            logger.error("Arena LLM error (%s/%s): %s", p_key, m_key, e)
            await queue.put(f"\n\n❌ **Error**: {e}")
        finally:
            await queue.put(None)  # signal end-of-stream

    # ------------------------------------------------------------------
    # Cloud provider tasks — safe to run in parallel
    # ------------------------------------------------------------------
    for entry in cloud_entries:
        async def _cloud_wrapper(e=entry):
            try:
                await asyncio.wait_for(
                    _generate_single(e["stream_id"], e["provider"], e["model"]),
                    timeout=_ARENA_MODEL_TIMEOUT,
                )
            except asyncio.TimeoutError:
                q = _arena_queues.get(e["stream_id"])
                if q:
                    await q.put("\n\n⏱️ **Timeout** — model took too long.")
                    await q.put(None)
        asyncio.create_task(_cloud_wrapper())

    # ------------------------------------------------------------------
    # Ollama coordinator — runs models ONE AT A TIME with unload between
    # ------------------------------------------------------------------
    if ollama_entries:
        async def _ollama_coordinator():
            for entry in ollama_entries:
                s_id = entry["stream_id"]
                m_key = entry["model"]
                try:
                    await asyncio.wait_for(
                        _generate_single(s_id, entry["provider"], m_key),
                        timeout=_ARENA_MODEL_TIMEOUT,
                    )
                except asyncio.TimeoutError:
                    logger.error("Arena Ollama timeout for %s after %ds", m_key, _ARENA_MODEL_TIMEOUT)
                    q = _arena_queues.get(s_id)
                    if q:
                        await q.put(f"\n\n⏱️ **Timeout** — `{m_key}` took over {_ARENA_MODEL_TIMEOUT}s.")
                        await q.put(None)
                except Exception as e:
                    logger.error("Arena Ollama coordinator error for %s: %s", m_key, e)
                finally:
                    # Unload model to free VRAM before loading the next one
                    try:
                        await _unload_ollama_model(m_key)
                    except Exception:
                        pass
                    # Pause to let VRAM actually flush on the remote GPU
                    await asyncio.sleep(3)

        asyncio.create_task(_ollama_coordinator())

    return {"status": "processing", "streams": streams}


@app.get("/arena/stream/{stream_id}")
async def arena_stream(stream_id: str):
    """SSE endpoint for Arena columns."""
    if stream_id not in _arena_queues:
        raise HTTPException(404, "Stream not found")

    async def event_generator():
        queue = _arena_queues[stream_id]
        try:
            while True:
                try:
                    # Keep-alive every 15s to prevent proxy drops while
                    # waiting behind the Ollama sequential queue.
                    token = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield {"event": "keepalive", "data": ""}
                    continue

                if token is None:
                    yield {"data": "[DONE]"}
                    break
                yield {"data": token}
        finally:
            # Immediate cleanup — no dangling references
            _arena_queues.pop(stream_id, None)

    return EventSourceResponse(event_generator())


async def _unload_ollama_model(model_name: str):
    """Unload a specific Ollama model to free up VRAM and prevent saturation."""
    from app.core.llm_provider import _resolve_ollama_host, _resolve_ollama_api_key, _resolve_ollama_verify
    import httpx
    if not model_name:
        return
    try:
        ollama_host = _resolve_ollama_host()
        ollama_key = _resolve_ollama_api_key()
        headers = {"Authorization": f"Bearer {ollama_key}"} if ollama_key else {}
        async with httpx.AsyncClient(verify=_resolve_ollama_verify()) as client:
            await client.post(
                f"{ollama_host}/api/generate",
                json={"model": model_name, "keep_alive": 0},
                headers=headers,
                timeout=30.0
            )
            logger.info("Unloaded Ollama model: %s", model_name)
    except Exception as e:
        logger.warning("Failed to unload Ollama model %s: %s", model_name, e)


@app.post("/arena/evaluate")
async def arena_evaluate(request: Request):
    """Judge the models' responses."""
    data = await request.json()
    prompt = data.get("prompt", "")
    responses = data.get("responses", {})  # dict of stream_id -> text
    
    from config import LLM_PROVIDER
    provider_key = LLM_PROVIDER
    provider = get_llm_provider(provider_key)
    model_key = getattr(provider, "default_model", "")
    
    if not prompt or not responses:
        raise HTTPException(400, "Prompt and responses required")
        
    kwargs = {}
    if model_key:
        kwargs["model"] = model_key

    if provider_key in ("ollama", "local"):
        kwargs["response_format"] = {"type": "json_object"}
    
    sys_prompt = "You are an impartial AI judge. Your task is to evaluate an AI response to a given prompt. Score it out of 10 and give a 1-sentence explanation."
    
    import json
    import re
    from app.metrics import get_metrics
    
    final_ratings = {}
    
    try:
        # Evaluate each response individually
        for s_id, text in responses.items():
            try:
                user_prompt = f"PROMPT:\n{prompt}\n\nRESPONSE TO EVALUATE:\n{text}\n\n"
                user_prompt += "Evaluate the response above. Format your output strictly as a JSON object with EXACTLY two keys: 'score' (number from 0 to 10) and 'rationale' (string, 1 short sentence). DO NOT wrap the JSON in markdown blocks or output any extra text. Example: {\"score\": 8, \"rationale\": \"...\"}"
                
                t0 = time.perf_counter()
                result_text = ""
                async for token in provider.chat_stream([
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": user_prompt}
                ], **kwargs):
                    result_text += token
                    
                latency_s = time.perf_counter() - t0
                input_tokens = count_message_tokens([{"role": "system", "content": sys_prompt}, {"role": "user", "content": user_prompt}])
                output_tokens = count_tokens(result_text)
                
                get_metrics().record_llm_call(
                    provider=provider_key,
                    model=model_key or getattr(provider, "default_model", "unknown"),
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    latency_s=latency_s,
                    session_id="arena_eval"
                )
                
                # Parse JSON
                clean_text = re.sub(r'```json\s*', '', result_text, flags=re.IGNORECASE)
                clean_text = re.sub(r'```\s*', '', clean_text)
                clean_text = clean_text.strip()
                
                parsed = {}
                parse_success = False
                
                try:
                    match = re.search(r'\{[\s\S]*\}', clean_text)
                    if match:
                        parsed = json.loads(match.group(0))
                    else:
                        parsed = json.loads(clean_text)
                    parse_success = True
                except json.JSONDecodeError:
                    pass
                
                score_val = None
                rationale_val = None
                
                if parse_success and isinstance(parsed, dict):
                    # Look for variations of keys
                    score_val = parsed.get("score", parsed.get("Score", parsed.get("note", parsed.get("Note", parsed.get("rating", parsed.get("rating"))))))
                    rationale_val = parsed.get("rationale", parsed.get("Rationale", parsed.get("justification", parsed.get("Justification", parsed.get("explanation", parsed.get("reasoning"))))))
                    
                    if score_val is None and "ratings" in parsed and isinstance(parsed["ratings"], dict):
                        first_val = list(parsed["ratings"].values())[0] if parsed["ratings"] else {}
                        score_val = first_val.get("score", first_val.get("Score", first_val.get("note")))
                        rationale_val = first_val.get("rationale", first_val.get("Rationale", first_val.get("justification")))
                        
                # Aggressive fallback if no valid score/rationale found via JSON
                if score_val is None or rationale_val is None:
                    # Look for a score in the raw text
                    score_match = re.search(r'(?:score|note|évaluation|rating)[\s"\'=:]*(\d+(?:\.\d+)?)(?:/10)?', clean_text, re.IGNORECASE)
                    if score_match:
                        score_val = float(score_match.group(1))
                    else:
                        # Find any obvious score format like "8/10" or "8 sur 10"
                        any_num = re.search(r'\b([0-9](?:\.[0-9]+)?|10)\b\s*(?:/|sur)\s*10', clean_text)
                        score_val = float(any_num.group(1)) if any_num else "-"
                        
                    # Look for a rationale in the raw text
                    rat_match = re.search(r'(?:rationale|justification|explanation|raison)[\s"\'=:]*([^"\'\n\{\}]+)', clean_text, re.IGNORECASE)
                    if rat_match:
                        rationale_val = rat_match.group(1).strip()
                    else:
                        # Grab the first 250 chars of cleaned text as rationale
                        clean_no_json = re.sub(r'["\{\}\[\]]', '', clean_text).strip()
                        if re.search(r'^(?:score|note)', clean_no_json, re.IGNORECASE):
                            clean_no_json = re.sub(r'^(?:score|note).*?\d+.*?\n', '', clean_no_json, flags=re.IGNORECASE).strip()
                        rationale_val = clean_no_json[:250] + "..." if len(clean_no_json) > 250 else clean_no_json
                
                # Sanitize the final values
                try:
                    if score_val != "-":
                        score_val = float(score_val)
                        if score_val > 10: score_val = 10.0
                        if score_val < 0: score_val = 0.0
                except (ValueError, TypeError):
                    score_val = "-"
                    
                if rationale_val is None or str(rationale_val).strip() == "":
                    rationale_val = clean_text[:250] + "..." if len(clean_text) > 250 else clean_text
                    
                error_flag = False
                if score_val == "-":
                    error_flag = True
                    if not rationale_val or rationale_val == "..." or rationale_val.strip() == "":
                        rationale_val = "The model was unable to evaluate the response (unreadable format)."
                    
                final_ratings[s_id] = {"score": score_val, "rationale": str(rationale_val).strip(), "error": error_flag}
            except Exception as e:
                logger.error("Arena evaluation error for %s: %s. Last Response: %s", s_id, e, locals().get('result_text', ''))
                final_ratings[s_id] = {"score": "-", "rationale": f"Generation error: {str(e)[:150]}", "error": True}
                
        return {"ratings": final_ratings}
    except Exception as e:
        logger.error("Arena evaluation error: %s. Last Response: %s", e, locals().get('result_text', ''))
        raise HTTPException(500, detail="The AI judge failed to return a valid evaluation JSON (timeout or format error).")
    finally:
        # Unload the evaluation model to free VRAM for the next request
        if provider_key in ("ollama", "local"):
            try:
                await _unload_ollama_model(model_key)
            except Exception:
                pass


# --- Preprompts API ---
@app.get("/api/preprompts")
async def get_preprompts():
    """Return all available pre-prompt templates."""
    return {"preprompts": list_preprompts()}


# --- Providers API ---
@app.get("/api/providers")
async def get_providers():
    """Return available LLM providers and their models."""
    return {"providers": await _get_provider_models()}


# --- LLM Health Status API ---
@app.get("/api/llm-status")
async def get_llm_status():
    """Return current local LLM status from Ollama."""
    try:
        from config import OLLAMA_MODEL
        from app.core.llm_provider import _resolve_ollama_host, _resolve_ollama_api_key
        import httpx
        ollama_host = _resolve_ollama_host()
        ollama_key = _resolve_ollama_api_key()
        headers = {"Authorization": f"Bearer {ollama_key}"} if ollama_key else {}
        async with httpx.AsyncClient(timeout=3.0, verify=OLLAMA_VERIFY_SSL) as client:
            resp = await client.get(f"{ollama_host}/api/tags", headers=headers)
            if resp.status_code == 200:
                return {"status": "running", "active_model": OLLAMA_MODEL, "host": ollama_host}
        return {"status": "stopped", "active_model": OLLAMA_MODEL, "host": ollama_host}
    except Exception:
        return {"status": "stopped", "detail": "Cannot reach Ollama"}


# --- Code autocomplete API ---

# FIM tokens for common code models
_FIM_MODELS = {"codellama", "deepseek-coder", "starcoder", "codegemma", "qwen2.5-coder", "stable-code"}

def _is_fim_model(model_name: str) -> bool:
    """Check if a model likely supports Fill-in-the-Middle."""
    base = model_name.split(":")[0].lower()
    return any(f in base for f in _FIM_MODELS)

def _clean_completion(text: str, prefix: str, intent: str = "continuation") -> str:
    """Clean up a raw LLM completion for inline display.
    
    Args:
        text: Raw LLM output
        prefix: Code before cursor
        intent: 'comment_generate' | 'correction' | 'continuation'
    """
    if not text:
        return ""
    text = text.strip()
    # Strip markdown fences if the model wrapped it
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]
        text = "\n".join(lines)
    if text.endswith("```"):
        text = text[:-3].rstrip()
    text = text.strip("\n")
    if not text:
        return ""
    # Remove meta-commentary lines
    lines = text.split("\n")
    cleaned = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("//") and any(w in stripped.lower() for w in
            ["here", "the following", "complete", "continuation", "rest of",
             "this function", "this code", "implementation"]):
            continue
        if stripped.startswith("#") and any(w in stripped.lower() for w in
            ["here", "the following", "complete", "continuation", "rest of",
             "this function", "this code", "implementation"]):
            continue
        if stripped in ("...", "…", "# ...", "// ...", "# TODO", "// TODO"):
            continue
        # Skip lines that look like LLM meta-instructions
        if stripped.startswith("Note:") or stripped.startswith("Explanation:"):
            continue
        cleaned.append(line)
    text = "\n".join(cleaned).strip("\n")
    if not text:
        return ""

    # Adaptive line limit based on intent
    max_lines = 20 if intent == "comment_generate" else 8
    lines = text.split("\n")
    if len(lines) > max_lines:
        text = "\n".join(lines[:max_lines])

    # Don't return if it just repeats the current line
    last_prefix_line = prefix.rstrip().split("\n")[-1].strip() if prefix.strip() else ""
    if last_prefix_line and text.strip() == last_prefix_line:
        return ""
    if last_prefix_line and text.startswith(last_prefix_line):
        text = text[len(last_prefix_line):]
    return text.rstrip()


# Intent-specific prompt builders for local (Ollama) models
def _build_local_prompt(intent: str, context_prefix: str, suffix_preview: str,
                        file_path: str, language: str) -> tuple[str, list[str]]:
    """Build prompt and stop tokens for Ollama based on intent.
    
    Returns: (prompt, stop_tokens)
    """
    if intent == "comment_generate":
        # Extract the comment text to guide generation
        prompt = (
            f"# File: {file_path} [{language}]\n"
            f"# Read the comment(s) above the cursor and generate the corresponding code.\n"
            f"# Output ONLY the implementation code. No explanations. No repeating the comment.\n\n"
            f"{context_prefix}"
        )
        stop_tokens = ["\n\n\n", "# File:", "# Task:", "# Rules:", "```"]
    elif intent == "correction":
        prompt = (
            f"# File: {file_path} [{language}]\n"
            f"# The user is editing code mid-line. Complete or fix the expression at the cursor.\n"
            f"# Output ONLY the missing part to make the line correct. No explanations.\n\n"
            f"{context_prefix}"
        )
        if suffix_preview:
            prompt += f"{{{{CURSOR}}}}{suffix_preview}"
        stop_tokens = ["\n\n", "# File:", "# Task:", "# Rules:", "```"]
    else:
        # continuation (default)
        prompt = (
            f"# File: {file_path} [{language}]\n"
            f"# Continue the code naturally. Output ONLY code, no explanations.\n\n"
            f"{context_prefix}"
        )
        stop_tokens = ["\n\n\n", "# File:", "# Task:", "# Rules:"]
    return prompt, stop_tokens


# Intent-specific system/user messages for external providers
def _build_external_messages(intent: str, context_prefix: str, suffix_preview: str,
                             file_path: str, language: str) -> list[dict]:
    """Build chat messages for external providers based on intent."""
    if intent == "comment_generate":
        system_msg = (
            "You are an inline code generator embedded in an IDE. "
            "The user has written a comment describing what code they want. "
            "Your job is to generate the implementation code that fulfills the comment. "
            "Rules:\n"
            "- Output ONLY raw code. No markdown. No fences. No backticks.\n"
            "- Do NOT repeat the comment. Start with the code directly.\n"
            "- Generate a complete, working implementation (function, class, or block).\n"
            "- Match the existing code style and indentation.\n"
            "- Output up to 20 lines.\n"
            "- If you're unsure, output nothing."
        )
    elif intent == "correction":
        system_msg = (
            "You are an inline code correction engine embedded in an IDE. "
            "The user is editing code mid-line and needs help completing or fixing the current expression. "
            "Rules:\n"
            "- Output ONLY the missing code fragment to complete/fix the expression.\n"
            "- No markdown. No fences. No backticks. No explanations.\n"
            "- Output should seamlessly connect the text before and after the cursor.\n"
            "- Output 1-3 lines maximum.\n"
            "- If you're unsure, output nothing.\n"
            "- Do NOT repeat code that's already written."
        )
    else:
        system_msg = (
            "You are an inline code completion engine embedded in an IDE. "
            "Your ONLY job is to predict what code comes next at the cursor position. "
            "Rules:\n"
            "- Output ONLY raw code. No markdown. No fences. No backticks.\n"
            "- No explanations. No comments about what the code does.\n"
            "- Continue naturally from the last line, maintaining the same style and indentation.\n"
            "- Output 1-6 lines maximum.\n"
            "- If you're unsure, output nothing.\n"
            "- Do NOT repeat code that's already written."
        )

    user_msg = f"[{language}] {file_path}\n\n{context_prefix}"
    if suffix_preview:
        user_msg += f"\n{{{{CURSOR}}}}\n{suffix_preview}"
    else:
        user_msg += "\n{{CURSOR}}"

    if intent == "comment_generate":
        user_msg += "\n\nGenerate the code described in the comment above {{CURSOR}}:"
    elif intent == "correction":
        user_msg += "\n\nComplete/fix the expression at {{CURSOR}}:"
    else:
        user_msg += "\n\nComplete the code at {{CURSOR}}:"

    return [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_msg},
    ]


@app.post("/api/autocomplete")
async def api_autocomplete(request: Request):
    """Provide inline code completion using the LLM.

    Strategy:
    1. FIM-native models → Ollama /api/generate with FIM tokens
    2. All other Ollama models → Ollama /api/generate with intent-specific prompt
    3. External providers → chat_stream with intent-specific messages
    """
    data = await request.json()
    prefix = data.get("prefix", "")
    suffix = data.get("suffix", "")
    language = data.get("language", "")
    file_path = data.get("file_path", "")
    intent = data.get("intent", "continuation")  # NEW: intent from frontend
    max_tokens = min(data.get("max_tokens", 120), 300)

    if not prefix.strip():
        return {"completion": ""}

    provider_key = data.get("provider", "local")
    model_key = data.get("model", "")

    # Adapt temperature by intent
    temperature = 0.1 if intent == "correction" else 0.2 if intent == "comment_generate" else 0.15

    # ============================================================
    # LOCAL MODELS: use Ollama /api/generate directly (fast path)
    # ============================================================
    if provider_key in ("local", "ollama"):
        try:
            from config import OLLAMA_HOST, OLLAMA_MODEL

            prefix_lines = prefix.split("\n")
            context_prefix = "\n".join(prefix_lines[-40:])  # More context for generation
            suffix_preview = "\n".join(suffix.split("\n")[:8]) if suffix.strip() else ""

            if _is_fim_model(model_key or ""):
                prompt = f"<|fim_prefix|>{context_prefix}<|fim_suffix|>{suffix_preview}<|fim_middle|>"
                stop_tokens = ["<|fim_pad|>", "<|endoftext|>", "<|fim_prefix|>",
                               "<|fim_suffix|>", "<|fim_middle|>", "\n\n\n"]
                payload = {
                    "model": model_key or OLLAMA_MODEL,
                    "prompt": prompt,
                    "raw": True,
                    "stream": False,
                    "options": {
                        "num_predict": max_tokens,
                        "temperature": temperature,
                        "top_p": 0.9,
                        "repeat_penalty": 1.1,
                        "stop": stop_tokens,
                    },
                }
            else:
                prompt, stop_tokens = _build_local_prompt(
                    intent, context_prefix, suffix_preview, file_path, language
                )
                payload = {
                    "model": model_key or OLLAMA_MODEL,
                    # /no_think disables Qwen 3 reasoning chain for fast output
                    "prompt": f"/no_think\n{prompt}",
                    "system": "You are a code completion assistant. Output ONLY the raw code. No markdown, no explanations.",
                    "raw": False,
                    "stream": False,
                    "options": {
                        "num_predict": max_tokens,
                        "temperature": temperature,
                        "top_p": 0.9,
                        "repeat_penalty": 1.1,
                        "stop": stop_tokens,
                    },
                }

            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{OLLAMA_HOST}/api/generate",
                    json=payload,
                )
                if resp.status_code == 200:
                    raw = resp.json().get("response", "")
                    result = _clean_completion(raw, prefix, intent)
                    logger.info("Autocomplete [%s/%s]: %d→%d chars",
                                model_key, intent, len(raw), len(result))
                    return {"completion": result}
                else:
                    logger.warning("Ollama autocomplete HTTP %s: %s",
                                   resp.status_code, resp.text[:200])
        except Exception as e:
            logger.warning("Ollama autocomplete error: %s", e)

        return {"completion": ""}

    # ============================================================
    # EXTERNAL PROVIDERS: chat_stream with intent-specific messages
    # ============================================================
    prefix_lines = prefix.split("\n")
    context_prefix = "\n".join(prefix_lines[-40:])
    suffix_preview = "\n".join(suffix.split("\n")[:8]) if suffix.strip() else ""

    messages = _build_external_messages(
        intent, context_prefix, suffix_preview, file_path, language
    )

    # Adaptive line limit for streaming
    max_stream_lines = 20 if intent == "comment_generate" else 8

    try:
        provider = get_llm_provider(provider_key)
        kwargs = {"max_tokens": max_tokens, "temperature": temperature}
        if model_key:
            kwargs["model"] = model_key
        result = ""
        async for token in provider.chat_stream(messages, **kwargs):
            result += token
            if result.count("\n") > max_stream_lines or len(result) > 600:
                break
        result = _clean_completion(result, prefix, intent)
        return {"completion": result}
    except Exception as e:
        logger.warning("Autocomplete error: %s", e)
        return {"completion": ""}

# --- Audio Transcription API ---
_whisper_model = None

@app.post("/api/transcribe")
async def api_transcribe(file: UploadFile = File(...)):
    """Transcribe audio using local openai-whisper model."""
    import tempfile
    import os
    import whisper

    global _whisper_model
    if _whisper_model is None:
        try:
            logger.info("Loading local Whisper model (base)...")
            _whisper_model = whisper.load_model("base")
        except Exception as e:
            logger.error("Failed to load Whisper model: %s", e)
            return {"error": f"Model load failed: {e}"}

    try:
        # Save uploaded file to a temporary file for whisper to read
        with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name

        # Transcribe
        result = _whisper_model.transcribe(tmp_path)
        
        # Cleanup
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

        return {"text": result["text"]}
    except Exception as e:
        logger.error("Transcription error: %s", e)
        return {"error": str(e)}


# --- RAG Profile API ---
@app.get("/api/rag-profiles")
async def api_list_rag_profiles():
    import os
    from config import PROFILES_DIR
    os.makedirs(PROFILES_DIR, exist_ok=True)
    files = []
    for root, _, filenames in os.walk(PROFILES_DIR):
        for f in filenames:
            if f.endswith(".md"):
                rel_path = os.path.relpath(os.path.join(root, f), PROFILES_DIR)
                # Normalize path separators for frontend
                files.append(rel_path.replace("\\", "/"))
    
    if "user/USER.md" not in files and "USER.md" not in files:
        files.append("user/USER.md")
    if "user/MEMORY.md" not in files and "MEMORY.md" not in files:
        files.append("user/MEMORY.md")
    return {"profiles": sorted(list(set(files)))}

@app.get("/api/rag-profil/{filename:path}")
async def api_get_rag_profil(filename: str):
    import os
    from config import PROFILES_DIR
    if not filename.endswith(".md"):
        raise HTTPException(400, "Invalid filename")
    
    # Prevent directory traversal
    path = os.path.realpath(os.path.join(PROFILES_DIR, filename))
    base = os.path.realpath(PROFILES_DIR)
    if not path.startswith(base):
        raise HTTPException(403, "Path traversal not allowed")

    os.makedirs(os.path.dirname(path), exist_ok=True)
    
    if not os.path.exists(path):
        # Auto-create with default template
        base_name = os.path.basename(filename)
        defaults = {
            "USER.md": (
                "# User Profile\n\n"
                "## Preferences\n"
                "- Language: \n"
                "- Communication style: \n\n"
                "## Expertise\n"
                "- \n\n"
                "## Goals\n"
                "- \n"
            ),
            "MEMORY.md": (
                "# Agent Memory\n\n"
                "## Environment\n"
                "- \n\n"
                "## Project Notes\n"
                "- \n\n"
                "## Lessons Learned\n"
                "- \n"
            ),
        }
        with open(path, "w", encoding="utf-8") as f:
            f.write(defaults.get(base_name, f"# {base_name}\n\n"))
    with open(path, "r", encoding="utf-8") as f:
        return {"content": f.read()}

@app.post("/api/rag-profil/{filename:path}")
async def api_save_rag_profil(filename: str, request: Request):
    import os
    from config import PROFILES_DIR
    if not filename.endswith(".md"):
        raise HTTPException(400, "Invalid filename")
    
    # Prevent directory traversal
    path = os.path.realpath(os.path.join(PROFILES_DIR, filename))
    base = os.path.realpath(PROFILES_DIR)
    if not path.startswith(base):
        raise HTTPException(403, "Path traversal not allowed")

    data = await request.json()
    content = data.get("content", "")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return {"status": "ok"}


# --- Code execution API ---
@app.post("/api/execute")
async def api_execute(request: Request):
    """Execute Python code in sandbox."""
    import json as _json
    data = await request.json()
    # Handle double-serialized JSON (client sends a JSON string instead of object)
    if isinstance(data, str):
        try:
            data = _json.loads(data)
        except (ValueError, TypeError):
            data = {"code": data}
    code = data.get("code", "")
    if not code.strip():
        raise HTTPException(400, "Code is required")
    return executor.execute(code)


# --- Local shell command execution (editor terminal) ---
@app.post("/local/run")
async def local_run(request: Request):
    """Execute a shell command in the workspace directory.

    Used by the editor's integrated terminal panel.
    Returns: { stdout, stderr, returncode }
    """
    import asyncio
    import os
    from config import WORKSPACE_DIR

    data = await request.json()
    command = data.get("command", "").strip()
    if not command:
        return {"stdout": "", "stderr": "No command provided", "returncode": 1}

    # Determine working directory (use active project subdir if set)
    cwd = WORKSPACE_DIR
    project = data.get("project", "")
    if project and project != ".":
        project_dir = os.path.join(WORKSPACE_DIR, project)
        if os.path.isdir(project_dir):
            cwd = project_dir

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        except asyncio.TimeoutError:
            proc.kill()
            return {"stdout": "", "stderr": "Command timed out (30s limit)", "returncode": -1}

        return {
            "stdout": stdout.decode(errors="replace").rstrip(),
            "stderr": stderr.decode(errors="replace").rstrip(),
            "returncode": proc.returncode,
        }
    except Exception as e:
        logger.warning("local/run error: %s", e)
        return {"stdout": "", "stderr": str(e), "returncode": 1}


# --- Workspace File API (Editor Mode) ---
from config import WORKSPACE_DIR as _WORKSPACE_DIR


def _safe_workspace_path(rel_path: str) -> str:
    """Resolve a relative path inside the workspace, preventing traversal."""
    base = _os.path.realpath(_WORKSPACE_DIR)
    full = _os.path.realpath(_os.path.join(base, rel_path))
    if not full.startswith(base):
        raise HTTPException(403, "Path traversal not allowed")
    return full


def _get_workspace_tree_sync(base: str) -> list:
    tree = []
    for root, dirs, files in _os.walk(base):
        # Skip hidden directories
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        rel_root = _os.path.relpath(root, base)
        for f in sorted(files):
            if f.startswith('.') and f != '.gitkeep':
                continue
            rel_path = f if rel_root == '.' else _os.path.join(rel_root, f)
            full_path = _os.path.join(root, f)
            try:
                size = _os.path.getsize(full_path)
            except OSError:
                size = 0
            tree.append({"path": rel_path, "size": size})
    return tree

@app.get("/workspace/tree")
async def workspace_tree():
    """List all files in the workspace directory recursively."""
    base = _os.path.realpath(_WORKSPACE_DIR)
    _os.makedirs(base, exist_ok=True)
    tree = await asyncio.to_thread(_get_workspace_tree_sync, base)
    return {"files": tree}


@app.get("/workspace/file")
async def workspace_read_file(path: str):
    """Read a file from the workspace."""
    full = _safe_workspace_path(path)
    if not _os.path.isfile(full):
        raise HTTPException(404, "File not found")
    try:
        with open(full, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        return {"path": path, "content": content}
    except Exception as e:
        raise HTTPException(500, f"Read error: {e}")


@app.get("/workspace/file-raw")
async def workspace_read_file_raw(path: str):
    """Serve a workspace file as raw binary (for image preview, downloads, etc.)."""
    full = _safe_workspace_path(path)
    if not _os.path.isfile(full):
        raise HTTPException(404, "File not found")
    import mimetypes
    mime, _ = mimetypes.guess_type(full)
    return FileResponse(full, media_type=mime or "application/octet-stream")


@app.get("/preview/{path:path}")
async def workspace_preview_file(path: str):
    """Serve a workspace file for web preview (allows relative CSS/JS paths)."""
    full = _safe_workspace_path(path)
    if not _os.path.isfile(full):
        raise HTTPException(404, "File not found")
    import mimetypes
    mime, _ = mimetypes.guess_type(full)
    # Add no-cache headers for preview
    headers = {
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0"
    }
    return FileResponse(full, media_type=mime or "application/octet-stream", headers=headers)


@app.post("/workspace/file")
async def workspace_write_file(request: Request):
    """Create or update a file in the workspace."""
    data = await request.json()
    path = data.get("path", "").strip()
    content = data.get("content", "")
    if not path:
        raise HTTPException(400, "Path is required")
    full = _safe_workspace_path(path)
    _os.makedirs(_os.path.dirname(full), exist_ok=True)
    try:
        with open(full, "w", encoding="utf-8") as f:
            f.write(content)
        return {"status": "ok", "path": path}
    except Exception as e:
        raise HTTPException(500, f"Write error: {e}")


@app.delete("/workspace/file")
async def workspace_delete_file(path: str):
    """Delete a file from the workspace."""
    full = _safe_workspace_path(path)
    if not _os.path.isfile(full):
        raise HTTPException(404, "File not found")
    try:
        _os.remove(full)
        # Clean up empty parent directories
        parent = _os.path.dirname(full)
        base = _os.path.realpath(_WORKSPACE_DIR)
        while parent != base and not _os.listdir(parent):
            _os.rmdir(parent)
            parent = _os.path.dirname(parent)
        return {"status": "ok", "path": path}
    except Exception as e:
        raise HTTPException(500, f"Delete error: {e}")


@app.delete("/workspace/dir")
async def workspace_delete_dir(path: str):
    """Recursively delete a directory from the workspace."""
    import shutil
    full = _safe_workspace_path(path)
    if not _os.path.isdir(full):
        raise HTTPException(404, "Directory not found")
    # Prevent deleting the workspace root
    base = _os.path.realpath(_WORKSPACE_DIR)
    if _os.path.realpath(full) == base:
        raise HTTPException(403, "Cannot delete workspace root")
    try:
        shutil.rmtree(full)
        return {"status": "ok", "path": path}
    except Exception as e:
        raise HTTPException(500, f"Delete error: {e}")


@app.post("/workspace/undo")
async def workspace_undo(request: Request):
    """Undo the last file edit (or a specific file's last edit)."""
    from app.tools_code import snapshot_manager
    data = await request.json()
    file_path = data.get("file_path", "")
    if file_path:
        return snapshot_manager.undo(file_path)
    return snapshot_manager.undo_last()


@app.post("/workspace/rename")
async def workspace_rename_file(request: Request):
    """Rename or move a file or directory within the workspace."""
    data = await request.json()
    old_path = data.get("old_path", "").strip()
    new_path = data.get("new_path", "").strip()
    if not old_path or not new_path:
        raise HTTPException(400, "old_path and new_path are required")
    old_full = _safe_workspace_path(old_path)
    new_full = _safe_workspace_path(new_path)
    if not _os.path.exists(old_full):
        raise HTTPException(404, "Source not found")
    _os.makedirs(_os.path.dirname(new_full), exist_ok=True)
    try:
        _os.rename(old_full, new_full)
        return {"status": "ok", "old_path": old_path, "new_path": new_path}
    except Exception as e:
        raise HTTPException(500, f"Rename error: {e}")


@app.get("/workspace/context")
async def workspace_get_context():
    """Read the clawzd.md project context file."""
    ctx_path = _os.path.join(_os.path.realpath(_WORKSPACE_DIR), "clawzd.md")
    if _os.path.isfile(ctx_path):
        with open(ctx_path, "r", encoding="utf-8") as f:
            return {"content": f.read(), "exists": True}
    return {"content": "", "exists": False}


@app.post("/workspace/context")
async def workspace_save_context(request: Request):
    """Save the clawzd.md project context file."""
    data = await request.json()
    content = data.get("content", "")
    ctx_path = _os.path.join(_os.path.realpath(_WORKSPACE_DIR), "clawzd.md")
    _os.makedirs(_os.path.dirname(ctx_path), exist_ok=True)
    with open(ctx_path, "w", encoding="utf-8") as f:
        f.write(content)
    return {"status": "ok"}


@app.post("/workspace/git-clone")
async def workspace_git_clone(request: Request):
    """Clone a git repository into the workspace.

    Supports optional authentication via username + token (PAT).
    Credentials are injected into the HTTPS URL for the clone command
    and stripped from any output before returning.
    """
    import subprocess as _sp
    data = await request.json()
    url = data.get("url", "").strip()
    folder = data.get("folder", "").strip()
    branch = data.get("branch", "").strip()
    username = data.get("username", "").strip()
    token = data.get("token", "").strip()
    if not url:
        raise HTTPException(400, "Repository URL is required")

    base = _os.path.realpath(_WORKSPACE_DIR)
    _os.makedirs(base, exist_ok=True)

    # Inject credentials into HTTPS URL if provided
    clone_url = url
    if username and token and url.startswith("https://"):
        # https://github.com/user/repo.git → https://user:token@github.com/user/repo.git
        clone_url = url.replace("https://", f"https://{username}:{token}@", 1)
    elif token and url.startswith("https://"):
        # Token-only auth (GitHub PAT style)
        clone_url = url.replace("https://", f"https://{token}@", 1)

    # Build git clone command
    cmd = ["git", "clone", "--progress"]
    if branch:
        cmd += ["-b", branch]
    cmd.append(clone_url)
    if folder:
        # Sanitize folder name
        folder = folder.replace("..", "").replace("/", "_").strip()
        cmd.append(folder)

    # Prevent git from prompting for credentials interactively
    env = _os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"

    try:
        result = _sp.run(cmd, capture_output=True, text=True, timeout=120,
                         cwd=base, env=env)
        if result.returncode != 0:
            error_msg = result.stderr or result.stdout or "Unknown git error"
            # Strip credentials from error output
            if token:
                error_msg = error_msg.replace(token, "***")
            if username:
                error_msg = error_msg.replace(f"{username}:", "***:")
            return {"status": "error", "error": error_msg.strip()}
        output = (result.stdout + "\n" + result.stderr).strip()
        # Strip credentials from output
        if token:
            output = output.replace(token, "***")
        return {
            "status": "ok",
            "message": "Repository cloned successfully",
            "output": output
        }
    except _sp.TimeoutExpired:
        return {"status": "error", "error": "Clone timed out after 120s"}
    except FileNotFoundError:
        return {"status": "error", "error": "git is not installed on this system"}
    except Exception as e:
        msg = str(e)
        if token:
            msg = msg.replace(token, "***")
        return {"status": "error", "error": msg}


@app.get("/workspace/search")
async def workspace_search(q: str):
    """Search for text across all workspace files."""
    base = _os.path.realpath(_WORKSPACE_DIR)
    if not q or not q.strip():
        return {"results": [], "query": q}

    results = []
    query = q.strip().lower()
    for root, dirs, files in _os.walk(base):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for fname in sorted(files):
            if fname.startswith('.'):
                continue
            full = _os.path.join(root, fname)
            rel = _os.path.relpath(full, base)
            # Skip binary-looking files
            ext = fname.rsplit('.', 1)[-1].lower() if '.' in fname else ''
            if ext in ('png', 'jpg', 'jpeg', 'gif', 'webp', 'ico', 'woff', 'woff2', 'ttf', 'eot', 'zip', 'gz', 'tar', 'pdf', 'pyc', 'so', 'o'):
                continue
            try:
                with open(full, "r", encoding="utf-8", errors="ignore") as f:
                    for line_num, line in enumerate(f, 1):
                        if query in line.lower():
                            results.append({
                                "path": rel,
                                "line": line_num,
                                "text": line.rstrip()[:200]
                            })
                            if len(results) >= 100:
                                return {"results": results, "query": q, "truncated": True}
            except Exception:
                continue

    return {"results": results, "query": q, "truncated": False}


@app.post("/workspace/upload")
async def workspace_upload(file: UploadFile = File(...), path: str = Form("")):
    """Upload a file to the workspace."""
    base = _os.path.realpath(_WORKSPACE_DIR)
    target_path = path.strip() if path.strip() else file.filename
    full = _os.path.realpath(_os.path.join(base, target_path))
    if not full.startswith(base):
        raise HTTPException(403, "Path traversal not allowed")
    _os.makedirs(_os.path.dirname(full), exist_ok=True)
    content = await file.read()
    with open(full, "wb") as f:
        f.write(content)
    return {"status": "ok", "path": target_path, "size": len(content)}


@app.post("/workspace/transfer")
async def workspace_transfer(request: Request):
    """Transfer project files from the chat file tree to the workspace as an independent folder.

    Expects JSON: { "project": "my-project", "files": [{"path": "index.html", "content": "..."}, ...] }
    Creates workspace/<project>/<path> for each file.
    """
    data = await request.json()
    project = data.get("project", "").strip()
    files = data.get("files", [])
    if not project:
        raise HTTPException(400, "Project name is required")
    if not files:
        raise HTTPException(400, "No files to transfer")

    # Sanitize project name: prevent traversal, remove dangerous chars
    project = project.replace("..", "").replace("/", "_").replace("\\", "_").strip(". ")
    if not project:
        raise HTTPException(400, "Invalid project name")

    base = _os.path.realpath(_WORKSPACE_DIR)
    project_dir = _os.path.join(base, project)

    written = 0
    errors = []
    for f in files:
        fpath = f.get("path", "").strip()
        fcontent = f.get("content", "")
        if not fpath:
            continue
        # Skip binary/placeholder content
        if fcontent.startswith("[Generated image:") or fcontent.startswith("[Generated SVG:"):
            continue
        full = _os.path.realpath(_os.path.join(project_dir, fpath))
        if not full.startswith(_os.path.realpath(project_dir)):
            errors.append(f"Skipped (traversal): {fpath}")
            continue
        try:
            _os.makedirs(_os.path.dirname(full), exist_ok=True)
            with open(full, "w", encoding="utf-8") as fh:
                fh.write(fcontent)
            written += 1
        except Exception as e:
            errors.append(f"{fpath}: {e}")

    return {
        "status": "ok",
        "project": project,
        "written": written,
        "errors": errors,
    }


# --- Git operations ---
def _git_run(args, cwd=None, timeout=30, env_extra=None):
    """Run a git command in workspace and return (ok, stdout, stderr)."""
    import subprocess as _sp
    base = _os.path.realpath(_WORKSPACE_DIR)
    work = cwd or base
    env = _os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"  # Never prompt for credentials
    if env_extra:
        env.update(env_extra)
    try:
        r = _sp.run(["git"] + args, capture_output=True, text=True,
                     timeout=timeout, cwd=work, env=env)
        return r.returncode == 0, r.stdout.strip(), r.stderr.strip()
    except _sp.TimeoutExpired:
        return False, "", "Command timed out"
    except FileNotFoundError:
        return False, "", "git is not installed"
    except Exception as e:
        return False, "", str(e)


def _find_git_root():
    """Find the first git repo inside workspace (or workspace itself)."""
    base = _os.path.realpath(_WORKSPACE_DIR)
    # Check workspace root first
    if _os.path.isdir(_os.path.join(base, ".git")):
        return base
    # Check one level of subdirs
    for d in sorted(_os.listdir(base)):
        full = _os.path.join(base, d)
        if _os.path.isdir(full) and _os.path.isdir(_os.path.join(full, ".git")):
            return full
    return None


@app.get("/workspace/git-status")
async def workspace_git_status():
    """Get git status: branch, changed files, ahead/behind."""
    repo = _find_git_root()
    if not repo:
        return {"has_repo": False}

    base = _os.path.realpath(_WORKSPACE_DIR)
    repo_name = _os.path.relpath(repo, base) if repo != base else "."

    # Current branch
    ok, branch, _ = _git_run(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo)
    if not ok:
        branch = "unknown"

    # Remote URL
    _, remote_url, _ = _git_run(["remote", "get-url", "origin"], cwd=repo)

    # Ahead/behind
    ahead, behind = 0, 0
    ok2, ab, _ = _git_run(["rev-list", "--left-right", "--count",
                           f"HEAD...origin/{branch}"], cwd=repo)
    if ok2 and ab:
        parts = ab.split()
        if len(parts) == 2:
            ahead, behind = int(parts[0]), int(parts[1])

    # Changed files (porcelain v1)
    _, status_out, _ = _git_run(["status", "--porcelain", "-u"], cwd=repo)
    files = []
    for line in status_out.split("\n"):
        if not line.strip():
            continue
        xy = line[:2]
        path = line[3:]
        # Map git status codes
        idx = xy[0] if xy[0] != " " else ""
        wt = xy[1] if xy[1] != " " else ""
        staged = idx in ("M", "A", "D", "R", "C")
        status = "modified"
        if "A" in xy or "?" in xy:
            status = "added"
        elif "D" in xy:
            status = "deleted"
        elif "R" in xy:
            status = "renamed"
        files.append({
            "path": path, "status": status, "staged": staged,
            "index": idx, "working": wt
        })

    return {
        "has_repo": True,
        "repo": repo_name,
        "branch": branch,
        "remote_url": remote_url or "",
        "ahead": ahead,
        "behind": behind,
        "files": files
    }


@app.get("/workspace/git-log")
async def workspace_git_log(limit: int = 60):
    """Get commit log with parent info for graph rendering."""
    repo = _find_git_root()
    if not repo:
        return {"commits": []}

    # Format: hash|short|parents|author|date|subject|refs
    fmt = "%H|%h|%P|%an|%ai|%s|%D"
    ok, out, _ = _git_run([
        "log", f"-{limit}", f"--format={fmt}", "--all", "--topo-order"
    ], cwd=repo, timeout=15)
    if not ok:
        return {"commits": []}

    commits = []
    for line in out.split("\n"):
        if not line.strip():
            continue
        parts = line.split("|", 6)
        if len(parts) < 7:
            continue
        parents = parts[2].split() if parts[2] else []
        refs_raw = parts[6].strip()
        refs = []
        if refs_raw:
            for ref in refs_raw.split(", "):
                ref = ref.strip()
                if ref.startswith("HEAD -> "):
                    refs.append({"type": "head", "name": ref[8:]})
                elif ref == "HEAD":
                    refs.append({"type": "head", "name": "HEAD"})
                elif ref.startswith("origin/"):
                    refs.append({"type": "remote", "name": ref})
                elif ref.startswith("tag: "):
                    refs.append({"type": "tag", "name": ref[5:]})
                else:
                    refs.append({"type": "branch", "name": ref})

        commits.append({
            "hash": parts[0], "short": parts[1], "parents": parents,
            "author": parts[3], "date": parts[4], "subject": parts[5],
            "refs": refs
        })

    # Collect all branch names
    _, branches_out, _ = _git_run(["branch", "-a", "--format=%(refname:short)"], cwd=repo)
    branches = [b.strip() for b in branches_out.split("\n") if b.strip()]

    return {"commits": commits, "branches": branches}


@app.get("/workspace/git-show")
async def workspace_git_show(commit: str = "HEAD"):
    """Get changed files and stats for a specific commit."""
    repo = _find_git_root()
    if not repo:
        return {"error": "No git repo"}
    # Sanitize commit hash
    import re as _re
    if not _re.match(r'^[a-fA-F0-9]{4,40}$', commit) and commit != 'HEAD':
        return {"error": "Invalid commit hash"}
    ok, out, _ = _git_run(
        ["show", "--stat", "--format=%H|%h|%an|%ae|%ai|%s|%b", commit],
        cwd=repo, timeout=10
    )
    if not ok:
        return {"error": "Cannot read commit"}
    lines = out.strip().split("\n")
    if not lines:
        return {"error": "Empty output"}
    # Parse header
    header = lines[0].split("|", 6)
    info = {
        "hash": header[0] if len(header) > 0 else "",
        "short": header[1] if len(header) > 1 else "",
        "author": header[2] if len(header) > 2 else "",
        "email": header[3] if len(header) > 3 else "",
        "date": header[4] if len(header) > 4 else "",
        "subject": header[5] if len(header) > 5 else "",
        "body": header[6].strip() if len(header) > 6 else "",
    }
    # Parse file stats (lines after header)
    files = []
    for line in lines[1:]:
        line = line.strip()
        if not line or line.startswith("---"):
            continue
        # Parse "  filename | 5 ++-" format
        if "|" in line:
            parts = line.split("|", 1)
            fname = parts[0].strip()
            stat = parts[1].strip() if len(parts) > 1 else ""
            # Count additions/deletions from stat
            adds = stat.count("+")
            dels = stat.count("-")
            # Get numeric change count
            num = ""
            for ch in stat:
                if ch.isdigit():
                    num += ch
                else:
                    break
            files.append({
                "name": fname,
                "changes": int(num) if num else 0,
                "additions": adds,
                "deletions": dels,
                "stat": stat
            })
        elif "changed" in line:
            # Summary line: "3 files changed, 10 insertions(+), 2 deletions(-)"
            info["summary"] = line
    info["files"] = files
    return info


@app.get("/workspace/git-file-diff")
async def workspace_git_file_diff(commit: str, path: str):
    """Get before/after content of a file for a specific commit (for side-by-side diff)."""
    repo = _find_git_root()
    if not repo:
        return {"error": "No git repo"}
    import re as _re
    if not _re.match(r'^[a-fA-F0-9]{4,40}$', commit) and commit != 'HEAD':
        return {"error": "Invalid commit hash"}

    # Get the file content AFTER the commit
    ok_after, after_content, _ = _git_run(
        ["show", f"{commit}:{path}"], cwd=repo, timeout=10
    )
    # Get the file content BEFORE the commit (parent)
    ok_before, before_content, _ = _git_run(
        ["show", f"{commit}~1:{path}"], cwd=repo, timeout=10
    )

    # Get the unified diff
    ok_diff, diff_content, _ = _git_run(
        ["diff", f"{commit}~1", commit, "--", path], cwd=repo, timeout=10
    )

    return {
        "path": path,
        "commit": commit,
        "before": before_content if ok_before else "",
        "after": after_content if ok_after else "",
        "diff": diff_content if ok_diff else "",
        "is_new": not ok_before,
        "is_deleted": not ok_after,
    }

@app.post("/workspace/git-add")
async def workspace_git_add(request: Request):
    """Stage files for commit."""
    data = await request.json()
    paths = data.get("paths", [])
    all_flag = data.get("all", False)
    repo = _find_git_root()
    if not repo:
        return {"status": "error", "error": "No git repository found"}

    if all_flag:
        ok, out, err = _git_run(["add", "-A"], cwd=repo)
    else:
        ok, out, err = _git_run(["add", "--"] + paths, cwd=repo)

    return {"status": "ok" if ok else "error", "error": err if not ok else ""}


@app.post("/workspace/git-commit")
async def workspace_git_commit(request: Request):
    """Commit staged changes."""
    data = await request.json()
    message = data.get("message", "").strip()
    if not message:
        return {"status": "error", "error": "Commit message is required"}
    repo = _find_git_root()
    if not repo:
        return {"status": "error", "error": "No git repository found"}

    ok, out, err = _git_run(["commit", "-m", message], cwd=repo)
    return {
        "status": "ok" if ok else "error",
        "output": out,
        "error": err if not ok else ""
    }


@app.post("/workspace/git-push")
async def workspace_git_push(request: Request):
    """Push commits to remote. Supports optional token authentication."""
    data = await request.json()
    remote = data.get("remote", "origin")
    branch = data.get("branch", "")
    force = data.get("force", False)
    token = data.get("token", "").strip()
    username = data.get("username", "").strip()
    repo = _find_git_root()
    if not repo:
        return {"status": "error", "error": "No git repository found"}

    # If credentials provided, temporarily set the remote URL with token
    original_url = None
    if token:
        _, original_url, _ = _git_run(["remote", "get-url", remote], cwd=repo)
        if original_url and original_url.startswith("https://"):
            if username:
                auth_url = original_url.replace("https://", f"https://{username}:{token}@", 1)
            else:
                auth_url = original_url.replace("https://", f"https://{token}@", 1)
            _git_run(["remote", "set-url", remote, auth_url], cwd=repo)

    cmd = ["push", remote]
    if branch:
        cmd.append(branch)
    if force:
        cmd.append("--force")

    ok, out, err = _git_run(cmd, cwd=repo, timeout=60)

    # Restore original remote URL (strip credentials)
    if original_url and token:
        _git_run(["remote", "set-url", remote, original_url], cwd=repo)

    # Strip credentials from output
    combined = (out + "\n" + err).strip()
    if token:
        combined = combined.replace(token, "***")

    return {
        "status": "ok" if ok else "error",
        "output": combined,
        "error": (err.replace(token, "***") if token else err) if not ok else ""
    }


@app.post("/workspace/git-pull")
async def workspace_git_pull(request: Request):
    """Pull from remote. Supports optional token authentication."""
    data = await request.json()
    remote = data.get("remote", "origin")
    branch = data.get("branch", "")
    token = data.get("token", "").strip()
    username = data.get("username", "").strip()
    repo = _find_git_root()
    if not repo:
        return {"status": "error", "error": "No git repository found"}

    # If credentials provided, temporarily set the remote URL with token
    original_url = None
    if token:
        _, original_url, _ = _git_run(["remote", "get-url", remote], cwd=repo)
        if original_url and original_url.startswith("https://"):
            if username:
                auth_url = original_url.replace("https://", f"https://{username}:{token}@", 1)
            else:
                auth_url = original_url.replace("https://", f"https://{token}@", 1)
            _git_run(["remote", "set-url", remote, auth_url], cwd=repo)

    cmd = ["pull", remote]
    if branch:
        cmd.append(branch)

    ok, out, err = _git_run(cmd, cwd=repo, timeout=60)

    # Restore original remote URL (strip credentials)
    if original_url and token:
        _git_run(["remote", "set-url", remote, original_url], cwd=repo)

    # Strip credentials from output
    combined = (out + "\n" + err).strip()
    if token:
        combined = combined.replace(token, "***")

    return {
        "status": "ok" if ok else "error",
        "output": combined,
        "error": (err.replace(token, "***") if token else err) if not ok else ""
    }


@app.get("/workspace/git-diff")
async def workspace_git_diff(path: str = "", staged: bool = False):
    """Get diff for a specific file or all changes."""
    repo = _find_git_root()
    if not repo:
        return {"diff": "", "error": "No git repository found"}

    cmd = ["diff"]
    if staged:
        cmd.append("--cached")
    cmd += ["--no-color"]
    if path:
        cmd += ["--", path]

    ok, out, err = _git_run(cmd, cwd=repo, timeout=15)
    return {"diff": out, "error": err if not ok else ""}


# --- ZIP export API ---
@app.get("/workspace/export-zip")
async def workspace_export_zip(project: str = "."):
    """Bundle a project or the workspace into a downloadable ZIP archive."""
    base = _os.path.realpath(_WORKSPACE_DIR)
    target_dir = base
    if project and project != ".":
        # Sanitize project name
        project = project.replace("..", "").replace("/", "_").replace("\\", "_").strip()
        target_dir = _os.path.realpath(_os.path.join(base, project))
        if not target_dir.startswith(base):
            raise HTTPException(403, "Invalid project path")
            
    if not _os.path.isdir(target_dir):
        raise HTTPException(404, "Project directory not found")
        
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in _os.walk(target_dir):
            # Skip hidden dirs like .git
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            for file in files:
                if file.startswith('.'):
                    continue
                full_path = _os.path.join(root, file)
                # Compute relative path for zip structure
                rel_path = _os.path.relpath(full_path, target_dir)
                zf.write(full_path, rel_path)
                
    buf.seek(0)
    filename = f"{project if project != '.' else 'workspace'}_export.zip"
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.post("/api/export-zip")
async def api_export_zip(request: Request):
    """Bundle files into a downloadable ZIP archive."""
    data = await request.json()
    files = data.get("files", [])
    if not files:
        raise HTTPException(400, "No files to export")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.writestr(f["path"], f["content"])
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=clawzd_project.zip"},
    )