"""
Clawzd — Artifacts, Plugins, Uploads, Replays, UI, Dashboard router.

Extracted from gateway.py to reduce monolith size.
"""
import logging
from fastapi import APIRouter, Request, HTTPException

logger = logging.getLogger("clawzd.artifacts_api")
router = APIRouter()


# --- Persistent Artifacts API ---

@router.get("/artifacts")
async def list_artifacts_endpoint(session_id: str = "", kind: str = "", pinned: bool = False, limit: int = 50):
    from app.core.artifacts import list_artifacts
    return list_artifacts(session_id=session_id or None, kind=kind or None, pinned_only=pinned, limit=limit)


@router.get("/artifacts/{artifact_id}")
async def get_artifact_endpoint(artifact_id: str):
    from app.core.artifacts import get_artifact
    artifact = get_artifact(artifact_id)
    if not artifact:
        raise HTTPException(404, "Artifact not found")
    return artifact


@router.post("/artifacts")
async def create_artifact_endpoint(request: Request):
    from app.core.artifacts import create_artifact
    data = await request.json()
    return create_artifact(title=data.get("title", "Untitled"), content=data.get("content", ""), session_id=data.get("session_id"), language=data.get("language", ""), kind=data.get("kind", "code"), parent_id=data.get("parent_id"))


@router.put("/artifacts/{artifact_id}")
async def update_artifact_endpoint(artifact_id: str, request: Request):
    from app.core.artifacts import update_artifact, get_artifact, create_artifact
    data = await request.json()
    if data.get("version") and "content" in data:
        parent = get_artifact(artifact_id)
        if not parent:
            raise HTTPException(404, "Artifact not found")
        return create_artifact(title=data.get("title", parent["title"]), content=data["content"], session_id=parent.get("session_id"), language=data.get("language", parent.get("language", "")), kind=parent.get("kind", "code"), parent_id=artifact_id)
    result = update_artifact(artifact_id, title=data.get("title"), content=data.get("content"), pinned=data.get("pinned"))
    if not result:
        raise HTTPException(404, "Artifact not found")
    return result


@router.delete("/artifacts/{artifact_id}")
async def delete_artifact_endpoint(artifact_id: str):
    from app.core.artifacts import delete_artifact
    delete_artifact(artifact_id)
    return {"status": "deleted", "id": artifact_id}


@router.get("/artifacts/{artifact_id}/history")
async def artifact_history_endpoint(artifact_id: str):
    from app.core.artifacts import get_artifact_history
    return get_artifact_history(artifact_id)


# --- Plugin Management API ---

@router.get("/plugins")
async def list_plugins_endpoint():
    from app.core.plugin_system import list_plugins
    return list_plugins()


@router.post("/plugins/{plugin_name}/toggle")
async def toggle_plugin_endpoint(plugin_name: str):
    from app.core.plugin_system import get_plugin
    plugin = get_plugin(plugin_name)
    if not plugin:
        raise HTTPException(404, f"Plugin '{plugin_name}' not found")
    plugin.enabled = not plugin.enabled
    return {"name": plugin.name, "enabled": plugin.enabled}


# --- Upload Store API ---

@router.get("/uploads")
async def list_uploads(category: str = "", session_id: str = "", limit: int = 50):
    from app.core.upload_store import list_files
    return list_files(category=category or None, session_id=session_id or None, limit=limit)


@router.get("/uploads/stats")
async def upload_stats():
    from app.core.upload_store import get_store_stats
    return get_store_stats()


@router.get("/uploads/{file_id}")
async def get_upload(file_id: str):
    from app.core.upload_store import get_file
    meta = get_file(file_id)
    if not meta:
        raise HTTPException(404, "File not found")
    return meta


@router.delete("/uploads/{file_id}")
async def delete_upload(file_id: str):
    from app.core.upload_store import delete_file
    deleted = delete_file(file_id)
    if not deleted:
        raise HTTPException(404, "File not found")
    return {"status": "deleted", "id": file_id}


# --- Structured UI API ---

@router.get("/ui/components")
async def get_ui_components():
    from app.core.structured_ui import COMPONENT_SCHEMAS
    return COMPONENT_SCHEMAS


# --- Tool Replay API ---

@router.get("/replays")
async def list_replays_endpoint(limit: int = 20):
    from app.core.tool_replay import list_replays
    return list_replays(limit=limit)


@router.get("/replays/{session_id}")
async def get_replay_endpoint(session_id: str):
    from app.core.tool_replay import get_session_replay
    return get_session_replay(session_id)


@router.get("/replays/{session_id}/summary")
async def replay_summary_endpoint(session_id: str):
    from app.core.tool_replay import get_replay_summary
    return get_replay_summary(session_id)


@router.get("/replays/{session_id}/workflow")
async def replay_workflow_endpoint(session_id: str):
    from app.core.tool_replay import export_as_workflow
    return export_as_workflow(session_id)


@router.delete("/replays/{session_id}")
async def delete_replay_endpoint(session_id: str):
    from app.core.tool_replay import delete_replay
    deleted = delete_replay(session_id)
    if not deleted:
        raise HTTPException(404, "Replay not found")
    return {"status": "deleted", "session_id": session_id}


# --- Performance Dashboard API ---

@router.get("/dashboard/metrics")
async def dashboard_metrics():
    from app.core.dashboard import get_system_metrics
    return get_system_metrics()
