# 📐 Clawzd — Development Conventions

> **This file is the single source of truth** for all structure, naming, and file creation rules.  
> It must be read by every human developer **and** every AI assistant before modifying the project.

---

## 1. File Size Limits

| File Type | Max Lines | Action if Exceeded |
|-----------|-----------|-------------------|
| Python `.py` | **500 lines** | Split into sub-modules within the package |
| JavaScript `.js` | **500 lines** | Extract into a separate ES module |
| CSS `.css` | **300 lines** | Create a partial `_component.css` file |
| JSON (data) | **1 MB** | Archive or paginate |

> If a file exceeds these limits, it **must** be refactored before adding more code.

---

## 2. Where to Create Files

### Backend (Python)

| Type | Location |
|------|----------|
| Core infrastructure (cache, DB, LLM) | `app/core/{module}.py` |
| AI tools (image, audio, code, etc.) | `app/tools/{module}.py` |
| Skills engine | `app/skills/{module}.py` |
| External integrations (Discord, Twitter) | `app/integrations/{service}.py` |
| Automation, workflows, playbooks | `app/automation/{module}.py` |
| AI model management | `app/ai_models/{module}.py` |
| FastAPI routers | `app/routers/{domain}.py` |
| Agent personas | `agents/{role}.md` |
| Utility scripts | `scripts/{name}.py` |

### Frontend

| Type | Location |
|------|----------|
| JS infrastructure (API, state, router) | `static/js/core/{module}.js` |
| Reusable UI components | `static/js/components/{module}.js` |
| Pages / Studios | `static/js/studios/{module}.js` |
| Bundled third-party libraries | `static/js/vendors/{lib}.js` |
| Web Workers | `static/js/workers/{module}.js` |
| CSS variables, reset, typography | `static/css/base/_{module}.css` |
| CSS components | `static/css/components/_{module}.css` |
| Per-studio styles | `static/css/studios/_{module}.css` |
| Layout (sidebar, header, grid) | `static/css/layout/_{module}.css` |

### Data (Generated Files)

| Type | Location |
|------|----------|
| Generated images | `data/media/images/` |
| Generated audio | `data/media/audio/` |
| Generated video | `data/media/video/` |
| User uploads | `data/media/uploads/` |
| Thumbnails | `data/media/thumbnails/` |
| Documents (DOCX, PDF, XLSX, MD) | `data/documents/` |
| Presentations (JSON + exports) | `data/presentations/` |
| Kanban projects | `data/projects/` |
| Temporary exports | `data/exports/` |
| Research output | `data/research/` |
| Chat sessions | `data/sessions/` |
| Audit reports | `data/audit_reports/` |

---

## 3. Forbidden Actions

- ❌ **Never add code** directly to these legacy monolithic files:
  - `static/js/app.js` → use `static/js/studios/` or `static/js/components/`
  - `app/gateway.py` → create a router in `app/routers/`
  - `static/css/style.css` → create a partial in `static/css/{category}/`

- ❌ **Never hardcode** file paths → use `config.py` constants:
  - `DATA_DIR`, `WORKSPACE_DIR`, `STATIC_DIR`, `MODELS_DIR`, etc.

- ❌ **Never store** temporary files in the repo → use `tempfile.TemporaryDirectory()`

- ❌ **Never create** a Python module without a docstring header

- ❌ **Never create** files at the root of `app/` → use the appropriate sub-package

---

## 4. Naming Conventions

| Element | Convention | Example |
|---------|-----------|---------|
| Python package | `snake_case`, singular | `app/tools/`, `app/core/` |
| Python module | `snake_case.py` | `image.py`, `llm_provider.py` |
| Python class | `PascalCase` | `MediaStudio`, `CodeAuditor` |
| Python function | `snake_case` | `execute_tool()` |
| Constant | `UPPER_SNAKE` | `MAX_TOOL_ROUNDS` |
| API route | `kebab-case` | `/api/generate-image` |
| JS file | `kebab-case.js` | `media-studio.js` |
| CSS partial | `_component.css` | `_buttons.css`, `_chat.css` |
| Generated file | `{type}_{YYYYMMDD}_{HHMMSS}_{hash6}.{ext}` | `gen_20260504_183000_a1b2c3.png` |
| Project / Presentation ID | Truncated UUID (8 chars) | `41042d80` |

---

## 5. Pre-Commit Checklist

- [ ] File is under 500 lines (Python/JS) or 300 lines (CSS)?
- [ ] Module docstring present at the top of every `.py` file?
- [ ] `__init__.py` exports updated?
- [ ] No hardcoded paths (using `config.py` constants)?
- [ ] `.gitignore` updated if new data type was introduced?
- [ ] Naming follows conventions above?
- [ ] Router registered in `gateway.py` or `main.py`?

---

## 6. Generated File Naming Patterns

| Type | Pattern | Example |
|------|---------|---------|
| Images | `gen_YYYYMMDD_HHMMSS_{hash6}.png` | `gen_20260504_183000_a1b2c3.png` |
| Audio | `audio_YYYYMMDD_HHMMSS_{hash6}.mp3` | `audio_20260504_183000_d4e5f6.mp3` |
| Documents | `doc_YYYYMMDD_HHMMSS_{hash6}.{ext}` | `doc_20260504_183000_g7h8i9.pdf` |
| Presentations (data) | `{uuid8}.json` | `41042d80.json` |
| Presentations (export) | `presentation_YYYYMMDD_HHMMSS_{hash6}.pptx` | — |
| Uploads | `upload_YYYYMMDD_HHMMSS_{hash6}.{ext}` | `upload_20260504_183000_j1k2l3.png` |
| Thumbnails | `thumb_{hash8}.png` | `thumb_a1b2c3d4.png` |
| Screenshots | `screenshot_YYYYMMDD_HHMMSS.png` | — |
| Audit reports | `{report_id}.html` + `{report_id}.json` | — |

---

## 7. Legacy Files — Migration Status

> ⚠️ These files are historical monoliths. **Do not add code to them.**  
> They will be progressively split into the structure described above.

### Backend

| File | Lines | Migration Target |
|------|-------|-----------------|
| `app/gateway.py` | 2,443 | `app/routers/*.py` |
| `app/tools_image.py` | 2,057 | `app/tools/image.py` (split) |
| `app/tools_presentation.py` | 1,810 | `app/tools/presentation.py` (split) |
| `app/tools_code.py` | 1,345 | `app/tools/code.py` (split) |
| `app/tools_automation.py` | 1,227 | `app/automation/automation.py` (split) |
| `app/tool_executor.py` | 1,074 | `app/tools/executor.py` (split) |

### Frontend

| File | Size | Migration Target |
|------|------|-----------------|
| `static/js/app.js` | 560 KB (~14,000 lines) | `static/js/studios/*.js` |
| `static/css/style.css` | 197 KB | `static/css/{category}/_*.css` |