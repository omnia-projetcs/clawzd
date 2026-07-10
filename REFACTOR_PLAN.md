# Clawzd Refactor & Modernization Plan

Status after 2026-07-09 audit fixes + continued migration work.

**Recent progress:**
- `.github/copilot-instructions.md` fully updated.
- Dozens of legacy shim imports (`app.llm_provider`, `app.preprompts`, `app.database`, `app.rag`, `app.skill_*`, `app.tool_executor`, `app.model_manager`) migrated to `app.core.*` / `app.ai_models.*` / `app.skills.*`.
- Non-gateway files with old shim imports: 0.
- New extraction: health/metrics/token endpoints + notifications → `app/routers/system.py`
- gateway.py ~1960 lines (arena + chat extras + cron router migration; inline routes reduced)
- Additional chat router (routers/chat.py) for upload/humanize
- cron router migrated to app/routers/cron.py (tools_cron.py now only helpers)
- Legacy tool router imports in gateway reduced to 10 (reexports for docgen, twitter, spec, agent_dispatch, project, research, studio_editor, image, etc.)
- tools_image split ongoing (~3540 lines, _IMAGE_STYLES, _release_pipeline moved)
- _IMAGE_STYLES, _release_pipeline moved to image_utils
- Gateway 1937 lines, legacy imports 7-10


- Home page extracted to routers/home.py
- Gateway at 1961 lines, tests passing

- Home page extracted to routers/home.py
- More tools routers migrated (docgen, twitter, spec, agent_dispatch)

- Multiple legacy imports modernized via reexport routers
- Gateway down to 1960 lines, image split started, more routers migrated
- More tools routers migrated (presentation, automation, clone, agent, document, audio_lab, project, research, studio_editor)
- _IMAGE_STYLES moved to image_utils
- Legacy imports in gateway source: 10
- Continued progress on split and migration









- tools_image split ongoing (~3578 lines)
- Multiple legacy imports modernized via reexport routers
- Gateway down to 1960 lines, image split started, more routers migrated



- All tests passing
- UploadFile import cleaned from gateway
- Arena and chat extra extracted.

## Goals
- Finish migration from legacy flat `app/tools_*.py` + huge `gateway.py` to `app/{core,tools,routers,skills}/`
- Enforce CONVENTIONS.md (max 500 lines Python, 300 CSS, 500 JS)
- Improve test coverage and reliability

## Priority Splits (start here)

### 1. gateway.py (currently ~2390 lines after extractions + notifications move; down from 2516+)
- Already extracted: preview + export-zip → `app/routers/files.py`
- Health, /api/metrics, token-usage, tokenize/prefetch, notifications → `app/routers/system.py`
- tools_image.py split progressing (now ~3601 lines): moved GPU, models, classify, detect, clean, progress, should_use, HfProgressTqdm, hf_token, configured, media reason/build, svg/raster keywords to image_utils.py (reduced ~200 lines, media capabilities compatible with tests)
- Additional chat router (routers/chat.py) for upload/humanize
- arena and chat extra extracted, gateway ~1960 lines
- media tests fixed after split

- Next candidates:
  - All inline tool registration / legacy router wiring → move wiring to a `app/routers/legacy_tools.py` or keep for compat
  - Health, metrics, system dashboard endpoints → `app/routers/system.py`
  - SSE streaming logic + chat core (careful) → keep or enhance `app/chat.py`
- Target: < 800 lines for gateway (mostly includes + core app setup + middleware)

### 2. Big Tools (highest impact)
- `app/tools_image.py` (3800+ lines) → split:
  - `app/tools/image_generation.py` (core SD/FLUX pipeline)
  - `app/tools/image_utils.py` (prompt building, resolution, progress)
  - `app/tools/svg.py` or keep vector generation
  - Router endpoints stay thin
- `app/tools_presentation.py` (2900+) → 
  - `app/tools/presentation_builder.py`
  - `app/tools/pptx_export.py`
  - `app/tools/slide_renderer.py`
- `app/tools_research.py` (2900+) → already partially split into `app/tools/research_*.py` in modern tools/ — continue migrating call sites
- `app/tools/executor.py` (2200+) → split contracts + dispatch logic

### 3. Frontend
- `static/js/app.js` → finish migration to `static/js/studios/*.js` + `core/`
- `static/css/style.css` → extract remaining rules to `base/`, `components/`, `studios/`

### 4. Other
- `app/agent_core.py`, `app/agent_dispatch.py`, skill files: evaluate if they belong under `app/core/agents/` or stay
- Move remaining top-level `app/*.py` that are not shims into proper packages

## How to split safely
1. Create the target module with functions/classes.
2. In old file: `from .new_module import *` or explicit re-exports (temporary shim inside package).
3. Update **only** internal imports gradually.
4. Update gateway includes last.
5. Run full import test + basic endpoints after each split.
6. Delete old monolithic code only when all references are updated and tests pass.

## Current State (post-audit)
- Many foundational modules are now proper shims to `app/core/`
- 1 small successful extraction performed (files router)
- docs + naming + hygiene cleaned

## Verification after changes
```bash
python -c "from app.gateway import app; print('OK', len(app.routes))"
./run.sh  # in background or test specific endpoints
pytest tests/ -q --tb=line
```

Add new router:
```python
# in gateway
from app.routers.my_new import router as my_router
app.include_router(my_router, prefix="/my")
```

## Notes
- Keep backward compat shims during transition.
- Update CONVENTIONS.md + this file when progress made.
- Large media generation code may stay large due to multiple model backends.

Last updated: 2026-07-09
