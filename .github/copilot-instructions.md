# Copilot Instructions for Clawzd

- Focus on the Python backend. `main.py` launches a FastAPI app defined in `app/gateway.py`.
- The server is monolithic. `app/gateway.py` wires domain routers from `app/tools_*`, `app/skills/*`, `app/integrations_*`, `app/rag.py`, `app/chat.py`, and `app/agent_core.py`.
- Dynamic runtime behavior is key:
  - Plugins are auto-discovered in `app/plugins/` by `app/core/plugin_system.py` at startup.
  - Dynamic skills are loaded from `data/skills/` by `app/skills/registry.py` and must subclass `BaseSkill` from `app/skills/model.py`.
  - `app/gateway.py` startup also initializes the upload store, optional Discord/Telegram listeners, and a background skill rebuilder/maintenance loop.
- Tool invocation is not raw shell execution. The LLM output is parsed by `app/tools/executor.py` and mapped to known tools using fuzzy alias matching.
  - The shell-style executor is `run_command`; avoid treating it as unrestricted bash.
- The app expects a local Ollama service for `LLM_PROVIDER=ollama`; `main.py` validates `OLLAMA_HOST` and `OLLAMA_MODEL` before startup.

## Run / install workflow

- Use `./install.sh` for full setup: virtualenv, dependencies, Ollama, Playwright, and optional Docker support.
- Start the app with `./run.sh`.
- Update code and restart with `./update.sh`.
- `./run.sh` launches `python main.py`; `main.py` runs `uvicorn app.gateway:app` with optional reload in debug mode.

## Deployment / environment notes
## Important conventions
- `./install.sh` can install Docker + NVIDIA Container Toolkit and start the app via `docker compose up -d --build`.
- `docker-compose.yml` is available for containerized deployment, with host mounts for `data/`, `models/`, and `workspace/`.
- `.env.example` documents the supported provider toggles: `LLM_PROVIDER`, `ENABLE_CLOUD_MODELS`, `OLLAMA_HOST`, `OLLAMA_MODEL`, and security settings like `API_SECRET_TOKEN`.
- `update.sh` tries to restart an existing `clawzd.service` via `systemctl`/`launchctl` before falling back to `./run.sh`.
- The app is designed to run with a local `.venv`; if `.venv/bin/python` exists, `./run.sh` prefers it.

- `config.py` reads `.env` and defines runtime paths, security, provider settings, and data directories.
- `DEBUG=true` enables uvicorn auto-reload for `app/`, `templates/`, `static/`, and `agents/`.
- `data/` contains runtime state: `data/skills/`, `data/rag/`, `data/images/`, `data/screenshots/`, `data/documents/`, `data/audio/`, and more.
- `app/core/plugin_system.py` provides hooks: `before_prompt_build`, `after_skill_detect`, `before_tool_execute`, `after_tool_execute`, `after_generation`, `on_session_create`, and `register_routes`.
- Plugin modules in `app/plugins/` are auto-discovered and should register a singleton plugin instance at import time.
- Built-in skills use the `builtin_*.py` naming pattern and are treated as protected source skills.
- Dynamic skills must live under `data/skills/` and can be nested one level deep. The registry imports every `.py` file and loads `BaseSkill` subclasses.
- Skill subclasses must implement `async def execute(self, params: dict, context: SkillContext) -> SkillResult` and can define `parameters`, `triggers`, `category`, and `description`.

## Behavioral patterns to respect

- Do not assume a microservice architecture; most logic lives in `app/gateway.py` and the runtime skill/plugin engine.
- Do not add new skill files outside `data/skills/`; the runtime loader only scans that directory.
- Do not change API routing without checking `app/gateway.py` and the referenced router modules.
- Route prefixes to check before modifying them:
  `/chat`, `/profile`, `/code`, `/web`, `/local`, `/quality`, `/rag`, `/improve`, `/agent`, `/api`, `/screenshot`, `/image`, `/audio`, `/browser`, `/cron`, `/skills`, `/document`, `/models`, `/presentation`, `/automation`, `/clone`, `/docgen`.

## Useful entry points

- `main.py` — startup flow, Ollama health check, and debug reload behavior.
- `app/gateway.py` — central FastAPI app, startup hooks, static mounts, router inclusion.
- `app/tools/executor.py` — LLM tool call parsing, fuzzy alias mapping, and tool execution dispatch.
- `app/skills/registry.py` — dynamic skill discovery, hot-reload, and execution tracking.
- `app/skills/model.py` — BaseSkill contract, `SkillContext`, and `SkillResult`.
- `app/core/plugin_system.py` — plugin lifecycle and route registration.
- `app/tools_*.py` — specific tool domain routers and execution logic.
