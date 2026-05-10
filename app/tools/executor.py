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
    "browse_web": [
        "browse", "navigate", "open", "click", "fill", "form", "interact",
        "scrape", "extract",
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
}

# Direct alias map for common invented names
TOOL_ALIASES: dict[str, str] = {
    # Crypto / finance
    "cryptocurrency-analysis": "search_web",
    "crypto-analysis": "search_web",
    "crypto_analysis": "search_web",
    "market-analysis": "search_web",
    "stock-analysis": "search_web",
    "finance-analysis": "search_web",
    "price-checker": "search_web",
    "trend-analysis": "search_web",
    # Search variants
    "cybersearch": "search_web",
    "cyber-search": "search_web",
    "web-search": "search_web",
    "internet-search": "search_web",
    "google-search": "search_web",
    "web_scraper": "search_web",
    "web_scraping": "browse_web",
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
    # Other
    "file-search": "run_command",
    "search-file": "run_command",
    "search_file": "run_command",
    "find-file": "run_command",
    "find_file": "run_command",
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

    elif resolved_tool == "browse_web":
        return {"url": params.get("url", ""), "actions": params.get("actions", [])}

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

        elif resolved == "browse_web":
            url = params.get("url", "")
            if not url:
                return {"error": "URL is required"}
            actions = params.get("actions", [])
            # Try Playwright-based automation first
            try:
                from app.tools_browser import execute_actions
                return await execute_actions(
                    url, actions, take_final_screenshot=True,
                )
            except (ImportError, HTTPException):
                # Fallback to simulated browser (requests + BeautifulSoup)
                from app.web_browser_simul import simul_browse
                return await simul_browse(url, actions)

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

        elif resolved == "create_app":
            from app.core.app_builder import create_app
            name = params.get("name", "My App")
            files = params.get("files", {})
            template = params.get("template", "blank")
            icon = params.get("icon")
            visual = params.get("visual")
            session_id = (context or {}).get("session_id")
            result = create_app(name, files, session_id=session_id, template=template, icon=icon, visual=visual)
            if files:
                result["_hint"] = "App created successfully. Remember to verify the generated code for correctness."
            return result

        elif resolved == "update_app":
            from app.core.app_builder import update_app
            app_id = params.get("app_id", "")
            files = params.get("files", {})
            name = params.get("name")
            icon = params.get("icon")
            visual = params.get("visual")
            if not app_id:
                return {"error": "app_id is required"}
            if not files and name is None and icon is None and visual is None:
                return {"error": "At least one of files, name, icon, or visual is required to update"}
            result = update_app(app_id, files=files, name=name, icon=icon, visual=visual)
            if not result:
                return {"error": f"App '{app_id}' not found"}
            if files:
                result["_hint"] = "App updated successfully. Remember to verify the generated code for correctness."
            return result

        elif resolved == "analyze_data":
            from app.tools_data_analysis import analyze_file
            file_path = params.get("file_path", "")
            if not file_path:
                return {"error": "file_path is required (CSV or Excel file)"}
            focus = params.get("focus", "")
            max_charts = params.get("max_charts", 5)
            return await analyze_file(file_path, focus=focus, max_charts=max_charts)

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
    """
    try:
        from app.tools_image import generate_image_core
        return await generate_image_core(
            prompt=prompt,
            negative_prompt=negative_prompt or "blurry, low quality, distorted",
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
    "|generate_image|generate_animation|run_command|browse_web|audit_code|rag_search"
    "|edit_file|read_file|create_document"
    "|send_email|post_to_twitter|post_to_linkedin|post_to_medium|trigger_n8n"
    "|memory|rebuild_skill|search_twitter|search_linkedin"
    "|bash|sh|python"
)
TOOL_CALL_RE = re.compile(
    rf"```({_TOOL_FENCE_NAMES})\n([\s\S]*?)\n```", re.MULTILINE
)


def parse_tool_calls(text: str) -> list[dict]:
    """Extract all tool_call blocks from LLM response text.

    Supports two formats:
    1. JSON: ```tool_call\n{"tool": "...", "params": {...}}\n```
    2. Bare code with tool-name fence: ```execute_python\nprint('hello')\n```

    Returns a list of {"tool": ..., "params": ..., "raw": ...} dicts.
    """
    calls = []
    from app.tool_repair import repair_tool_call_arguments

    for match in TOOL_CALL_RE.finditer(text):
        fence_label = match.group(1).strip()
        raw = match.group(2).strip()
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
    return calls


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

    # Generic result — compressed
    text = json.dumps(result, ensure_ascii=False)
    return compress_generic(text, max_chars=1500)
