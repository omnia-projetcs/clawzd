"""
Clawzd — Local command execution tool.
Only whitelisted commands are allowed, running in the workspace directory.
"""
import subprocess
import shlex
from fastapi import APIRouter, HTTPException, Request

router = APIRouter()

ALLOWED_COMMANDS = [
    "ls", "cat", "head", "tail", "wc", "grep", "find",
    "python", "pip", "git", "docker", "curl", "wget",
    "echo", "date", "whoami", "uname", "df", "du",
    "mkdir", "touch", "rm", "cp", "mv",
]


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

    if tokens[0] not in ALLOWED_COMMANDS:
        raise HTTPException(
            400,
            f"Command '{tokens[0]}' not allowed. Allowed: {', '.join(ALLOWED_COMMANDS)}",
        )

    try:
        result = subprocess.run(
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