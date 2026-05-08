"""
Clawzd — Graphify Integration.

Auto-detects the `graphify` CLI tool and exposes semantic knowledge graph
queries as tools for the AI agent.

Graphify (https://github.com/closedloop-technologies/graphify) builds an
AST-based semantic graph of a codebase, enabling conceptual queries like
"how does authentication work?" or "what would break if I remove X?".

This integration is PASSIVE: if graphify is not installed, everything
is silently skipped.  No forced dependency.
"""
import json
import logging
import os
import shutil
import subprocess
from typing import Dict, List, Optional

from config import WORKSPACE_DIR

logger = logging.getLogger("clawzd.graphify")

# Cache detection result
_graphify_available: Optional[bool] = None


def is_graphify_available() -> bool:
    """Check if the `graphify` CLI is installed and accessible."""
    global _graphify_available
    if _graphify_available is None:
        _graphify_available = shutil.which("graphify") is not None
        if _graphify_available:
            logger.info("graphify detected — semantic graph tools available")
        else:
            logger.debug("graphify not found — semantic graph tools disabled")
    return _graphify_available


def _run_graphify(args: List[str], cwd: str = None) -> Dict:
    """Run a graphify command and return the output."""
    if not is_graphify_available():
        return {"error": "graphify is not installed. Install with: pip install graphifyy"}

    cmd = ["graphify"] + args
    work_dir = cwd or WORKSPACE_DIR

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            cwd=work_dir,
        )
        if result.returncode != 0:
            return {
                "error": f"graphify exited with code {result.returncode}",
                "stderr": result.stderr[:1000],
            }
        return {
            "status": "ok",
            "output": result.stdout[:5000],
        }
    except subprocess.TimeoutExpired:
        return {"error": "graphify timed out (60s limit)"}
    except FileNotFoundError:
        return {"error": "graphify binary not found"}
    except Exception as e:
        return {"error": f"graphify execution failed: {e}"}


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def graphify_update(project_path: str = ".") -> Dict:
    """Build or update the semantic graph for a project."""
    cwd = os.path.join(WORKSPACE_DIR, project_path) if project_path != "." else WORKSPACE_DIR
    return _run_graphify(["update", "."], cwd=cwd)


def graphify_query(query: str, project_path: str = ".") -> Dict:
    """Query the semantic graph with a natural language question."""
    cwd = os.path.join(WORKSPACE_DIR, project_path) if project_path != "." else WORKSPACE_DIR
    return _run_graphify(["query", query], cwd=cwd)


def graphify_explain(node: str, project_path: str = ".") -> Dict:
    """Explain a specific node (class, function, module) in the graph."""
    cwd = os.path.join(WORKSPACE_DIR, project_path) if project_path != "." else WORKSPACE_DIR
    return _run_graphify(["explain", node], cwd=cwd)


def graphify_path(source: str, target: str, project_path: str = ".") -> Dict:
    """Find the shortest path between two nodes in the graph."""
    cwd = os.path.join(WORKSPACE_DIR, project_path) if project_path != "." else WORKSPACE_DIR
    return _run_graphify(["path", source, target], cwd=cwd)


# ---------------------------------------------------------------------------
# Dynamic tool definitions (only if graphify is available)
# ---------------------------------------------------------------------------

def get_graphify_tool_definitions() -> List[Dict]:
    """Return OpenAI-compatible tool definitions if graphify is available."""
    if not is_graphify_available():
        return []

    return [
        {
            "name": "graphify_query",
            "description": (
                "Query the semantic knowledge graph of the codebase. "
                "Ask conceptual questions like 'how does auth work?', "
                "'what would break if I remove UserStore?', "
                "'how does a request flow from the API to the database?'. "
                "Much more efficient than reading files one by one."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural language question about the codebase",
                    },
                    "project_path": {
                        "type": "string",
                        "description": "Project directory (relative to workspace)",
                        "default": ".",
                    },
                },
                "required": ["query"],
            },
        },
        {
            "name": "graphify_explain",
            "description": (
                "Explain a specific code entity (class, function, module) "
                "using the semantic graph. Returns its role, dependencies, "
                "and relationships."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "node": {
                        "type": "string",
                        "description": "Name of the entity to explain (e.g. 'CodeEditor', 'compress_messages')",
                    },
                    "project_path": {
                        "type": "string",
                        "description": "Project directory",
                        "default": ".",
                    },
                },
                "required": ["node"],
            },
        },
        {
            "name": "graphify_path",
            "description": (
                "Find the call/dependency path between two code entities. "
                "Useful for understanding how data flows through the system."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "source": {
                        "type": "string",
                        "description": "Starting entity name",
                    },
                    "target": {
                        "type": "string",
                        "description": "Ending entity name",
                    },
                    "project_path": {
                        "type": "string",
                        "description": "Project directory",
                        "default": ".",
                    },
                },
                "required": ["source", "target"],
            },
        },
    ]
