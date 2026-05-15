"""
Clawzd — Automation workflow engine (n8n-style).
Visual workflow builder with node-based execution pipeline.
Triggers run independently in the background (Discord, Telegram, Cron, Webhook).
Skills and automation nodes are interoperable.
"""
import os, json, uuid, logging, asyncio, subprocess, shutil, re
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Request, HTTPException
from config import DATA_DIR

router = APIRouter()
logger = logging.getLogger("clawzd.automation")

WORKFLOWS_DIR = os.path.join(DATA_DIR, "workflows")
EXECUTIONS_DIR = os.path.join(DATA_DIR, "workflow_executions")
TEMPLATES_DIR_AUTO = os.path.join(DATA_DIR, "email_templates")
os.makedirs(WORKFLOWS_DIR, exist_ok=True)
os.makedirs(EXECUTIONS_DIR, exist_ok=True)
os.makedirs(TEMPLATES_DIR_AUTO, exist_ok=True)

# ── Node type definitions ──
NODE_TYPES = {
    "trigger_manual": {"label": "Manual Trigger", "category": "trigger", "color": "#3b82f6",
        "icon": "bolt", "inputs": [], "outputs": ["main"],
        "params": []},
    "trigger_cron": {"label": "Cron Schedule", "category": "trigger", "color": "#3b82f6",
        "icon": "clock", "inputs": [], "outputs": ["main"],
        "params": [{"key": "cron_expr", "label": "Cron Expression", "type": "text", "default": "0 9 * * *"},
                   {"key": "timezone", "label": "Timezone", "type": "text", "default": "UTC"}]},
    "trigger_webhook": {"label": "Webhook", "category": "trigger", "color": "#3b82f6",
        "icon": "link", "inputs": [], "outputs": ["main"],
        "params": [{"key": "method", "label": "Method", "type": "select", "options": ["GET","POST","PUT"], "default": "POST"}]},
    "trigger_discord": {"label": "Discord Message Received", "category": "trigger", "color": "#5865F2",
        "icon": "discord", "inputs": [], "outputs": ["main"],
        "params": [{"key": "channel_id", "label": "Channel ID (optional)", "type": "text", "default": ""},
                   {"key": "keyword", "label": "Keyword Filter (regex)", "type": "text", "default": ""}]},
    "trigger_telegram": {"label": "Telegram Message Received", "category": "trigger", "color": "#0088cc",
        "icon": "telegram", "inputs": [], "outputs": ["main"],
        "params": [{"key": "chat_id", "label": "Chat ID (optional)", "type": "text", "default": ""},
                   {"key": "keyword", "label": "Keyword Filter (regex)", "type": "text", "default": ""}]},
    "email_send": {"label": "Send Email", "category": "communication", "color": "#8b5cf6",
        "icon": "send", "inputs": ["main"], "outputs": ["main"],
        "params": [{"key": "to", "label": "To", "type": "text", "default": ""},
                   {"key": "subject", "label": "Subject", "type": "text", "default": ""},
                   {"key": "body", "label": "Body (HTML)", "type": "textarea", "default": ""},
                   {"key": "template", "label": "Template Name", "type": "text", "default": ""}]},
    "discord_send": {"label": "Discord Message", "category": "communication", "color": "#5865F2",
        "icon": "discord", "inputs": ["main"], "outputs": ["main"],
        "params": [{"key": "channel_id", "label": "Channel ID", "type": "text", "default": ""},
                   {"key": "message", "label": "Message", "type": "textarea", "default": ""}]},
    "signal_send": {"label": "Signal Message", "category": "communication", "color": "#3A76F0",
        "icon": "signal", "inputs": ["main"], "outputs": ["main"],
        "params": [{"key": "recipient", "label": "Recipient (+phone)", "type": "text", "default": ""},
                   {"key": "message", "label": "Message", "type": "textarea", "default": ""}]},
    "telegram_send": {"label": "Telegram Message", "category": "communication", "color": "#0088cc",
        "icon": "telegram", "inputs": ["main"], "outputs": ["main"],
        "params": [{"key": "chat_id", "label": "Chat ID", "type": "text", "default": ""},
                   {"key": "message", "label": "Message", "type": "textarea", "default": ""}]},
    "whatsapp_send": {"label": "WhatsApp Message", "category": "communication", "color": "#25D366",
        "icon": "whatsapp", "inputs": ["main"], "outputs": ["main"],
        "params": [{"key": "recipient", "label": "Recipient (+phone)", "type": "text", "default": ""},
                   {"key": "message", "label": "Message", "type": "textarea", "default": ""}]},
    "db_query": {"label": "Database Query", "category": "data", "color": "#06b6d4",
        "icon": "layers", "inputs": ["main"], "outputs": ["main"],
        "params": [{"key": "db_type", "label": "DB Type", "type": "select", "options": ["sqlite","postgresql","mysql"], "default": "sqlite"},
                   {"key": "connection", "label": "Connection String", "type": "text", "default": ""},
                   {"key": "query", "label": "SQL Query", "type": "textarea", "default": "SELECT 1"}]},
    "data_list": {"label": "Data List", "category": "data", "color": "#06b6d4",
        "icon": "clipboard", "inputs": ["main"], "outputs": ["main"],
        "params": [{"key": "items", "label": "Items (one per line)", "type": "textarea", "default": ""},
                   {"key": "destination", "label": "Send To", "type": "select", "options": ["none","email","discord","telegram","signal","whatsapp"], "default": "none"},
                   {"key": "dest_target", "label": "Destination (email/ID/phone)", "type": "text", "default": ""},
                   {"key": "dest_template", "label": "Message Template (use {{item}})", "type": "textarea", "default": "{{item}}"}]},
    "web_search": {"label": "Web Search", "category": "data", "color": "#06b6d4",
        "icon": "search", "inputs": ["main"], "outputs": ["main"],
        "params": [{"key": "query", "label": "Search Query", "type": "text", "default": ""},
                   {"key": "max_results", "label": "Max Results", "type": "number", "default": 5}]},
    "http_request": {"label": "HTTP Request", "category": "data", "color": "#06b6d4",
        "icon": "link", "inputs": ["main"], "outputs": ["main"],
        "params": [{"key": "url", "label": "URL", "type": "text", "default": ""},
                   {"key": "method", "label": "Method", "type": "select", "options": ["GET","POST","PUT","DELETE"], "default": "GET"},
                   {"key": "headers", "label": "Headers (JSON)", "type": "textarea", "default": "{}"},
                   {"key": "body", "label": "Body (JSON)", "type": "textarea", "default": ""}]},
    "ai_prompt": {"label": "AI Prompt", "category": "ai", "color": "#f59e0b",
        "icon": "cpu", "inputs": ["main"], "outputs": ["main"],
        "params": [{"key": "prompt", "label": "Prompt", "type": "textarea", "default": ""},
                   {"key": "provider", "label": "Provider", "type": "select", "options": ["google","grok","groq","huggingface","mistral","ollama","openai","openrouter"], "default": "ollama"},
                   {"key": "model", "label": "Model", "type": "text", "default": ""}]},
    "condition": {"label": "Condition (If/Else)", "category": "flow", "color": "#10b981",
        "icon": "gitBranch", "inputs": ["main"], "outputs": ["true", "false"],
        "params": [{"key": "operator", "label": "Operator", "type": "select", "options": ["EXPR","AND","OR"], "default": "EXPR"},
                   {"key": "expression", "label": "Expression / Condition 1", "type": "text", "default": "data.status == 'ok'"},
                   {"key": "expression2", "label": "Condition 2 (for AND/OR)", "type": "text", "default": ""},
                   {"key": "expression3", "label": "Condition 3 (optional)", "type": "text", "default": ""}]},
    "transform": {"label": "Transform Data", "category": "transform", "color": "#ec4899",
        "icon": "settings", "inputs": ["main"], "outputs": ["main"],
        "params": [{"key": "code", "label": "Python Code", "type": "textarea", "default": "# 'data' is the input\nresult = data"}]},
    "delay": {"label": "Delay", "category": "flow", "color": "#10b981",
        "icon": "clock", "inputs": ["main"], "outputs": ["main"],
        "params": [{"key": "seconds", "label": "Seconds", "type": "number", "default": 5}]},
    "export_file": {"label": "Export to File", "category": "export", "color": "#ef4444",
        "icon": "download", "inputs": ["main"], "outputs": ["main"],
        "params": [{"key": "path", "label": "File Path", "type": "text", "default": "output.json"},
                   {"key": "format", "label": "Format", "type": "select", "options": ["json","csv","txt"], "default": "json"}]},
    "export_email": {"label": "Export by Email", "category": "export", "color": "#ef4444",
        "icon": "send", "inputs": ["main"], "outputs": ["main"],
        "params": [{"key": "to", "label": "To", "type": "text", "default": ""},
                   {"key": "subject", "label": "Subject", "type": "text", "default": "Data Export"},
                   {"key": "format", "label": "Attachment Format", "type": "select", "options": ["json","csv","txt"], "default": "json"}]},
    "merge": {"label": "Merge", "category": "flow", "color": "#10b981",
        "icon": "gitMerge", "inputs": ["input1", "input2"], "outputs": ["main"],
        "params": []},
    "run_skill": {"label": "Run Skill", "category": "integration", "color": "#a855f7",
        "icon": "bolt", "inputs": ["main"], "outputs": ["main"],
        "params": [{"key": "skill_name", "label": "Skill Name", "type": "text", "default": ""},
                   {"key": "params_json", "label": "Params (JSON)", "type": "textarea", "default": "{}"}]},
    "code_audit": {"label": "Code Audit", "category": "code", "color": "#1d4ed8",
        "icon": "search", "inputs": ["main"], "outputs": ["main"],
        "params": [{"key": "source", "label": "Source (Path/URL)", "type": "text", "default": ""},
                   {"key": "provider", "label": "AI Provider", "type": "select", "options": ["google","grok","groq","huggingface","mistral","ollama","openai","openrouter"], "default": "ollama"},
                   {"key": "model", "label": "Model", "type": "text", "default": ""},
                   {"key": "prompt", "label": "Audit Prompt", "type": "textarea", "default": "Audit this code and provide a detailed report on bugs, vulnerabilities, and improvements."}]},
    "code_fix": {"label": "Code Fix", "category": "code", "color": "#1d4ed8",
        "icon": "penTool", "inputs": ["main"], "outputs": ["main"],
        "params": [{"key": "source", "label": "Source Path (Local)", "type": "text", "default": ""},
                   {"key": "provider", "label": "AI Provider", "type": "select", "options": ["google","grok","groq","huggingface","mistral","ollama","openai","openrouter"], "default": "ollama"},
                   {"key": "model", "label": "Model", "type": "text", "default": ""},
                   {"key": "apply_fix", "label": "Apply Fix to File?", "type": "select", "options": ["No", "Yes"], "default": "No"}]},
    "code_report": {"label": "Code Report", "category": "code", "color": "#1d4ed8",
        "icon": "clipboard", "inputs": ["main"], "outputs": ["main"],
        "params": [{"key": "format", "label": "Format", "type": "select", "options": ["markdown", "html"], "default": "markdown"},
                   {"key": "output_path", "label": "Output Path (optional)", "type": "text", "default": ""}]},
    "medium_publish": {"label": "Publish to Medium", "category": "publish", "color": "#00ab6c",
        "icon": "medium", "inputs": ["main"], "outputs": ["main"],
        "params": [{"key": "title", "label": "Title", "type": "text", "default": ""},
                   {"key": "content", "label": "Content (Markdown/HTML)", "type": "textarea", "default": ""},
                   {"key": "content_format", "label": "Format", "type": "select", "options": ["markdown", "html"], "default": "markdown"},
                   {"key": "tags", "label": "Tags (comma-sep)", "type": "text", "default": ""},
                   {"key": "publish_status", "label": "Status", "type": "select", "options": ["draft", "public", "unlisted"], "default": "draft"}]},
    "twitter_publish": {"label": "Publish to X (Twitter)", "category": "publish", "color": "#000000",
        "icon": "xTwitter", "inputs": ["main"], "outputs": ["main"],
        "params": [{"key": "text", "label": "Tweet Text (280 chars)", "type": "textarea", "default": ""},
                   {"key": "reply_to", "label": "Reply To (Tweet ID, optional)", "type": "text", "default": ""}]},
    "linkedin_publish": {"label": "Publish to LinkedIn", "category": "publish", "color": "#0A66C2",
        "icon": "linkedin", "inputs": ["main"], "outputs": ["main"],
        "params": [{"key": "text", "label": "Post Text", "type": "textarea", "default": ""},
                   {"key": "visibility", "label": "Visibility", "type": "select", "options": ["PUBLIC", "CONNECTIONS"], "default": "PUBLIC"}]},
    "rag_search": {"label": "RAG Search", "category": "data", "color": "#06b6d4",
        "icon": "layers", "inputs": ["main"], "outputs": ["main"],
        "params": [{"key": "query", "label": "Search Query", "type": "text", "default": ""},
                   {"key": "k", "label": "Max Results", "type": "number", "default": 5},
                   {"key": "threshold", "label": "Min Relevance (0-1, lower=stricter)", "type": "text", "default": "0.5"}]},
    "rag_ingest": {"label": "RAG Ingest", "category": "data", "color": "#8b5cf6",
        "icon": "layers", "inputs": ["main"], "outputs": ["main"],
        "params": [{"key": "source_path", "label": "File / Folder Path", "type": "text", "default": ""}]},
    "rag_clear": {"label": "RAG Clear Source", "category": "data", "color": "#ef4444",
        "icon": "trash", "inputs": ["main"], "outputs": ["main"],
        "params": [{"key": "source_name", "label": "Source Name", "type": "text", "default": ""}]},
}


# ── Workflow CRUD ──

def _wf_path(wf_id: str) -> str:
    return os.path.join(WORKFLOWS_DIR, f"{wf_id}.json")

def _load_wf(wf_id: str) -> Optional[dict]:
    p = _wf_path(wf_id)
    if os.path.exists(p):
        with open(p) as f:
            return json.load(f)
    return None

def _save_wf(wf: dict):
    wf["updated_at"] = datetime.now(timezone.utc).isoformat()
    with open(_wf_path(wf["id"]), "w") as f:
        json.dump(wf, f, indent=2, ensure_ascii=False)

def _list_wfs() -> list:
    wfs = []
    for fname in os.listdir(WORKFLOWS_DIR):
        if fname.endswith(".json"):
            try:
                with open(os.path.join(WORKFLOWS_DIR, fname)) as f:
                    wfs.append(json.load(f))
            except Exception:
                pass
    return sorted(wfs, key=lambda w: w.get("updated_at", ""), reverse=True)


@router.get("/node-types")
async def get_node_types():
    """Return all node types, including dynamic skills as run_skill presets."""
    types = dict(NODE_TYPES)
    # Inject registered skills as available skill names for the run_skill node
    try:
        from app.skill_registry import get_registry
        registry = get_registry()
        skill_names = registry.get_names()
        if skill_names:
            types["run_skill"]["params"][0]["type"] = "select"
            types["run_skill"]["params"][0]["options"] = skill_names
    except Exception:
        pass
    
    # Return models by provider for dynamic frontend logic
    models_by_provider = {}
    try:
        from app.llm_provider import _get_provider_models
        models_dict = await _get_provider_models()
        for prov, mlist in models_dict.items():
            models_by_provider[prov] = [m["id"] for m in mlist]
    except Exception as e:
        logger.error(f"Failed to fetch models for automation node: {e}")

    return {"types": types, "models_by_provider": models_by_provider}

@router.get("/workflows")
async def list_workflows():
    return {"workflows": _list_wfs()}

@router.post("/workflows")
async def create_workflow(request: Request):
    data = await request.json()
    wf = {
        "id": str(uuid.uuid4())[:8],
        "name": data.get("name", "New Workflow"),
        "description": data.get("description", ""),
        "nodes": data.get("nodes", []),
        "connections": data.get("connections", []),
        "active": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    _save_wf(wf)
    return {"status": "created", "workflow": wf}

@router.get("/workflows/{wf_id}")
async def get_workflow(wf_id: str):
    wf = _load_wf(wf_id)
    if not wf:
        raise HTTPException(404, "Workflow not found")
    return {"workflow": wf}

@router.put("/workflows/{wf_id}")
async def update_workflow(wf_id: str, request: Request):
    wf = _load_wf(wf_id)
    if not wf:
        raise HTTPException(404, "Workflow not found")
    data = await request.json()
    for k in ("name", "description", "nodes", "connections", "active"):
        if k in data:
            wf[k] = data[k]
    _save_wf(wf)
    return {"status": "updated", "workflow": wf}

@router.delete("/workflows/{wf_id}")
async def delete_workflow(wf_id: str):
    p = _wf_path(wf_id)
    if os.path.exists(p):
        os.remove(p)
    return {"status": "deleted"}

@router.post("/workflows/{wf_id}/toggle")
async def toggle_workflow(wf_id: str):
    wf = _load_wf(wf_id)
    if not wf:
        raise HTTPException(404, "Workflow not found")
    wf["active"] = not wf["active"]
    _save_wf(wf)
    # Schedule/unschedule cron triggers
    _sync_cron(wf)
    return {"status": "toggled", "active": wf["active"]}

# ── Global Variables ──
GLOBALS_FILE = os.path.join(DATA_DIR, "automation_globals.json")

def _get_globals() -> dict:
    if os.path.exists(GLOBALS_FILE):
        try:
            with open(GLOBALS_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}

@router.get("/globals")
async def get_globals():
    return {"globals": _get_globals()}

@router.post("/globals")
async def save_globals(request: Request):
    data = await request.json()
    new_globals = data.get("globals", {})
    with open(GLOBALS_FILE, "w") as f:
        json.dump(new_globals, f, indent=2)
    return {"status": "saved", "globals": new_globals}

@router.post("/workflows/ai-generate")
async def ai_generate_workflow(request: Request):
    data = await request.json()
    prompt = data.get("prompt", "")
    current_wf = data.get("current_workflow")

    from app.llm_provider import get_llm_provider
    provider = get_llm_provider()

    system_prompt = f"""You are an AI that generates or updates automation workflows.
A workflow consists of 'nodes' and 'connections'.
Available node types and their properties:
{json.dumps(NODE_TYPES, indent=2)}

You receive the user's prompt and the current workflow (if any).
Return ONLY a valid JSON object matching this schema:
{{
  "name": "Generated Workflow Name",
  "nodes": [
    {{"id": "n1", "type": "trigger_manual", "label": "Start", "x": 100, "y": 100, "params": {{}} }}
  ],
  "connections": [
    {{"source": "n1", "sourceOutput": "main", "target": "n2", "targetInput": "main"}}
  ]
}}

Ensure valid node types, matching inputs/outputs, and sensible (x, y) coordinates to form a clean graph visually (x increases to the right, y increases downwards, spacing around 250px).
Return ONLY JSON, with no markdown code blocks, just raw JSON.
"""
    
    user_msg = f"User Prompt: {prompt}\n"
    if current_wf:
        user_msg += f"Current Workflow State:\n{json.dumps(current_wf, indent=2)}\nPlease update this workflow."

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_msg}
    ]

    try:
        response_text = ""
        async for chunk in provider.chat_stream(messages):
            response_text += chunk
        
        # Extract JSON
        start = response_text.find('{')
        end = response_text.rfind('}')
        if start != -1 and end != -1:
            json_str = response_text[start:end+1]
            return json.loads(json_str)
        else:
            raise ValueError("No JSON object found in response")
    except Exception as e:
        logger.error(f"AI Generation failed: {e}")
        raise HTTPException(500, f"AI generation failed: {e}")

# ── Node Execution Engine ──

def _resolve_template(text: str, ctx: dict) -> str:
    """Replace {{var}} placeholders with context values."""
    import re
    def repl(m):
        key = m.group(1).strip()
        parts = key.split(".")
        val = ctx
        for p in parts:
            if isinstance(val, dict):
                val = val.get(p, "")
            else:
                return m.group(0)
        return str(val) if val is not None else ""
    return re.sub(r"\{\{(.+?)\}\}", repl, text)


COMMUNICATION_NODES = {"email_send", "discord_send", "signal_send", "telegram_send", "whatsapp_send", "export_email", "linkedin_publish"}

async def _exec_node(node: dict, input_data: dict, wf: dict, testing_mode: bool = False) -> dict:
    """Execute a single node and return its output data.
    When testing_mode is True, communication nodes are simulated (no real send).
    """
    ntype = node.get("type", "")
    params = node.get("params", {})
    # Fetch global variables
    global_vars = _get_globals()
    # Resolve templates in all string params
    resolved = {}
    for k, v in params.items():
        if isinstance(v, str):
            resolved[k] = _resolve_template(v, {"data": input_data, "env": dict(os.environ), "global": global_vars})
        else:
            resolved[k] = v

    # ── Testing mode: simulate communication nodes ──
    if testing_mode and ntype in COMMUNICATION_NODES:
        logger.info("[TEST MODE] Simulating node %s (%s) — no real send", node.get("id"), ntype)
        return {**input_data, "_simulated": True, "_node_type": ntype, "_resolved_params": resolved,
                "_test_message": f"Would send via {ntype} with params: {json.dumps(resolved, default=str)[:500]}"}

    try:
        if ntype == "trigger_manual":
            return {"triggered": True, "timestamp": datetime.now(timezone.utc).isoformat()}

        elif ntype == "trigger_cron":
            return {"triggered": True, "cron": resolved.get("cron_expr", "")}

        elif ntype == "trigger_webhook":
            return input_data or {"triggered": True}

        elif ntype == "email_send":
            from app.integrations_social import send_email
            body = resolved.get("body", "")
            tpl = resolved.get("template", "")
            if tpl:
                tpl_path = os.path.join(TEMPLATES_DIR_AUTO, tpl)
                if os.path.exists(tpl_path):
                    with open(tpl_path) as f:
                        body = _resolve_template(f.read(), {"data": input_data})
            result = await send_email(resolved.get("subject", ""), body, resolved.get("to", ""))
            return {**input_data, "email_result": result}

        elif ntype == "discord_send":
            import httpx
            token = os.environ.get("DISCORD_BOT_TOKEN", "")
            ch = resolved.get("channel_id", "")
            msg = resolved.get("message", str(input_data))
            if token and ch:
                async with httpx.AsyncClient(timeout=10) as c:
                    await c.post(f"https://discord.com/api/v10/channels/{ch}/messages",
                        headers={"Authorization": f"Bot {token}", "Content-Type": "application/json"},
                        json={"content": msg[:2000]})
                return {**input_data, "discord_sent": True}
            return {**input_data, "discord_sent": False, "error": "Missing token or channel"}

        elif ntype == "signal_send":
            signal_cli = os.environ.get("SIGNAL_CLI_PATH", "signal-cli")
            sender = os.environ.get("SIGNAL_PHONE", "")
            recipient = resolved.get("recipient", "")
            msg = resolved.get("message", str(input_data))
            if sender and recipient:
                proc = await asyncio.create_subprocess_exec(
                    signal_cli, "-u", sender, "send", "-m", msg, recipient,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                stdout, stderr = await proc.communicate()
                return {**input_data, "signal_sent": proc.returncode == 0,
                        "signal_output": stdout.decode()[:500]}
            return {**input_data, "signal_sent": False, "error": "Missing SIGNAL_PHONE or recipient"}

        elif ntype == "telegram_send":
            import httpx
            token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
            chat_id = resolved.get("chat_id", "")
            msg = resolved.get("message", str(input_data))
            if token and chat_id:
                async with httpx.AsyncClient(timeout=10) as c:
                    await c.post(f"https://api.telegram.org/bot{token}/sendMessage",
                        json={"chat_id": chat_id, "text": msg[:4096], "parse_mode": "Markdown"})
                return {**input_data, "telegram_sent": True}
            return {**input_data, "telegram_sent": False, "error": "Missing token or chat_id"}

        elif ntype == "whatsapp_send":
            import httpx
            phone_id = os.environ.get("WHATSAPP_PHONE_ID", "")
            wa_token = os.environ.get("WHATSAPP_TOKEN", "")
            recipient = resolved.get("recipient", "")
            msg = resolved.get("message", str(input_data))
            if phone_id and wa_token and recipient:
                async with httpx.AsyncClient(timeout=15) as c:
                    await c.post(
                        f"https://graph.facebook.com/v18.0/{phone_id}/messages",
                        headers={"Authorization": f"Bearer {wa_token}", "Content-Type": "application/json"},
                        json={"messaging_product": "whatsapp", "to": recipient,
                              "type": "text", "text": {"body": msg[:4096]}})
                return {**input_data, "whatsapp_sent": True}
            return {**input_data, "whatsapp_sent": False, "error": "Missing WHATSAPP_PHONE_ID, WHATSAPP_TOKEN or recipient"}

        elif ntype == "db_query":
            db_type = resolved.get("db_type", "sqlite")
            conn_str = resolved.get("connection", "")
            query = resolved.get("query", "")
            rows = await asyncio.to_thread(_exec_db_query, db_type, conn_str, query)
            return {"rows": rows, "count": len(rows)}

        elif ntype == "data_list":
            raw_items = resolved.get("items", "")
            items = [item.strip() for item in raw_items.split("\n") if item.strip()]
            csv_str = ", ".join(items)
            destination = resolved.get("destination", "none")
            dest_target = resolved.get("dest_target", "")
            dest_template = resolved.get("dest_template", "{{item}}")
            send_results = []
            if destination != "none" and dest_target:
                for item in items:
                    msg = dest_template.replace("{{item}}", item)
                    try:
                        fake_node = {"id": node.get("id") + "_send", "type": "", "params": {}}
                        if destination == "email":
                            fake_node["type"] = "email_send"
                            fake_node["params"] = {"to": dest_target, "subject": msg[:80], "body": msg, "template": ""}
                        elif destination == "discord":
                            fake_node["type"] = "discord_send"
                            fake_node["params"] = {"channel_id": dest_target, "message": msg}
                        elif destination == "telegram":
                            fake_node["type"] = "telegram_send"
                            fake_node["params"] = {"chat_id": dest_target, "message": msg}
                        elif destination == "signal":
                            fake_node["type"] = "signal_send"
                            fake_node["params"] = {"recipient": dest_target, "message": msg}
                        elif destination == "whatsapp":
                            fake_node["type"] = "whatsapp_send"
                            fake_node["params"] = {"recipient": dest_target, "message": msg}
                        res = await _exec_node(fake_node, input_data, wf, testing_mode=testing_mode)
                        send_results.append({"item": item, "status": "sent", "result": res})
                    except Exception as e:
                        send_results.append({"item": item, "status": "error", "error": str(e)})
            return {**input_data, "list": items, "list_csv": csv_str, "destination": destination, "send_results": send_results}

        elif ntype == "web_search":
            query = resolved.get("query", "")
            max_results = int(resolved.get("max_results", 5))
            try:
                import asyncio
                from app.tools_web import _do_search
                results = await asyncio.to_thread(_do_search, query, max_results)
                combined_text = "\n\n".join([f"Title: {r.get('title', '')}\nURL: {r.get('url', '')}\nSnippet: {r.get('snippet', '')}" for r in results])
                return {**input_data, "search_results": results, "search_text": combined_text}
            except Exception as e:
                return {**input_data, "search_error": str(e), "search_text": ""}

        elif ntype == "http_request":
            import httpx
            url = resolved.get("url", "")
            method = resolved.get("method", "GET").upper()
            hdrs = json.loads(resolved.get("headers", "{}") or "{}")
            body = resolved.get("body", "")
            async with httpx.AsyncClient(timeout=30) as c:
                if method == "GET":
                    r = await c.get(url, headers=hdrs)
                elif method == "POST":
                    r = await c.post(url, headers=hdrs, content=body)
                elif method == "PUT":
                    r = await c.put(url, headers=hdrs, content=body)
                elif method == "DELETE":
                    r = await c.delete(url, headers=hdrs)
                else:
                    r = await c.get(url, headers=hdrs)
                try:
                    resp_data = r.json()
                except Exception:
                    resp_data = r.text
            return {"status_code": r.status_code, "response": resp_data}

        elif ntype == "ai_prompt":
            from app.llm_provider import get_llm_provider
            prompt = resolved.get("prompt", "")
            provider_key = resolved.get("provider", "local")
            model = resolved.get("model", "")
            provider = get_llm_provider(provider_key)
            messages = [{"role": "user", "content": prompt}]
            kwargs = {"model": model} if model else {}
            full = ""
            async for tok in provider.chat_stream(messages, **kwargs):
                full += tok
            return {**input_data, "ai_response": full}

        elif ntype == "condition":
            operator = resolved.get("operator", "EXPR")
            exprs = [resolved.get("expression", "True")]
            if resolved.get("expression2"):
                exprs.append(resolved["expression2"])
            if resolved.get("expression3"):
                exprs.append(resolved["expression3"])
            safe_globals = {"__builtins__": {}, "len": len, "str": str, "int": int, "float": float, "bool": bool}
            safe_locals = {"data": input_data}
            results = []
            for expr in exprs:
                try:
                    results.append(bool(eval(expr, safe_globals, safe_locals)))
                except Exception:
                    results.append(False)
            if operator == "AND":
                final = all(results)
            elif operator == "OR":
                final = any(results)
            else:  # EXPR — single expression
                final = results[0] if results else False
            return {"_condition_result": final, "_condition_operator": operator, "_condition_details": results, **input_data}

        elif ntype == "transform":
            code = resolved.get("code", "result = data")
            local_ns = {"data": input_data, "result": None, "json": json}
            exec(code, {"__builtins__": {"len": len, "str": str, "int": int, "float": float,
                                          "list": list, "dict": dict, "range": range, "enumerate": enumerate,
                                          "zip": zip, "map": map, "filter": filter, "sorted": sorted,
                                          "min": min, "max": max, "sum": sum, "round": round,
                                          "json": json, "print": print}}, local_ns)
            return local_ns.get("result", input_data)

        elif ntype == "delay":
            secs = int(resolved.get("seconds", 5))
            await asyncio.sleep(min(secs, 300))
            return input_data

        elif ntype == "export_file":
            path = resolved.get("path", "output.json")
            fmt = resolved.get("format", "json")
            export_dir = os.path.join(DATA_DIR, "exports")
            os.makedirs(export_dir, exist_ok=True)
            full_path = os.path.join(export_dir, os.path.basename(path))
            content = _format_data(input_data, fmt)
            with open(full_path, "w") as f:
                f.write(content)
            return {**input_data, "exported_path": full_path}

        elif ntype == "export_email":
            from app.integrations_social import send_email
            fmt = resolved.get("format", "json")
            content = _format_data(input_data, fmt)
            subject = resolved.get("subject", "Data Export")
            to = resolved.get("to", "")
            result = await send_email(subject, content, to)
            return {**input_data, "export_email_result": result}

        elif ntype == "merge":
            return input_data

        elif ntype == "run_skill":
            from app.skill_registry import get_registry
            from app.skill_model import SkillContext
            skill_name = resolved.get("skill_name", "")
            try:
                skill_params = json.loads(resolved.get("params_json", "{}") or "{}")
            except Exception:
                skill_params = {}
            # Merge input data into skill params
            for k, v in input_data.items():
                if k not in skill_params and not k.startswith("_"):
                    skill_params[k] = v
            registry = get_registry()
            ctx = SkillContext(data_dir=DATA_DIR)
            result = await registry.execute(skill_name, skill_params, ctx)
            return {**input_data, "skill_result": result.to_dict()}

        elif ntype == "code_audit":
            from app.llm_provider import get_llm_provider
            import httpx
            source = resolved.get("source", "")
            provider_key = resolved.get("provider", "local")
            model = resolved.get("model", "")
            prompt_text = resolved.get("prompt", "Audit this code.")
            
            code_content = ""
            if source.startswith("http://") or source.startswith("https://"):
                try:
                    async with httpx.AsyncClient() as client:
                        resp = await client.get(source)
                        code_content = resp.text
                except Exception as e:
                    code_content = f"Error fetching URL: {e}"
            elif os.path.exists(source):
                try:
                    with open(source, "r", encoding="utf-8") as f:
                        code_content = f.read()
                except Exception as e:
                    code_content = f"Error reading file: {e}"
            else:
                code_content = f"Source not found: {source}"

            provider = get_llm_provider(provider_key)
            # Inject dev best practices as system context
            from app.preprompts import _load_dev_profile
            dev_profile = _load_dev_profile()
            messages = []
            if dev_profile:
                messages.append({"role": "system", "content": f"Follow these coding standards when auditing:\n{dev_profile}"})
            messages.append({"role": "user", "content": f"{prompt_text}\n\nCode:\n```\n{code_content}\n```"})
            kwargs = {"model": model} if model else {}
            report = ""
            async for tok in provider.chat_stream(messages, **kwargs):
                report += tok
                
            return {**input_data, "code_audit_report": report, "audited_source": source}

        elif ntype == "code_fix":
            from app.llm_provider import get_llm_provider
            source = resolved.get("source", "")
            provider_key = resolved.get("provider", "local")
            model = resolved.get("model", "")
            apply_fix = resolved.get("apply_fix", "No") == "Yes"
            
            # Use audit report from input data if available
            audit_report = input_data.get("code_audit_report", "No previous audit report found.")
            code_content = ""
            
            if os.path.exists(source):
                try:
                    with open(source, "r", encoding="utf-8") as f:
                        code_content = f.read()
                except Exception as e:
                    code_content = f"Error reading file: {e}"
            else:
                code_content = f"Source not found: {source}"

            prompt_text = "Here is the code and an audit report. Please provide the completely fixed code without markdown wrappers or other text, just the raw code.\n\n"
            prompt_text += f"Report:\n{audit_report}\n\nCode:\n```\n{code_content}\n```"

            provider = get_llm_provider(provider_key)
            # Inject dev best practices as system context
            from app.preprompts import _load_dev_profile
            dev_profile = _load_dev_profile()
            messages = []
            if dev_profile:
                messages.append({"role": "system", "content": f"Follow these coding standards when fixing code:\n{dev_profile}"})
            messages.append({"role": "user", "content": prompt_text})
            kwargs = {"model": model} if model else {}
            fixed_code = ""
            async for tok in provider.chat_stream(messages, **kwargs):
                fixed_code += tok
                
            fixed_code = fixed_code.strip()
            if fixed_code.startswith("```"):
                lines = fixed_code.split("\n")
                if len(lines) > 2:
                    fixed_code = "\n".join(lines[1:-1])

            res = {**input_data, "fixed_code": fixed_code, "fixed_source": source}
            if apply_fix and os.path.exists(source) and fixed_code:
                try:
                    with open(source, "w", encoding="utf-8") as f:
                        f.write(fixed_code)
                    res["fix_applied"] = True
                except Exception as e:
                    res["fix_applied"] = False
                    res["fix_error"] = str(e)
                    
            return res

        elif ntype == "code_report":
            fmt = resolved.get("format", "markdown")
            out_path = resolved.get("output_path", "")
            audit_report = input_data.get("code_audit_report", "No audit report.")
            
            if fmt == "html":
                import markdown
                try:
                    report_content = f"<html><body><h1>Code Audit Report</h1><div>{markdown.markdown(audit_report)}</div></body></html>"
                except Exception:
                    report_content = f"<html><body><h1>Code Audit Report</h1><pre>{audit_report}</pre></body></html>"
            else:
                report_content = f"# Code Audit Report\n\n{audit_report}"
                
            res = {**input_data, "formatted_report": report_content}
            if out_path:
                try:
                    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
                    with open(out_path, "w", encoding="utf-8") as f:
                        f.write(report_content)
                    res["report_saved_to"] = out_path
                except Exception as e:
                    res["report_save_error"] = str(e)
            return res

        elif ntype == "medium_publish":
            import httpx
            token = os.environ.get("MEDIUM_TOKEN", "")
            title = resolved.get("title", "")
            content = resolved.get("content", "")
            content_fmt = resolved.get("content_format", "markdown")
            tags = [t.strip() for t in resolved.get("tags", "").split(",") if t.strip()]
            pub_status = resolved.get("publish_status", "draft")
            if not token:
                return {**input_data, "medium_published": False, "error": "Missing MEDIUM_TOKEN env variable"}
            async with httpx.AsyncClient(timeout=20) as c:
                # Get user ID
                me = await c.get("https://api.medium.com/v1/me",
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
                user_id = me.json().get("data", {}).get("id", "")
                if not user_id:
                    return {**input_data, "medium_published": False, "error": "Failed to get Medium user ID"}
                # Publish
                resp = await c.post(f"https://api.medium.com/v1/users/{user_id}/posts",
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                    json={"title": title, "contentFormat": content_fmt, "content": content,
                          "tags": tags[:5], "publishStatus": pub_status})
                rdata = resp.json()
            return {**input_data, "medium_published": True, "medium_url": rdata.get("data", {}).get("url", ""),
                    "medium_id": rdata.get("data", {}).get("id", "")}

        elif ntype == "twitter_publish":
            import httpx, hashlib, hmac, base64, time as _time
            api_key = os.environ.get("TWITTER_API_KEY", "")
            api_secret = os.environ.get("TWITTER_API_SECRET", "")
            access_token = os.environ.get("TWITTER_ACCESS_TOKEN", "")
            access_secret = os.environ.get("TWITTER_ACCESS_SECRET", "")
            bearer = os.environ.get("TWITTER_BEARER_TOKEN", "")
            text = resolved.get("text", "")[:280]
            reply_to = resolved.get("reply_to", "")
            if not text:
                return {**input_data, "twitter_published": False, "error": "Tweet text is empty"}
            # Use OAuth 1.0a via httpx-auth or fallback to Bearer
            payload = {"text": text}
            if reply_to:
                payload["reply"] = {"in_reply_to_tweet_id": reply_to}
            headers = {}
            if bearer:
                headers = {"Authorization": f"Bearer {bearer}", "Content-Type": "application/json"}
            elif access_token and api_key:
                # Simple OAuth 1.0 header (requires requests-oauthlib or manual signing)
                try:
                    from requests_oauthlib import OAuth1Session
                    oauth = OAuth1Session(api_key, client_secret=api_secret,
                                          resource_owner_key=access_token, resource_owner_secret=access_secret)
                    resp = oauth.post("https://api.twitter.com/2/tweets", json=payload)
                    rdata = resp.json()
                    return {**input_data, "twitter_published": True,
                            "tweet_id": rdata.get("data", {}).get("id", ""), "tweet_text": text}
                except ImportError:
                    return {**input_data, "twitter_published": False,
                            "error": "requests-oauthlib not installed. Set TWITTER_BEARER_TOKEN instead."}
            else:
                return {**input_data, "twitter_published": False,
                        "error": "Missing Twitter credentials (TWITTER_BEARER_TOKEN or OAuth keys)"}
            async with httpx.AsyncClient(timeout=15) as c:
                resp = await c.post("https://api.twitter.com/2/tweets", headers=headers, json=payload)
                rdata = resp.json()
            return {**input_data, "twitter_published": True,
                    "tweet_id": rdata.get("data", {}).get("id", ""), "tweet_text": text}

        elif ntype == "linkedin_publish":
            import httpx
            access_token = os.environ.get("LINKEDIN_ACCESS_TOKEN", "")
            author_id = os.environ.get("LINKEDIN_AUTHOR_ID", "")
            text = resolved.get("text", "")
            visibility = resolved.get("visibility", "PUBLIC")
            if not text:
                return {**input_data, "linkedin_published": False, "error": "Post text is empty"}
            if not access_token or not author_id:
                return {**input_data, "linkedin_published": False,
                        "error": "Missing LINKEDIN_ACCESS_TOKEN or LINKEDIN_AUTHOR_ID env variables"}
            payload = {
                "author": author_id,
                "lifecycleState": "PUBLISHED",
                "specificContent": {
                    "com.linkedin.ugc.ShareContent": {
                        "shareCommentary": {"text": text},
                        "shareMediaCategory": "NONE"
                    }
                },
                "visibility": {
                    "com.linkedin.ugc.MemberNetworkVisibility": visibility
                }
            }
            async with httpx.AsyncClient(timeout=20) as c:
                resp = await c.post("https://api.linkedin.com/v2/ugcPosts",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "X-Restli-Protocol-Version": "2.0.0",
                        "Content-Type": "application/json"
                    },
                    json=payload)
                rdata = resp.json()
            return {**input_data, "linkedin_published": True,
                    "linkedin_post_id": rdata.get("id", ""), "linkedin_text": text}

        elif ntype in ("trigger_discord", "trigger_telegram"):
            # These are handled by the background listener, not direct execution
            return input_data or {"triggered": True, "source": ntype}

        elif ntype == "rag_search":
            from app.rag import search as rag_search_fn
            query = resolved.get("query", "")
            k = int(resolved.get("k", 5))
            threshold = float(resolved.get("threshold", "0.5"))
            if not query:
                # Use input data as query if no explicit query
                query = str(input_data.get("ai_response", input_data.get("search_text", str(input_data))))
            results = await rag_search_fn(query=query, k=k)
            docs = results.get("documents", [])
            metas = results.get("metadatas", [])
            # Format results
            rag_results = []
            for doc, meta in zip(docs, metas):
                rag_results.append({
                    "source": (meta or {}).get("source", "?"),
                    "file_type": (meta or {}).get("file_type", ""),
                    "content": doc[:500],
                })
            rag_text = "\n\n---\n\n".join(
                f"[{r['source']}] {r['content']}" for r in rag_results
            )
            return {**input_data, "rag_results": rag_results, "rag_text": rag_text, "rag_query": query}

        elif ntype == "rag_ingest":
            from app.ai_models.rag import _index_document, _extract_text, _chunk_text, _ALL_SUPPORTED
            source_path = resolved.get("source_path", "")
            if not source_path or not os.path.exists(source_path):
                return {**input_data, "rag_ingest_error": f"Path not found: {source_path}"}
            indexed = []
            if os.path.isfile(source_path):
                with open(source_path, "rb") as f:
                    content = f.read()
                result = _index_document(content, os.path.basename(source_path))
                indexed.append(result)
            elif os.path.isdir(source_path):
                for root, dirs, files in os.walk(source_path):
                    dirs[:] = [d for d in dirs if not d.startswith(".")]
                    for fname in files:
                        ext = ("." + fname.rsplit(".", 1)[-1].lower()) if "." in fname else ""
                        if ext not in _ALL_SUPPORTED:
                            continue
                        fpath = os.path.join(root, fname)
                        try:
                            with open(fpath, "rb") as f:
                                content = f.read()
                            result = _index_document(content, fname)
                            indexed.append(result)
                        except Exception as e:
                            indexed.append({"status": "error", "filename": fname, "error": str(e)})
            return {**input_data, "rag_ingested": indexed, "rag_ingest_count": len(indexed)}

        elif ntype == "rag_clear":
            source_name = resolved.get("source_name", "")
            if not source_name:
                return {**input_data, "rag_clear_error": "No source_name provided"}
            try:
                from app.ai_models.rag import _delete_source_chunks
                _delete_source_chunks(source_name)
                return {**input_data, "rag_cleared": source_name}
            except Exception as e:
                return {**input_data, "rag_clear_error": str(e)}

        else:
            return {**input_data, "error": f"Unknown node type: {ntype}"}

    except Exception as e:
        logger.error("Node %s execution error: %s", node.get("id"), e)
        return {**input_data, "_error": str(e), "_node_id": node.get("id")}


def _exec_db_query(db_type: str, conn_str: str, query: str) -> list:
    """Execute a DB query (runs in thread)."""
    if db_type == "sqlite":
        import sqlite3
        conn = sqlite3.connect(conn_str or os.path.join(DATA_DIR, "clawzd.db"))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(query).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    elif db_type == "postgresql":
        try:
            import psycopg2, psycopg2.extras
            conn = psycopg2.connect(conn_str)
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(query)
            rows = cur.fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except ImportError:
            return [{"error": "psycopg2 not installed"}]
    elif db_type == "mysql":
        try:
            import mysql.connector
            conn = mysql.connector.connect(**json.loads(conn_str))
            cur = conn.cursor(dictionary=True)
            cur.execute(query)
            rows = cur.fetchall()
            conn.close()
            return rows
        except ImportError:
            return [{"error": "mysql-connector-python not installed"}]
    return [{"error": f"Unsupported db_type: {db_type}"}]


def _format_data(data: dict, fmt: str) -> str:
    if fmt == "csv":
        if isinstance(data, dict) and "rows" in data:
            rows = data["rows"]
        elif isinstance(data, list):
            rows = data
        else:
            rows = [data]
        if not rows:
            return ""
        import csv, io
        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=rows[0].keys() if rows else [])
        writer.writeheader()
        writer.writerows(rows)
        return out.getvalue()
    elif fmt == "txt":
        return str(data)
    else:
        return json.dumps(data, indent=2, ensure_ascii=False, default=str)


# ── Workflow Execution ──

async def execute_workflow(wf: dict, initial_data: dict = None, testing_mode: bool = False) -> dict:
    """Execute all nodes in a workflow following connections.
    When testing_mode is True, communication nodes are simulated.
    """
    nodes = {n["id"]: n for n in wf.get("nodes", [])}
    connections = wf.get("connections", [])
    
    # Build adjacency: source_id.output -> [(target_id, target_input)]
    adj = {}
    for c in connections:
        key = (c["source"], c.get("sourceOutput", "main"))
        if key not in adj:
            adj[key] = []
        adj[key].append((c["target"], c.get("targetInput", "main")))

    # Find trigger nodes (no incoming connections)
    targets = {c["target"] for c in connections}
    triggers = [n for n in wf.get("nodes", []) if n["id"] not in targets]
    if not triggers:
        return {"error": "No trigger node found"}

    results = {}
    execution_log = []

    async def run_node(node_id: str, data: dict):
        node = nodes.get(node_id)
        if not node:
            return
        start = datetime.now(timezone.utc)
        try:
            output = await _exec_node(node, data, wf, testing_mode=testing_mode)
            status = "error" if output.get("_error") else "success"
        except Exception as e:
            output = {"_error": str(e)}
            status = "error"
        end = datetime.now(timezone.utc)
        simulated = output.get("_simulated", False)
        results[node_id] = output
        log_entry = {
            "node_id": node_id, "node_type": node.get("type"),
            "node_label": node.get("label", node.get("type")),
            "status": status, "duration_ms": (end - start).total_seconds() * 1000,
            "timestamp": start.isoformat(),
            "simulated": simulated,
        }
        if testing_mode:
            # In testing mode, provide full output for debugging
            log_entry["output_preview"] = str(output)[:2000]
        else:
            log_entry["output_preview"] = str(output)[:500]
        execution_log.append(log_entry)

        # Route to next nodes
        if node.get("type") == "condition":
            branch = "true" if output.get("_condition_result") else "false"
            next_nodes = adj.get((node_id, branch), [])
        else:
            next_nodes = adj.get((node_id, "main"), [])

        for next_id, _ in next_nodes:
            await run_node(next_id, output)

    # Execute from each trigger
    for trigger in triggers:
        await run_node(trigger["id"], initial_data or {})

    # Save execution record
    exec_id = str(uuid.uuid4())[:8]
    overall_status = "error" if any(l["status"] == "error" for l in execution_log) else "success"
    if testing_mode:
        overall_status = f"test_{overall_status}"
    exec_record = {
        "id": exec_id, "workflow_id": wf["id"], "workflow_name": wf.get("name", ""),
        "started_at": execution_log[0]["timestamp"] if execution_log else "",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "status": overall_status, "testing_mode": testing_mode,
        "log": execution_log,
        "results": {k: str(v)[:2000] if testing_mode else str(v)[:1000] for k, v in results.items()}
    }
    exec_path = os.path.join(EXECUTIONS_DIR, f"{wf['id']}_{exec_id}.json")
    with open(exec_path, "w") as f:
        json.dump(exec_record, f, indent=2, ensure_ascii=False, default=str)

    return exec_record


@router.post("/workflows/{wf_id}/execute")
async def execute_workflow_endpoint(wf_id: str, request: Request):
    wf = _load_wf(wf_id)
    if not wf:
        raise HTTPException(404, "Workflow not found")
    try:
        data = await request.json()
    except Exception:
        data = {}
    testing_mode = data.pop("testing_mode", False)
    result = await execute_workflow(wf, data, testing_mode=testing_mode)
    return result

@router.get("/workflows/{wf_id}/executions")
async def get_executions(wf_id: str):
    execs = []
    for fname in os.listdir(EXECUTIONS_DIR):
        if fname.startswith(wf_id) and fname.endswith(".json"):
            with open(os.path.join(EXECUTIONS_DIR, fname)) as f:
                execs.append(json.load(f))
    return {"executions": sorted(execs, key=lambda e: e.get("completed_at", ""), reverse=True)[:20]}


# ── Email Templates ──

@router.get("/email-templates")
async def list_email_templates():
    templates = []
    for f in os.listdir(TEMPLATES_DIR_AUTO):
        if f.endswith((".html", ".txt")):
            templates.append(f)
    return {"templates": templates}

@router.post("/email-templates")
async def save_email_template(request: Request):
    data = await request.json()
    name = data.get("name", "template.html")
    content = data.get("content", "")
    with open(os.path.join(TEMPLATES_DIR_AUTO, name), "w") as f:
        f.write(content)
    return {"status": "saved", "name": name}


# ── Cron sync ──

def _sync_cron(wf: dict):
    """Sync cron trigger nodes with APScheduler."""
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError:
        return

    for node in wf.get("nodes", []):
        if node.get("type") != "trigger_cron":
            continue
        job_id = f"auto_{wf['id']}_{node['id']}"
        try:
            from app.tools_cron import _get_scheduler
            scheduler = _get_scheduler()
            try:
                scheduler.remove_job(job_id)
            except Exception:
                pass
            if wf.get("active"):
                cron = node.get("params", {}).get("cron_expr", "0 9 * * *")
                parts = cron.split()
                if len(parts) >= 5:
                    trigger = CronTrigger(minute=parts[0], hour=parts[1],
                                          day=parts[2], month=parts[3], day_of_week=parts[4])
                    async def _run(w_id=wf["id"]):
                        w = _load_wf(w_id)
                        if w:
                            await execute_workflow(w)
                    scheduler.add_job(_run, trigger, id=job_id)
        except Exception as e:
            logger.warning("Failed to sync cron for %s: %s", wf["id"], e)


# ══════════════════════════════════════════════════════════════════════════
# BACKGROUND EVENT LISTENERS  (run independently of UI)
# ══════════════════════════════════════════════════════════════════════════

_listeners_started = False


def _get_active_event_triggers() -> dict:
    """Scan all active workflows for Discord/Telegram trigger nodes."""
    triggers = {"discord": [], "telegram": []}
    for wf in _list_wfs():
        if not wf.get("active"):
            continue
        for node in wf.get("nodes", []):
            ntype = node.get("type", "")
            if ntype == "trigger_discord":
                triggers["discord"].append({"wf": wf, "node": node})
            elif ntype == "trigger_telegram":
                triggers["telegram"].append({"wf": wf, "node": node})
    return triggers


async def dispatch_event(source: str, event_data: dict):
    """Called by Discord/Telegram listeners when a message arrives.
    Checks all active workflows for matching triggers and executes them.
    """
    triggers = _get_active_event_triggers()
    items = triggers.get(source, [])
    for item in items:
        node = item["node"]
        wf = item["wf"]
        params = node.get("params", {})
        # Filter by channel/chat ID
        filter_id = params.get("channel_id") or params.get("chat_id", "")
        if filter_id and str(event_data.get("channel_id", "")) != filter_id:
            continue
        # Filter by keyword
        keyword = params.get("keyword", "")
        if keyword:
            msg = event_data.get("message", "")
            if not re.search(keyword, msg, re.IGNORECASE):
                continue
        # Match! Execute the workflow with event data
        logger.info("Automation trigger matched: %s → workflow '%s'", source, wf.get("name"))
        try:
            # Reload workflow from disk to get latest version
            fresh_wf = _load_wf(wf["id"])
            if fresh_wf:
                await execute_workflow(fresh_wf, event_data)
        except Exception as e:
            logger.error("Failed to execute triggered workflow %s: %s", wf["id"], e)


async def start_automation_listeners():
    """Start background listeners for Discord and Telegram events.
    Called once at app startup. Hooks into existing integrations.
    """
    global _listeners_started
    if _listeners_started:
        return
    _listeners_started = True
    logger.info("Automation: background event listeners initialized")
    # The actual hooking happens via patches to Discord/Telegram integrations
    # See: _patch_discord_listener() and _patch_telegram_listener()
    _patch_discord_listener()
    _patch_telegram_listener()
    # Also start cron triggers for active workflows
    for wf in _list_wfs():
        if wf.get("active"):
            _sync_cron(wf)


def _patch_discord_listener():
    """Hook into the Discord bot to dispatch automation events."""
    try:
        from app.integrations_discord import _bot
        if _bot is None:
            return
        import discord

        original_on_message = None
        for name, callback in _bot._listeners.get("on_message", []):
            original_on_message = callback
            break

        @_bot.event
        async def on_message(message):
            if message.author.bot:
                return
            # Dispatch to automation workflows
            asyncio.create_task(dispatch_event("discord", {
                "message": message.content,
                "author": str(message.author),
                "author_id": str(message.author.id),
                "channel_id": str(message.channel.id),
                "guild_id": str(message.guild.id) if message.guild else "",
                "timestamp": message.created_at.isoformat(),
            }))
            # Also call original handler for chat responses
            if original_on_message:
                await original_on_message(message)
            await _bot.process_commands(message)

        logger.info("Automation: Discord listener patched")
    except Exception as e:
        logger.debug("Automation: Discord patch skipped (%s)", e)


def _patch_telegram_listener():
    """Hook into Telegram polling to dispatch automation events."""
    # Telegram integration uses polling or webhook — we'll add a simple poller
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        return

    async def _telegram_poller():
        import httpx
        offset = 0
        logger.info("Automation: Telegram poller started")
        while True:
            try:
                async with httpx.AsyncClient(timeout=35) as c:
                    r = await c.get(f"https://api.telegram.org/bot{token}/getUpdates",
                                    params={"offset": offset, "timeout": 30})
                    data = r.json()
                    for update in data.get("result", []):
                        offset = update["update_id"] + 1
                        msg = update.get("message", {})
                        if msg.get("text"):
                            await dispatch_event("telegram", {
                                "message": msg["text"],
                                "chat_id": str(msg["chat"]["id"]),
                                "author": msg.get("from", {}).get("username", ""),
                                "author_id": str(msg.get("from", {}).get("id", "")),
                                "timestamp": datetime.fromtimestamp(msg.get("date", 0), tz=timezone.utc).isoformat(),
                            })
            except Exception as e:
                logger.debug("Telegram poller error: %s", e)
                await asyncio.sleep(5)

    asyncio.create_task(_telegram_poller())
    logger.info("Automation: Telegram listener started")


# ══════════════════════════════════════════════════════════════════════════
# SKILL BRIDGE  (expose automation as skills for chat)
# ══════════════════════════════════════════════════════════════════════════

async def execute_workflow_as_skill(workflow_name: str, params: dict) -> dict:
    """Execute a named workflow from the chat skill system."""
    for wf in _list_wfs():
        if wf.get("name", "").lower() == workflow_name.lower():
            return await execute_workflow(wf, params)
    return {"error": f"Workflow '{workflow_name}' not found"}


@router.get("/skill-bridge/workflows")
async def list_workflows_for_skills():
    """Return active workflows that can be called as skills from chat."""
    return {"workflows": [
        {"name": wf["name"], "id": wf["id"], "active": wf.get("active", False)}
        for wf in _list_wfs()
    ]}
