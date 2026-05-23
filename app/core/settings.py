"""
Clawzd — Runtime settings persisted in a JSON file.
Provides defaults, load, save, and API router.
"""
import os
import json
from fastapi import APIRouter
from config import SETTINGS_PATH
from dotenv import dotenv_values, set_key

router = APIRouter()

DEFAULT_SETTINGS = {
    "default_provider": "ollama",
    "default_model": "",
    "default_preprompt": "none",
    "theme": "dark",
    "language": "en",
    "code_execution_timeout": 30,
    "code_max_memory_mb": 512,
    "streaming_enabled": True,
    "require_command_confirmation": True,
    "enable_suggestions": False,
    "show_automation": True,
    "show_media": True,
    "show_presentation": True,
    "show_project": True,
    "show_editor": True,
    # Cloud AI providers toggle (OpenAI, Anthropic, Google, Grok, Groq, Mistral, etc.)
    # When False: only Ollama (local) is available — fully offline mode.
    "enable_cloud_models": True,
}


def load_settings() -> dict:
    """Load settings from disk, merging with defaults for any missing keys."""
    settings = dict(DEFAULT_SETTINGS)
    if os.path.exists(SETTINGS_PATH):
        try:
            with open(SETTINGS_PATH, "r") as f:
                saved = json.load(f)
            settings.update(saved)
        except (json.JSONDecodeError, OSError):
            pass
    return settings


def save_settings(settings: dict) -> dict:
    """Persist settings to disk and return the merged result."""
    merged = dict(DEFAULT_SETTINGS)
    merged.update(settings)
    os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
    with open(SETTINGS_PATH, "w") as f:
        json.dump(merged, f, indent=2)
    return merged


# --- API Routes ---

# Keys containing these substrings are considered sensitive
_SENSITIVE_SUBSTRINGS = {"key", "secret", "token", "password", "api_key"}


def _mask_value(key: str, value: str) -> str:
    """Mask sensitive values, showing only the last 4 characters."""
    key_lower = key.lower()
    if any(s in key_lower for s in _SENSITIVE_SUBSTRINGS):
        if value and len(value) > 4:
            return "***" + value[-4:]
        elif value:
            return "***"
    return value


@router.get("/settings")
async def get_settings():
    """Return current application settings."""
    return load_settings()


@router.post("/settings")
async def update_settings_endpoint(request: dict):
    """Update one or more settings. Accepts partial updates.

    Only keys present in DEFAULT_SETTINGS are accepted to prevent
    arbitrary key injection.
    """
    current = load_settings()
    # Filter to only known keys
    filtered = {k: v for k, v in request.items() if k in DEFAULT_SETTINGS}
    current.update(filtered)
    saved = save_settings(current)
    return {"status": "ok", "settings": saved}


@router.get("/env")
async def get_env_settings():
    """Return environment variables from .env file."""
    env_path = ".env"
    if not os.path.exists(env_path):
        return {}
    return dotenv_values(env_path)


@router.post("/env")
async def update_env_settings(request: dict):
    """Update variables in .env file."""
    env_path = ".env"
    if not os.path.exists(env_path):
        open(env_path, 'a').close()  # create empty if not exists
    for k, v in request.items():
        set_key(env_path, k, v)
        # Also propagate to os.environ so code using os.getenv() picks
        # up the change immediately (especially OLLAMA_HOST for remote servers).
        os.environ[k] = v
    return {"status": "ok"}


@router.get("/update/check")
async def check_update():
    """Check if a new git update is available by fetching origin."""
    import subprocess
    try:
        if not os.path.exists(".git"):
            return {"status": "error", "message": "Not a git repository."}
        
        # silent fetch origin
        subprocess.run(["git", "fetch", "origin"], capture_output=True, text=True, check=True)
        
        # active branch
        branch_res = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True, check=True)
        branch = branch_res.stdout.strip()
        
        # shas
        local_res = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True)
        local_sha = local_res.stdout.strip()
        
        remote_res = subprocess.run(["git", "rev-parse", f"origin/{branch}"], capture_output=True, text=True, check=True)
        remote_sha = remote_res.stdout.strip()
        
        if local_sha == remote_sha:
            return {
                "status": "ok",
                "update_available": False,
                "branch": branch,
                "local_sha": local_sha[:7],
            }
        
        log_res = subprocess.run(["git", "log", "-n", "1", f"origin/{branch}", "--oneline"], capture_output=True, text=True, check=True)
        commit_msg = log_res.stdout.strip()
        
        return {
            "status": "ok",
            "update_available": True,
            "branch": branch,
            "local_sha": local_sha[:7],
            "remote_sha": remote_sha[:7],
            "commit_message": commit_msg,
        }
    except subprocess.CalledProcessError as e:
        return {"status": "error", "message": f"Git command failed: {e.stderr or str(e)}"}
    except Exception as e:
        return {"status": "error", "message": f"Error: {str(e)}"}


@router.post("/update/pull")
async def pull_update():
    """Execute git pull origin [active branch] to fetch latest changes."""
    import subprocess
    try:
        if not os.path.exists(".git"):
            return {"status": "error", "message": "Not a git repository."}
            
        branch_res = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True, check=True)
        branch = branch_res.stdout.strip()
        
        pull_res = subprocess.run(["git", "pull", "origin", branch], capture_output=True, text=True)
        if pull_res.returncode != 0:
            return {"status": "error", "message": f"Git pull failed: {pull_res.stderr or pull_res.stdout}"}
            
        return {"status": "ok", "output": pull_res.stdout.strip()}
    except subprocess.CalledProcessError as e:
        return {"status": "error", "message": f"Git pull command failed: {e.stderr or str(e)}"}
    except Exception as e:
        return {"status": "error", "message": f"Error: {str(e)}"}
