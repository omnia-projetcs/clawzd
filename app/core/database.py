"""
Clawzd — SQLite database layer for session and message persistence.
Replaces the previous JSON-file storage with a single database.
"""
import sqlite3
import json
import os
import threading
import subprocess
import shutil
import logging
import time
from datetime import datetime, timezone
from typing import Optional
from functools import wraps
from config import DB_PATH

_local = threading.local()


def _get_conn() -> sqlite3.Connection:
    """Return a thread-local SQLite connection (created lazily)."""
    if not hasattr(_local, "conn") or _local.conn is None:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        _local.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA foreign_keys=ON")
    return _local.conn


def repair_database():
    """Attempt to automatically repair a corrupted SQLite database."""
    logging.warning(f"Database corruption detected at {DB_PATH}. Attempting auto-repair...")
    
    # Close connection if open
    if hasattr(_local, "conn") and _local.conn is not None:
        try:
            _local.conn.close()
        except Exception:
            pass
        _local.conn = None

    corrupt_path = f"{DB_PATH}.corrupt_{int(time.time())}"
    try:
        # Move original to corrupt
        shutil.move(DB_PATH, corrupt_path)
        
        # Dump and restore
        dump_cmd = ["sqlite3", corrupt_path, ".dump"]
        restore_cmd = ["sqlite3", DB_PATH]
        
        p1 = subprocess.Popen(dump_cmd, stdout=subprocess.PIPE)
        p2 = subprocess.Popen(restore_cmd, stdin=p1.stdout, stdout=subprocess.PIPE)
        p1.stdout.close()  # Allow p1 to receive a SIGPIPE if p2 exits.
        p2.communicate()
        
        logging.info("Database auto-repair completed successfully.")
    except Exception as e:
        logging.error(f"Auto-repair failed: {e}")


def with_auto_repair(func):
    """Decorator to catch corruption and missing-schema errors, then retry."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except sqlite3.DatabaseError as e:
            err_msg = str(e).lower()
            if "malformed" in err_msg or "corruption" in err_msg:
                repair_database()
                return func(*args, **kwargs)
            if "no such table" in err_msg or "no such column" in err_msg:
                logging.warning("Missing schema detected (%s). Running init_db()…", e)
                init_db()
                return func(*args, **kwargs)
            raise
    return wrapper


@with_auto_repair
def init_db():
    """Create the schema if it does not exist."""
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            id          TEXT PRIMARY KEY,
            title       TEXT NOT NULL DEFAULT 'New Chat',
            provider    TEXT DEFAULT 'local',
            model       TEXT DEFAULT '',
            preprompt   TEXT DEFAULT '',
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL,
            message_count INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS messages (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id  TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            role        TEXT NOT NULL,
            content     TEXT NOT NULL,
            timestamp   TEXT NOT NULL,
            metadata    TEXT DEFAULT '{}'
        );

        CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
        CREATE INDEX IF NOT EXISTS idx_sessions_updated ON sessions(updated_at DESC);

        CREATE TABLE IF NOT EXISTS artifacts (
            id          TEXT PRIMARY KEY,
            session_id  TEXT REFERENCES sessions(id) ON DELETE SET NULL,
            title       TEXT NOT NULL DEFAULT 'Untitled',
            content     TEXT NOT NULL DEFAULT '',
            language    TEXT DEFAULT '',
            kind        TEXT DEFAULT 'code',
            version     INTEGER DEFAULT 1,
            parent_id   TEXT DEFAULT NULL,
            pinned      INTEGER DEFAULT 0,
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_artifacts_session ON artifacts(session_id);
        CREATE INDEX IF NOT EXISTS idx_artifacts_updated ON artifacts(updated_at DESC);
    """)
    conn.commit()


# --- Session CRUD ---

@with_auto_repair
def create_session(session_id: str, title: str = "New Chat",
                   provider: str = "local", model: str = "",
                   preprompt: str = "") -> dict:
    """Insert a new session row and return it as a dict."""
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    conn.execute(
        "INSERT INTO sessions (id, title, provider, model, preprompt, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (session_id, title, provider, model, preprompt, now, now),
    )
    conn.commit()
    return {
        "id": session_id, "title": title, "provider": provider,
        "model": model, "preprompt": preprompt,
        "created_at": now, "updated_at": now, "message_count": 0,
    }


@with_auto_repair
def list_sessions(limit: int = 50, offset: int = 0, exclude_preprompts: list[str] | None = None) -> list[dict]:
    """Return recent sessions ordered by last activity."""
    conn = _get_conn()
    if exclude_preprompts:
        placeholders = ",".join("?" * len(exclude_preprompts))
        query = f"SELECT * FROM sessions WHERE preprompt NOT IN ({placeholders}) ORDER BY updated_at DESC LIMIT ? OFFSET ?"
        params = tuple(exclude_preprompts) + (limit, offset)
    else:
        query = "SELECT * FROM sessions ORDER BY updated_at DESC LIMIT ? OFFSET ?"
        params = (limit, offset)
    
    rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


@with_auto_repair
def get_session(session_id: str) -> Optional[dict]:
    """Return a single session or None."""
    conn = _get_conn()
    row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    return dict(row) if row else None


@with_auto_repair
def update_session(session_id: str, **kwargs):
    """Update arbitrary session fields."""
    allowed = {"title", "provider", "model", "preprompt", "message_count"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return
    fields["updated_at"] = datetime.now(timezone.utc).isoformat()
    sets = ", ".join(f"{k} = ?" for k in fields)
    conn = _get_conn()
    conn.execute(f"UPDATE sessions SET {sets} WHERE id = ?",
                 (*fields.values(), session_id))
    conn.commit()


@with_auto_repair
def delete_session(session_id: str):
    """Delete a session and all its messages (cascaded)."""
    conn = _get_conn()
    conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    conn.commit()


@with_auto_repair
def clear_all_sessions():
    """Delete all sessions and messages (cascaded)."""
    conn = _get_conn()
    conn.execute("DELETE FROM sessions")
    conn.commit()


# --- Message CRUD ---

@with_auto_repair
def add_message(session_id: str, role: str, content: str,
                metadata: dict | None = None) -> dict:
    """Insert a message and update the session's counters."""
    now = datetime.now(timezone.utc).isoformat()
    meta_json = json.dumps(metadata or {})
    conn = _get_conn()
    conn.execute(
        "INSERT INTO messages (session_id, role, content, timestamp, metadata) "
        "VALUES (?, ?, ?, ?, ?)",
        (session_id, role, content, now, meta_json),
    )
    conn.execute(
        "UPDATE sessions SET message_count = message_count + 1, updated_at = ? WHERE id = ?",
        (now, session_id),
    )
    conn.commit()
    return {"role": role, "content": content, "timestamp": now, "metadata": metadata or {}}


@with_auto_repair
def get_messages(session_id: str) -> list[dict]:
    """Return all messages for a session in chronological order."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT role, content, timestamp, metadata FROM messages "
        "WHERE session_id = ? ORDER BY id ASC",
        (session_id,),
    ).fetchall()
    result = []
    for r in rows:
        m = r["metadata"]
        try:
            meta = {} if m == "{}" else json.loads(m)
        except (json.JSONDecodeError, TypeError):
            meta = {}
        result.append({
            "role": r["role"],
            "content": r["content"],
            "timestamp": r["timestamp"],
            "metadata": meta
        })
    return result


def export_session_markdown(session_id: str) -> Optional[str]:
    """Export a session as a Markdown document."""
    session = get_session(session_id)
    if not session:
        return None
    messages = get_messages(session_id)
    if not messages:
        return None
    md = f"# {session['title']}\n\n"
    md += f"*Session {session_id} — Created {session['created_at']}*\n\n---\n\n"
    for m in messages:
        role = "**User**" if m["role"] == "user" else "**Assistant**"
        md += f"{role} ({m['timestamp']}):\n{m['content']}\n\n---\n\n"
    return md


# --- Auto-title ---

def auto_title(session_id: str, first_message: str):
    """Generate a short title from the first user message."""
    import re
    clean_message = re.sub(r'^\[.*?\]\s*', '', first_message.strip())
    title = clean_message[:80]
    if len(clean_message) > 80:
        title = title.rsplit(" ", 1)[0] + "…"
    update_session(session_id, title=title)




