"""
Clawzd — Upload Store (OpenClaw OS-inspired).

Centralized file management for all uploaded and generated files.
Replaces the scattered `data/images/`, `data/audio/`, `data/screenshots/`
approach with a unified store that provides:
- Automatic deduplication via content hash (SHA-256)
- File lifecycle management (creation, access tracking, expiration)
- Category-based organization (image, audio, document, code, video)
- Quick file listing and metadata lookup
- Thumbnail/preview placeholder support
"""
import hashlib
import json
import logging
import os
import shutil
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("clawzd.upload_store")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_CATEGORIES = {"image", "audio", "document", "code", "video", "screenshot", "other"}

_EXT_TO_CATEGORY = {
    # Images
    ".png": "image", ".jpg": "image", ".jpeg": "image", ".gif": "image",
    ".webp": "image", ".svg": "image", ".bmp": "image", ".ico": "image",
    # Audio
    ".mp3": "audio", ".wav": "audio", ".ogg": "audio", ".flac": "audio",
    ".m4a": "audio", ".aac": "audio",
    # Video
    ".mp4": "video", ".webm": "video", ".avi": "video", ".mov": "video",
    # Documents
    ".pdf": "document", ".docx": "document", ".xlsx": "document",
    ".pptx": "document", ".md": "document", ".txt": "document",
    ".csv": "document", ".json": "document",
    # Code
    ".py": "code", ".js": "code", ".ts": "code", ".html": "code",
    ".css": "code", ".sql": "code", ".sh": "code", ".yaml": "code",
    ".yml": "code",
}


# ---------------------------------------------------------------------------
# In-memory file index (backed by a JSON manifest)
# ---------------------------------------------------------------------------

_file_index: dict[str, dict] = {}  # file_id → metadata
_hash_index: dict[str, str] = {}   # content_hash → file_id (dedup)
_manifest_path: str = ""


def init_store(data_dir: str = "data"):
    """Initialize the upload store and load the manifest."""
    global _manifest_path
    _manifest_path = os.path.join(data_dir, "upload_manifest.json")
    os.makedirs(data_dir, exist_ok=True)
    _load_manifest()


def _load_manifest():
    """Load the file index from the manifest JSON file."""
    global _file_index, _hash_index
    if os.path.exists(_manifest_path):
        try:
            with open(_manifest_path, "r") as f:
                _file_index = json.load(f)
            # Rebuild hash index
            _hash_index = {
                meta["hash"]: fid
                for fid, meta in _file_index.items()
                if meta.get("hash")
            }
            logger.info("Upload store: loaded %d files from manifest", len(_file_index))
        except (json.JSONDecodeError, IOError) as e:
            logger.warning("Upload store manifest corrupted: %s", e)
            _file_index = {}
            _hash_index = {}
    else:
        _file_index = {}
        _hash_index = {}


def _save_manifest():
    """Persist the file index to disk."""
    if not _manifest_path:
        return
    try:
        with open(_manifest_path, "w") as f:
            json.dump(_file_index, f, indent=2, ensure_ascii=False)
    except IOError as e:
        logger.error("Failed to save upload manifest: %s", e)


def _compute_hash(filepath: str) -> str:
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()[:16]  # Short hash for storage efficiency


def _detect_category(filename: str) -> str:
    """Detect file category from extension."""
    ext = os.path.splitext(filename)[1].lower()
    return _EXT_TO_CATEGORY.get(ext, "other")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def register_file(
    filepath: str,
    session_id: Optional[str] = None,
    category: Optional[str] = None,
    source: str = "upload",
) -> dict:
    """Register a file in the upload store.

    If the file content already exists (by hash), returns the existing
    entry instead of creating a duplicate.

    Args:
        filepath: Absolute or relative path to the file.
        session_id: Optional session that created this file.
        category: Optional category override (auto-detected from extension).
        source: Origin of the file (upload, generation, tool, etc.).

    Returns:
        File metadata dict with id, hash, category, etc.
    """
    if not os.path.exists(filepath):
        logger.warning("Cannot register non-existent file: %s", filepath)
        return {"error": f"File not found: {filepath}"}

    content_hash = _compute_hash(filepath)
    filename = os.path.basename(filepath)

    # Dedup check
    if content_hash in _hash_index:
        existing_id = _hash_index[content_hash]
        existing = _file_index.get(existing_id)
        if existing:
            existing["access_count"] = existing.get("access_count", 0) + 1
            existing["last_accessed"] = datetime.now(timezone.utc).isoformat()
            _save_manifest()
            logger.debug("Dedup: %s already registered as %s", filename, existing_id)
            return existing

    # New file
    file_id = f"file-{uuid.uuid4().hex[:10]}"
    cat = category if category in _CATEGORIES else _detect_category(filename)
    now = datetime.now(timezone.utc).isoformat()

    meta = {
        "id": file_id,
        "filename": filename,
        "filepath": filepath,
        "hash": content_hash,
        "category": cat,
        "source": source,
        "session_id": session_id,
        "size_bytes": os.path.getsize(filepath),
        "created_at": now,
        "last_accessed": now,
        "access_count": 1,
    }

    _file_index[file_id] = meta
    _hash_index[content_hash] = file_id
    _save_manifest()

    logger.info("Registered file: %s (%s, %s, %d bytes)",
                filename, file_id, cat, meta["size_bytes"])
    return meta


def get_file(file_id: str) -> Optional[dict]:
    """Get file metadata by ID."""
    meta = _file_index.get(file_id)
    if meta:
        meta["access_count"] = meta.get("access_count", 0) + 1
        meta["last_accessed"] = datetime.now(timezone.utc).isoformat()
    return meta


def list_files(
    category: Optional[str] = None,
    session_id: Optional[str] = None,
    source: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    """List files with optional filters."""
    results = list(_file_index.values())

    if category:
        results = [f for f in results if f.get("category") == category]
    if session_id:
        results = [f for f in results if f.get("session_id") == session_id]
    if source:
        results = [f for f in results if f.get("source") == source]

    # Sort by creation time (newest first)
    results.sort(key=lambda f: f.get("created_at", ""), reverse=True)
    return results[:limit]


def delete_file(file_id: str, remove_from_disk: bool = False) -> bool:
    """Remove a file from the store index.

    Args:
        file_id: File ID to remove.
        remove_from_disk: If True, also delete the physical file.

    Returns:
        True if the file was found and removed.
    """
    meta = _file_index.pop(file_id, None)
    if not meta:
        return False

    # Remove from hash index
    content_hash = meta.get("hash")
    if content_hash and _hash_index.get(content_hash) == file_id:
        del _hash_index[content_hash]

    # Optionally remove physical file
    if remove_from_disk and meta.get("filepath"):
        try:
            if os.path.exists(meta["filepath"]):
                os.remove(meta["filepath"])
        except OSError as e:
            logger.warning("Could not remove file %s: %s", meta["filepath"], e)

    _save_manifest()
    logger.info("Deleted file: %s (%s)", meta.get("filename"), file_id)
    return True


def get_store_stats() -> dict:
    """Get storage statistics."""
    total_size = sum(f.get("size_bytes", 0) for f in _file_index.values())
    by_category = {}
    for f in _file_index.values():
        cat = f.get("category", "other")
        by_category[cat] = by_category.get(cat, 0) + 1

    return {
        "total_files": len(_file_index),
        "total_size_bytes": total_size,
        "total_size_mb": round(total_size / (1024 * 1024), 2),
        "by_category": by_category,
        "dedup_entries": len(_hash_index),
    }
