"""
Clawzd — Persistent Artifacts (OpenClaw OS-inspired).

Artifacts are versioned, session-linked content objects that persist
across conversations. Instead of regenerating code/charts/dashboards
from scratch, users can say "update the previous chart" and the LLM
works from the existing artifact — saving tokens and time.

Supported kinds: code, chart, dashboard, document, image, config.
"""
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from app.core.database import _get_conn

logger = logging.getLogger("clawzd.artifacts")


# ---------------------------------------------------------------------------
# CRUD operations
# ---------------------------------------------------------------------------

def create_artifact(
    title: str,
    content: str,
    session_id: Optional[str] = None,
    language: str = "",
    kind: str = "code",
    parent_id: Optional[str] = None,
) -> dict:
    """Create a new artifact and return it as a dict."""
    artifact_id = f"art-{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()

    # If it's a new version, increment from parent
    version = 1
    if parent_id:
        parent = get_artifact(parent_id)
        if parent:
            version = parent["version"] + 1

    conn = _get_conn()
    conn.execute(
        "INSERT INTO artifacts (id, session_id, title, content, language, kind, "
        "version, parent_id, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (artifact_id, session_id, title, content, language, kind,
         version, parent_id, now, now),
    )
    conn.commit()

    artifact = {
        "id": artifact_id,
        "session_id": session_id,
        "title": title,
        "content": content,
        "language": language,
        "kind": kind,
        "version": version,
        "parent_id": parent_id,
        "pinned": False,
        "created_at": now,
        "updated_at": now,
    }
    logger.info("Created artifact %s: %s (v%d, %s)", artifact_id, title, version, kind)
    return artifact


def get_artifact(artifact_id: str) -> Optional[dict]:
    """Return a single artifact or None."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM artifacts WHERE id = ?", (artifact_id,)
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["pinned"] = bool(d.get("pinned", 0))
    return d


def list_artifacts(
    session_id: Optional[str] = None,
    kind: Optional[str] = None,
    pinned_only: bool = False,
    limit: int = 50,
) -> list[dict]:
    """List artifacts, optionally filtered by session/kind/pinned."""
    conn = _get_conn()
    query = "SELECT * FROM artifacts WHERE 1=1"
    params: list = []

    if session_id:
        query += " AND session_id = ?"
        params.append(session_id)
    if kind:
        query += " AND kind = ?"
        params.append(kind)
    if pinned_only:
        query += " AND pinned = 1"

    query += " ORDER BY updated_at DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["pinned"] = bool(d.get("pinned", 0))
        result.append(d)
    return result


def update_artifact(
    artifact_id: str,
    title: Optional[str] = None,
    content: Optional[str] = None,
    pinned: Optional[bool] = None,
) -> Optional[dict]:
    """Update an artifact in place. For content changes, prefer
    ``create_artifact(parent_id=...)`` to create a versioned copy."""
    conn = _get_conn()
    now = datetime.now(timezone.utc).isoformat()
    fields = {"updated_at": now}

    if title is not None:
        fields["title"] = title
    if content is not None:
        fields["content"] = content
    if pinned is not None:
        fields["pinned"] = 1 if pinned else 0

    sets = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(
        f"UPDATE artifacts SET {sets} WHERE id = ?",
        (*fields.values(), artifact_id),
    )
    conn.commit()
    return get_artifact(artifact_id)


def delete_artifact(artifact_id: str):
    """Delete an artifact."""
    conn = _get_conn()
    conn.execute("DELETE FROM artifacts WHERE id = ?", (artifact_id,))
    conn.commit()
    logger.info("Deleted artifact %s", artifact_id)


def get_artifact_history(artifact_id: str) -> list[dict]:
    """Get the version history of an artifact (follow parent_id chain)."""
    history = []
    current = get_artifact(artifact_id)
    while current:
        history.append(current)
        parent_id = current.get("parent_id")
        if not parent_id:
            break
        current = get_artifact(parent_id)
    return list(reversed(history))  # oldest first


# ---------------------------------------------------------------------------
# Helpers for gateway integration
# ---------------------------------------------------------------------------

def extract_and_save_artifacts(
    text: str,
    session_id: str,
) -> list[dict]:
    """Auto-extract code blocks from LLM response and save as artifacts.

    Only saves substantial code (>5 lines). Returns the list of created artifacts.
    """
    import re

    created = []
    # Match ```lang:filename or ```lang filename or just ```lang
    pattern = re.compile(
        r'```(\w+)(?:[:\s]([^\n]*))?\n([\s\S]*?)```',
        re.MULTILINE,
    )

    _EXT_TO_KIND = {
        "py": "code", "js": "code", "ts": "code", "html": "code",
        "css": "code", "json": "config", "yaml": "config", "yml": "config",
        "sql": "code", "sh": "code", "bash": "code", "md": "document",
        "svg": "image",
    }

    for match in pattern.finditer(text):
        lang = match.group(1).lower()
        fname = (match.group(2) or "").strip()
        code = match.group(3).strip()

        # Skip tiny snippets and tool_call blocks
        if len(code.split("\n")) < 5:
            continue
        if lang in ("tool_call", "tool", "json") and '"tool"' in code:
            continue

        kind = _EXT_TO_KIND.get(lang, "code")
        title = fname if fname else f"snippet.{lang}"

        artifact = create_artifact(
            title=title,
            content=code,
            session_id=session_id,
            language=lang,
            kind=kind,
        )
        created.append(artifact)

    if created:
        logger.info(
            "Auto-extracted %d artifact(s) from session %s",
            len(created), session_id,
        )

    return created
