"""
Clawzd — Application entry point.
Checks Ollama health and launches the FastAPI web application.
"""
import logging
import time

import httpx
import uvicorn

from config import OLLAMA_HOST, OLLAMA_MODEL, LLM_PROVIDER, APP_HOST, APP_PORT

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
logger = logging.getLogger("clawzd.main")


def check_ollama_health() -> bool:
    """Verify that Ollama is running and the active model is available."""
    try:
        resp = httpx.get(f"{OLLAMA_HOST}/api/tags", timeout=5)
        if resp.status_code != 200:
            logger.error("Ollama not responding at %s (HTTP %d)", OLLAMA_HOST, resp.status_code)
            return False

        models = resp.json().get("models", [])
        model_names = [m.get("name", "") for m in models]
        logger.info("Ollama is running — %d models available", len(models))

        # Check if active model is installed
        active_base = OLLAMA_MODEL.split(":")[0]
        found = any(n.startswith(active_base) for n in model_names)
        if found:
            logger.info("Active model '%s' is installed ✓", OLLAMA_MODEL)
        else:
            logger.warning(
                "Active model '%s' is NOT installed in Ollama. "
                "Install it with: ollama pull %s",
                OLLAMA_MODEL, OLLAMA_MODEL,
            )

        return True

    except httpx.ConnectError:
        logger.error(
            "Cannot connect to Ollama at %s. "
            "Start it with: ollama serve",
            OLLAMA_HOST,
        )
        return False
    except Exception as e:
        logger.error("Ollama health check failed: %s", e)
        return False


if __name__ == "__main__":
    if LLM_PROVIDER == "local":
        logger.info("LLM backend: Ollama (%s)", OLLAMA_HOST)
        logger.info("Active model: %s", OLLAMA_MODEL)

        if check_ollama_health():
            logger.info("Ollama ready ✓")
        else:
            logger.warning(
                "Ollama is not available. The app will start anyway, "
                "but local LLM features won't work until Ollama is running."
            )
    else:
        logger.info("LLM backend: %s (cloud)", LLM_PROVIDER)

    from config import DEBUG

    if DEBUG:
        logger.info("🔧 DEBUG mode ON — auto-reload enabled")
        uvicorn.run(
            "app.gateway:app",
            host=APP_HOST,
            port=APP_PORT,
            reload=True,
            reload_dirs=["app", "templates", "static", "agents"],
            reload_excludes=[
                "data/**",
                "chroma_db/**",
                "workspace/**",
                "models/**",
                "__pycache__/**",
                ".git/**",
                "*.db",
                "*.db-journal",
                "*.pyc",
                "*.log",
            ],
            log_level="debug",
        )
    else:
        logger.info("Starting Clawzd web server on %s:%d", APP_HOST, APP_PORT)
        uvicorn.run("app.gateway:app", host=APP_HOST, port=APP_PORT, reload=False)