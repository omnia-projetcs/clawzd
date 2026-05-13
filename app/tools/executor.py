"""
Clawzd — Server-side tool executor.

Intercepts ```tool_call blocks from LLM responses, executes the matched
tool, and returns text results.  Includes fuzzy name matching so that
invented tool names (e.g. "cryptocurrency-analysis") are automatically
mapped to the closest real tool (e.g. "search_web").
"""
import json
import re
import logging
from difflib import SequenceMatcher
from typing import Optional

logger = logging.getLogger("clawzd.tool_executor")

# ---------------------------------------------------------------------------
# Known tools and their keyword associations for fuzzy matching
# ---------------------------------------------------------------------------
TOOL_KEYWORDS: dict[str, list[str]] = {
    "search_web": [
        "search", "web", "internet", "google", "find", "lookup", "query",
        "news", "info", "research", "crypto", "currency", "bitcoin", "btc",
        "eth", "stock", "market", "price", "trend", "analysis", "weather",
        "cyber", "cybersearch", "websearch", "duckduckgo",
    ],
    "execute_python": [
        "python", "code", "execute", "run", "script", "compute", "calculate",
        "math", "chart", "plot", "graph", "data", "pandas", "numpy",
        "analyze", "analysis", "csv", "statistics",
    ],
    "screenshot_remote": [
        "screenshot", "capture", "webpage", "website", "page", "url",
        "remote", "view", "preview", "show", "display", "render",
    ],
    "screenshot_local": [
        "screenshot", "local", "desktop", "screen", "capture",
    ],
    "generate_image": [
        "image", "generate", "draw", "create", "picture", "illustration",
        "photo", "art", "design", "logo", "icon", "stable", "diffusion",
        "svg", "vector", "badge", "shape", "geometric",
        "icon", "arrow", "symbol",
    ],
    "generate_animation": [
        "animate", "animation", "gif", "mp4", "video", "zoom", "motion",
        "movie", "moving", "animated",
    ],
    "run_command": [
        "command", "shell", "terminal", "bash", "cmd", "ls", "cat", "grep",
        "git", "docker", "pip",
    ],
    "audit_code": [
        "audit", "security", "vulnerability", "code", "quality", "review",
        "scan", "owasp", "semgrep", "trivy", "bandit",
    ],
    "rag_search": [
        "knowledge", "rag", "document", "base", "memory", "recall",
    ],

    "edit_file": [
        "edit", "file", "modify", "replace", "change", "write", "update",
        "patch", "refactor",
    ],
    "read_file": [
        "read", "file", "view", "show", "cat", "inspect", "open",
    ],
    "create_document": [
        "create", "document", "generate", "make", "pdf", "word", "excel",
        "powerpoint", "presentation", "markdown", "docx", "xlsx", "pptx", "md",
        "doc", "file"
    ],
    "send_email": [
        "email", "mail", "send", "smtp", "message", "notification",
    ],
    "post_to_twitter": [
        "twitter", "tweet", "post", "x", "social",
    ],
    "post_to_linkedin": [
        "linkedin", "post", "professional", "social",
    ],
    "post_to_medium": [
        "medium", "article", "blog", "publish", "post",
    ],
    "trigger_n8n": [
        "n8n", "webhook", "automation", "workflow", "trigger",
    ],
    "memory": [
        "memory", "remember", "save", "note", "preference", "profile",
        "forget", "recall", "persist",
    ],
    "rebuild_skill": [
        "rebuild", "improve", "optimize", "fix", "repair", "upgrade",
        "skill", "refactor",
    ],
    "create_skill": [
        "create", "skill", "new", "build", "make", "custom", "tool",
        "plugin", "extension",
    ],
    "search_twitter": [
        "twitter", "tweet", "x", "watch", "veille", "timeline",
        "trending", "hashtag", "social", "thread",
    ],
    "search_linkedin": [
        "linkedin", "profil", "profile", "cv", "resume",
        "article", "recrutement", "hiring", "career",
        "pulse", "post", "network",
    ],
    "undo": [
        "undo", "revert", "rollback", "restore", "cancel",
        "annuler", "défaire",
    ],
    "list_files": [
        "list", "files", "glob", "find", "discover", "explore",
        "structure", "tree", "directory", "workspace", "pattern",
        "*.py", "*.js", "*.ts", "lister", "fichiers",
    ],
    "todo_write": [
        "todo", "plan", "task", "step", "checklist", "agenda",
        "progress", "track", "tâche", "planifier", "étapes",
    ],
    "graphify_query": [
        "graphify", "graph", "semantic", "codebase", "architecture",
        "concept", "knowledge",
    ],
    "graphify_explain": [
        "graphify", "explain", "entity", "node", "class", "function",
    ],
    "graphify_path": [
        "graphify", "path", "flow", "trace", "chain", "call",
    ],
    "create_app": [
        "create", "app", "application", "mini", "webapp", "build",
        "website", "page", "dashboard", "calculator", "tool",
    ],
    "update_app": [
        "update", "app", "application", "edit", "modify", "change",
        "improve", "fix", "upgrade", "redesign",
    ],
    "analyze_data": [
        "analyze", "data", "csv", "excel", "dataset", "spreadsheet",
        "dataframe", "statistics", "profile", "insights", "xlsx",
        "tsv", "analysis", "visualize", "chart", "dashboard",
    ],
    "fetch_market_data": [
        "market", "price", "ohlcv", "candle", "kline", "ticker",
        "crypto", "stock", "forex", "bitcoin", "btc", "eth",
        "binance", "yahoo", "dukascopy", "cours", "bourse",
        "cotation", "historique", "trading", "financial",
    ],
}

# Direct alias map for common invented names
TOOL_ALIASES: dict[str, str] = {
    # Crypto / finance
    "cryptocurrency-analysis": "fetch_market_data",
    "crypto-analysis": "fetch_market_data",
    "crypto_analysis": "fetch_market_data",
    "market-analysis": "fetch_market_data",
    "stock-analysis": "fetch_market_data",
    "finance-analysis": "fetch_market_data",
    "price-checker": "fetch_market_data",
    "trend-analysis": "fetch_market_data",
    "get-price": "fetch_market_data",
    "get_price": "fetch_market_data",
    "market-data": "fetch_market_data",
    "market_data": "fetch_market_data",
    "fetch-market-data": "fetch_market_data",
    "get-market-data": "fetch_market_data",
    "get_market_data": "fetch_market_data",
    # Search variants
    "cybersearch": "search_web",
    "cyber-search": "search_web",
    "web-search": "search_web",
    "internet-search": "search_web",
    "google-search": "search_web",
    "web_scraper": "search_web",
    "web_scraping": "screenshot_remote",
    "browse_web": "screenshot_remote",
    # Code variants
    "code-executor": "execute_python",
    "python-executor": "execute_python",
    "run-code": "execute_python",
    "code-runner": "execute_python",
    "run_python": "execute_python",
    "python_run": "execute_python",
    # Image variants
    "image-generator": "generate_image",
    "create-image": "generate_image",
    "draw-image": "generate_image",
    "text-to-image": "generate_image",
    "generate-svg": "generate_image",
    "create-svg": "generate_image",
    "svg-generator": "generate_image",
    "create-animation": "generate_animation",
    "animate-image": "generate_animation",
    "generate-gif": "generate_animation",
    "create-gif": "generate_animation",
    "generate-video": "generate_animation",
    "create-video": "generate_animation",
    "video-generator": "generate_animation",
    "gif-generator": "generate_animation",
    # Screenshot variants
    "take-screenshot": "screenshot_remote",
    "webpage-capture": "screenshot_remote",
    "capture-page": "screenshot_remote",
    "page-screenshot": "screenshot_remote",
    # File search — now routed to list_files (GlobTool) instead of run_command
    "file-search": "list_files",
    "search-file": "list_files",
    "search_file": "list_files",
    "find-file": "list_files",
    "find_file": "list_files",
    "document-search": "rag_search",
    "code-audit": "audit_code",
    "security-scan": "audit_code",
    "shell": "run_command",
    "terminal": "run_command",
    "file-edit": "edit_file",
    "modify-file": "edit_file",
    "update-file": "edit_file",
    "file-read": "read_file",
    "view-file": "read_file",
    "remember": "memory",
    "save-memory": "memory",
    "update-memory": "memory",
    "rebuild-skill": "rebuild_skill",
    "improve-skill": "rebuild_skill",
    "fix-skill": "rebuild_skill",
    "upgrade-skill": "rebuild_skill",
    "skill-rebuild": "rebuild_skill",
    # Twitter
    "twitter-search": "search_twitter",
    "twitter_search": "search_twitter",
    "x-search": "search_twitter",
    "tweet-search": "search_twitter",
    "twitter-watch": "search_twitter",
    "veille-twitter": "search_twitter",
    # LinkedIn
    "linkedin-search": "search_linkedin",
    "linkedin_search": "search_linkedin",
    "search-linkedin": "search_linkedin",
    "linkedin-profiles": "search_linkedin",
    "linkedin-articles": "search_linkedin",
    "veille-linkedin": "search_linkedin",
    # Undo
    "revert": "undo",
    "rollback": "undo",
    "annuler": "undo",
    # list_files
    "glob": "list_files",
    "find-files": "list_files",
    "find_files": "list_files",
    "list-files": "list_files",
    "ls-files": "list_files",
    "explore-workspace": "list_files",
    # todo_write
    "write-todo": "todo_write",
    "write_todo": "todo_write",
    "create-plan": "todo_write",
    "create_plan": "todo_write",
    "update-plan": "todo_write",
    "update_plan": "todo_write",
    # App Builder
    "build-app": "create_app",
    "build_app": "create_app",
    "create-application": "create_app",
    "create_application": "create_app",
    "new-app": "create_app",
    "new_app": "create_app",
    "make-app": "create_app",
    "make_app": "create_app",
    "build-webapp": "create_app",
    "edit-app": "update_app",
    "edit_app": "update_app",
    "modify-app": "update_app",
    "modify_app": "update_app",
    "update-application": "update_app",
    "update_application": "update_app",
    # Data analysis
    "data-analysis": "analyze_data",
    "data_analysis": "analyze_data",
    "analyze-csv": "analyze_data",
    "analyze_csv": "analyze_data",
    "analyze-excel": "analyze_data",
    "analyze_excel": "analyze_data",
    "data-analyst": "analyze_data",
    "data_analyst": "analyze_data",
    "csv-analysis": "analyze_data",
    "excel-analysis": "analyze_data",
    "data-profiling": "analyze_data",
    "dataset-analysis": "analyze_data",
}


def _fuzzy_match_tool(name: str) -> Optional[str]:
    """Try to match an unknown tool name to a known one.

    Strategy:
    1. Direct alias lookup
    2. Keyword overlap scoring
    3. String similarity (SequenceMatcher)
    """
    normalized = name.lower().replace(" ", "_").replace("-", "_")

    # 1. Direct alias
    if normalized in TOOL_ALIASES:
        matched = TOOL_ALIASES[normalized]
        logger.info("Tool alias: '%s' → '%s'", name, matched)
        return matched

    # Also check with hyphens
    hyphenated = name.lower().replace(" ", "-").replace("_", "-")
    if hyphenated in TOOL_ALIASES:
        matched = TOOL_ALIASES[hyphenated]
        logger.info("Tool alias: '%s' → '%s'", name, matched)
        return matched

    # 2. Keyword overlap
    name_words = set(re.split(r"[_\-\s]+", normalized))
    best_score = 0
    best_tool = None

    for tool, keywords in TOOL_KEYWORDS.items():
        keyword_set = set(keywords)
        overlap = len(name_words & keyword_set)
        # Also check partial matches (e.g. "crypto" in "cryptocurrency")
        partial = sum(
            1 for word in name_words
            for kw in keywords
            if kw in word or word in kw
        )
        score = overlap * 3 + partial
        if score > best_score:
            best_score = score
            best_tool = tool

    if best_score >= 2:
        logger.info("Keyword match: '%s' → '%s' (score=%d)", name, best_tool, best_score)
        return best_tool

    # 3. String similarity
    best_ratio = 0
    best_similar = None
    all_known = list(TOOL_KEYWORDS.keys())

    for tool in all_known:
        ratio = SequenceMatcher(None, normalized, tool).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_similar = tool

    if best_ratio >= 0.5:
        logger.info("Fuzzy match: '%s' → '%s' (ratio=%.2f)", name, best_similar, best_ratio)
        return best_similar

    logger.warning("No match found for tool: '%s'", name)
    return None


def resolve_tool_name(name: str) -> Optional[str]:
    """Resolve a tool name (exact or fuzzy) to a known tool."""
    if name.startswith("mcp_"):
        return name
    known_tools = set(TOOL_KEYWORDS.keys())
    if name in known_tools:
        return name
    return _fuzzy_match_tool(name)


def _extract_query_from_params(params: dict, original_tool: str) -> str:
    """Extract a search query from arbitrary tool params.

    When the LLM invents a tool like "cryptocurrency-analysis" with params
    like {"crypto_currencies": ["BTC", "ETH"], "time_period": "1 month"},
    we need to convert those params into a search query.
    """
    # If there's already a "query" param, use it
    if "query" in params:
        return params["query"]

    # Build a query from all param values
    parts = []
    for key, value in params.items():
        if isinstance(value, list):
            parts.append(" ".join(str(v) for v in value))
        elif isinstance(value, bool):
            if value:
                parts.append(key.replace("_", " "))
        elif isinstance(value, str):
            parts.append(value)
        elif isinstance(value, (int, float)):
            parts.append(f"{key.replace('_', ' ')} {value}")

    query = " ".join(parts)

    # Add context from the original tool name
    tool_context = original_tool.replace("-", " ").replace("_", " ")
    if tool_context.lower() not in query.lower():
        query = f"{tool_context}: {query}"

    return query


def _adapt_params(resolved_tool: str, original_tool: str, params: dict) -> dict:
    """Adapt params from an invented tool to match the real tool's expected params."""
    if resolved_tool == "search_web":
        # Convert any params into a search query
        query = _extract_query_from_params(params, original_tool)
        return {"query": query}

    elif resolved_tool == "execute_python":
        if "code" in params:
            return {"code": params["code"]}
        # If no code param, generate a simple script from the request
        return {"code": f"# Auto-generated from {original_tool}\nprint('Tool {original_tool} not directly available')"}

    elif resolved_tool == "screenshot_remote":
        url = params.get("url", params.get("target", params.get("page", "")))
        return {"url": url, "full_page": params.get("full_page", False)}

    elif resolved_tool == "generate_image":
        prompt = params.get("prompt", params.get("description", params.get("text", "")))
        fmt = params.get("format", "auto")
        return {"prompt": prompt, "negative_prompt": params.get("negative_prompt", ""), "format": fmt}

    elif resolved_tool == "generate_animation":
        prompt = params.get("prompt", params.get("description", params.get("text", "")))
        fmt = params.get("format", "gif")
        return {"prompt": prompt, "format": fmt, "duration": params.get("duration", 2.0)}

    elif resolved_tool == "run_command":
        if original_tool in ("search_file", "search-file", "find_file", "find-file", "file-search"):
            query = params.get("query", params.get("file_name", params.get("filename", params.get("path", ""))))
            # If the AI passed a query like "search file: . *.md", clean it up
            if query.startswith("search file:"):
                query = query.split(":", 1)[1].strip()
                query = query.replace(".", "").strip() # remove lone dot
            # Basic sanitization
            query = query.replace("'", "").replace('"', "")
            if not query:
                return {"command": "find . -type f | head -n 10"}
            return {"command": f"find . -iname '*{query}*' -type f | head -n 15"}
        return {"command": params.get("command", params.get("cmd", "echo 'no command specified'"))}

    elif resolved_tool == "audit_code":
        return {
            "mode": params.get("mode", "quick"),
            "code": params.get("code", ""),
            "target": params.get("target", ""),
        }

    elif resolved_tool == "rag_search":
        query = params.get("query", _extract_query_from_params(params, original_tool))
        return {"query": query, "k": params.get("k", 3)}



    elif resolved_tool == "edit_file":
        return {
            "file_path": params.get("file_path", ""),
            "old_string": params.get("old_string", ""),
            "new_string": params.get("new_string", ""),
            "replace_all": params.get("replace_all", False),
        }

    elif resolved_tool == "read_file":
        return {
            "file_path": params.get("file_path", ""),
            "start_line": params.get("start_line", 1),
            "end_line": params.get("end_line", None),
        }

    elif resolved_tool == "create_app":
        name = params.get("name", params.get("app_name", "My App"))
        files = params.get("files", {})
        template = params.get("template", "blank")
        res = {"name": name, "files": files, "template": template}
        if "icon" in params: res["icon"] = params["icon"]
        if "visual" in params: res["visual"] = params["visual"]
        return res

    elif resolved_tool == "update_app":
        app_id = params.get("app_id", params.get("id", ""))
        files = params.get("files", {})
        res = {"app_id": app_id, "files": files}
        if "name" in params: res["name"] = params["name"]
        if "icon" in params: res["icon"] = params["icon"]
        if "visual" in params: res["visual"] = params["visual"]
        return res

    # Fallback: return params as-is
    return params


# ---------------------------------------------------------------------------
# Tool pipeline enhancements (inspired by OpenMonoAgent)
# ---------------------------------------------------------------------------

# Read-only tools can be cached to save tokens and time
READONLY_TOOLS = {
    "search_web", "read_file", "rag_search", "screenshot_remote",
    "screenshot_local", "search_twitter", "search_linkedin",
    "fetch_market_data",
}

# Simple in-memory cache for read-only tools (key → (result, timestamp))
_tool_cache: dict[str, tuple[dict, float]] = {}
_CACHE_TTL_S = 300  # 5 minutes
_CACHE_MAX_SIZE = 100

# Artifact store threshold — results bigger than this are stored on disk
_ARTIFACT_THRESHOLD = 10_000  # 10KB chars


def _cache_key(tool_name: str, params: dict) -> str:
    """Generate a deterministic cache key for a tool call."""
    import hashlib
    param_str = json.dumps(params, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(f"{tool_name}:{param_str}".encode()).hexdigest()[:16]


def _check_cache(tool_name: str, params: dict) -> Optional[dict]:
    """Return cached result if available and fresh."""
    if tool_name not in READONLY_TOOLS:
        return None
    key = _cache_key(tool_name, params)
    if key in _tool_cache:
        result, ts = _tool_cache[key]
        import time
        if time.time() - ts < _CACHE_TTL_S:
            logger.debug("Cache hit for %s (key=%s)", tool_name, key)
            return result
        else:
            del _tool_cache[key]
    return None


def _store_cache(tool_name: str, params: dict, result: dict):
    """Store a result in the cache if the tool is read-only."""
    if tool_name not in READONLY_TOOLS:
        return
    # Evict oldest if full
    if len(_tool_cache) >= _CACHE_MAX_SIZE:
        oldest_key = min(_tool_cache, key=lambda k: _tool_cache[k][1])
        del _tool_cache[oldest_key]
    import time
    _tool_cache[_cache_key(tool_name, params)] = (result, time.time())


def _path_sanity_check(params: dict, tool_name: str) -> Optional[str]:
    """Block file operations that try to escape the workspace.

    Returns an error string if the path is unsafe, None otherwise.
    """
    from config import WORKSPACE_DIR
    path_keys = ["file_path", "target", "path"]
    for key in path_keys:
        val = params.get(key, "")
        if not val or not isinstance(val, str):
            continue
        if val.startswith("/workspace/"):
            val = val.replace("/workspace/", "", 1)
        elif val == "/workspace":
            val = "./"
        elif val.startswith("/apps/"):
            val = val.replace("/apps/", "apps/", 1)
            
        # Block absolute paths and parent directory traversal
        if val.startswith("/") or val.startswith("~") or ".." in val:
            return f"Path '{val}' is not allowed — must be relative to workspace with no '..' segments."
        # Resolve and verify it stays within workspace (allowing symlinks like apps/)
        import os
        full = os.path.realpath(os.path.join(WORKSPACE_DIR, val))
        if not full.startswith(os.path.realpath(WORKSPACE_DIR)) and not full.startswith(os.path.realpath(os.path.join(WORKSPACE_DIR, "../data/apps"))):
            return f"Path '{val}' escapes the workspace boundary."
    return None


async def execute_tool(tool_name: str, params: dict, context: dict = None) -> dict:
    """Execute a tool by name with the given params.

    Pipeline (inspired by OpenMonoAgent):
      1. Resolve name (fuzzy match)
      2. Adapt params
      3. Coerce types
      4. Path sanity check
      5. Cache lookup (read-only tools)
      6. Execute
      7. Cache store
      8. Artifact store (large results)

    Returns a dict with the tool result (or error).
    """
    original_name = tool_name
    resolved = resolve_tool_name(tool_name)

    if resolved is None:
        return {
            "error": f"Unknown tool: {tool_name}",
            "suggestion": "Available tools: " + ", ".join(sorted(TOOL_KEYWORDS.keys())),
        }

    # Adapt params if the tool was fuzzy-matched
    if resolved != original_name:
        logger.info("Adapting params from '%s' to '%s'", original_name, resolved)
        params = _adapt_params(resolved, original_name, params)

    # Coerce argument types (e.g. "42" → 42, "true" → True)
    from app.tool_repair import coerce_tool_args
    params = coerce_tool_args(resolved, params)

    # --- Pipeline Step: Schema validation (typed contracts) ---
    try:
        from app.tools.contracts import validate_tool_params
        params = validate_tool_params(resolved, params)
    except Exception:
        pass  # Schema validation is non-critical

    # --- Pipeline Step: Path sanity check ---
    if resolved in ("edit_file", "read_file", "audit_code", "analyze_data"):
        path_err = _path_sanity_check(params, resolved)
        if path_err:
            return {"error": f"Path sanity check failed: {path_err}"}

    # --- Pipeline Step: Cache lookup (read-only tools) ---
    cached = _check_cache(resolved, params)
    if cached is not None:
        return cached

    try:
        if resolved.startswith("mcp_"):
            from app.mcp_tool import get_mcp_skills
            from app.skill_model import SkillContext
            mcp_skills = get_mcp_skills()
            for skill in mcp_skills:
                if skill.name == resolved:
                    context = SkillContext(session_id="system", user_message=str(params))
                    result = await skill.execute(params, context)
                    return result.to_dict()
            return {"error": f"MCP skill {resolved} not found"}

        if resolved == "search_web":
            from app.tools_web import search_web
            query = params.get("query", "")
            max_results = params.get("max_results", 50)
            result = await search_web(query=query, max_results=max_results)
            return result

        elif resolved == "execute_python":
            from app.tools_code import executor
            from app.settings import load_settings

            code = params.get("code", "")
            if not code.strip():
                return {"error": "No code provided"}

            # Check for SQL/DB operations requiring confirmation
            settings = load_settings()
            require_confirm = settings.get("require_command_confirmation", True)

            if require_confirm:
                code_lower = code.lower()
                is_sql_query = "sqlite3" in code_lower and ("execute" in code_lower or "cursor" in code_lower)
                is_risky_sql = is_sql_query and any(kw in code_lower for kw in ("insert", "update", "delete", "drop", "create", "alter"))

                if is_risky_sql and not params.get("confirmed", False):
                    return {"error": "Python code contains risky SQL operations (INSERT, UPDATE, DELETE, DROP, CREATE, ALTER). Please ask the user for confirmation. If they agree, re-run with '\"confirmed\": true' in the params."}

            return executor.execute(code)

        elif resolved == "screenshot_remote":
            from fastapi import Request as _Req
            from app.tools_screenshot import screenshot_remote
            # screenshot_remote expects a Request, but we can call playwright directly
            url = params.get("url", "")
            if not url:
                return {"error": "URL is required for screenshot_remote"}
            return await _screenshot_remote_direct(url, params.get("full_page", False))

        elif resolved == "screenshot_local":
            return await _screenshot_local_direct()

        elif resolved == "generate_image":
            prompt = params.get("prompt", "")
            if not prompt:
                return {"error": "Prompt is required for generate_image"}
            return await _generate_image_direct(prompt, params.get("negative_prompt", ""), params.get("format", "auto"), params.get("style", "none"))

        elif resolved == "generate_animation":
            prompt = params.get("prompt", "")
            if not prompt:
                return {"error": "Prompt is required for generate_animation"}
            return await _generate_animation_direct(prompt, params.get("format", "gif"), params.get("duration", 2.0))

        elif resolved == "create_skill":
            from app.skill_creator import create_skill_core
            name = params.get("name", "")
            description = params.get("description", "")
            category = params.get("category", "other")
            code = params.get("code", "")
            parameters = params.get("parameters", None)
            triggers = params.get("triggers", None)
            return await create_skill_core(name, description, category, code, parameters=parameters, triggers=triggers)

        elif resolved == "run_command":
            from app.tools_local import ALLOWED_COMMANDS
            from app.settings import load_settings
            import subprocess
            import shlex
            import os

            command = params.get("command", "")
            if not command.strip():
                return {"error": "No command provided"}
            tokens = shlex.split(command)
            if not tokens:
                return {"error": "Empty command"}

            # Risk confirmation check
            settings = load_settings()
            require_confirm = settings.get("require_command_confirmation", True)

            is_deletion = any(os.path.basename(token) in ("rm", "rmdir", "unlink") for token in tokens)
            base_cmd = os.path.basename(tokens[0])
            is_risky = base_cmd in {"python", "python3", "pip", "pip3", "git", "docker", "curl", "wget", "sqlite3", "psql", "mysql"} or is_deletion

            if is_risky and require_confirm:
                # If not confirmed, return an error asking the LLM to get permission
                if not params.get("confirmed", False):
                    return {"error": f"Command '{tokens[0]}' (or a deletion command) is risky. Please ask the user for confirmation. If they agree, re-run with '\"confirmed\": true' in the params."}

            # Allow deletion commands if confirmed, but we must bypass the ALLOWED_COMMANDS check for the main executable if it's rm
            raw_base_cmd = tokens[0]
            if raw_base_cmd not in ALLOWED_COMMANDS and raw_base_cmd not in ("rm", "rmdir", "unlink"):
                return {"error": f"Command '{raw_base_cmd}' not allowed"}
            
            # Prevent escaping the workspace
            for i, token in enumerate(tokens):
                if token.startswith("/workspace/") or token == "/workspace":
                    tokens[i] = token.replace("/workspace", ".", 1)
                    if tokens[i] == ".": tokens[i] = "./"
                    token = tokens[i]
                elif token.startswith("/apps/"):
                    tokens[i] = token.replace("/apps/", "./apps/", 1)
                    token = tokens[i]
                    
                if token.startswith("/") or token.startswith("~") or ".." in token:
                    return {"error": f"Access denied: Path '{token}' is not allowed. Use relative paths within the workspace (e.g., apps/app-id/index.html)."}
                    
            cwd = "./workspace"
            if context and context.get("active_project") and context["active_project"] != ".":
                proj_dir = os.path.join(cwd, context["active_project"])
                if os.path.isdir(proj_dir):
                    cwd = proj_dir
                    
            result = subprocess.run(tokens, shell=False, capture_output=True, text=True, timeout=30, cwd=cwd)
            return {"stdout": result.stdout[-5000:], "stderr": result.stderr[-500:], "returncode": result.returncode, "command": command}

        elif resolved == "audit_code":
            from app.tools_code import auditor
            mode = params.get("mode", "quick")
            if mode == "full":
                target = params.get("target", "")
                if not target:
                    return {"error": "target is required for full audit"}
                return auditor.full_audit(target)
            else:
                code = params.get("code", "")
                if not code.strip():
                    return {"error": "No code provided for audit"}
                return auditor.audit(code)

        elif resolved == "rag_search":
            from app.rag import search
            query = params.get("query", "")
            k = params.get("k", 3)
            return await search(query=query, k=k)


        elif resolved == "create_document":
            from app.tools_document import create_document_core
            format_type = params.get("format_type", "markdown")
            content = params.get("content", "")
            title = params.get("title", "")
            if not content:
                return {"error": "Content is required to create a document"}
            return await create_document_core(format_type, content, title)

        elif resolved == "edit_file":
            from app.tools_code import editor
            file_path = params.get("file_path", "")
            if not file_path:
                return {"error": "file_path is required"}
            # Handle LLM hallucinations where it uses 'content' instead of 'new_string'
            old_str = params.get("old_string", "")
            new_str = params.get("new_string")
            if new_str is None:
                new_str = params.get("content", "")
            replace_all = params.get("replace_all", False)
            return editor.edit_file(file_path, old_str, new_str, replace_all)

        elif resolved == "read_file":
            from app.tools_code import editor
            file_path = params.get("file_path", "")
            if not file_path:
                return {"error": "file_path is required"}
            start_line = params.get("start_line", 1)
            end_line = params.get("end_line", None)
            return editor.read_file(file_path, start_line, end_line)

        elif resolved == "send_email":
            from app.integrations_social import send_email
            subject = params.get("subject", "")
            body = params.get("body", "")
            if not subject or not body:
                return {"error": "subject and body are required"}
            return await send_email(subject, body, params.get("to_email"))

        elif resolved == "post_to_twitter":
            from app.integrations_social import post_to_twitter
            text = params.get("text", "")
            if not text:
                return {"error": "text is required"}
            return await post_to_twitter(text)

        elif resolved == "post_to_linkedin":
            from app.integrations_social import post_to_linkedin
            text = params.get("text", "")
            if not text:
                return {"error": "text is required"}
            return await post_to_linkedin(text)

        elif resolved == "post_to_medium":
            from app.integrations_social import post_to_medium
            title = params.get("title", "")
            content = params.get("content", "")
            if not title or not content:
                return {"error": "title and content are required"}
            return await post_to_medium(title, content, params.get("tags", []), params.get("publish_status", "draft"))

        elif resolved == "trigger_n8n":
            from app.integrations_social import trigger_n8n_webhook
            payload = params.get("payload", {})
            if not payload:
                return {"error": "payload is required"}
            return await trigger_n8n_webhook(payload)

        elif resolved == "memory":
            from app.memory import handle_memory_tool
            return handle_memory_tool(params)

        elif resolved == "rebuild_skill":
            from app.skill_rebuilder import rebuild_skill
            skill_name = params.get("name", params.get("skill_name", ""))
            if not skill_name:
                return {"error": "skill name is required (param: 'name')"}
            instruction = params.get("instruction", "")
            return await rebuild_skill(skill_name, instruction)

        elif resolved == "undo":
            from app.tools_code import snapshot_manager
            file_path = params.get("file_path", "")
            if file_path:
                return snapshot_manager.undo(file_path)
            else:
                return snapshot_manager.undo_last()

        elif resolved == "graphify_query":
            from app.graphify_integration import graphify_query
            query = params.get("query", "")
            if not query:
                return {"error": "query is required"}
            return graphify_query(query, params.get("project_path", "."))

        elif resolved == "graphify_explain":
            from app.graphify_integration import graphify_explain
            node = params.get("node", "")
            if not node:
                return {"error": "node name is required"}
            return graphify_explain(node, params.get("project_path", "."))

        elif resolved == "graphify_path":
            from app.graphify_integration import graphify_path
            source = params.get("source", "")
            target = params.get("target", "")
            if not source or not target:
                return {"error": "source and target are required"}
            return graphify_path(source, target, params.get("project_path", "."))

        elif resolved == "search_twitter":
            from app.tools_twitter import search_tweets, get_user_tweets
            query = params.get("query", "")
            username = params.get("username", "")
            max_results = params.get("max_results", 10)
            if username:
                results = await get_user_tweets(username, max_results)
                return {"username": username, "count": len(results), "tweets": results}
            elif query:
                results = await search_tweets(query, max_results)
                return {"query": query, "count": len(results), "tweets": results}
            else:
                return {"error": "query or username is required"}

        elif resolved == "search_linkedin":
            from app.tools_twitter import search_linkedin_profiles, search_linkedin_articles
            query = params.get("query", "")
            search_type = params.get("type", "profiles")  # "profiles" or "articles"
            max_results = params.get("max_results", 10)
            if not query:
                return {"error": "query is required"}
            if search_type == "articles":
                results = await search_linkedin_articles(query, max_results)
            else:
                results = await search_linkedin_profiles(query, max_results)
            return {"query": query, "type": search_type, "count": len(results), "results": results}

        elif resolved == "fetch_market_data":
            from app.tools_market import fetch_market_data
            return fetch_market_data(params)

        elif resolved == "create_app":
            from app.core.app_builder import create_app
            from app.core.app_validator import validate_app_files
            name = params.get("name", "My App")
            files = params.get("files", {})
            template = params.get("template", "blank")
            icon = params.get("icon")
            visual = params.get("visual")
            session_id = (context or {}).get("session_id")

            # --- Validate generated code BEFORE publishing ---
            if files:
                validation = validate_app_files(files)
                if not validation["valid"]:
                    error_list = "\n".join(f"  • {e}" for e in validation["errors"])
                    return {
                        "error": (
                            f"Code validation failed — fix these issues and retry:\n"
                            f"{error_list}\n\n"
                            f"Re-emit a corrected create_app tool call with the fixed code."
                        ),
                        "validation_errors": validation["errors"],
                    }

            result = create_app(name, files, session_id=session_id, template=template, icon=icon, visual=visual)
            if files:
                result["_hint"] = "App created and published (code validated ✅)."
            return result

        elif resolved == "update_app":
            from app.core.app_builder import update_app
            from app.core.app_validator import validate_app_files
            app_id = params.get("app_id", "")
            files = params.get("files", {})
            name = params.get("name")
            icon = params.get("icon")
            visual = params.get("visual")
            if not app_id:
                return {"error": "app_id is required"}
            if not files and name is None and icon is None and visual is None:
                return {"error": "At least one of files, name, icon, or visual is required to update"}

            # --- Validate generated code BEFORE updating ---
            if files:
                validation = validate_app_files(files)
                if not validation["valid"]:
                    error_list = "\n".join(f"  • {e}" for e in validation["errors"])
                    return {
                        "error": (
                            f"Code validation failed — fix these issues and retry:\n"
                            f"{error_list}\n\n"
                            f"Re-emit a corrected update_app tool call with the fixed code."
                        ),
                        "validation_errors": validation["errors"],
                    }

            result = update_app(app_id, files=files, name=name, icon=icon, visual=visual)
            if not result:
                return {"error": f"App '{app_id}' not found"}
            if files:
                result["_hint"] = "App updated and published (code validated ✅)."
            return result

        elif resolved == "analyze_data":
            from app.tools_data_analysis import analyze_file
            file_path = params.get("file_path", "")
            if not file_path:
                return {"error": "file_path is required (CSV or Excel file)"}
            focus = params.get("focus", "")
            max_charts = params.get("max_charts", 5)
            return await analyze_file(file_path, focus=focus, max_charts=max_charts)

        elif resolved == "list_files":
            import glob as _glob
            import os as _os
            from config import WORKSPACE_DIR
            pattern = params.get("pattern", "**/*") or "**/*"
            limit = min(int(params.get("limit", 60)), 200)
            include_dirs = bool(params.get("include_dirs", False))

            # Reject absolute paths and traversal sequences before globbing
            if pattern.startswith("/") or pattern.startswith("\\"):
                return {"error": "Absolute paths are not allowed in list_files pattern"}

            # Normalize and verify the pattern doesn't escape the workspace
            # after any manipulation by stripping dangerous sequences
            safe_parts = [p for p in pattern.replace("\\", "/").split("/") if p not in ("..", "")]
            pattern = "/".join(safe_parts) if safe_parts else "**/*"

            try:
                base = _os.path.realpath(WORKSPACE_DIR)
                all_matches = _glob.glob(pattern, root_dir=base, recursive=True)
                results = []
                for m in all_matches:
                    # Double-check resolved path stays within workspace
                    full = _os.path.realpath(_os.path.join(base, m))
                    if not full.startswith(base):
                        continue  # Skip paths that escaped the workspace
                    if _os.path.isdir(full):
                        if include_dirs:
                            results.append({"path": m, "type": "dir"})
                    else:
                        try:
                            size = _os.path.getsize(full)
                        except OSError:
                            size = 0
                        results.append({"path": m, "type": "file", "size": size})
                    if len(results) >= limit:
                        break

                is_truncated = len(all_matches) > limit or len(results) >= limit
                return {
                    "pattern": pattern,
                    "count": len(results),
                    "truncated": is_truncated,
                    "files": results,
                }
            except Exception as e:
                return {"error": f"list_files failed: {e}"}

        elif resolved == "todo_write":
            return _handle_todo_write(params, (context or {}).get("session_id", "default"))

        else:
            return {"error": f"Tool '{resolved}' is registered but has no executor"}

    except Exception as e:
        logger.error("Tool execution error (%s): %s", resolved, e)
        return {"error": f"Tool '{resolved}' failed: {str(e)}"}

    # --- Pipeline Step: Cache store (should not reach here, but safety) ---
    # Note: cache store is handled inline above for each tool return


# ---------------------------------------------------------------------------
# Direct tool implementations (bypass FastAPI Request objects)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# TodoWrite registry — in-memory per-session todo state (s03 Planning)
# ---------------------------------------------------------------------------
_todo_registry: dict[str, list[dict]] = {}  # session_id -> list of todos

_VALID_STATUSES = frozenset({"pending", "in_progress", "completed", "cancelled"})
_VALID_PRIORITIES = frozenset({"high", "medium", "low"})


def _handle_todo_write(params: dict, session_id: str) -> dict:
    """Manage a per-session structured todo list (inspired by Claude Code TodoWriteTool).

    Supports three actions:
    - 'write': Replace the entire todo list for this session
    - 'update': Update a specific todo item's status (by id)
    - 'clear': Remove all todos for this session

    The todo list is streamed to connected SSE clients via a special
    __TODO_UPDATE__ marker so the frontend can display it in real-time.
    """
    import time as _todo_time
    action = params.get("action", "write")
    # NOTE: no 'global' needed — dict mutations don't require it in Python

    if action == "clear":
        _todo_registry.pop(session_id, None)
        return {"status": "cleared", "session_id": session_id, "todos": [], "__todo_update__": True}

    if action == "update":
        item_id = params.get("id", "")
        new_status = params.get("status", "")
        if not item_id:
            return {"error": "'id' is required for the 'update' action"}
        if new_status and new_status not in _VALID_STATUSES:
            return {"error": f"Invalid status '{new_status}'. Valid: {sorted(_VALID_STATUSES)}"}
        todos = _todo_registry.get(session_id, [])
        if not todos:
            return {"error": f"No todo list found for session '{session_id}'"}
        updated = False
        for todo in todos:
            if todo.get("id") == item_id:
                if new_status:
                    todo["status"] = new_status
                todo["updated_at"] = _todo_time.time()
                updated = True
                break
        if not updated:
            return {"error": f"Todo item '{item_id}' not found"}
        # Only write back when actually updated
        _todo_registry[session_id] = todos
        return {"status": "updated", "id": item_id, "todos": todos, "__todo_update__": True}

    # Default: 'write' action
    raw_todos = params.get("todos", [])
    if not isinstance(raw_todos, list):
        return {"error": "'todos' must be a list of objects"}
    if not raw_todos:
        return {"error": "'todos' list is empty. Provide at least one todo item."}

    now = _todo_time.time()
    todos = []
    for i, item in enumerate(raw_todos):
        if not isinstance(item, dict):
            continue
        status = item.get("status", "pending")
        priority = item.get("priority", "medium")
        # Sanitize to valid enum values
        if status not in _VALID_STATUSES:
            status = "pending"
        if priority not in _VALID_PRIORITIES:
            priority = "medium"
        todos.append({
            "id": str(item.get("id") or f"step-{i + 1}"),
            "content": str(item.get("content", "")).strip(),
            "status": status,
            "priority": priority,
            "created_at": now,
            "updated_at": now,
        })

    if not todos:
        return {"error": "No valid todo items found. Each item must be an object with 'id' and 'content'."}

    _todo_registry[session_id] = todos
    logger.info("todo_write: session=%s action=write items=%d", session_id, len(todos))
    return {"status": "written", "count": len(todos), "todos": todos, "__todo_update__": True}


def get_session_todos(session_id: str) -> list[dict]:
    """Get the current todo list for a session (used by gateway SSE /todos endpoint)."""
    return list(_todo_registry.get(session_id, []))  # Return a copy to prevent external mutation


async def _screenshot_remote_direct(url: str, full_page: bool = False) -> dict:
    """Take a remote screenshot without going through the HTTP endpoint."""
    import os, uuid, base64
    from datetime import datetime
    from config import DATA_DIR

    screenshots_dir = os.path.join(DATA_DIR, "screenshots")
    os.makedirs(screenshots_dir, exist_ok=True)
    filename = f"remote_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.png"
    filepath = os.path.join(screenshots_dir, filename)
    extract = ""

    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            page = await browser.new_page(viewport={"width": 1920, "height": 1080})
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await page.screenshot(path=filepath, full_page=full_page)
            try:
                text = await page.inner_text("body", timeout=5000)
                extract = text[:3000] if text else ""
            except Exception:
                pass
            await browser.close()

        with open(filepath, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        return {"status": "ok", "filename": filename, "base64": b64, "url": url, "extract": extract}
    except Exception as e:
        return {"error": f"Screenshot failed: {e}"}


async def _screenshot_local_direct() -> dict:
    """Take a local screenshot without going through the HTTP endpoint."""
    import os, uuid, base64, subprocess
    from datetime import datetime
    from config import DATA_DIR

    screenshots_dir = os.path.join(DATA_DIR, "screenshots")
    os.makedirs(screenshots_dir, exist_ok=True)
    filename = f"local_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.png"
    filepath = os.path.join(screenshots_dir, filename)

    for cmd in [
        ["scrot", filepath],
        ["gnome-screenshot", "-f", filepath],
        ["import", "-window", "root", filepath],
    ]:
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=10)
            if result.returncode == 0 and os.path.exists(filepath):
                with open(filepath, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode()
                return {"status": "ok", "filename": filename, "base64": b64}
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return {"error": "No screenshot tool available"}


async def _generate_image_direct(prompt: str, negative_prompt: str = "", format: str = "auto", style: str = "none") -> dict:
    """Generate an image using the unified core (SVG → GPU → API fallback).

    Uses Flux.2 Klein by default (style='none') with AI prompt enrichment
    enabled for chat-based generation.
    Default resolution is 704×480 (standard chat resolution).
    """
    try:
        from app.tools_image import generate_image_core
        return await generate_image_core(
            prompt=prompt,
            negative_prompt=negative_prompt or "blurry, low quality, distorted",
            width=704,
            height=480,
            format=format,
            style=style,
            enhance_prompt=True,  # Always enhance for chat-based generation
        )
    except Exception as e:
        return {"error": f"Image generation failed: {e}"}


async def _generate_animation_direct(prompt: str, format: str = "gif", duration: float = 2.0) -> dict:
    """Generate an animation using the video diffusion pipeline."""
    try:
        from app.tools_image import generate_animation_core
        return await generate_animation_core(
            prompt=prompt,
            format=format,
            duration=duration,
            enhance_prompt=True,  # Always enhance for chat-based generation (includes translation)
        )
    except Exception as e:
        return {"error": f"Animation generation failed: {e}"}



# Fence labels that should be treated as tool calls
_TOOL_FENCE_NAMES = (
    "tool_call|tool|json"
    "|execute_python|search_web|screenshot_remote|screenshot_local"
    "|generate_image|generate_animation|run_command|audit_code|rag_search"
    "|edit_file|read_file|create_document"
    "|send_email|post_to_twitter|post_to_linkedin|post_to_medium|trigger_n8n"
    "|memory|rebuild_skill|search_twitter|search_linkedin"
    "|create_app|update_app|analyze_data"
    "|fetch_market_data|analyze_data"
    "|bash|sh|python"
)
TOOL_CALL_RE = re.compile(
    rf"```({_TOOL_FENCE_NAMES})\n([\s\S]*?)\n```", re.MULTILINE
)
# Fallback regex for unclosed fences (LLM truncated before closing ```)
TOOL_CALL_UNCLOSED_RE = re.compile(
    rf"```({_TOOL_FENCE_NAMES})\n([\s\S]+)$", re.MULTILINE
)


def parse_tool_calls(text: str) -> list[dict]:
    """Extract all tool_call blocks from LLM response text.

    Supports multiple formats:
    1. JSON: ```tool_call\n{"tool": "...", "params": {...}}\n```
    2. Bare code with tool-name fence: ```execute_python\nprint('hello')\n```
    3. Bare JSON (unfenced): {"tool":"create_app","params":{...}}

    Returns a list of {"tool": ..., "params": ..., "raw": ...} dicts.
    """
    calls = []
    matched_spans = []  # Track spans already captured by fenced blocks
    from app.tool_repair import repair_tool_call_arguments

    for match in TOOL_CALL_RE.finditer(text):
        fence_label = match.group(1).strip()
        raw = match.group(2).strip()
        matched_spans.append((match.start(), match.end()))
        # Strip hallucinated 'tool_call' or 'json' from start of block
        if raw.lower().startswith("tool_call\n"):
            raw = raw[10:].strip()
        elif raw.lower().startswith("json\n"):
            raw = raw[5:].strip()

        try:
            # Apply JSON repair before parsing (handles trailing commas,
            # unclosed brackets, Python None, etc.)
            repaired = repair_tool_call_arguments(raw, fence_label)
            data = json.loads(repaired)
            if isinstance(data, dict) and "tool" in data:
                calls.append({
                    "tool": data.get("tool", ""),
                    "params": data.get("params", {}),
                    "raw": match.group(0),
                })
                continue
        except (json.JSONDecodeError, ValueError):
            pass

        # --- Multi-call recovery ---
        # If json.loads failed, the LLM may have emitted multiple JSON
        # objects inside a single ```tool_call fence (e.g. two
        # fetch_market_data calls separated by a newline).  Scan the
        # raw content for individual {"tool":...} objects.
        if fence_label in ("tool_call", "tool", "json"):
            _MULTI_TOOL_RE = re.compile(r'\{\s*"tool"\s*:\s*"(\w+)"')
            found_any = False
            for sub_m in _MULTI_TOOL_RE.finditer(raw):
                sub_json = _extract_balanced_json(raw, sub_m.start())
                if not sub_json:
                    continue
                try:
                    repaired_sub = repair_tool_call_arguments(sub_json, fence_label)
                    sub_data = json.loads(repaired_sub)
                    if isinstance(sub_data, dict) and "tool" in sub_data:
                        calls.append({
                            "tool": sub_data.get("tool", ""),
                            "params": sub_data.get("params", {}),
                            "raw": sub_json,
                        })
                        found_any = True
                        logger.info(
                            "Multi-call recovery: found '%s' inside fenced block",
                            sub_data.get("tool"),
                        )
                except (json.JSONDecodeError, ValueError):
                    pass
            if found_any:
                continue

        # Bare code with tool-name fence (e.g. ```execute_python\nprint(...)\n```)
        if fence_label not in ("tool_call", "tool", "json") and raw:
            tool_name = fence_label
            if fence_label == "python":
                tool_name = "execute_python"
            elif fence_label in ("bash", "sh"):
                tool_name = "run_command"
            
            params = {"query": raw}
            if tool_name == "execute_python":
                params = {"code": raw}
            elif tool_name == "run_command":
                params = {"command": raw}
                
            calls.append({
                "tool": tool_name,
                "params": params,
                "raw": match.group(0),
            })
            logger.info("Bare code tool call: fence='%s' → '%s' (%d chars)", fence_label, tool_name, len(raw))

    # --- Fallback: unclosed fence recovery ---
    # If the LLM was truncated before emitting the closing ```, try to
    # extract tool calls from the unclosed fence content.
    if not calls:
        for match in TOOL_CALL_UNCLOSED_RE.finditer(text):
            start_pos = match.start()
            # Skip spans already matched by the closed-fence regex
            if any(s <= start_pos < e for s, e in matched_spans):
                continue
            fence_label = match.group(1).strip()
            raw = match.group(2).strip()
            if fence_label in ("tool_call", "tool", "json"):
                _MULTI_TOOL_RE = re.compile(r'\{\s*"tool"\s*:\s*"(\w+)"')
                for sub_m in _MULTI_TOOL_RE.finditer(raw):
                    sub_json = _extract_balanced_json(raw, sub_m.start())
                    if not sub_json:
                        continue
                    try:
                        repaired_sub = repair_tool_call_arguments(sub_json, fence_label)
                        sub_data = json.loads(repaired_sub)
                        if isinstance(sub_data, dict) and "tool" in sub_data:
                            calls.append({
                                "tool": sub_data.get("tool", ""),
                                "params": sub_data.get("params", {}),
                                "raw": sub_json,
                            })
                            logger.info(
                                "Unclosed-fence recovery: found '%s'",
                                sub_data.get("tool"),
                            )
                    except (json.JSONDecodeError, ValueError):
                        pass

    # --- Fallback: scan for bare/unfenced JSON tool calls ---
    # Some models (especially for create_app/update_app) emit the tool call
    # JSON without wrapping it in a code fence. We try to detect these.
    if not calls:
        calls.extend(_parse_bare_tool_calls(text, matched_spans))

    return calls


def _parse_bare_tool_calls(text: str, exclude_spans: list[tuple[int, int]]) -> list[dict]:
    """Fallback parser for tool calls emitted without code fences.

    Scans for JSON objects that look like {"tool": "...", "params": {...}}
    outside of already-matched fenced blocks.  Uses balanced-brace counting
    to handle nested JSON (e.g. HTML content inside `files` values).
    """
    results = []
    # Quick check — must contain a tool key pattern
    _TOOL_MARKER = re.compile(r'\{\s*"tool"\s*:\s*"(\w+)"')
    for m in _TOOL_MARKER.finditer(text):
        start = m.start()
        # Skip if inside an already-matched fenced block
        if any(s <= start < e for s, e in exclude_spans):
            continue

        # Extract balanced JSON starting from the opening brace
        json_str = _extract_balanced_json(text, start)
        if not json_str:
            continue

        try:
            data = json.loads(json_str)
            if isinstance(data, dict) and "tool" in data:
                results.append({
                    "tool": data["tool"],
                    "params": data.get("params", {}),
                    "raw": json_str,
                })
                logger.info(
                    "Bare (unfenced) tool call detected: %s (%d chars)",
                    data["tool"], len(json_str),
                )
        except (json.JSONDecodeError, ValueError):
            # Try repair
            try:
                from app.tool_repair import repair_tool_call_arguments
                repaired = repair_tool_call_arguments(json_str, m.group(1))
                data = json.loads(repaired)
                if isinstance(data, dict) and "tool" in data:
                    results.append({
                        "tool": data["tool"],
                        "params": data.get("params", {}),
                        "raw": json_str,
                    })
                    logger.info(
                        "Bare tool call (repaired): %s (%d chars)",
                        data["tool"], len(json_str),
                    )
            except (json.JSONDecodeError, ValueError):
                logger.debug("Failed to parse bare tool call at pos %d", start)
    return results


def _extract_balanced_json(text: str, start: int) -> Optional[str]:
    """Extract a balanced JSON object from *text* starting at *start*.

    Tracks brace nesting and handles strings (including escaped quotes)
    to find the matching closing brace.  Returns ``None`` if the braces
    never balance or the extracted region exceeds a safety limit.
    """
    MAX_LEN = 500_000  # Safety cap for huge app files
    depth = 0
    in_string = False
    i = start
    n = min(len(text), start + MAX_LEN)
    while i < n:
        ch = text[i]
        if in_string:
            if ch == '\\' and i + 1 < n:
                i += 2  # skip escaped char
                continue
            if ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    return text[start:i + 1]
        i += 1
    return None


def format_tool_result(tool_name: str, result: dict) -> str:
    """Format a tool result as a compact string for the LLM context.

    Uses RTK-style compression (smart filtering, grouping, truncation,
    deduplication) to minimize token consumption without losing quality.
    """
    from app.output_compressor import (
        compress_command_output,
        compress_search_results,
        compress_code_execution,
        compress_browse_result,
        compress_file_content,
        compress_generic,
    )

    if "error" in result:
        # Keep errors concise but complete
        err = result['error']
        if len(err) > 500:
            err = err[:400] + "..." + err[-100:]
        return f"Tool '{tool_name}' error: {err}"

    if "results" in result:
        # Search results — compressed
        items = result["results"]
        if not items:
            return "No search results."
        return compress_search_results(items)

    if "stdout" in result:
        out = result.get("stdout", "")
        err = result.get("stderr", "")
        imgs = result.get("images", [])
        rc = result.get("returncode", 0)

        if tool_name in ("execute_python", "execute_code"):
            # Python execution — compressed
            compressed = compress_code_execution(out, err, imgs, rc)
            return compressed
        else:
            # Shell command (run_command) — RTK-style compression
            command = result.get("command", "")
            compressed = compress_command_output(out, err, rc, command)
            if rc != 0:
                return f"exit {rc}:\n{compressed}"
            return compressed

    if "base64" in result or "svg" in result:
        # Image/screenshot — don't include the base64/svg in the LLM context
        fname = result.get('filename', 'image.png')
        fmt = result.get('format', 'png')
        method = result.get('method', 'unknown')
        res_str = f"ok {tool_name} ({method},{fmt}) -> {fname}"
        if result.get("extract"):
            res_str += f"\n\nPage Extract:\n{result['extract']}"
        return res_str

    if tool_name == "create_document" and "status" in result and result["status"] == "ok":
        fname = result.get('filename', 'document')
        fmt = result.get('format', 'unknown')
        return f"ok document created ({fmt}) -> {fname}"

    if "documents" in result:
        # RAG results — compact
        docs = result["documents"]
        if not docs:
            return "No knowledge base results."
        lines = []
        for i, doc in enumerate(docs[:3], 1):
            lines.append(f"{i}. {doc[:180]}")
        return "\n".join(lines)

    if "total_findings" in result:
        # Audit results — compact
        return (
            f"Audit: {result['total_findings']} findings. "
            f"Severity: {result.get('severity', {})}"
        )

    if tool_name == "list_files" and "files" in result:
        # GlobTool results — compact file listing
        files = result["files"]
        if not files:
            return f"No files match pattern '{result.get('pattern', '')}'."
        lines = [f"Found {result['count']} file(s) (pattern: {result.get('pattern', '**/*')})"]
        if result.get("truncated"):
            lines[0] += " [truncated]"
        for f in files[:50]:
            size_str = f" ({f['size']:,}B)" if f.get("size") else ""
            icon = "📂" if f["type"] == "dir" else "📄"
            lines.append(f"{icon} {f['path']}{size_str}")
        return "\n".join(lines)

    if tool_name == "todo_write" and "todos" in result:
        # TodoWrite — show the plan to the LLM as a compact checklist
        todos = result["todos"]
        if not todos:
            return "Todo list cleared."
        status_icons = {
            "pending": "⏳",
            "in_progress": "🔄",
            "completed": "✅",
            "cancelled": "❌",
        }
        action = result.get("status", "written")
        lines = [f"Todo list {action}: {len(todos)} item(s)"]
        for t in todos:
            icon = status_icons.get(t.get("status", "pending"), "⏳")
            lines.append(f"{icon} [{t.get('id', '?')}] {t.get('content', '')} ({t.get('priority', 'medium')})") 
        return "\n".join(lines)

    if tool_name in ("create_app", "update_app") and "id" in result:
        # App builder — compact output (don't send full file content back to LLM)
        app_id = result["id"]
        app_name = result.get("name", "App")
        version = result.get("version", 1)
        files = result.get("files", [])
        preview = result.get("preview_url", f"/apps/{app_id}/index.html")
        hint = result.get("_hint", "")
        lines = [
            f"ok {tool_name}: {app_name} (id={app_id}, v{version})",
            f"Files: {', '.join(files) if isinstance(files, list) else files}",
            f"Preview: {preview}",
        ]
        if hint:
            lines.append(hint)
        return "\n".join(lines)

    if tool_name == "fetch_market_data" and "data" in result:
        # Market data — return compact summary + CSV path + clear plotting template
        sym = result.get("symbol", "?")
        source = result.get("source", "?")
        count = result.get("count", 0)
        columns = result.get("columns", [])
        data = result.get("data", [])
        csv_path = result.get("csv_path", "")

        lines = [
            f"✅ {sym} ({source}): {count} candles fetched.",
            f"Columns: {columns}",
        ]
        # Show first 3 and last 2 rows for context
        if data:
            for row in data[:3]:
                lines.append(f"  {row}")
            if len(data) > 5:
                lines.append(f"  ... ({count - 5} more rows)")
            for row in data[-2:]:
                lines.append(f"  {row}")

        if csv_path:
            lines.append("")
            lines.append(f"Data saved to: {csv_path}")
            lines.append(
                "To plot, use execute_python with a SHORT script:\n"
                "import pandas as pd\n"
                "import matplotlib\n"
                "matplotlib.use('Agg')\n"
                "import matplotlib.pyplot as plt\n"
                f"df = pd.read_csv('{csv_path}')\n"
                f"plt.figure(figsize=(12, 6))\n"
                f"plt.plot(df['close'], label='{sym}')\n"
                f"plt.title('{sym} Price')\n"
                "plt.legend()\n"
                "plt.tight_layout()\n"
                "plt.savefig('/tmp/chart.png', dpi=100)\n"
                "print('Chart saved to /tmp/chart.png')"
            )
        return "\n".join(lines)

    # Generic result — compressed
    text = json.dumps(result, ensure_ascii=False)
    return compress_generic(text, max_chars=1500)
