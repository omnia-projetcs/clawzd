"""
Clawzd — Workspace File API router.

Extracted from gateway.py to reduce monolith size.
Handles file CRUD, search, upload, undo, context, and transfer operations.
"""
import asyncio
import os

from fastapi import APIRouter, Request, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse

from config import WORKSPACE_DIR

router = APIRouter()

_WORKSPACE_DIR = WORKSPACE_DIR


def _safe_workspace_path(rel_path: str) -> str:
    """Resolve a relative path inside the workspace, preventing traversal."""
    base = os.path.realpath(_WORKSPACE_DIR)
    full = os.path.realpath(os.path.join(base, rel_path))
    if not full.startswith(base):
        raise HTTPException(403, "Path traversal not allowed")
    return full


def _get_workspace_tree_sync(base: str) -> list:
    tree = []
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        rel_root = os.path.relpath(root, base)
        for f in sorted(files):
            if f.startswith('.') and f != '.gitkeep':
                continue
            rel_path = f if rel_root == '.' else os.path.join(rel_root, f)
            full_path = os.path.join(root, f)
            try:
                size = os.path.getsize(full_path)
            except OSError:
                size = 0
            tree.append({"path": rel_path, "size": size})
    return tree


@router.get("/tree")
async def workspace_tree():
    """List all files in the workspace directory recursively."""
    base = os.path.realpath(_WORKSPACE_DIR)
    os.makedirs(base, exist_ok=True)
    tree = await asyncio.to_thread(_get_workspace_tree_sync, base)
    return {"files": tree}


@router.get("/file")
async def workspace_read_file(path: str):
    """Read a file from the workspace."""
    full = _safe_workspace_path(path)
    if not os.path.isfile(full):
        raise HTTPException(404, "File not found")
    try:
        with open(full, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        return {"path": path, "content": content}
    except Exception as e:
        raise HTTPException(500, f"Read error: {e}")


@router.get("/file-raw")
async def workspace_read_file_raw(path: str):
    """Serve a workspace file as raw binary (for image preview, downloads, etc.)."""
    full = _safe_workspace_path(path)
    if not os.path.isfile(full):
        raise HTTPException(404, "File not found")
    import mimetypes
    mime, _ = mimetypes.guess_type(full)
    return FileResponse(full, media_type=mime or "application/octet-stream")


@router.post("/file")
async def workspace_write_file(request: Request):
    """Create or update a file in the workspace."""
    data = await request.json()
    path = data.get("path", "").strip()
    content = data.get("content", "")
    if not path:
        raise HTTPException(400, "Path is required")
    full = _safe_workspace_path(path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    try:
        with open(full, "w", encoding="utf-8") as f:
            f.write(content)
        return {"status": "ok", "path": path}
    except Exception as e:
        raise HTTPException(500, f"Write error: {e}")


@router.delete("/file")
async def workspace_delete_file(path: str):
    """Delete a file from the workspace."""
    full = _safe_workspace_path(path)
    if not os.path.isfile(full):
        raise HTTPException(404, "File not found")
    try:
        os.remove(full)
        parent = os.path.dirname(full)
        base = os.path.realpath(_WORKSPACE_DIR)
        while parent != base and not os.listdir(parent):
            os.rmdir(parent)
            parent = os.path.dirname(parent)
        return {"status": "ok", "path": path}
    except Exception as e:
        raise HTTPException(500, f"Delete error: {e}")


@router.delete("/dir")
async def workspace_delete_dir(path: str):
    """Recursively delete a directory from the workspace."""
    import shutil
    full = _safe_workspace_path(path)
    if not os.path.isdir(full):
        raise HTTPException(404, "Directory not found")
    base = os.path.realpath(_WORKSPACE_DIR)
    if os.path.realpath(full) == base:
        raise HTTPException(403, "Cannot delete workspace root")
    try:
        shutil.rmtree(full)
        return {"status": "ok", "path": path}
    except Exception as e:
        raise HTTPException(500, f"Delete error: {e}")


@router.post("/undo")
async def workspace_undo(request: Request):
    """Undo the last file edit (or a specific file's last edit)."""
    from app.tools_code import snapshot_manager
    data = await request.json()
    file_path = data.get("file_path", "")
    if file_path:
        return snapshot_manager.undo(file_path)
    return snapshot_manager.undo_last()


@router.post("/rename")
async def workspace_rename_file(request: Request):
    """Rename or move a file or directory within the workspace."""
    data = await request.json()
    old_path = data.get("old_path", "").strip()
    new_path = data.get("new_path", "").strip()
    if not old_path or not new_path:
        raise HTTPException(400, "old_path and new_path are required")
    old_full = _safe_workspace_path(old_path)
    new_full = _safe_workspace_path(new_path)
    if not os.path.exists(old_full):
        raise HTTPException(404, "Source not found")
    os.makedirs(os.path.dirname(new_full), exist_ok=True)
    try:
        os.rename(old_full, new_full)
        return {"status": "ok", "old_path": old_path, "new_path": new_path}
    except Exception as e:
        raise HTTPException(500, f"Rename error: {e}")


@router.get("/context")
async def workspace_get_context():
    """Read the clawzd.md project context file."""
    ctx_path = os.path.join(os.path.realpath(_WORKSPACE_DIR), "clawzd.md")
    if os.path.isfile(ctx_path):
        with open(ctx_path, "r", encoding="utf-8") as f:
            return {"content": f.read(), "exists": True}
    return {"content": "", "exists": False}


@router.post("/context")
async def workspace_save_context(request: Request):
    """Save the clawzd.md project context file."""
    data = await request.json()
    content = data.get("content", "")
    ctx_path = os.path.join(os.path.realpath(_WORKSPACE_DIR), "clawzd.md")
    os.makedirs(os.path.dirname(ctx_path), exist_ok=True)
    with open(ctx_path, "w", encoding="utf-8") as f:
        f.write(content)
    return {"status": "ok"}


@router.get("/search")
async def workspace_search(q: str):
    """Search for text across all workspace files."""
    base = os.path.realpath(_WORKSPACE_DIR)
    if not q or not q.strip():
        return {"results": [], "query": q}
    results = []
    query = q.strip().lower()
    _skip_ext = {'png','jpg','jpeg','gif','webp','ico','woff','woff2','ttf','eot',
                 'zip','gz','tar','pdf','pyc','so','o'}
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for fname in sorted(files):
            if fname.startswith('.'):
                continue
            ext = fname.rsplit('.', 1)[-1].lower() if '.' in fname else ''
            if ext in _skip_ext:
                continue
            full = os.path.join(root, fname)
            rel = os.path.relpath(full, base)
            try:
                with open(full, "r", encoding="utf-8", errors="ignore") as f:
                    for line_num, line in enumerate(f, 1):
                        if query in line.lower():
                            results.append({"path": rel, "line": line_num, "text": line.rstrip()[:200]})
                            if len(results) >= 100:
                                return {"results": results, "query": q, "truncated": True}
            except Exception:
                continue
    return {"results": results, "query": q, "truncated": False}


@router.post("/upload")
async def workspace_upload(file: UploadFile = File(...), path: str = Form("")):
    """Upload a file to the workspace."""
    base = os.path.realpath(_WORKSPACE_DIR)
    target_path = path.strip() if path.strip() else file.filename
    full = os.path.realpath(os.path.join(base, target_path))
    if not full.startswith(base):
        raise HTTPException(403, "Path traversal not allowed")
    os.makedirs(os.path.dirname(full), exist_ok=True)
    content = await file.read()
    with open(full, "wb") as f:
        f.write(content)
    return {"status": "ok", "path": target_path, "size": len(content)}


@router.post("/transfer")
async def workspace_transfer(request: Request):
    """Transfer project files from the chat file tree to the workspace."""
    data = await request.json()
    project = data.get("project", "").strip()
    files = data.get("files", [])
    if not project:
        raise HTTPException(400, "Project name is required")
    if not files:
        raise HTTPException(400, "No files to transfer")
    project = project.replace("..", "").replace("/", "_").replace("\\", "_").strip(". ")
    if not project:
        raise HTTPException(400, "Invalid project name")
    base = os.path.realpath(_WORKSPACE_DIR)
    project_dir = os.path.join(base, project)
    written = 0
    errors = []
    for f in files:
        fpath = f.get("path", "").strip()
        fcontent = f.get("content", "")
        if not fpath:
            continue
        if fcontent.startswith("[Generated image:") or fcontent.startswith("[Generated SVG:"):
            continue
        full = os.path.realpath(os.path.join(project_dir, fpath))
        if not full.startswith(os.path.realpath(project_dir)):
            errors.append(f"Skipped (traversal): {fpath}")
            continue
        try:
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", encoding="utf-8") as fh:
                fh.write(fcontent)
            written += 1
        except Exception as e:
            errors.append(f"{fpath}: {e}")
    return {"status": "ok", "project": project, "written": written, "errors": errors}
