"""
Clawzd — App Builder API router.

Extracted from gateway.py. Handles CRUD, templates, file management,
secrets, database, ZIP export, and static file serving for mini-apps.
"""
import io
import os
import logging
import zipfile

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import FileResponse, StreamingResponse, PlainTextResponse

logger = logging.getLogger("clawzd.apps_api")
router = APIRouter()


@router.post("")
async def create_app_endpoint(request: Request):
    from app.core.app_builder import create_app
    data = await request.json()
    name = data.get("name", "Untitled App")
    files = data.get("files", {})
    session_id = data.get("session_id")
    template = data.get("template")
    icon = data.get("icon")
    visual = data.get("visual")
    if not files and not template:
        raise HTTPException(400, "Provide 'files' or 'template'")
    return create_app(name, files, session_id=session_id, template=template, icon=icon, visual=visual)


@router.get("")
async def list_apps_endpoint(limit: int = 20):
    from app.core.app_builder import list_apps
    return list_apps(limit=limit)


@router.post("/import-from-workspace")
async def import_app_from_workspace(request: Request):
    from app.core.app_builder import import_from_workspace
    data = await request.json()
    project = data.get("project", "").strip()
    name = data.get("name", "").strip()
    session_id = data.get("session_id")
    icon = data.get("icon")
    if not project:
        raise HTTPException(400, "'project' is required")
    if not name:
        name = project.split("/")[-1] or project
    try:
        from config import WORKSPACE_DIR
        return import_from_workspace(project_path=project, name=name, workspace_dir=WORKSPACE_DIR, session_id=session_id, icon=icon)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/templates")
async def list_templates():
    from app.core.app_builder import STARTER_TEMPLATES
    return {k: {"name": v["name"], "description": v["description"]} for k, v in STARTER_TEMPLATES.items()}


@router.get("/{app_id}/meta")
async def get_app_meta(app_id: str):
    from app.core.app_builder import get_app
    meta = get_app(app_id)
    if not meta:
        raise HTTPException(404, "App not found")
    return meta


@router.put("/{app_id}")
async def update_app_endpoint(app_id: str, request: Request):
    from app.core.app_builder import update_app
    data = await request.json()
    result = update_app(app_id, files=data.get("files"), name=data.get("name"), icon=data.get("icon"), visual=data.get("visual"))
    if not result:
        raise HTTPException(404, "App not found")
    return result


@router.delete("/{app_id}")
async def delete_app_endpoint(app_id: str):
    from app.core.app_builder import delete_app
    deleted = delete_app(app_id)
    if not deleted:
        raise HTTPException(404, "App not found")
    return {"status": "deleted", "id": app_id}


@router.get("/{app_id}/preview")
async def preview_app(app_id: str):
    from app.core.app_builder import APPS_DIR
    filepath = os.path.join(APPS_DIR, app_id, "index.html")
    if not os.path.exists(filepath):
        raise HTTPException(404, "App not found or has no index.html")
    return FileResponse(filepath, media_type="text/html")


@router.get("/{app_id}/files")
async def get_app_files(app_id: str):
    from app.core.app_builder import get_app, get_app_file
    meta = get_app(app_id)
    if not meta:
        raise HTTPException(404, "App not found")
    files = {}
    for fname in meta.get("files", []):
        content = get_app_file(app_id, fname)
        if content is not None:
            files[fname] = content
    return {"id": app_id, "name": meta.get("name", ""), "files": files}


@router.delete("/{app_id}/files/{filename}")
async def delete_app_file_endpoint(app_id: str, filename: str):
    from app.core.app_builder import delete_app_file
    deleted = delete_app_file(app_id, filename)
    if not deleted:
        raise HTTPException(404, "File not found")
    return {"status": "deleted", "app_id": app_id, "filename": filename}


# --- App Secrets ---

@router.get("/{app_id}/secrets")
async def list_app_secrets(app_id: str):
    from app.core.app_services import get_secrets
    return {"app_id": app_id, "secrets": get_secrets(app_id)}


@router.post("/{app_id}/secrets")
async def set_app_secret(app_id: str, request: Request):
    from app.core.app_services import set_secret
    data = await request.json()
    key = data.get("key", "").strip()
    value = data.get("value", "")
    if not key:
        raise HTTPException(400, "Secret key is required")
    return set_secret(app_id, key, value)


@router.delete("/{app_id}/secrets/{key}")
async def delete_app_secret(app_id: str, key: str):
    from app.core.app_services import delete_secret
    if not delete_secret(app_id, key):
        raise HTTPException(404, "Secret not found")
    return {"status": "deleted", "key": key}


@router.get("/{app_id}/api/secrets/{key}")
async def get_app_secret_runtime(app_id: str, key: str):
    from app.core.app_services import get_secret_value
    value = get_secret_value(app_id, key)
    if value is None:
        raise HTTPException(404, "Secret not found")
    return PlainTextResponse(value)


# --- App Database ---

@router.get("/{app_id}/api/db/tables")
async def list_app_db_tables(app_id: str):
    from app.core.app_services import list_tables
    return {"app_id": app_id, "tables": list_tables(app_id)}


@router.post("/{app_id}/api/db/query")
async def app_db_query(app_id: str, request: Request):
    from app.core.app_services import execute_query
    data = await request.json()
    sql = data.get("sql", "").strip()
    params = data.get("params", [])
    if not sql:
        raise HTTPException(400, "SQL query is required")
    result = execute_query(app_id, sql, params)
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.get("/{app_id}/api/db/tables/{table}/schema")
async def app_db_table_schema(app_id: str, table: str):
    from app.core.app_services import get_table_schema
    return {"table": table, "columns": get_table_schema(app_id, table)}


# --- App ZIP Export ---

@router.get("/{app_id}/export")
async def export_app_zip(app_id: str):
    from app.core.app_builder import get_app, APPS_DIR
    from app.core.app_services import INTERNAL_FILES
    meta = get_app(app_id)
    if not meta:
        raise HTTPException(404, "App not found")
    app_dir = os.path.join(APPS_DIR, app_id)
    buf = io.BytesIO()
    app_name = meta.get("name", app_id).replace(" ", "_")
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname in os.listdir(app_dir):
            if fname in INTERNAL_FILES:
                continue
            fpath = os.path.join(app_dir, fname)
            if os.path.isfile(fpath):
                zf.write(fpath, f"{app_name}/{fname}")
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{app_name}.zip"'})


@router.post("/{app_id}/export-to-workspace")
async def export_app_to_workspace(app_id: str, request: Request):
    from app.core.app_builder import get_app, APPS_DIR
    from app.core.app_services import INTERNAL_FILES
    meta = get_app(app_id)
    if not meta:
        raise HTTPException(404, "App not found")
    data = await request.json()
    project_name = data.get("project", "").strip()
    if not project_name:
        project_name = (meta.get("name") or app_id).replace(" ", "_").replace("..", "").replace("/", "_").replace("\\", "_").strip("._")
    from config import WORKSPACE_DIR
    ws_base = os.path.realpath(WORKSPACE_DIR)
    project_dir = os.path.realpath(os.path.join(ws_base, project_name))
    if not project_dir.startswith(ws_base):
        raise HTTPException(403, "Invalid project path")
    app_dir = os.path.join(APPS_DIR, app_id)
    written = 0
    errors = []
    for root, dirs, files in os.walk(app_dir):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for fname in sorted(files):
            if fname in INTERNAL_FILES or fname.startswith('.'):
                continue
            src = os.path.join(root, fname)
            rel = os.path.relpath(src, app_dir)
            dst = os.path.join(project_dir, rel)
            try:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                with open(src, "rb") as fsrc, open(dst, "wb") as fdst:
                    fdst.write(fsrc.read())
                written += 1
            except Exception as e:
                errors.append(f"{rel}: {e}")
    return {"status": "ok", "project": project_name, "app_id": app_id, "written": written, "errors": errors}


@router.get("/{app_id}/{filename:path}")
async def serve_app_file(app_id: str, filename: str):
    """Serve a file from a mini-app (blocks internal files, supports subdirs)."""
    from app.core.app_builder import APPS_DIR
    from app.core.app_services import INTERNAL_FILES
    base = os.path.basename(filename)
    if base in INTERNAL_FILES:
        raise HTTPException(403, "Access denied")
    clean = filename.replace("..", "").lstrip("/")
    filepath = os.path.realpath(os.path.join(APPS_DIR, app_id, clean))
    app_root = os.path.realpath(os.path.join(APPS_DIR, app_id))
    if not filepath.startswith(app_root):
        raise HTTPException(403, "Path traversal not allowed")
    if not os.path.exists(filepath):
        raise HTTPException(404, "File not found")
    return FileResponse(filepath)
