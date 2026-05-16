"""
Clawzd — App Builder (OpenClaw OS-inspired).

Allows the LLM to generate complete mini web applications (HTML + CSS + JS)
and serve them as live previews. The user can say "build me a calculator"
and get a working, previewable app.

Storage: data/apps/{app_id}/
Serving: /apps/{app_id}/ (static files)
Preview: /apps/{app_id}/preview → iframe-friendly page

Features:
- Single-file or multi-file app generation
- Live preview via iframe
- Versioning (overwrite or create new version)
- Template starter kits
"""
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from config import DATA_DIR

logger = logging.getLogger("clawzd.app_builder")

APPS_DIR = os.path.join(DATA_DIR, "apps")


# ---------------------------------------------------------------------------
# App Templates (starter kits)
# ---------------------------------------------------------------------------

STARTER_TEMPLATES = {
    "blank": {
        "name": "Blank App",
        "description": "Empty canvas with modern dark theme",
        "files": {
            "index.html": """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>My App</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <div id="app">
    <h1>Hello World</h1>
  </div>
  <script src="app.js"></script>
</body>
</html>""",
            "style.css": """* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  font-family: 'Inter', system-ui, sans-serif;
  background: #0f172a;
  color: #e2e8f0;
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
}
#app { text-align: center; }
h1 { font-size: 2rem; background: linear-gradient(135deg, #6366f1, #ec4899); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
""",
            "app.js": "// Your app logic here\nconsole.log('App loaded');\n",
        },
    },
    "dashboard": {
        "name": "Dashboard",
        "description": "Data dashboard with cards layout",
        "files": {
            "index.html": """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Dashboard</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <div class="dashboard">
    <header class="dash-header"><h1>📊 Dashboard</h1></header>
    <div class="cards" id="cards"></div>
  </div>
  <script src="app.js"></script>
</body>
</html>""",
            "style.css": """* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: 'Inter', system-ui, sans-serif; background: #0f172a; color: #e2e8f0; }
.dashboard { max-width: 1200px; margin: 0 auto; padding: 24px; }
.dash-header { margin-bottom: 24px; }
.dash-header h1 { font-size: 24px; }
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; }
.card { background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 20px; }
.card-title { font-size: 14px; color: #94a3b8; margin-bottom: 8px; }
.card-value { font-size: 32px; font-weight: 700; }
.card-change { font-size: 12px; margin-top: 4px; }
.card-change.up { color: #10b981; }
.card-change.down { color: #ef4444; }
""",
            "app.js": """const data = [
  { title: 'Revenue', value: '$12,450', change: '+12.5%', direction: 'up' },
  { title: 'Users', value: '1,234', change: '+8.2%', direction: 'up' },
  { title: 'Bounce Rate', value: '24.5%', change: '-3.1%', direction: 'down' },
  { title: 'Sessions', value: '5,678', change: '+15.7%', direction: 'up' },
];
const container = document.getElementById('cards');
data.forEach(d => {
  container.innerHTML += `<div class="card">
    <div class="card-title">${d.title}</div>
    <div class="card-value">${d.value}</div>
    <div class="card-change ${d.direction}">${d.change}</div>
  </div>`;
});
""",
        },
    },
}


# ---------------------------------------------------------------------------
# CRUD Operations
# ---------------------------------------------------------------------------

def create_app(
    name: str,
    files: dict[str, str],
    session_id: Optional[str] = None,
    template: Optional[str] = None,
    icon: Optional[str] = None,
    visual: Optional[str] = None,
) -> dict:
    """Create a new mini-app.

    Args:
        name: Display name for the app.
        files: Dict of filename → content (e.g. {"index.html": "...", "app.js": "..."}).
        session_id: Optional chat session that created this app.
        template: Optional starter template key to use as base.
        icon: Optional icon for the app.
        visual: Optional visual/cover for the app.

    Returns:
        App metadata dict with id, url, etc.
    """
    app_id = f"app-{uuid.uuid4().hex[:10]}"
    app_dir = os.path.join(APPS_DIR, app_id)
    os.makedirs(app_dir, exist_ok=True)

    # Start from template if specified
    if template and template in STARTER_TEMPLATES:
        base_files = dict(STARTER_TEMPLATES[template]["files"])
        base_files.update(files)  # User files override template
        files = base_files

    # Ensure at least an index.html exists
    if "index.html" not in files:
        files["index.html"] = "<h1>App</h1>"

    # Write all files (preserve subdirectory structure)
    for filename, content in files.items():
        safe_name = _sanitize_rel_path(filename)
        if safe_name is None:
            continue
        filepath = os.path.join(app_dir, safe_name)
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)

    # Save metadata
    meta = {
        "id": app_id,
        "name": name,
        "icon": icon,
        "visual": visual,
        "files": list(files.keys()),
        "session_id": session_id,
        "version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "preview_url": f"/apps/{app_id}/index.html",
    }

    meta_path = os.path.join(app_dir, "_meta.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)

    logger.info("Created app: %s (%s, %d files)", name, app_id, len(files))
    return meta


def get_app(app_id: str) -> Optional[dict]:
    """Get app metadata by ID."""
    meta_path = os.path.join(APPS_DIR, app_id, "_meta.json")
    if not os.path.exists(meta_path):
        return None

    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def list_apps(limit: int = 20) -> list[dict]:
    """List all created apps."""
    if not os.path.isdir(APPS_DIR):
        return []

    apps = []
    for dirname in os.listdir(APPS_DIR):
        if not dirname.startswith("app-"):
            continue
        meta = get_app(dirname)
        if meta:
            apps.append(meta)

    # Sort by updated_at descending (newest first)
    apps.sort(key=lambda a: a.get("updated_at", ""), reverse=True)
    return apps[:limit]


def update_app(
    app_id: str, 
    files: Optional[dict[str, str]] = None, 
    name: Optional[str] = None,
    icon: Optional[str] = None,
    visual: Optional[str] = None,
) -> Optional[dict]:
    """Update an existing app's files or metadata."""
    app_dir = os.path.join(APPS_DIR, app_id)
    meta_path = os.path.join(app_dir, "_meta.json")

    if not os.path.exists(meta_path):
        return None

    # Update files (preserve subdirectory structure)
    if files:
        for filename, content in files.items():
            safe_name = _sanitize_rel_path(filename)
            if safe_name is None:
                continue
            filepath = os.path.join(app_dir, safe_name)
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)

    # Update metadata
    meta = get_app(app_id)
    if meta:
        if files:
            existing_files = set(meta.get("files", []))
            existing_files.update(files.keys())
            meta["files"] = sorted(existing_files)
            
        if name is not None:
            meta["name"] = name
        if icon is not None:
            meta["icon"] = icon
        if visual is not None:
            meta["visual"] = visual
            
        if files:
            meta["version"] = meta.get("version", 1) + 1
        meta["updated_at"] = datetime.now(timezone.utc).isoformat()

        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)

    return meta


def delete_app(app_id: str) -> bool:
    """Delete an app and all its files."""
    import shutil
    app_dir = os.path.join(APPS_DIR, app_id)
    if not os.path.isdir(app_dir):
        return False

    shutil.rmtree(app_dir)
    logger.info("Deleted app: %s", app_id)
    return True


def get_app_file(app_id: str, filename: str) -> Optional[str]:
    """Get a specific file content from an app."""
    safe_name = _sanitize_rel_path(filename)
    if safe_name is None:
        return None
    filepath = os.path.realpath(os.path.join(APPS_DIR, app_id, safe_name))
    app_root = os.path.realpath(os.path.join(APPS_DIR, app_id))
    if not filepath.startswith(app_root):
        return None
    if not os.path.exists(filepath):
        return None
    with open(filepath, "r", encoding="utf-8") as f:
        return f.read()


def delete_app_file(app_id: str, filename: str) -> bool:
    """Delete a specific file from an app and update metadata."""
    safe_name = os.path.basename(filename)
    filepath = os.path.join(APPS_DIR, app_id, safe_name)
    if not os.path.exists(filepath):
        return False

    os.remove(filepath)

    # Update metadata
    meta = get_app(app_id)
    if meta:
        file_list = meta.get("files", [])
        if safe_name in file_list:
            file_list.remove(safe_name)
        if filename in file_list:
            file_list.remove(filename)
        meta["files"] = file_list
        meta["updated_at"] = datetime.now(timezone.utc).isoformat()
        meta_path = os.path.join(APPS_DIR, app_id, "_meta.json")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)

    logger.info("Deleted file %s from app %s", safe_name, app_id)
    return True


# ---------------------------------------------------------------------------
# Path Sanitization
# ---------------------------------------------------------------------------

def _sanitize_rel_path(filename: str) -> Optional[str]:
    """Sanitize a relative file path, blocking traversal.

    Returns the cleaned path or None if dangerous.
    """
    # Normalize separators
    cleaned = filename.replace("\\", "/")
    # Remove leading slashes
    cleaned = cleaned.lstrip("/")
    # Block path traversal
    if ".." in cleaned.split("/"):
        return None
    # Block internal metadata files
    basename = os.path.basename(cleaned)
    if basename.startswith("_") and basename.endswith(".json"):
        return None
    if basename in ("app.db",):
        return None
    return cleaned if cleaned else None


# ---------------------------------------------------------------------------
# Import from Workspace
# ---------------------------------------------------------------------------

# Extensions considered binary (skip during import)
_BINARY_EXTS = {
    "png", "jpg", "jpeg", "gif", "bmp", "ico", "webp", "svg",
    "mp4", "webm", "mp3", "wav", "ogg", "flac",
    "pdf", "zip", "tar", "gz", "7z", "rar",
    "woff", "woff2", "ttf", "otf", "eot",
    "exe", "dll", "so", "dylib",
    "pyc", "pyo", "class", "o", "obj",
}

# Directories always skipped during import
_SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    ".mypy_cache", ".pytest_cache", ".tox", "dist", "build",
    ".eggs", ".idea", ".vscode",
}

# Max file size for text import (2 MB)
_MAX_IMPORT_FILE_SIZE = 2 * 1024 * 1024


def import_from_workspace(
    project_path: str,
    name: str,
    workspace_dir: str = "./workspace",
    session_id: Optional[str] = None,
    icon: Optional[str] = None,
) -> dict:
    """Import a workspace project folder as a mini-app.

    Recursively reads all text files from the project directory,
    preserving the folder structure, and creates an app.

    Args:
        project_path: Relative path inside the workspace (e.g. 'myproject').
        name: Display name for the created app.
        workspace_dir: Absolute or relative path to the workspace root.
        session_id: Optional chat session ID.
        icon: Optional icon emoji/string.

    Returns:
        App metadata dict.

    Raises:
        FileNotFoundError: If the project directory doesn't exist.
        ValueError: If no importable files found.
    """
    ws_base = os.path.realpath(workspace_dir)
    # Sanitize project path
    clean_project = project_path.replace("..", "").strip("/")
    target_dir = os.path.realpath(os.path.join(ws_base, clean_project))

    # Security: must stay inside workspace
    if not target_dir.startswith(ws_base):
        raise ValueError("Project path escapes workspace boundary")

    if not os.path.isdir(target_dir):
        raise FileNotFoundError(f"Project directory not found: {clean_project}")

    files: dict[str, str] = {}
    skipped = 0

    for root, dirs, filenames in os.walk(target_dir):
        # Skip hidden and known non-source directories
        dirs[:] = [
            d for d in dirs
            if not d.startswith(".") and d not in _SKIP_DIRS
        ]

        for fname in sorted(filenames):
            # Skip hidden files
            if fname.startswith("."):
                continue

            # Skip binary extensions
            ext = fname.rsplit(".", 1)[-1].lower() if "." in fname else ""
            if ext in _BINARY_EXTS:
                skipped += 1
                continue

            full_path = os.path.join(root, fname)

            # Skip files that are too large
            try:
                if os.path.getsize(full_path) > _MAX_IMPORT_FILE_SIZE:
                    skipped += 1
                    continue
            except OSError:
                continue

            # Compute relative path from project root
            rel_path = os.path.relpath(full_path, target_dir)

            # Read as text
            try:
                with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                files[rel_path] = content
            except (IOError, UnicodeDecodeError):
                skipped += 1
                continue

    if not files:
        raise ValueError(
            f"No importable files found in '{clean_project}' "
            f"(skipped {skipped} binary/large files)"
        )

    logger.info(
        "Importing workspace project '%s': %d files (%d skipped)",
        clean_project, len(files), skipped,
    )

    return create_app(
        name=name,
        files=files,
        session_id=session_id,
        icon=icon or "📦",
    )
