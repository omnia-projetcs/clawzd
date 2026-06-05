"""
Clawzd — Miscellaneous API router.

Extracted from gateway.py. Handles tool permissions, conversation branching,
agent modes, diff viewer, system health, preprompts, agents CRUD, providers,
LLM status, RAG profiles, code execution, and local shell.
"""
import asyncio
import logging
import os

from fastapi import APIRouter, Request, HTTPException

logger = logging.getLogger("clawzd.misc_api")
router = APIRouter()


# --- Tool Permissions (HITL approval) ---

@router.get("/tool-permissions")
async def get_tool_permissions():
    from app.core.tool_permissions import load_permissions
    return {"permissions": load_permissions()}


@router.post("/tool-permissions")
async def update_tool_permissions(request: Request):
    from app.core.tool_permissions import load_permissions, set_tool_permission
    body = await request.json()
    for tool_name, level in body.items():
        if level in ("always", "ask", "deny"):
            set_tool_permission(tool_name, level)
    return {"status": "ok", "permissions": load_permissions()}


@router.post("/tool-approval")
async def handle_tool_approval(request: Request):
    from app.core.tool_permissions import resolve_approval
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


@router.get("/tool-approvals")
async def get_pending_approvals(session_id: str = ""):
    from app.core.tool_permissions import list_pending_approvals
    return {"approvals": list_pending_approvals(session_id)}


# --- Conversation Branching ---

@router.post("/branch/fork")
async def fork_conversation(request: Request):
    from app.core.database import fork_at_message
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


@router.get("/branch/{session_id}")
async def get_branches(session_id: str):
    from app.core.database import list_branches
    return {"branches": list_branches(session_id)}


@router.get("/branch/{session_id}/{branch_id}")
async def get_branch_messages(session_id: str, branch_id: str):
    from app.core.database import get_messages
    messages = get_messages(session_id, branch_id=branch_id)
    return {"branch_id": branch_id, "messages": messages}


@router.delete("/branch/{session_id}/{branch_id}")
async def remove_branch(session_id: str, branch_id: str):
    from app.core.database import delete_branch
    if branch_id == "main":
        raise HTTPException(400, "Cannot delete the main branch")
    ok = delete_branch(session_id, branch_id)
    if not ok:
        raise HTTPException(400, "Could not delete branch")
    return {"status": "deleted", "branch_id": branch_id}


# --- Agent Modes ---

@router.get("/modes")
async def get_agent_modes():
    from app.core.agent_modes import list_modes
    return {"modes": list_modes()}


@router.get("/modes/{mode_key}")
async def get_mode_detail(mode_key: str):
    from app.core.agent_modes import get_mode
    mode = get_mode(mode_key)
    return {
        "key": mode_key, "label": mode.get("label", mode_key),
        "icon": mode.get("icon", "💬"),
        "allowed_tools": mode.get("allowed_tools"),
        "blocked_tools": mode.get("blocked_tools", []),
        "ui_hints": mode.get("ui_hints", {}),
    }


# --- Diff Viewer ---

@router.get("/diff")
async def get_diff_endpoint(project: str = ""):
    from app.core.diff_viewer import get_diff
    path = project or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "workspace")
    return get_diff(path, staged=False)


@router.post("/diff/stage")
async def stage_file_endpoint(request: Request):
    from app.core.diff_viewer import stage_file
    body = await request.json()
    project = body.get("project", "")
    file_path = body.get("file", "")
    if not file_path:
        raise HTTPException(400, "file is required")
    path = project or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "workspace")
    return stage_file(path, file_path)


@router.post("/diff/revert")
async def revert_file_endpoint(request: Request):
    from app.core.diff_viewer import revert_file
    body = await request.json()
    project = body.get("project", "")
    file_path = body.get("file", "")
    if not file_path:
        raise HTTPException(400, "file is required")
    path = project or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "workspace")
    return revert_file(path, file_path)


# --- System Health ---

@router.get("/system/health")
async def system_health():
    from app.core.metrics import MetricsCollector
    resources = MetricsCollector.get_system_resources()
    ollama_status = "unknown"
    try:
        import httpx
        from app.core.llm_provider import _resolve_ollama_host, _resolve_ollama_api_key
        host = _resolve_ollama_host()
        key = _resolve_ollama_api_key()
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        async with httpx.AsyncClient(timeout=3) as client:
            resp = await client.get(f"{host}/api/version", headers=headers)
            ollama_status = "running" if resp.status_code == 200 else "error"
    except Exception:
        ollama_status = "offline"
    return {**resources, "ollama_status": ollama_status}


# --- Preprompts ---

@router.get("/preprompts")
async def get_preprompts():
    from app.preprompts import list_preprompts
    return {"preprompts": list_preprompts()}


# --- Agents CRUD ---

@router.get("/agents")
async def get_agents():
    from config import AGENTS_DIR
    agents = []
    if os.path.exists(AGENTS_DIR):
        for f in sorted(os.listdir(AGENTS_DIR)):
            if f.endswith(".md"):
                name = f[:-3]
                path = os.path.join(AGENTS_DIR, f)
                try:
                    with open(path, "r", encoding="utf-8") as file:
                        content = file.read()
                    agents.append({"name": name, "content": content})
                except Exception as e:
                    logger.error("Failed to read agent %s: %s", name, e)
    return {"agents": agents}


@router.post("/agents/{name}")
async def save_agent(name: str, request: Request):
    from config import AGENTS_DIR
    clean_name = "".join(c for c in name if c.isalnum() or c in ("-", "_")).strip()
    if not clean_name:
        raise HTTPException(400, "Invalid agent name")
    data = await request.json()
    content = data.get("content", "").strip()
    if not content:
        raise HTTPException(400, "Content cannot be empty")
    os.makedirs(AGENTS_DIR, exist_ok=True)
    path = os.path.join(AGENTS_DIR, f"{clean_name}.md")
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info("Saved custom agent preprompt: %s", clean_name)
        return {"status": "ok", "name": clean_name}
    except Exception as e:
        logger.error("Failed to save custom agent %s: %s", clean_name, e)
        raise HTTPException(500, f"Failed to save agent: {e}")


@router.delete("/agents/{name}")
async def delete_agent(name: str):
    from config import AGENTS_DIR
    clean_name = "".join(c for c in name if c.isalnum() or c in ("-", "_")).strip()
    path = os.path.join(AGENTS_DIR, f"{clean_name}.md")
    if os.path.exists(path):
        try:
            os.remove(path)
            logger.info("Deleted custom agent preprompt: %s", clean_name)
            return {"status": "ok"}
        except Exception as e:
            logger.error("Failed to delete custom agent %s: %s", clean_name, e)
            raise HTTPException(500, f"Failed to delete agent: {e}")
    else:
        raise HTTPException(404, "Agent not found")


# --- Providers ---

@router.get("/providers")
async def get_providers():
    from app.gateway import _get_provider_models
    return {"providers": await _get_provider_models()}


# --- LLM Status ---

@router.get("/llm-status")
async def get_llm_status():
    try:
        from config import OLLAMA_MODEL, OLLAMA_VERIFY_SSL
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


# --- RAG Profiles ---

@router.get("/rag-profiles")
async def api_list_rag_profiles():
    from config import PROFILES_DIR
    os.makedirs(PROFILES_DIR, exist_ok=True)
    files = []
    for root, _, filenames in os.walk(PROFILES_DIR):
        for f in filenames:
            if f.endswith(".md"):
                rel_path = os.path.relpath(os.path.join(root, f), PROFILES_DIR)
                files.append(rel_path.replace("\\", "/"))
    if "user/USER.md" not in files and "USER.md" not in files:
        files.append("user/USER.md")
    if "user/MEMORY.md" not in files and "MEMORY.md" not in files:
        files.append("user/MEMORY.md")
    return {"profiles": sorted(list(set(files)))}


@router.get("/rag-profil/{filename:path}")
async def api_get_rag_profil(filename: str):
    from config import PROFILES_DIR
    if not filename.endswith(".md"):
        raise HTTPException(400, "Invalid filename")
    path = os.path.realpath(os.path.join(PROFILES_DIR, filename))
    base = os.path.realpath(PROFILES_DIR)
    if not path.startswith(base):
        raise HTTPException(403, "Path traversal not allowed")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        base_name = os.path.basename(filename)
        defaults = {
            "USER.md": "# User Profile\n\n## Preferences\n- Language: \n- Communication style: \n\n## Expertise\n- \n\n## Goals\n- \n",
            "MEMORY.md": "# Agent Memory\n\n## Environment\n- \n\n## Project Notes\n- \n\n## Lessons Learned\n- \n",
        }
        with open(path, "w", encoding="utf-8") as f:
            f.write(defaults.get(base_name, f"# {base_name}\n\n"))
    with open(path, "r", encoding="utf-8") as f:
        return {"content": f.read()}


@router.post("/rag-profil/{filename:path}")
async def api_save_rag_profil(filename: str, request: Request):
    from config import PROFILES_DIR
    if not filename.endswith(".md"):
        raise HTTPException(400, "Invalid filename")
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


# --- Code Execution ---

@router.post("/execute")
async def api_execute(request: Request):
    import json as _json
    from app.tools_code import executor
    data = await request.json()
    if isinstance(data, str):
        try:
            data = _json.loads(data)
        except (ValueError, TypeError):
            data = {"code": data}
    code = data.get("code", "")
    if not code.strip():
        raise HTTPException(400, "Code is required")
    return executor.execute(code)


# --- Local Shell (editor terminal) ---

@router.post("/local/run")
async def local_run(request: Request):
    """Execute a shell command in the workspace directory."""
    from config import WORKSPACE_DIR
    data = await request.json()
    command = data.get("command", "").strip()
    if not command:
        return {"stdout": "", "stderr": "No command provided", "returncode": 1}
    cwd = WORKSPACE_DIR
    project = data.get("project", "")
    if project and project != ".":
        project_dir = os.path.join(WORKSPACE_DIR, project)
        if os.path.isdir(project_dir):
            cwd = project_dir
    _blocked_patterns = ("rm -rf /", "mkfs.", "dd if=", "> /dev/sd", ":(){ :", "fork()")
    if any(p in command for p in _blocked_patterns):
        return {"stdout": "", "stderr": "Command blocked by security policy", "returncode": 1}
    try:
        proc = await asyncio.create_subprocess_shell(
            command, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, cwd=cwd,
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
