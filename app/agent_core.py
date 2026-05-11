"""
Clawzd — Agent core: tool definitions and skill registry.
Exposes available tools to the LLM for function-calling.
Combines static built-in tools with dynamically loaded custom skills.
"""
from fastapi import APIRouter
from app.llm_provider import _get_provider_models

router = APIRouter()

# Tool definitions compatible with OpenAI function-calling schema
BUILTIN_TOOL_DEFINITIONS = [
    {
        "name": "execute_python",
        "description": "Execute Python code in a sandboxed environment with timeout and memory limits.",
        "parameters": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Python code to execute"}
            },
            "required": ["code"],
        },
    },
    {
        "name": "search_web",
        "description": "Search the internet using DuckDuckGo and return relevant results.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"}
            },
            "required": ["query"],
        },
    },
    {
        "name": "create_skill",
        "description": "Create a new custom skill dynamically from code or a template.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Unique skill identifier (snake_case)"},
                "description": {"type": "string", "description": "What the skill does"},
                "category": {"type": "string", "description": "One of: code, data, web, media, automation, integration, other"},
                "code": {"type": "string", "description": "Full Python source code (optional)"},
                "parameters": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Parameter names for the template generator (optional)"
                },
                "triggers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Regex patterns for auto-detection and integration (optional)"
                }
            },
            "required": ["name", "description"],
        },
    },
    {
        "name": "audit_code",
        "description": (
            "Audit code for quality and security. Two modes available:\n"
            "- quick: pylint + bandit + radon on a Python snippet (param: code)\n"
            "- full: Semgrep OWASP + Trivy + detect-secrets + dep-scan on a "
            "directory or Git repo URL (param: target). Returns normalized OWASP "
            "findings with HTML/JSON reports."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["quick", "full"],
                    "description": "Audit mode: 'quick' for snippet, 'full' for directory/repo",
                    "default": "quick",
                },
                "code": {"type": "string", "description": "Python code to audit (quick mode)"},
                "target": {
                    "type": "string",
                    "description": "Directory path or Git URL to audit (full mode)",
                },
            },
            "required": [],
        },
    },
    {
        "name": "run_command",
        "description": "Execute a whitelisted local shell command (ls, cat, grep, git, etc.).",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to run"}
            },
            "required": ["command"],
        },
    },
    {
        "name": "rag_search",
        "description": "Search the local knowledge base (RAG) for relevant documents.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "k": {"type": "integer", "description": "Number of results", "default": 3},
            },
            "required": ["query"],
        },
    },
    {
        "name": "screenshot_local",
        "description": "Capture a screenshot of the local desktop screen.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "screenshot_remote",
        "description": (
            "Capture a screenshot of a remote webpage/URL and return it as a base64 image. "
            "Use this whenever the user asks to see, view, show, preview, or visualize a website or web page. "
            "Also use this when the user asks what a website looks like (e.g. 'show me the page X', "
            "'what does X look like', 'show me X website')."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Full URL of the page to capture (e.g. https://example.com)"},
                "full_page": {"type": "boolean", "description": "Capture the full scrollable page", "default": False},
            },
            "required": ["url"],
        },
    },
    {
        "name": "generate_image",
        "description": (
            "Generate an image from a text description. "
            "For simple images (icons, logos, badges, shapes, diagrams), generates instant SVG. "
            "For complex/photorealistic images, uses Stable Diffusion. "
            "Use 'format' param to force a specific output: 'auto' (default), 'svg', or 'png'."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "Text description of the image to generate"},
                "negative_prompt": {"type": "string", "description": "What to exclude from the image", "default": ""},
                "format": {
                    "type": "string",
                    "enum": ["auto", "svg", "png"],
                    "description": "Output format: 'auto' (detect from prompt), 'svg' (vector), 'png' (raster)",
                    "default": "auto",
                },
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "browse_web",
        "description": (
            "Control a headless browser to navigate, interact with, and extract data from web pages. "
            "Use this for web scraping, form filling, clicking buttons, scrolling, and multi-step automation. "
            "Provide a URL and an optional list of sequential actions to perform.\n\n"
            "Supported actions:\n"
            "- {action: 'click', selector: 'CSS'} — click an element\n"
            "- {action: 'type', selector: 'CSS', text: '...'} — type into a field\n"
            "- {action: 'select', selector: 'CSS', value: '...'} — select dropdown option\n"
            "- {action: 'scroll', direction: 'down'|'up', amount: 500} — scroll the page\n"
            "- {action: 'wait', selector: 'CSS'} or {action: 'wait', time: 2} — wait for element/time\n"
            "- {action: 'extract', selector: 'CSS'} — extract text from element\n"
            "- {action: 'screenshot'} — capture current page state\n"
            "- {action: 'evaluate', script: 'JS code'} — run JavaScript\n"
            "- {action: 'hover', selector: 'CSS'} — hover over element\n"
            "- {action: 'press', key: 'Enter'} — press keyboard key\n"
            "- {action: 'go_back'} — navigate back\n"
            "- {action: 'navigate', url: '...'} — navigate to another URL\n\n"
            "Falls back to HTTP-based simulation if no browser engine is available."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to navigate to"},
                "actions": {
                    "type": "array",
                    "description": "Sequential browser actions to perform after navigation",
                    "items": {
                        "type": "object",
                        "properties": {
                            "action": {
                                "type": "string",
                                "enum": [
                                    "click", "type", "select", "scroll",
                                    "wait", "extract", "screenshot",
                                    "evaluate", "hover", "press",
                                    "go_back", "navigate",
                                ],
                            },
                            "selector": {"type": "string"},
                            "text": {"type": "string"},
                            "value": {"type": "string"},
                            "script": {"type": "string"},
                            "key": {"type": "string"},
                            "url": {"type": "string"},
                            "direction": {"type": "string"},
                            "amount": {"type": "integer"},
                            "time": {"type": "number"},
                            "attribute": {"type": "string"},
                        },
                        "required": ["action"],
                    },
                },
            },
            "required": ["url"],
        },
    },
    {
        "name": "cron_schedule",
        "description": "Schedule a recurring task (cron job) that runs at specified intervals.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Job name"},
                "schedule": {"type": "string", "description": "Cron expression (e.g. '*/5 * * * *')"},
                "action": {"type": "string", "description": "Action to execute"},
            },
            "required": ["name", "schedule", "action"],
        },
    },
    {
        "name": "send_email",
        "description": "Send an email to a specified recipient.",
        "parameters": {
            "type": "object",
            "properties": {
                "subject": {"type": "string", "description": "The subject of the email"},
                "body": {"type": "string", "description": "The body content of the email"},
                "to_email": {"type": "string", "description": "The recipient's email address"}
            },
            "required": ["subject", "body"]
        }
    },
    {
        "name": "post_to_twitter",
        "description": "Post a tweet to Twitter.",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "The text content of the tweet (max 280 characters)"}
            },
            "required": ["text"]
        }
    },
    {
        "name": "post_to_linkedin",
        "description": "Post a message to LinkedIn.",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "The text content to post on LinkedIn"}
            },
            "required": ["text"]
        }
    },
    {
        "name": "post_to_medium",
        "description": "Post an article to Medium.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "The title of the article"},
                "content": {"type": "string", "description": "The markdown content of the article"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Tags for the article"},
                "publish_status": {"type": "string", "enum": ["public", "draft", "unlisted"], "description": "Publish status", "default": "draft"}
            },
            "required": ["title", "content"]
        }
    },
    {
        "name": "trigger_n8n",
        "description": "Trigger an n8n webhook with a JSON payload.",
        "parameters": {
            "type": "object",
            "properties": {
                "payload": {
                    "type": "object",
                    "description": "A JSON object containing the data to send to the n8n webhook."
                }
            },
            "required": ["payload"]
        }
    },
    {
        "name": "generate_animation",
        "description": (
            "Generate a video animation (GIF or MP4) from a text description using a diffusion model. "
            "Use this when the user asks for an animation, a GIF, a video, or moving images."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "Text description of the animation to generate"},
                "negative_prompt": {"type": "string", "description": "What to exclude from the animation", "default": "blurry, low quality, distorted"},
                "format": {
                    "type": "string",
                    "enum": ["gif", "mp4"],
                    "description": "Output format: 'gif' (default) or 'mp4'",
                    "default": "gif",
                },
                "duration": {"type": "number", "description": "Duration of the video in seconds", "default": 2.0},
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "create_document",
        "description": "Create a document (Markdown, Word, Excel, PowerPoint, PDF) from text content.",
        "parameters": {
            "type": "object",
            "properties": {
                "format_type": {
                    "type": "string",
                    "enum": ["markdown", "md", "word", "docx", "excel", "xlsx", "powerpoint", "pptx", "pdf"],
                    "description": "Document format to generate"
                },
                "content": {
                    "type": "string",
                    "description": "The main content of the document"
                },
                "title": {
                    "type": "string",
                    "description": "Title of the document (optional)"
                }
            },
            "required": ["format_type", "content"],
        },
    },
    {
        "name": "memory",
        "description": (
            "Manage persistent memory across sessions. Use to save user preferences, "
            "environment facts, project conventions, corrections, and lessons learned. "
            "Memory persists across sessions and is injected into the system prompt. "
            "Actions: 'add' (new entry), 'replace' (update via substring match), "
            "'remove' (delete via substring match). "
            "Targets: 'memory' (agent notes about environment/projects) or "
            "'user' (user preferences/profile)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["add", "replace", "remove"],
                    "description": "Memory operation to perform"
                },
                "target": {
                    "type": "string",
                    "enum": ["memory", "user"],
                    "description": "Which memory store: 'memory' (agent notes) or 'user' (user profile)",
                    "default": "memory",
                },
                "content": {
                    "type": "string",
                    "description": "Content to add or replacement content (for add/replace)"
                },
                "old_text": {
                    "type": "string",
                    "description": "Unique substring identifying the entry to replace/remove"
                },
            },
            "required": ["action"],
        },
    },
    {
        "name": "undo",
        "description": (
            "Undo the last file modification made by the AI. "
            "Can target a specific file (file_path param) or undo the most recent "
            "edit across all files (no params). Each edit_file call creates a snapshot "
            "that can be reverted."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Workspace-relative path of the file to undo. If omitted, undoes the most recent edit across all files.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "list_files",
        "description": (
            "List files in the workspace matching a glob pattern. "
            "Use this BEFORE read_file or edit_file to discover what files exist. "
            "Faster and safer than run_command with find/ls. "
            "Examples: '**/*.py' (all Python files), 'src/**/*.js' (JS in src/), "
            "'*.md' (markdowns at root), '' or '**/*' (all files)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern relative to workspace root (e.g. '**/*.py', 'src/*.js', '')",
                    "default": "**/*",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of files to return",
                    "default": 60,
                },
                "include_dirs": {
                    "type": "boolean",
                    "description": "Include directory entries in results",
                    "default": False,
                },
            },
            "required": [],
        },
    },
    {
        "name": "todo_write",
        "description": (
            "Create or update a structured todo list for multi-step tasks. "
            "ALWAYS call this first for complex requests to plan your work. "
            "The plan is shown to the user in real-time. "
            "Update todo items as you progress (set status to 'in_progress' when starting, "
            "'completed' when done, 'cancelled' if skipped). "
            "Actions: 'write' (replace all todos), 'update' (update specific item by id), "
            "'clear' (remove all todos)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["write", "update", "clear"],
                    "description": "Operation: 'write' (set all todos), 'update' (change one item), 'clear' (remove all)",
                    "default": "write",
                },
                "todos": {
                    "type": "array",
                    "description": "List of todo items (for 'write' action)",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "description": "Unique identifier (e.g. 'step-1')"},
                            "content": {"type": "string", "description": "Description of the task"},
                            "status": {
                                "type": "string",
                                "enum": ["pending", "in_progress", "completed", "cancelled"],
                                "default": "pending",
                            },
                            "priority": {
                                "type": "string",
                                "enum": ["high", "medium", "low"],
                                "default": "medium",
                            },
                        },
                        "required": ["id", "content"],
                    },
                },
                "id": {
                    "type": "string",
                    "description": "ID of the todo to update (for 'update' action)",
                },
                "status": {
                    "type": "string",
                    "enum": ["pending", "in_progress", "completed", "cancelled"],
                    "description": "New status for the todo item (for 'update' action)",
                },
            },
            "required": ["action"],
        },
    },
]


def _get_dynamic_tool_definitions() -> list[dict]:
    """Fetch tool definitions from dynamically loaded custom skills."""
    try:
        from app.skill_registry import get_registry
        return get_registry().get_tool_definitions()
    except Exception:
        return []


def _get_mcp_tool_definitions() -> list[dict]:
    try:
        from app.mcp_tool import get_mcp_skills
        return [s.to_tool_definition() for s in get_mcp_skills()]
    except Exception as e:
        import logging
        logging.getLogger("clawzd.agent").error("Error fetching MCP tools: %s", e)
        return []


def _get_graphify_tool_definitions() -> list[dict]:
    """Return graphify tools if the CLI is detected on the system."""
    try:
        from app.graphify_integration import get_graphify_tool_definitions
        return get_graphify_tool_definitions()
    except Exception:
        return []


@router.get("/tools")
async def list_tools():
    """Return all available tool definitions (built-in + dynamic + MCP + graphify)."""
    dynamic = _get_dynamic_tool_definitions()
    mcp = _get_mcp_tool_definitions()
    graphify = _get_graphify_tool_definitions()
    all_tools = BUILTIN_TOOL_DEFINITIONS + dynamic + mcp + graphify
    return {
        "tools": all_tools,
        "builtin_count": len(BUILTIN_TOOL_DEFINITIONS),
        "dynamic_count": len(dynamic),
        "mcp_count": len(mcp),
        "graphify_count": len(graphify),
        "total": len(all_tools),
    }


@router.get("/providers")
async def list_providers():
    """Return available LLM providers and their models."""
    return {"providers": await _get_provider_models()}