"""Clawzd — MCP tool integration (re-export shim).

This module has been moved to ``app.tools.mcp``.
This shim exists for backward compatibility — import from ``app.tools.mcp`` in new code.
"""
from app.tools.mcp import *  # noqa: F401,F403
from app.tools.mcp import mcp_manager, get_mcp_skills, MCPToolSkill, MCPManager  # noqa: F401
