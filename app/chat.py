"""
Clawzd — Chat session management (API routes).
Uses SQLite via the database module for persistence.
"""
import os
import re
import uuid
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.database import (
    create_session, list_sessions, get_session, delete_session,
    get_messages, export_session_markdown, clear_all_sessions
)
from config import DATA_DIR

router = APIRouter()
logger = logging.getLogger("clawzd.chat")

# Directories where tool-generated files are stored
_IMAGES_DIR = os.path.join(DATA_DIR, "images")
_SCREENSHOTS_DIR = os.path.join(DATA_DIR, "screenshots")

# Regex patterns to extract filenames from assistant messages
_IMG_MARKER_RE = re.compile(r'__IMG__[^|]+\|[^|]+\|(.+?)__IMG__')
_SVG_MARKER_RE = re.compile(r'__SVG__[^|]+\|[^|]+\|(.+?)__SVG__')
_SCREENSHOT_URL_RE = re.compile(r'/data/screenshots/([^\s"\'<>|]+)')
_IMAGE_URL_RE = re.compile(r'/data/images/([^\s"\'<>|]+)')


def _cleanup_session_files(session_id: str):
    """Delete all images and screenshots referenced in a session's messages.

    Scans assistant messages for __IMG__, __SVG__ markers and /data/ URLs
    to find associated files, then removes them from disk.
    """
    messages = get_messages(session_id)
    filenames_to_delete = set()

    for msg in messages:
        if msg["role"] != "assistant":
            continue
        content = msg.get("content", "")

        # Extract filenames from markers
        for m in _IMG_MARKER_RE.finditer(content):
            filenames_to_delete.add(("images", m.group(1)))
        for m in _SVG_MARKER_RE.finditer(content):
            filenames_to_delete.add(("images", m.group(1)))
        # Extract from URL references
        for m in _SCREENSHOT_URL_RE.finditer(content):
            filenames_to_delete.add(("screenshots", m.group(1)))
        for m in _IMAGE_URL_RE.finditer(content):
            filenames_to_delete.add(("images", m.group(1)))

    # Delete files from disk
    deleted = 0
    for subdir, fname in filenames_to_delete:
        base_dir = _SCREENSHOTS_DIR if subdir == "screenshots" else _IMAGES_DIR
        filepath = os.path.join(base_dir, fname)
        # Security: ensure the resolved path stays within the data directory
        real_path = os.path.realpath(filepath)
        if not real_path.startswith(os.path.realpath(base_dir)):
            logger.warning("Path traversal attempt blocked: %s", filepath)
            continue
        if os.path.isfile(real_path):
            try:
                os.remove(real_path)
                deleted += 1
            except OSError as e:
                logger.warning("Failed to delete %s: %s", real_path, e)

    if deleted:
        logger.info("Session %s: cleaned up %d associated file(s)", session_id, deleted)


class NewSessionRequest(BaseModel):
    provider: str = "local"
    model: str = ""
    preprompt: str = "none"


@router.post("/new")
async def create_session_endpoint(body: NewSessionRequest | None = None):
    """Create a new chat session and return its ID."""
    body = body or NewSessionRequest()
    session_id = str(uuid.uuid4())
    session = create_session(
        session_id,
        title="New Chat",
        provider=body.provider,
        model=body.model,
        preprompt=body.preprompt,
    )
    return session


@router.get("/sessions")
async def list_sessions_endpoint(limit: int = 50, offset: int = 0):
    """Return a list of recent sessions for the sidebar."""
    sessions = list_sessions(limit=limit, offset=offset, exclude_preprompts=["ide_developer"])
    return {"sessions": sessions}


@router.get("/sessions/{session_id}")
async def get_session_endpoint(session_id: str):
    """Return a session with all its messages."""
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    messages = get_messages(session_id)
    
    # If a generation is currently in progress, append the partial response
    # so the frontend can recover it on page reload
    from app.gateway import _active_generations
    if session_id in _active_generations:
        messages.append({
            "role": "assistant",
            "content": _active_generations[session_id],
            "timestamp": "in-progress",
            "metadata": {"status": "generating"}
        })
        
    return {"session": session, "messages": messages}


@router.delete("/sessions/{session_id}")
async def delete_session_endpoint(session_id: str):
    """Delete a session, its messages, and all associated data files (images, screenshots)."""
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Clean up associated files (images, screenshots) before deleting messages
    _cleanup_session_files(session_id)

    delete_session(session_id)
    return {"status": "deleted", "session_id": session_id}


@router.delete("/sessions")
async def clear_all_sessions_endpoint():
    """Delete all sessions and messages."""
    # Note: For simplicity, we are not cleaning up all files here.
    # It would require iterating over all sessions or clearing the directories entirely.
    clear_all_sessions()
    return {"status": "cleared"}



@router.get("/sessions/{session_id}/export")
async def export_session_endpoint(session_id: str):
    """Export a session as Markdown."""
    md = export_session_markdown(session_id)
    if not md:
        raise HTTPException(status_code=404, detail="No messages to export")
    return {"markdown": md}