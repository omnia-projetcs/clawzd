"""
Clawzd — Files / Export / Preview router.
Extracted from the legacy monolithic gateway.py to improve maintainability.
Contains workspace preview and ZIP export endpoints.
"""
import io
import os as _os
import zipfile
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

from config import WORKSPACE_DIR as _WORKSPACE_DIR

router = APIRouter(tags=["files"])


@router.get("/preview/{path:path}")
async def workspace_preview_file(path: str):
    """Serve a workspace file for web preview (allows relative CSS/JS paths)."""
    base = _os.path.realpath(_WORKSPACE_DIR)
    full = _os.path.realpath(_os.path.join(base, path))
    if not full.startswith(base):
        raise HTTPException(403, "Path traversal not allowed")
    if not _os.path.isfile(full):
        raise HTTPException(404, "File not found")
    import mimetypes
    mime, _ = mimetypes.guess_type(full)
    headers = {
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0"
    }
    return FileResponse(full, media_type=mime or "application/octet-stream", headers=headers)


@router.post("/api/export-zip")
async def api_export_zip(request: Request):
    """Bundle files into a downloadable ZIP archive."""
    data = await request.json()
    files = data.get("files", [])
    if not files:
        raise HTTPException(400, "No files to export")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.writestr(f["path"], f["content"])
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=clawzd_project.zip"},
    )
