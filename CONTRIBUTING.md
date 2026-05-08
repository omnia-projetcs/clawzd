# Contributing to Clawzd

Thank you for your interest in contributing to Clawzd! This guide will help you get started.

## Development Setup

```bash
# 1. Fork and clone the repository
git clone https://github.com/omnia-projetcs/clawsd.git
cd clawsd

# 2. Run the installer
chmod +x install.sh
./install.sh

# 3. Activate the virtual environment
source .venv/bin/activate

# 4. Configure your .env
cp .env.example .env
nano .env
```

## Project Architecture

> **📋 See [`CONVENTIONS.md`](CONVENTIONS.md) for the complete rules file (AI assistants & developers).**

```
clawsd/
├── main.py                  # Entry point (Ollama health + uvicorn)
├── config.py                # Centralized configuration from .env
├── CONVENTIONS.md           # ⚡ Dev & AI conventions (MUST READ)
│
├── app/                     # Application modules (Python packages)
│   ├── gateway.py           # FastAPI app, middleware (LEGACY — being split)
│   │
│   ├── core/                # Infrastructure services
│   │   ├── cache.py         # Semantic response cache
│   │   ├── compression.py   # Data compression
│   │   ├── database.py      # SQLite access layer
│   │   ├── llm_provider.py  # Multi-provider LLM abstraction
│   │   ├── memory.py        # Conversation memory
│   │   ├── metrics.py       # Performance metrics
│   │   ├── output_compressor.py
│   │   ├── settings.py      # App settings
│   │   └── preprompts.py    # System prompt templates
│   │
│   ├── tools/               # AI tools by domain
│   │   ├── audio.py         # TTS, voice cloning, music
│   │   ├── code.py          # Code execution & auditing
│   │   ├── document.py      # Document generation
│   │   ├── image.py         # Image generation (SD, FLUX)
│   │   ├── presentation.py  # Slide deck creation
│   │   ├── project.py       # Kanban project management
│   │   ├── research.py      # Web research (Tavily)
│   │   └── executor.py      # Tool dispatch engine
│   │
│   ├── skills/              # Dynamic skill system
│   │   ├── model.py         # Skill data model
│   │   ├── registry.py      # Skill lifecycle
│   │   └── selector.py      # AI skill matching
│   │
│   ├── integrations/        # Third-party connectors
│   │   ├── discord.py
│   │   ├── telegram.py
│   │   ├── twitter.py
│   │   └── social.py        # LinkedIn, Medium
│   │
│   ├── automation/          # Workflows & playbooks
│   │   ├── automation.py
│   │   └── playbook_engine.py
│   │
│   ├── ai_models/           # AI model management
│   │   ├── manager.py       # Ollama/HF model lifecycle
│   │   └── rag.py           # ChromaDB + BM25 search
│   │
│   └── routers/             # FastAPI routers (split from gateway)
│       ├── chat.py          # /chat, /stream
│       ├── media.py         # /images, /audio, /video
│       ├── documents.py     # /documents, /presentations
│       ├── projects.py      # /projects
│       ├── admin.py         # /settings, /tokens, /models
│       └── tools.py         # /execute, /audit
│
├── agents/                  # Agent personas (Markdown)
├── templates/               # Jinja2 HTML templates
│
├── static/                  # Frontend assets (offline, no CDN)
│   ├── js/
│   │   ├── app.js           # Entry point (LEGACY — being split)
│   │   ├── core/            # API, state, router, theme, utils
│   │   ├── components/      # Reusable UI components
│   │   ├── studios/         # Page-level modules (chat, media, etc.)
│   │   ├── vendors/         # Bundled third-party libraries
│   │   └── workers/         # Web Workers for heavy tasks
│   └── css/
│       ├── style.css        # Main (LEGACY — being split)
│       ├── base/            # Variables, reset, typography
│       ├── components/      # Buttons, cards, modals, forms
│       ├── studios/         # Per-studio styles
│       ├── layout/          # Sidebar, header, grid
│       └── vendors/         # Library overrides
│
└── data/                    # Runtime data (gitignored)
    ├── media/               # Generated media (images, audio, video)
    ├── documents/           # Generated documents
    ├── presentations/       # Presentation data + exports
    ├── projects/            # Kanban project JSON
    ├── research/            # Research session outputs
    ├── sessions/            # Chat session data
    ├── skills/              # Custom skills
    └── ...                  # See CONVENTIONS.md for complete listing
```

## File Size Limits

> ⚠️ **Enforced by convention** — see [`CONVENTIONS.md`](CONVENTIONS.md) for details.

| File Type | Max Lines | Action if exceeded |
|-----------|-----------|-------------------|
| Python `.py` | **500** | Split into sub-modules |
| JavaScript `.js` | **500** | Extract into ES module |
| CSS `.css` | **300** | Create a `_partial.css` |
| JSON data | **1 MB** | Archive or paginate |

## Code Style

### Python

- **Python 3.11+** — use modern type hints (`str | None`, `list[dict]`, etc.)
- **Docstrings** — use Google-style docstrings for all public functions
- **Module docstring** — every `.py` file must start with a `"""..."""` docstring
- **Comments** — explain **why**, not **what**; write in English
- **Imports** — stdlib → third-party → local, separated by blank lines
- **Type hints** — use them on all function signatures
- **Error handling** — use `try/except` with specific exceptions; avoid bare `except`
- **Paths** — always use `config.py` constants (`DATA_DIR`, `WORKSPACE_DIR`, etc.)

### Naming Conventions

| Element | Convention | Example |
|---------|-----------|---------|
| Python packages | `snake_case`, singular | `app/tools/`, `app/core/` |
| Python modules | `snake_case.py` | `image.py`, `llm_provider.py` |
| Python classes | `PascalCase` | `LLMProvider`, `CodeAuditor` |
| Python functions | `snake_case` | `execute_tool()` |
| Constants | `UPPER_SNAKE` | `MAX_TOOL_ROUNDS` |
| API routes | `kebab-case` | `/api/generate-image` |
| JS files | `kebab-case.js` | `media-studio.js` |
| CSS partials | `_component.css` | `_buttons.css`, `_chat.css` |
| Generated files | `{type}_{YYYYMMDD}_{HHMMSS}_{hash6}.{ext}` | `gen_20260504_183000_a1b2c3.png` |

### Frontend

- **No external CDN** — all assets must be in `static/`
- **HTML** — Jinja2 templates in `templates/`
- **CSS** — Dark theme as default; use CSS custom properties
- **JS** — Vanilla JS or minimal libraries; no build step required

## Pull Request Process

### 1. Create a Feature Branch

```bash
git checkout -b feature/my-feature
# or
git checkout -b fix/bug-description
```

### 2. Make Your Changes

- Write tests if applicable
- Update documentation if your change affects the API
- Follow the code style guidelines above
- **Ensure no file exceeds the size limits** (see table above)

### 3. Test Your Changes

```bash
# Verify the app loads without errors
python -c "from app.gateway import app; print('OK')"

# Run the app and test manually
./run.sh
```

### 4. Commit and Push

```bash
git add .
git commit -m "feat: add new feature description"
# or: fix: | docs: | refactor: | perf: | test:
git push origin feature/my-feature
```

### 5. Open a Pull Request

- Provide a clear description of the changes
- Reference any related issues
- Include screenshots for UI changes
- List any new dependencies added

## Commit Message Format

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <description>

[optional body]
```

**Types:** `feat`, `fix`, `docs`, `refactor`, `perf`, `test`, `chore`

**Examples:**
```
feat(tools/audio): add voice cloning mode
fix(routers/chat): handle empty session ID
docs(readme): add HTTPS setup instructions
perf(core/cache): implement semantic response caching
refactor(tools/image): split into sub-modules
```

## Adding a New Tool

1. Create `app/tools/yourname.py` with a FastAPI `APIRouter`
2. Register the router in `app/gateway.py` (or `app/routers/tools.py`)
3. Add tool patterns to `app/skills/selector.py`
4. Add tool handling to `app/tools/executor.py`
5. Update `app/core/preprompts.py` if the tool needs LLM instructions
6. **Verify** file stays under 500 lines

## Adding a New LLM Provider

1. Create a new class in `app/core/llm_provider.py` inheriting from `LLMProvider`
2. Implement `chat_stream()` as an async generator
3. Add to `PROVIDER_CLASSES` dict
4. Add static model list to `PROVIDER_MODELS_STATIC`
5. Add API key to `config.py` and `.env.example`

## Adding a New Studio (Frontend)

1. Create `static/js/studios/your-studio.js` with the studio class
2. Create `static/css/studios/_your-studio.css` for dedicated styles
3. Import the studio module in `static/js/app.js`
4. Add the navigation entry in the sidebar template
5. **Verify** each file stays under the size limits

## Questions?

Open an issue or start a discussion in the repository.

