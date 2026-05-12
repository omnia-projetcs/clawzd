"""
Clawzd — Model Manager (Ollama backend).
Pull, list, activate, delete models via Ollama REST API.
"""
import json
import os
import logging
import threading
import time

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config import BASE_DIR, OLLAMA_HOST

logger = logging.getLogger("clawzd.models")

router = APIRouter()

CATALOG_PATH = str(BASE_DIR / "models_catalog.json")

# ---------------------------------------------------------------------------
# Model catalog — loaded from external JSON file
# ---------------------------------------------------------------------------
import asyncio

def _load_catalog_sync() -> list:
    """Load model catalog from JSON file synchronously."""
    try:
        with open(CATALOG_PATH, "r", encoding="utf-8") as f:
            catalog = json.load(f)
        logger.info("Loaded %d models from %s", len(catalog), CATALOG_PATH)
        return catalog
    except FileNotFoundError:
        logger.warning("Catalog file not found: %s — using empty catalog", CATALOG_PATH)
        return []
    except json.JSONDecodeError as e:
        logger.error("Invalid JSON in catalog file %s: %s", CATALOG_PATH, e)
        return []

async def _load_catalog() -> list:
    """Load model catalog from JSON file asynchronously without blocking."""
    return await asyncio.to_thread(_load_catalog_sync)

MODEL_CATALOG = _load_catalog_sync()


# ---------------------------------------------------------------------------
# Ollama API helpers
# ---------------------------------------------------------------------------
def _ollama_api(method: str, path: str, **kwargs) -> httpx.Response:
    """Make a request to the Ollama REST API."""
    url = f"{OLLAMA_HOST}{path}"
    return httpx.request(method, url, timeout=10, **kwargs)


def _get_ollama_models() -> list[dict]:
    """Get list of models installed in Ollama."""
    try:
        resp = _ollama_api("GET", "/api/tags")
        if resp.status_code == 200:
            return resp.json().get("models", [])
    except Exception as e:
        logger.warning("Cannot reach Ollama: %s", e)
    return []


def _get_ollama_running() -> list[dict]:
    """Get list of currently loaded/running models in Ollama."""
    try:
        resp = _ollama_api("GET", "/api/ps")
        if resp.status_code == 200:
            return resp.json().get("models", [])
    except Exception:
        pass
    return []


def _is_model_in_ollama(model_name: str) -> bool:
    """Check if a model is installed in Ollama.

    Matches by base name (e.g. 'qwen3:8b' matches 'qwen3:latest').
    """
    models = _get_ollama_models()
    base = model_name.split(":")[0]
    return any(m.get("name", "").split(":")[0] == base for m in models)


def _is_hf_model_downloaded(repo_id: str) -> bool:
    """Check if a Hugging Face model is locally downloaded."""
    from pathlib import Path
    import os
    
    # Check config for custom MODELS_DIR, fallback to ~/.cache
    try:
        from config import MODELS_DIR
        cache_dir = Path(MODELS_DIR) / "hub"
    except ImportError:
        cache_dir = Path.home() / ".cache" / "huggingface" / "hub"
        
    safe_name = "models--" + repo_id.replace("/", "--")
    model_path = cache_dir / safe_name
    if model_path.exists():
        snapshots = model_path / "snapshots"
        if snapshots.exists() and any(snapshots.iterdir()):
            return True
    return False


# ---------------------------------------------------------------------------
# Download state (for pull progress tracking)
# ---------------------------------------------------------------------------
_download_state = {
    "active": False,
    "model_id": None,
    "ollama_id": None,
    "progress": 0.0,     # 0-100
    "downloaded_mb": 0,
    "total_mb": 0,
    "speed_mbps": 0.0,
    "error": None,
    "completed": False,
    "status_text": "",
}
_download_lock = threading.Lock()


def _pull_worker(model: dict):
    """Background thread to pull a model via Ollama API."""
    global _download_state
    ollama_id = model.get("ollama_id", model.get("id"))

    with _download_lock:
        _download_state.update({
            "active": True,
            "model_id": model["id"],
            "ollama_id": ollama_id,
            "progress": 0.0,
            "downloaded_mb": 0,
            "total_mb": 0,
            "speed_mbps": 0.0,
            "error": None,
            "completed": False,
            "status_text": "Starting pull...",
        })

    try:
        logger.info("Pulling model via Ollama: %s", ollama_id)
        # Ollama pull is a streaming endpoint
        url = f"{OLLAMA_HOST}/api/pull"
        t0 = time.time()

        with httpx.stream(
            "POST", url,
            json={"name": ollama_id, "stream": True},
            timeout=httpx.Timeout(connect=10, read=600, write=10, pool=10),
        ) as resp:
            if resp.status_code != 200:
                raise Exception(f"Ollama pull failed: HTTP {resp.status_code}")

            for line in resp.iter_lines():
                if not _download_state["active"]:
                    logger.info("Pull cancelled")
                    return
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue

                status = data.get("status", "")
                _download_state["status_text"] = status

                total = data.get("total", 0)
                completed = data.get("completed", 0)

                if total > 0:
                    _download_state["total_mb"] = round(total / (1024 * 1024))
                    _download_state["downloaded_mb"] = round(completed / (1024 * 1024))
                    _download_state["progress"] = round(completed / total * 100, 1)
                    elapsed = max(time.time() - t0, 0.001)
                    _download_state["speed_mbps"] = round(completed / elapsed / (1024 * 1024), 1)

                if status == "success":
                    break

        _download_state["progress"] = 100.0
        _download_state["completed"] = True
        _download_state["status_text"] = "Pull complete"
        logger.info("Model pulled successfully: %s", ollama_id)

    except Exception as e:
        _download_state["error"] = str(e)
        _download_state["status_text"] = f"Error: {e}"
        logger.error("Pull failed: %s", e)
    finally:
        _download_state["active"] = False


def _hf_pull_worker(model: dict):
    """Background thread to pull a Hugging Face model."""
    global _download_state
    repo_id = model.get("ollama_id", model.get("id"))

    with _download_lock:
        _download_state.update({
            "active": True,
            "model_id": model["id"],
            "ollama_id": repo_id,
            "progress": 0.0,
            "downloaded_mb": 0,
            "total_mb": 0,
            "speed_mbps": 0.0,
            "error": None,
            "completed": False,
            "status_text": "Starting Hugging Face download...",
        })

    try:
        import sys
        import subprocess
        import json

        # Attempt to get HF_TOKEN if available to download gated models
        hf_token = os.environ.get("HF_TOKEN", os.environ.get("HUGGINGFACE_API_KEY", ""))
        if not hf_token:
            try:
                from config import HUGGINGFACE_API_KEY
                hf_token = HUGGINGFACE_API_KEY
            except ImportError:
                pass

        # We run the download in an isolated subprocess to avoid monkey-patching the main process's tqdm
        script = """
import sys, json, os
from huggingface_hub import snapshot_download
import tqdm
import tqdm.auto
orig_tqdm = tqdm.auto.tqdm

class JsonProgressTracker(orig_tqdm):
    def update(self, n=1):
        super().update(n)
        total = getattr(self, "total", 0)
        current = getattr(self, "n", 0)
        if total:
            prog = min(100.0, (current / total) * 100)
            dl_mb = int(current / (1024*1024))
            tot_mb = int(total / (1024*1024))
            print(json.dumps({"progress": prog, "downloaded_mb": dl_mb, "total_mb": tot_mb, "status_text": self.desc or ""}))
            sys.stdout.flush()

tqdm.auto.tqdm = JsonProgressTracker
tqdm.tqdm = JsonProgressTracker
try:
    import huggingface_hub.utils.tqdm
    huggingface_hub.utils.tqdm.tqdm = JsonProgressTracker
except ImportError: pass
try:
    import huggingface_hub.utils._progress
    huggingface_hub.utils._progress.tqdm = JsonProgressTracker
except ImportError: pass

repo_id = sys.argv[1]
hf_token = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] else None
snapshot_download(repo_id=repo_id, max_workers=4, token=hf_token)
print(json.dumps({"progress": 100.0, "completed": True}))
"""

        process = subprocess.Popen(
            [sys.executable, "-c", script, repo_id, hf_token or ""],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )

        for line in iter(process.stdout.readline, ""):
            if not _download_state["active"]:
                process.terminate()
                raise KeyboardInterrupt("Download cancelled")
            try:
                data = json.loads(line.strip())
                if "progress" in data:
                    _download_state["progress"] = data["progress"]
                if "downloaded_mb" in data:
                    _download_state["downloaded_mb"] = data["downloaded_mb"]
                if "total_mb" in data:
                    _download_state["total_mb"] = data["total_mb"]
                if "status_text" in data:
                    _download_state["status_text"] = f"Downloading... {data['status_text']}"
                if data.get("completed"):
                    _download_state["progress"] = 100.0
                    _download_state["completed"] = True
                    _download_state["status_text"] = "Download complete"
            except json.JSONDecodeError:
                pass  # Ignore non-JSON logs from huggingface_hub

        process.wait()
        if process.returncode != 0 and process.returncode != -15:
            raise RuntimeError(f"Subprocess failed with code {process.returncode}")

        logger.info("HF Model pulled successfully: %s", repo_id)

    except KeyboardInterrupt:
        _download_state["error"] = "Download cancelled"
        _download_state["status_text"] = "Cancelled"
        logger.info("HF Pull cancelled: %s", repo_id)
    except Exception as e:
        _download_state["error"] = str(e)
        _download_state["status_text"] = f"Error: {e}"
        logger.error("HF Pull failed: %s", e)
    finally:
        _download_state["active"] = False


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

@router.post("/catalog/reload")
async def reload_catalog():
    """Hot-reload the model catalog from JSON file."""
    global MODEL_CATALOG
    MODEL_CATALOG = await _load_catalog()
    return {"status": "reloaded", "count": len(MODEL_CATALOG)}


@router.get("/catalog")
async def get_catalog():
    """Return the model catalog with download/active status from Ollama."""
    # Get installed Ollama models
    ollama_models = _get_ollama_models()

    # Build lookup indexes: exact name → model, base_name → [models]
    ollama_by_name: dict[str, dict] = {}
    ollama_by_base: dict[str, list[dict]] = {}
    for om in ollama_models:
        name = om.get("name", "")
        ollama_by_name[name] = om
        base = name.split(":")[0]
        ollama_by_base.setdefault(base, []).append(om)

    # Get the currently active model from config
    try:
        from config import OLLAMA_MODEL
        active_model = OLLAMA_MODEL
    except ImportError:
        active_model = None

    # Get running models
    running = _get_ollama_running()
    running_names = {m.get("name", "") for m in running}

    catalog = []
    for m in MODEL_CATALOG:
        entry = dict(m)
        ollama_id = m.get("ollama_id", "")
        backend = m.get("backend", "ollama")

        if not ollama_id:
            entry["downloaded"] = False
            entry["active"] = False
            entry["running"] = False
            catalog.append(entry)
            continue

        if backend == "hf":
            entry["downloaded"] = _is_hf_model_downloaded(ollama_id)
            entry["active"] = False
            entry["running"] = False
            entry["local_size_gb"] = entry.get("size_gb", 0) if entry["downloaded"] else 0
            catalog.append(entry)
            continue

        cat_base = ollama_id.split(":")[0]
        cat_tag = ollama_id.split(":")[1] if ":" in ollama_id else "latest"

        # --- Match: is this catalog model installed in Ollama? ---
        matched_om = None

        # 1) Exact name match (e.g. "qwen2.5:14b" in Ollama)
        if ollama_id in ollama_by_name:
            matched_om = ollama_by_name[ollama_id]

        # 2) Check base:latest → match only if param size is compatible
        elif cat_base in ollama_by_base:
            candidates = ollama_by_base[cat_base]
            cat_params = m.get("params", "").lower().replace("b", "").strip()
            for cand in candidates:
                cand_name = cand.get("name", "")
                cand_tag = cand_name.split(":")[1] if ":" in cand_name else "latest"
                cand_params = cand.get("details", {}).get("parameter_size", "")

                # If the Ollama model has the same specific tag
                if cand_tag == cat_tag:
                    matched_om = cand
                    break

                # If Ollama has :latest, check if param size matches our catalog
                if cand_tag == "latest" and cat_tag != "latest":
                    # Extract numeric param sizes for comparison
                    try:
                        cat_num = float(cat_params.split("(")[0].strip()) if cat_params else 0
                        cand_num = float(cand_params.lower().replace("b", "").strip()) if cand_params else 0
                        # Allow ~30% tolerance (e.g. "8B" catalog vs "8.2B" Ollama)
                        if cat_num > 0 and cand_num > 0 and abs(cat_num - cand_num) / max(cat_num, 1) < 0.35:
                            matched_om = cand
                            break
                    except (ValueError, ZeroDivisionError):
                        pass

        entry["downloaded"] = matched_om is not None

        # --- Active check: does the active_model match this catalog entry? ---
        if active_model:
            active_base = active_model.split(":")[0]
            entry["active"] = (
                ollama_id == active_model or
                (cat_base == active_base and matched_om is not None)
            )
        else:
            entry["active"] = False

        # --- Running check ---
        entry["running"] = any(
            cat_base == n.split(":")[0] for n in running_names
        ) if running_names else False

        # --- Size from matched Ollama model ---
        if matched_om:
            entry["local_size_gb"] = round(matched_om.get("size", 0) / (1024**3), 1)

        catalog.append(entry)

    return {"catalog": catalog, "active_model": active_model}


@router.get("/local")
async def get_local_models():
    """List models installed in Ollama."""
    ollama_models = _get_ollama_models()
    models = []
    for m in ollama_models:
        name = m.get("name", "unknown")
        size_gb = round(m.get("size", 0) / (1024**3), 1)
        family = m.get("details", {}).get("family", "unknown")
        params = m.get("details", {}).get("parameter_size", "?")
        quant = m.get("details", {}).get("quantization_level", "?")

        # Try to match with catalog
        catalog_entry = next(
            (c for c in MODEL_CATALOG if c.get("ollama_id") == name or
             c.get("ollama_id", "").split(":")[0] == name.split(":")[0]),
            None
        )

        models.append({
            "name": name,
            "size_gb": size_gb,
            "family": family,
            "params": params,
            "quant": quant,
            "catalog_id": catalog_entry["id"] if catalog_entry else None,
            "display_name": catalog_entry["name"] if catalog_entry else name,
            "vendor": catalog_entry["vendor"] if catalog_entry else family.capitalize(),
        })

    return {"models": models}


class DownloadRequest(BaseModel):
    model_id: str


@router.post("/download")
async def download_model(req: DownloadRequest):
    """Pull a model from the Ollama registry or Hugging Face Hub."""
    model = next((m for m in MODEL_CATALOG if m["id"] == req.model_id), None)
    if not model:
        raise HTTPException(404, f"Model not found in catalog: {req.model_id}")

    ollama_id = model.get("ollama_id")
    if not ollama_id:
        raise HTTPException(400, f"Model {req.model_id} has no ollama_id — cannot pull")

    if _download_state["active"]:
        raise HTTPException(409, "A download is already in progress")

    backend = model.get("backend", "ollama")

    if backend == "hf":
        if _is_hf_model_downloaded(ollama_id):
            return {"status": "already_installed", "ollama_id": ollama_id}
        thread = threading.Thread(target=_hf_pull_worker, args=(model,), daemon=True)
    else:
        # Check if already installed
        if _is_model_in_ollama(ollama_id):
            return {"status": "already_installed", "ollama_id": ollama_id}
        thread = threading.Thread(target=_pull_worker, args=(model,), daemon=True)

    thread.start()
    return {"status": "pulling", "ollama_id": ollama_id, "model_id": req.model_id}


@router.get("/download/status")
async def download_status():
    """Return current download/pull progress."""
    return dict(_download_state)


@router.post("/download/cancel")
async def cancel_download():
    """Cancel the current pull."""
    if _download_state["active"]:
        _download_state["active"] = False
        return {"status": "cancelling"}
    return {"status": "no_active_download"}


class DeleteRequest(BaseModel):
    filename: str  # Actually the ollama model name now


@router.post("/delete")
async def delete_model(req: DeleteRequest):
    """Delete a model from Ollama.

    If the deleted model is the currently active one, automatically
    activate another installed model.
    """
    model_name = req.filename  # field name kept for frontend compat

    # Check if this is the active model
    is_active = False
    try:
        from config import OLLAMA_MODEL
        is_active = (model_name == OLLAMA_MODEL or
                     model_name.split(":")[0] == OLLAMA_MODEL.split(":")[0])
    except ImportError:
        pass

    # Delete from Ollama
    try:
        resp = _ollama_api("DELETE", "/api/delete", json={"name": model_name})
        if resp.status_code not in (200, 404):
            raise HTTPException(500, f"Ollama delete failed: {resp.text}")
    except httpx.HTTPError as e:
        raise HTTPException(500, f"Cannot reach Ollama: {e}")

    logger.info("Deleted model from Ollama: %s", model_name)

    fallback_model = None
    if is_active:
        # Find another installed model to fall back to
        remaining = _get_ollama_models()
        remaining = [m for m in remaining if m.get("name") != model_name]

        if remaining:
            # Prefer a model from our catalog
            for rm in remaining:
                rname = rm.get("name", "")
                cat = next(
                    (c for c in MODEL_CATALOG if c.get("ollama_id") == rname or
                     c.get("ollama_id", "").split(":")[0] == rname.split(":")[0]),
                    None
                )
                if cat and cat.get("backend", "ollama") != "hf":
                    fallback_model = rname
                    break
            if not fallback_model:
                fallback_model = remaining[0].get("name")

            logger.info("Active model deleted — falling back to: %s", fallback_model)
            _update_active_model(fallback_model)
        else:
            logger.warning("Active model deleted — no remaining models")

    return {
        "status": "deleted",
        "filename": model_name,
        "was_active": is_active,
        "fallback_model": fallback_model,
    }


class ActivateRequest(BaseModel):
    filename: str  # Actually the ollama model name


@router.post("/activate")
async def activate_model(req: ActivateRequest):
    """Set a model as the active Ollama model.

    Updates .env and in-memory config. Ollama loads models on-demand,
    so no restart is needed.
    """
    model_name = req.filename  # field name kept for frontend compat

    # Verify model exists in Ollama
    if not _is_model_in_ollama(model_name):
        raise HTTPException(404, f"Model not found in Ollama: {model_name}")

    _update_active_model(model_name)

    # Pre-load the model with GPU settings
    try:
        from config import OLLAMA_NUM_GPU, OLLAMA_NUM_CTX
        options = {"num_gpu": OLLAMA_NUM_GPU}
        if OLLAMA_NUM_CTX != -1:
            options["num_ctx"] = OLLAMA_NUM_CTX
        resp = httpx.post(
            f"{OLLAMA_HOST}/api/generate",
            json={
                "model": model_name,
                "prompt": "",
                "keep_alive": "10m",
                "options": options,
            },
            timeout=60,
        )
        if resp.status_code == 200:
            logger.info("Model pre-loaded in Ollama: %s (num_gpu=%d, num_ctx=%d)", model_name, OLLAMA_NUM_GPU, OLLAMA_NUM_CTX)
    except Exception as e:
        logger.warning("Could not pre-load model: %s", e)

    return {
        "status": "activated",
        "filename": model_name,
        "message": f"Model {model_name} activated.",
        "hot_swap": True,
    }


def _update_active_model(model_name: str):
    """Update the active model in .env and in-memory config."""
    # Update .env
    env_path = str(BASE_DIR / ".env")
    try:
        if os.path.exists(env_path):
            with open(env_path, "r") as f:
                lines = f.readlines()
        else:
            lines = []

        new_lines = []
        found = False
        for line in lines:
            if line.strip().startswith("OLLAMA_MODEL="):
                new_lines.append(f"OLLAMA_MODEL={model_name}\n")
                found = True
            else:
                new_lines.append(line)

        if not found:
            new_lines.append(f"OLLAMA_MODEL={model_name}\n")

        with open(env_path, "w") as f:
            f.writelines(new_lines)
    except Exception as e:
        logger.warning("Could not update .env: %s", e)

    # Update in-memory config
    try:
        import config as cfg
        cfg.OLLAMA_MODEL = model_name
        logger.info("Active model updated: %s", model_name)
    except Exception as e:
        logger.warning("Could not update config in-memory: %s", e)


@router.get("/hardware")
async def get_hardware_info():
    """Return current hardware info for model compatibility display."""
    import subprocess

    info = {"vram_total_mib": None, "vram_free_mib": None, "ram_total_mib": None, "ram_free_mib": None, "gpu_name": None}

    # GPU info
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            parts = result.stdout.strip().split(", ")
            info["gpu_name"] = parts[0]
            info["vram_total_mib"] = int(parts[1])
            info["vram_free_mib"] = int(parts[2])
    except Exception:
        pass

    # RAM info
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    info["ram_total_mib"] = int(line.split()[1]) // 1024
                elif line.startswith("MemAvailable:"):
                    info["ram_free_mib"] = int(line.split()[1]) // 1024
    except Exception:
        pass

    return info


@router.get("/llm-status")
async def get_llm_status():
    """Return current LLM status from Ollama."""
    try:
        from config import OLLAMA_MODEL

        # Check if Ollama is reachable
        try:
            resp = _ollama_api("GET", "/api/tags")
            if resp.status_code != 200:
                return {"status": "stopped", "active_model": OLLAMA_MODEL}
        except Exception:
            return {"status": "stopped", "active_model": OLLAMA_MODEL}

        # Check if a model is currently loaded
        running = _get_ollama_running()
        is_running = any(
            m.get("name", "").startswith(OLLAMA_MODEL.split(":")[0])
            for m in running
        )

        return {
            "status": "running" if is_running else "ready",
            "active_model": OLLAMA_MODEL,
            "gpu_layers": "auto",
            "ctx_size": "auto",
            "crash_count": 0,
            "last_error": "",
            "pid": None,
        }
    except ImportError:
        return {"status": "unavailable", "active_model": None}
