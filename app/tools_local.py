"""
Clawzd — Local command execution tool.
Only whitelisted commands are allowed, running in the workspace directory.
"""
import subprocess
import shlex
import asyncio
import re
from fastapi import APIRouter, HTTPException, Request

router = APIRouter()

# Whitelisted commands
ALLOWED_COMMANDS = [
    "ls", "cat", "head", "tail", "wc", "grep", "find",
    "python", "pip", "git", "docker", "curl", "wget",
    "echo", "date", "whoami", "uname", "df", "du",
    "mkdir", "touch", "rm", "cp", "mv",
]

# Regex pattern for safe arguments: only alphanumeric, dots, hyphens, underscores, slashes, spaces, commas, colons, quotes
_SAFE_ARG_RE = re.compile(r'^[a-zA-Z0-9._\-/ :\'",]+$')

# Dangerous argument patterns that are always blocked
_DANGEROUS_ARGS = [
    '|', '&&', '||', ';', '`', '$(', '>', '<', '\n', '\r',
    '../', '/etc/', '/proc/', '/sys/', '/root/', '/shadow',
    '/passwd', 'eval(', 'exec(', 'rm -rf', 'chmod 777',
]


def _is_safe_arg(arg: str) -> bool:
    """Check if an argument is safe (no shell metacharacters or dangerous patterns)."""
    if not arg:
        return True
    # Block dangerous patterns
    for pattern in _DANGEROUS_ARGS:
        if pattern in arg:
            return False
    # Only allow safe characters
    return bool(_SAFE_ARG_RE.match(arg))


@router.post("/command")
async def run_command(request: Request):
    """Execute a whitelisted shell command in the workspace directory."""
    data = await request.json()
    command = data.get("command", "")
    if not command.strip():
        raise HTTPException(400, "Empty command")

    tokens = shlex.split(command)
    if not tokens:
        raise HTTPException(400, "Empty command")

    # Validate command name
    if tokens[0] not in ALLOWED_COMMANDS:
        raise HTTPException(
            400,
            f"Command '{tokens[0]}' not allowed. Allowed: {', '.join(ALLOWED_COMMANDS)}",
        )

    # Validate ALL arguments (not just the command name)
    for arg in tokens[1:]:
        if not _is_safe_arg(arg):
            raise HTTPException(
                400,
                f"Argument '{arg}' contains unsafe characters or patterns",
            )

    try:
        # Run the blocking subprocess in a thread to avoid blocking the event loop
        result = await asyncio.to_thread(
            subprocess.run,
            tokens,
            capture_output=True,
            text=True,
            timeout=30,
            cwd="./workspace",
        )
        return {
            "stdout": result.stdout[-5000:],
            "stderr": result.stderr[-500:],
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"error": "Command timed out after 30s", "returncode": -1}
    except Exception as e:
        return {"error": str(e), "returncode": -1}