"""
Clawzd — Model Context Protocol (MCP) tool integration.
Manages connections to external MCP servers and exposes their tools as dynamic skills.
"""
import asyncio
import logging
import os
import shlex
import sys
from typing import Any, Dict, List, Optional
from datetime import datetime

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from config import DATA_DIR
from app.skill_model import BaseSkill, SkillContext, SkillResult

logger = logging.getLogger("clawzd.mcp")

class MCPToolSkill(BaseSkill):
    def __init__(self, mcp_name: str, mcp_tool_info: dict, session_getter):
        self.name = f"mcp_{mcp_name}_{mcp_tool_info['name']}"
        self.description = mcp_tool_info.get("description", "MCP Tool")
        self.category = "integration"
        self.version = "1.0.0"
        self.triggers = [rf"(?i)\b{self.name.replace('_', '|')}\b"]

        # MCP tool definitions use JSON Schema similar to OpenAI function calling
        self.parameters = {
            "type": "object",
            "properties": mcp_tool_info.get("inputSchema", {}).get("properties", {}),
            "required": mcp_tool_info.get("inputSchema", {}).get("required", [])
        }
        self.session_getter = session_getter
        self.mcp_tool_name = mcp_tool_info['name']

    async def execute(self, params: dict, context: SkillContext) -> SkillResult:
        import time
        t0 = time.perf_counter()
        try:
            session = await self.session_getter()
            if not session:
                return SkillResult(success=False, error="MCP Session not available", execution_time=time.perf_counter() - t0)

            # call the MCP tool
            result = await session.call_tool(self.mcp_tool_name, arguments=params)

            # Parse MCP result
            # Assuming MCP results are returned as a list of content blocks
            content = ""
            for block in getattr(result, "content", []):
                if block.type == "text":
                    content += block.text + "\n"

            return SkillResult(
                success=not getattr(result, "isError", False),
                data={"result": content.strip()},
                message="Tool executed via MCP",
                execution_time=time.perf_counter() - t0
            )
        except Exception as e:
            logger.exception("Error executing MCP tool %s: %s", self.name, e)
            return SkillResult(
                success=False,
                error=str(e),
                execution_time=time.perf_counter() - t0
            )

class MCPManager:
    def __init__(self):
        self.servers = {} # name -> config
        self.sessions = {} # name -> ClientSession
        self.exit_stacks = {} # name -> AsyncExitStack
        self.dynamic_skills = []

    async def connect_stdio(self, name: str, command: str, args: List[str], env: Optional[Dict] = None):
        import contextlib
        from mcp.client.stdio import stdio_client

        server_env = os.environ.copy()
        if env:
            server_env.update(env)

        server_parameters = StdioServerParameters(
            command=command,
            args=args,
            env=server_env
        )

        try:
            stack = contextlib.AsyncExitStack()
            read, write = await stack.enter_async_context(stdio_client(server_parameters))
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()

            self.sessions[name] = session
            self.exit_stacks[name] = stack

            # Discover tools
            tools_response = await session.list_tools()
            for tool in tools_response.tools:
                tool_dict = {
                    "name": tool.name,
                    "description": tool.description,
                    "inputSchema": tool.inputSchema
                }
                async def session_getter(s_name=name):
                    return self.sessions.get(s_name)

                skill = MCPToolSkill(name, tool_dict, session_getter)
                self.dynamic_skills.append(skill)

            logger.info(f"Connected to MCP Server {name} (stdio) and loaded tools.")
        except Exception as e:
            logger.error(f"Failed to connect to MCP Server {name} (stdio): {e}")

    def load_config(self):
        import yaml
        config_path = os.path.join(DATA_DIR, "mcp_servers.yaml")
        if not os.path.exists(config_path):
            return

        with open(config_path, "r") as f:
            data = yaml.safe_load(f)
            if not data or "mcp_servers" not in data:
                return
            self.servers = data["mcp_servers"]

    async def connect_all(self):
        self.load_config()
        self.dynamic_skills = []
        for name, cfg in self.servers.items():
            if "command" in cfg:
                await self.connect_stdio(name, cfg["command"], cfg.get("args", []), cfg.get("env"))

        # Auto-detect code-review-graph if not already configured
        await self._auto_detect_code_review_graph()

    async def _auto_detect_code_review_graph(self):
        """Auto-detect and register code-review-graph MCP server if installed.

        code-review-graph provides structural call-graph analysis (callers,
        blast-radius, dead code detection) via MCP stdio transport.
        """
        import shutil
        if "code_review_graph" in self.servers:
            return  # Already manually configured

        crg_path = shutil.which("code-review-graph")
        if not crg_path:
            logger.debug("code-review-graph not found — structural graph tools disabled")
            return

        logger.info("code-review-graph detected at %s — auto-registering as MCP server", crg_path)
        try:
            await self.connect_stdio(
                "code_review_graph",
                crg_path,
                ["serve"],
            )
        except Exception as e:
            logger.warning("Failed to auto-connect code-review-graph: %s", e)

mcp_manager = MCPManager()

def get_mcp_skills() -> List[BaseSkill]:
    return mcp_manager.dynamic_skills

