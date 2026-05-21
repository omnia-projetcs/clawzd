"""
Clawzd — Multi-agent dispatch system.
Orchestrator (Atlas) analyzes user requests, dispatches to specialized agents,
and synthesizes results. All agents share the same tool set.
"""
import os
import json
import logging
from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel

from config import AGENTS_DIR, DATA_DIR

logger = logging.getLogger("clawzd.agents")

AGENT_HISTORY_FILE = os.path.join(DATA_DIR, "agent_history.jsonl")


# ---------------------------------------------------------------------------
# Agent definitions (loaded from agents/ Markdown files)
# ---------------------------------------------------------------------------

class AgentProfile:
    """An agent loaded from a Markdown file in agents/."""

    def __init__(self, name: str, role: str, model: str, skills: str, system_prompt: str):
        self.name = name
        self.role = role
        self.model = model
        self.skills = skills
        self.system_prompt = system_prompt

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "role": self.role,
            "model": self.model,
            "skills": self.skills,
        }


def _parse_agent_md(filepath: str) -> Optional[AgentProfile]:
    """Parse an agent Markdown file into an AgentProfile."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        lines = content.strip().split("\n")
        name = ""
        role = ""
        model = ""
        skills = ""
        system_prompt = ""
        in_prompt = False

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("# "):
                name = stripped[2:].strip()
            elif stripped.startswith("role:"):
                role = stripped[5:].strip()
            elif stripped.startswith("model:"):
                model = stripped[6:].strip()
            elif stripped.startswith("skills:"):
                skills = stripped[7:].strip()
            elif stripped.startswith("system_prompt:"):
                in_prompt = True
                continue
            elif in_prompt:
                system_prompt += line.rstrip() + "\n"
            else:
                if stripped and not any(stripped.startswith(prefix) for prefix in ["role:", "model:", "skills:"]):
                    system_prompt += line.rstrip() + "\n"

        if not name:
            return None

        return AgentProfile(
            name=name,
            role=role,
            model=model,
            skills=skills,
            system_prompt=system_prompt.strip(),
        )
    except Exception as e:
        logger.error("Failed to parse agent file %s: %s", filepath, e)
        return None


def _load_agents() -> dict[str, AgentProfile]:
    """Load all agent profiles from agents/ directory."""
    agents = {}
    if not os.path.isdir(AGENTS_DIR):
        return agents

    for filename in sorted(os.listdir(AGENTS_DIR)):
        if not filename.endswith(".md"):
            continue
        filepath = os.path.join(AGENTS_DIR, filename)
        agent = _parse_agent_md(filepath)
        if agent:
            key = filename.removesuffix(".md")
            agents[key] = agent
            logger.info("  Loaded agent: %s (%s)", agent.name, agent.role)

    return agents


# Cached agents (loaded once on first use)
_agents: Optional[dict[str, AgentProfile]] = None


def get_agents() -> dict[str, AgentProfile]:
    """Return the agent registry, loading from disk if needed."""
    global _agents
    if _agents is None:
        _agents = _load_agents()
    return _agents


# ---------------------------------------------------------------------------
# Orchestrator dispatch logic
# ---------------------------------------------------------------------------

# Keywords that map to specific agents
_AGENT_KEYWORDS = {
    "developer": [
        "code", "program", "debug", "refactor", "fix", "implement", "function",
        "class", "api", "database", "sql", "python", "javascript", "typescript",
        "build", "create app", "application", "bug", "error", "test", "deploy",
        "git", "commit", "merge", "docker", "backend", "frontend", "architecture",
        "audit", "security", "lint", "review",
        "spec", "proposal", "design", "verify", "archive", "change",
    ],
    "researcher": [
        "search", "find", "research", "investigate", "analyze", "compare",
        "what is", "who is", "how does", "explain", "summary", "article",
        "news", "latest", "trend", "data", "statistics", "source", "reference",
    ],
    "soul": [
        "profile", "personality", "soul", "interview", "preferences",
        "values", "traits", "character",
    ],
}


def detect_agent(user_message: str) -> str:
    """Analyze a user message and return the best agent key.

    Returns 'orchestrator' if no specialized agent matches clearly,
    letting the orchestrator handle routing.
    """
    msg_lower = user_message.lower()
    scores: dict[str, int] = {}

    for agent_key, keywords in _AGENT_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in msg_lower)
        if score > 0:
            scores[agent_key] = score

    if not scores:
        return "orchestrator"

    best = max(scores, key=lambda k: scores[k])
    # Only dispatch if confidence is strong enough (at least 2 keyword matches)
    if scores[best] >= 2:
        return best

    return "orchestrator"


# ---------------------------------------------------------------------------
# Agent tool isolation policies (inspired by OpenMonoAgent sub-agents)
# ---------------------------------------------------------------------------

AGENT_TOOL_POLICIES: dict[str, dict] = {
    "developer": {
        "allowed_tools": ["*"],  # Full access
        "max_tool_rounds": 8,
        "description": "Full file + exec access for implementation",
    },
    "researcher": {
        "allowed_tools": [
            "search_web", "screenshot_remote", "rag_search", "read_file",
            "screenshot_remote", "search_twitter", "search_linkedin",
        ],
        "max_tool_rounds": 6,
        "description": "Read-only exploration & web research",
    },
    "soul": {
        "allowed_tools": ["memory", "rag_search"],
        "max_tool_rounds": 5,
        "description": "Profile & memory management only",
    },
    "orchestrator": {
        "allowed_tools": ["*"],  # Full access for routing
        "max_tool_rounds": 10,
        "description": "General-purpose, full access",
    },
}


def get_agent_tool_policy(agent_key: str) -> dict:
    """Return the tool policy for an agent (defaults to orchestrator)."""
    return AGENT_TOOL_POLICIES.get(agent_key, AGENT_TOOL_POLICIES["orchestrator"])


def is_tool_allowed(agent_key: str, tool_name: str) -> bool:
    """Check whether *tool_name* is in the agent's whitelist.

    MCP tools (mcp_*) and custom skills are always allowed for the
    developer and orchestrator agents.
    """
    policy = get_agent_tool_policy(agent_key)
    allowed = policy["allowed_tools"]
    if "*" in allowed:
        return True
    # Always allow the undo tool (safety net)
    if tool_name == "undo":
        return True
    return tool_name in allowed


def get_max_tool_rounds(agent_key: str) -> int:
    """Return the max tool rounds budget for an agent."""
    policy = get_agent_tool_policy(agent_key)
    return policy.get("max_tool_rounds", 8)


def get_agent_system_prompt(agent_key: str) -> Optional[str]:
    """Get the system prompt for a specific agent.

    Returns the agent's system_prompt from its Markdown file, or None
    if the agent is not found.
    """
    agents = get_agents()
    agent = agents.get(agent_key)
    if agent and agent.system_prompt:
        return agent.system_prompt
    return None


# ---------------------------------------------------------------------------
# Agent execution history
# ---------------------------------------------------------------------------

def record_agent_execution(
    session_id: str,
    agent_key: str,
    user_message: str,
    duration_s: float,
    tokens: int = 0,
    tools_used: list[str] | None = None,
):
    """Record an agent execution for traceability."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
        "agent": agent_key,
        "message_preview": user_message[:100],
        "duration_s": round(duration_s, 3),
        "tokens": tokens,
        "tools_used": tools_used or [],
    }
    try:
        os.makedirs(os.path.dirname(AGENT_HISTORY_FILE), exist_ok=True)
        with open(AGENT_HISTORY_FILE, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def get_agent_history(session_id: str | None = None, limit: int = 50) -> list[dict]:
    """Return recent agent execution history, optionally filtered by session."""
    if not os.path.exists(AGENT_HISTORY_FILE):
        return []

    entries = []
    try:
        with open(AGENT_HISTORY_FILE) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if session_id is None or entry.get("session_id") == session_id:
                        entries.append(entry)
                except json.JSONDecodeError:
                    continue
    except Exception:
        pass

    return entries[-limit:]


# ---------------------------------------------------------------------------
# FastAPI router
# ---------------------------------------------------------------------------

from fastapi import APIRouter

router = APIRouter()


@router.get("/list")
async def list_agents():
    """List all available agents with their profiles."""
    agents = get_agents()
    return {
        "agents": {k: v.to_dict() for k, v in agents.items()},
        "total": len(agents),
    }


@router.get("/detect")
async def detect_agent_endpoint(message: str):
    """Detect the best agent for a given message."""
    agent_key = detect_agent(message)
    agents = get_agents()
    agent = agents.get(agent_key)
    return {
        "agent_key": agent_key,
        "agent_name": agent.name if agent else agent_key,
        "agent_role": agent.role if agent else "",
    }


@router.get("/history")
async def agent_history(session_id: str | None = None, limit: int = 50):
    """Return agent execution history."""
    return {"history": get_agent_history(session_id, limit)}


@router.post("/reload")
async def reload_agents():
    """Reload agent profiles from disk."""
    global _agents
    _agents = _load_agents()
    return {"status": "reloaded", "agents": len(_agents)}


@router.get("/detail")
async def get_agent_detail(key: str):
    """Get full details of an agent including system_prompt."""
    agents = get_agents()
    agent = agents.get(key)
    if not agent:
        return {"error": "Agent not found"}
    return {
        "name": agent.name,
        "role": agent.role,
        "model": agent.model,
        "skills": agent.skills,
        "system_prompt": agent.system_prompt,
    }


class SaveAgentRequest(BaseModel):
    key: str
    name: str
    role: str
    model: str
    skills: str
    system_prompt: str


@router.post("/save")
async def save_agent_endpoint(req: SaveAgentRequest):
    """Save or create a new agent profile."""
    key = "".join(c for c in req.key.lower() if c.isalnum() or c in "_-").strip()
    if not key:
        return {"error": "Invalid agent key"}
    
    filepath = os.path.join(AGENTS_DIR, f"{key}.md")
    
    content = (
        f"# {req.name}\n"
        f"role: {req.role}\n"
        f"model: {req.model}\n"
        f"skills: {req.skills}\n"
        f"system_prompt:\n"
        f"{req.system_prompt}\n"
    )
    
    try:
        os.makedirs(AGENTS_DIR, exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        
        # Hot-reload agents registry
        global _agents
        _agents = _load_agents()
        
        return {"status": "saved", "key": key}
    except Exception as e:
        logger.error("Failed to save agent profile: %s", e)
        return {"error": str(e)}
