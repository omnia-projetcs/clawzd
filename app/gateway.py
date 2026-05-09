"""
Clawzd — FastAPI application gateway.
Main router that wires all modules together and handles chat streaming.
"""
import asyncio
import io
import logging
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

from app.database import init_db, create_session, get_session, add_message, get_messages, auto_title, update_session
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
from app.tools_automation import router as automation_router
from app.tools_document_gen import router as docgen_router
from app.tool_executor import parse_tool_calls, execute_tool, format_tool_result, resolve_tool_name
from app.metrics import get_metrics
from app.cache import cache_stats
from app.core.tokens import count_tokens, count_message_tokens
from config import STATIC_DIR, TEMPLATES_DIR, DATA_DIR, CORS_ORIGINS, RATE_LIMIT

import re as _re
import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("websockets").setLevel(logging.WARNING)
logging.getLogger("websockets.server").setLevel(logging.WARNING)

logger = logging.getLogger("clawzd.gateway")

# Regex to strip base64 data URIs from text (images bloat LLM context)
_BASE64_RE = _re.compile(r'!\[[^\]]*\]\(data:image/[^)]+\)', _re.DOTALL)

# Regex to strip HTML tags from user input (XSS prevention)
_HTML_TAG_RE = _re.compile(r'<[^>]+>', _re.DOTALL | _re.IGNORECASE)


def _strip_base64(text: str) -> str:
    """Remove inline base64 image data from text to reduce LLM context size."""
    return _BASE64_RE.sub('[image displayed to user]', text)


def _sanitize_input(text: str) -> str:
    """Sanitize user input by removing all HTML tags."""
    return _HTML_TAG_RE.sub('', text)


# --- App Setup ---
app = FastAPI(title="Clawzd", version="2.0")

# --- CORS Middleware ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS or ["*"],
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
app.include_router(browser_router, prefix="/browser")
app.include_router(cron_router, prefix="/cron")
app.include_router(skills_router, prefix="/skills")
app.include_router(document_router, prefix="/document")
app.include_router(telegram_router, prefix="/telegram")
app.include_router(models_router, prefix="/models")
app.include_router(presentation_router, prefix="/presentation")
app.include_router(automation_router, prefix="/automation")
app.include_router(docgen_router, prefix="/docgen")

from app.tools_research import router as research_router
app.include_router(research_router, prefix="/research")

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

# --- In-memory SSE queues per session ---
_sse_queues: dict[str, asyncio.Queue] = {}
_arena_queues: dict[str, asyncio.Queue] = {}
_active_generations: dict[str, str] = {}
_cancelled_sessions: set[str] = set()


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

    # Save user message
    add_message(session_id, "user", user_msg)

    # Auto-title from first message
    messages = get_messages(session_id)
    user_messages = [m for m in messages if m["role"] == "user"]
    if len(user_messages) == 1:
        auto_title(session_id, user_msg)

    # Build messages for the LLM
    llm_messages = []
    system_prompt = get_preprompt(preprompt_key, model=model_key)
    
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
        # Apply L1B3RT4S jailbreak wrapper to the last user message if jailbreak mode is active
        if preprompt_key == "jailbreak" and i == len(messages) - 1 and m["role"] == "user":
            wrapped_content = get_jailbreak_wrapper(model_key, m["content"], provider_key)
            llm_messages.append({"role": m["role"], "content": wrapped_content})
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

        # Force-inject generate_image when user message contains image-related keywords
        _image_keywords = {"image", "photo", "picture", "logo", "illustration", "draw",
                           "icon", "avatar", "banner", "poster", "wallpaper",
                           "dessin", "dessine", "g\u00e9n\u00e8re", "cr\u00e9e", "cr\u00e9er", "affiche",
                           "generate an image", "generate a logo", "make a logo",
                           "create an image", "create a logo"}
        _user_lower = user_msg.lower()
        if any(kw in _user_lower for kw in _image_keywords):
            if not any(d["skill"] == "generate_image" for d in detected):
                detected.insert(0, {"skill": "generate_image", "confidence": 1.0, "source": "keyword"})

        # Merge manually activated skills from the catalog (always injected)
        try:
            from app.skill_registry import load_active_skills
            from app.skill_selector import get_skill_description
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
        from app.skill_selector import get_skill_description, get_skill_catalog_entry, get_skill_full_instructions

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
    MAX_CONTINUATION_ROUNDS = 5
    # Maximum total output characters to prevent runaway generation
    MAX_TOTAL_OUTPUT = 50_000

    def _is_truncated(text: str) -> bool:
        """Detect if a response was truncated mid-output.

        Checks for unclosed code fences (odd number of ```) which indicates
        the LLM hit its token limit while generating code.
        Also avoids false positives when the model emitted stop tokens.
        """
        stripped = text.rstrip()
        if not stripped:
            return False

        fence_count = text.count("```")
        if fence_count % 2 != 0:
            return True

        if len(stripped) < 200:
            return False

        # If the response contains LLM stop tokens, it completed normally
        stop_markers = ["<|endoftext|>", "<|im_start|>", "<|im_end|>",
                        "<|eot_id|>", "</s>", "<|end|>"]
        tail = stripped[-200:]
        if any(marker in tail for marker in stop_markers):
            return False

        # Also check if it ends mid-sentence (no final punctuation or newline)
        if len(stripped) > 3000:
            last_char = stripped[-1]
            if last_char not in '.!?\n`>)]}':
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

                t0_llm = time.perf_counter()

                # Stream the LLM response for this round
                async for token in provider.chat_stream(current_messages, **kwargs):
                    # Check for cancellation
                    if session_id in _cancelled_sessions:
                        _cancelled_sessions.discard(session_id)
                        logger.info("Generation cancelled by user for session %s", session_id)
                        full_conversation += "\n\n*⏹️ Generation stopped by user.*"
                        await queue.put(None)
                        return
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
                continuation_round = 0
                while _is_truncated(round_response) and continuation_round < MAX_CONTINUATION_ROUNDS:
                    continuation_round += 1
                    logger.info("Response truncated, auto-continuing (round %d)...", continuation_round)

                    # Notify the user (only if not inside a code block, to keep code seamless)
                    # Build continuation context — detect if we were inside a code block
                    tail = round_response[-1500:] if len(round_response) > 1500 else round_response
                    # Count code fences to detect if truncated mid-code
                    fence_count = round_response.count("```")
                    in_code_block = fence_count % 2 != 0

                    if not in_code_block:
                        cont_notice = "\n\n⏳ *Response truncated — continuing automatically...*\n\n"
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
                            elif len(cont_round_response) > 500:
                                # Fallback: LLM forgot the fence, flush buffer and stream
                                _found_code_start = True
                                await queue.put(cont_round_response)
                        else:
                            await queue.put(token)

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
                    cap_msg = "\n\n⚠️ **Output limit reached** — response capped at ~50K characters to prevent excessive generation.\n\n"
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

                    # Execute the tool
                    import time as _time_mod
                    _exec_start = _time_mod.time()
                    if _skip_tool:
                        result = {"output": "Tool execution skipped by plugin."}
                    else:
                        result = await execute_tool(tool_name, params, {"active_project": active_project})

                    # Push notification for long-running tools (OpenClaw OS-inspired)
                    try:
                        from app.core.notifications import notify_tool_complete
                        _long_tools = {"generate_image", "generate_animation", "audit_code",
                                       "screenshot_remote", "browse_web", "search_web"}
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
                        _exec_end = _time_mod.time()
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
                    else:
                        # For other tools, do not stream raw text to avoid double results
                        status_done = f"✅ *Done.*\n\n"
                        await queue.put(status_done)
                        full_conversation += status_done

                    # Stream images inline if the tool returned any
                    if isinstance(result, dict):
                        # Matplotlib plots (multiple images)
                        if result.get("images"):
                            for idx, b64 in enumerate(result["images"], 1):
                                img_md = f"\n\n![Plot {idx}](data:image/png;base64,{b64})\n\n"
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
                                "diff": result.get("diff", "")
                            }
                            edit_marker = f"\n\n__FILE_EDIT__{_json.dumps(edit_data)}__\n\n"
                            await queue.put(edit_marker)
                            full_conversation += edit_marker

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

            _active_generations.pop(session_id, None)

    asyncio.create_task(generate())
    return {"status": "processing", "session_id": session_id}


@app.post("/send/{session_id}")
async def send_message(session_id: str, request: Request):
    """Send a user message and trigger LLM response generation (HTTP)."""
    data = await request.json()
    return await _process_chat(session_id, data)


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
        from app.core.notifications import subscribe, unsubscribe, get_recent
        notif_queue = subscribe(session_id)
        # Send any recent unread notifications
        for n in get_recent(limit=5, session_id=session_id):
            await websocket.send_json(n)
    except Exception:
        notif_queue = None

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


@app.get("/apps/{app_id}/{filename:path}")
async def serve_app_file(app_id: str, filename: str):
    """Serve a file from a mini-app."""
    from app.core.app_builder import APPS_DIR
    filepath = _os.path.join(APPS_DIR, app_id, _os.path.basename(filename))
    if not _os.path.exists(filepath):
        raise HTTPException(404, "File not found")
    return _AppFileResponse(filepath)


# --- Battle Arena API ---

@app.post("/arena/send")
async def arena_send(request: Request):
    """Start generation for multiple models in the Arena."""
    data = await request.json()
    user_msg = _sanitize_input(data.get("message", "").strip())
    models = data.get("models", [])
    
    if not user_msg:
        raise HTTPException(400, "Message is required")
    if not models or len(models) > 10:
        raise HTTPException(400, "1 to 10 models required")
        
    streams = []
    
    for m in models:
        provider_key = m.get("provider", "local")
        model_key = m.get("model", "")
        stream_id = str(uuid.uuid4())
        _arena_queues[stream_id] = asyncio.Queue()
        streams.append({
            "stream_id": stream_id,
            "provider": provider_key,
            "model": model_key
        })
        
        # Launch generation task for this specific model
        async def _generate(s_id=stream_id, p_key=provider_key, m_key=model_key):
            queue = _arena_queues[s_id]
            try:
                import time
                t0 = time.perf_counter()
                tokens_count = 0
                
                provider = get_llm_provider(p_key)
                kwargs = {}
                if m_key:
                    kwargs["model"] = m_key
                    
                messages = [
                    {"role": "system", "content": "You are a helpful assistant. Keep your answer concise and to the point."},
                    {"role": "user", "content": user_msg}
                ]
                
                async for token in provider.chat_stream(messages, **kwargs):
                    if any(marker in token for marker in ["<|endoftext|>", "<|im_start|>", "<|im_end|>", "<|eot_id|>", "</s>", "<|end|>"]):
                        for marker in ["<|endoftext|>", "<|im_start|>", "<|im_end|>", "<|eot_id|>", "</s>", "<|end|>"]:
                            token = token.replace(marker, "")
                        if not token:
                            continue
                    tokens_count += 1
                    await queue.put(token)
                    
                total_time = time.perf_counter() - t0
                tps = tokens_count / total_time if total_time > 0 else 0
                import json
                stats_msg = f'\n\n__STATS__{json.dumps({"time": round(total_time, 2), "tokens": tokens_count, "tps": round(tps, 1)})}__STATS__\n\n'
                await queue.put(stats_msg)

                # Track metrics for Arena generation
                input_tokens = count_tokens(user_msg, model=model_key or "")
                from app.metrics import get_metrics
                get_metrics().record_llm_call(
                    provider=p_key,
                    model=m_key or getattr(provider, "default_model", "unknown"),
                    input_tokens=input_tokens,
                    output_tokens=tokens_count,
                    latency_s=total_time,
                    session_id="arena"
                )
            except Exception as e:
                logger.error("Arena LLM error (%s/%s): %s", p_key, m_key, e)
                await queue.put(f"\n\n❌ **Error**: {e}")
            finally:
                await queue.put(None)
                
        asyncio.create_task(_generate())
        
    return {"status": "processing", "streams": streams}


@app.get("/arena/stream/{stream_id}")
async def arena_stream(stream_id: str):
    """SSE endpoint for Arena columns."""
    if stream_id not in _arena_queues:
        raise HTTPException(404, "Stream not found")
        
    async def event_generator():
        queue = _arena_queues[stream_id]
        while True:
            token = await queue.get()
            if token is None:
                yield {"data": "[DONE]"}
                # Cleanup queue after short delay
                async def _cleanup():
                    await asyncio.sleep(60)
                    _arena_queues.pop(stream_id, None)
                asyncio.create_task(_cleanup())
                break
            yield {"data": token}
            
    return EventSourceResponse(event_generator())


@app.post("/arena/evaluate")
async def arena_evaluate(request: Request):
    """Judge the models' responses."""
    data = await request.json()
    prompt = data.get("prompt", "")
    responses = data.get("responses", {})  # dict of stream_id -> text
    provider_key = data.get("provider", "local")
    model_key = data.get("model", "")
    
    if not prompt or not responses:
        raise HTTPException(400, "Prompt and responses required")
        
    provider = get_llm_provider(provider_key)
    kwargs = {}
    if model_key:
        kwargs["model"] = model_key
    
    # Map UUID stream_ids to sequential IDs to make it easier for the LLM
    id_map = {}
    user_prompt = f"PROMPT:\n{prompt}\n\nRESPONSES:\n"
    for idx, (s_id, text) in enumerate(responses.items(), 1):
        idx_str = str(idx)
        id_map[idx_str] = s_id
        user_prompt += f"--- RESPONSE {idx_str} ---\n{text}\n\n"
        
    sys_prompt = "You are an impartial AI judge. Your task is to evaluate multiple AI responses to a given prompt. Score each out of 10 and give a 1-sentence explanation."
    user_prompt += "Evaluate ALL responses provided above. Format your output strictly as a JSON object where each key is the response number (e.g. \"1\", \"2\") and the value is an object with 'score' (number) and 'rationale' (string). Example: {\"ratings\": {\"1\": {\"score\": 8, \"rationale\": \"...\"}, \"2\": {\"score\": 6, \"rationale\": \"...\"}}} . You MUST include an evaluation for every single response listed."
    
    try:
        t0 = time.perf_counter()
        result_text = ""
        async for token in provider.chat_stream([
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_prompt}
        ], **kwargs):
            result_text += token
            
        latency_s = time.perf_counter() - t0
        # Track metrics for Arena evaluation
        input_tokens = count_message_tokens([{"role": "system", "content": sys_prompt}, {"role": "user", "content": user_prompt}])
        output_tokens = count_tokens(result_text)
        from app.metrics import get_metrics
        get_metrics().record_llm_call(
            provider=provider_key,
            model=model_key or getattr(provider, "default_model", "unknown"),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_s=latency_s,
            session_id="arena_eval"
        )
            
        # Parse JSON
        import json
        import re
        
        clean_text = re.sub(r'```json\s*', '', result_text)
        clean_text = re.sub(r'```\s*', '', clean_text)
        
        match = re.search(r'\{[\s\S]*\}', clean_text)
        if match:
            data = json.loads(match.group(0))
        else:
            data = json.loads(clean_text)
            
        if "ratings" not in data:
            is_ratings = all(isinstance(v, dict) and "score" in v for v in data.values())
            if is_ratings:
                data = {"ratings": data}
                
        # Map sequential IDs back to original stream_ids
        final_ratings = {}
        for k, v in data.get("ratings", {}).items():
            match = re.search(r'\d+', str(k))
            if match:
                idx_str = match.group(0)
                if idx_str in id_map:
                    final_ratings[id_map[idx_str]] = v
            elif str(k) in id_map:
                final_ratings[id_map[str(k)]] = v
                
        return {"ratings": final_ratings}
    except Exception as e:
        logger.error("Arena evaluation error: %s. Response: %s", e, locals().get('result_text', ''))
        return {"ratings": {}}


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
        from config import OLLAMA_HOST, OLLAMA_MODEL
        import httpx
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{OLLAMA_HOST}/api/tags")
            if resp.status_code == 200:
                return {"status": "running", "active_model": OLLAMA_MODEL}
        return {"status": "stopped", "active_model": OLLAMA_MODEL}
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
            else:
                prompt, stop_tokens = _build_local_prompt(
                    intent, context_prefix, suffix_preview, file_path, language
                )

            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{OLLAMA_HOST}/api/generate",
                    json={
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
                    },
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
@app.get("/api/rag-profil/{filename}")
async def api_get_rag_profil(filename: str):
    import os
    from config import PROFILES_DIR
    if filename not in ["USER.md", "MEMORY.md"]:
        raise HTTPException(400, "Invalid filename")
    profil_dir = os.path.join(PROFILES_DIR, "user")
    os.makedirs(profil_dir, exist_ok=True)
    path = os.path.join(profil_dir, filename)
    if not os.path.exists(path):
        # Auto-create with default template
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
            f.write(defaults.get(filename, ""))
    with open(path, "r", encoding="utf-8") as f:
        return {"content": f.read()}

@app.post("/api/rag-profil/{filename}")
async def api_save_rag_profil(filename: str, request: Request):
    import os
    from config import PROFILES_DIR
    if filename not in ["USER.md", "MEMORY.md"]:
        raise HTTPException(400, "Invalid filename")
    data = await request.json()
    content = data.get("content", "")
    profil_dir = os.path.join(PROFILES_DIR, "user")
    os.makedirs(profil_dir, exist_ok=True)
    path = os.path.join(profil_dir, filename)
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
            "message": f"Repository cloned successfully",
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