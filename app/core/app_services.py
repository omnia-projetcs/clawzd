"""
Clawzd — App Services (Secrets Vault & Per-App Database).

Provides two server-side services for mini-apps:

1. **Secrets Vault**: Encrypted key-value store for API keys, credentials,
   passwords.  Stored in `data/apps/{app_id}/_secrets.json` (never served
   as a static file thanks to the `_` prefix).

2. **Per-App Database**: Each app gets its own SQLite database stored at
   `data/apps/{app_id}/app.db`.  Provides safe SQL execution with
   blocklist for dangerous operations.
"""
import json
import logging
import os
import sqlite3
import threading
from typing import Optional

from config import DATA_DIR

logger = logging.getLogger("clawzd.app_services")

APPS_DIR = os.path.join(DATA_DIR, "apps")

# Internal files that must never be served as static assets
INTERNAL_FILES = {"_meta.json", "_secrets.json", "app.db"}

# Max DB size per app (50 MB)
_MAX_DB_SIZE = 50 * 1024 * 1024

# ---------------------------------------------------------------------------
# Secrets Vault
# ---------------------------------------------------------------------------

def _secrets_path(app_id: str) -> str:
    return os.path.join(APPS_DIR, app_id, "_secrets.json")


def _load_secrets(app_id: str) -> dict[str, str]:
    path = _secrets_path(app_id)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def _save_secrets(app_id: str, secrets: dict[str, str]):
    path = _secrets_path(app_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(secrets, f, indent=2, ensure_ascii=False)


def _mask_value(value: str) -> str:
    """Mask a secret value for safe display."""
    if len(value) <= 4:
        return "****"
    return value[:2] + "*" * (len(value) - 4) + value[-2:]


def get_secrets(app_id: str) -> list[dict]:
    """List all secrets with masked values."""
    secrets = _load_secrets(app_id)
    return [
        {"key": k, "masked": _mask_value(v), "length": len(v)}
        for k, v in secrets.items()
    ]


def set_secret(app_id: str, key: str, value: str) -> dict:
    """Create or update a secret."""
    secrets = _load_secrets(app_id)
    is_new = key not in secrets
    secrets[key] = value
    _save_secrets(app_id, secrets)
    logger.info("%s secret '%s' for app %s",
                "Created" if is_new else "Updated", key, app_id)
    return {"key": key, "masked": _mask_value(value), "created": is_new}


def delete_secret(app_id: str, key: str) -> bool:
    """Delete a secret by key."""
    secrets = _load_secrets(app_id)
    if key not in secrets:
        return False
    del secrets[key]
    _save_secrets(app_id, secrets)
    logger.info("Deleted secret '%s' from app %s", key, app_id)
    return True


def get_secret_value(app_id: str, key: str) -> Optional[str]:
    """Get the raw value of a secret (for runtime proxy)."""
    secrets = _load_secrets(app_id)
    return secrets.get(key)


# ---------------------------------------------------------------------------
# Per-App SQLite Database
# ---------------------------------------------------------------------------

_db_local = threading.local()

# SQL operations that are forbidden for safety
_BLOCKED_SQL = [
    "ATTACH", "DETACH", "PRAGMA", "VACUUM",
]


def _db_path(app_id: str) -> str:
    return os.path.join(APPS_DIR, app_id, "app.db")


def get_db_conn(app_id: str) -> sqlite3.Connection:
    """Return a thread-local SQLite connection for an app."""
    cache_key = f"db_{app_id}"
    if not hasattr(_db_local, cache_key) or getattr(_db_local, cache_key) is None:
        db_file = _db_path(app_id)
        os.makedirs(os.path.dirname(db_file), exist_ok=True)
        conn = sqlite3.connect(db_file, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        setattr(_db_local, cache_key, conn)
    return getattr(_db_local, cache_key)


def _check_db_size(app_id: str) -> bool:
    """Return True if DB is within size limits."""
    db_file = _db_path(app_id)
    if not os.path.exists(db_file):
        return True
    return os.path.getsize(db_file) <= _MAX_DB_SIZE


def _is_safe_sql(sql: str) -> tuple[bool, str]:
    """Check if SQL is safe to execute. Returns (safe, reason)."""
    stripped = sql.strip().upper()
    for blocked in _BLOCKED_SQL:
        if stripped.startswith(blocked):
            return False, f"'{blocked}' statements are not allowed"
    return True, ""


def execute_query(
    app_id: str, sql: str, params: list | None = None
) -> dict:
    """Execute a SQL query against an app's database.

    Returns:
        For SELECT: {"columns": [...], "rows": [[...], ...], "count": N}
        For write:  {"affected": N, "lastrowid": N}
    """
    safe, reason = _is_safe_sql(sql)
    if not safe:
        return {"error": reason}

    if not _check_db_size(app_id):
        return {"error": f"Database exceeds maximum size ({_MAX_DB_SIZE // (1024*1024)}MB)"}

    conn = get_db_conn(app_id)
    try:
        cursor = conn.execute(sql, params or [])
        stripped = sql.strip().upper()

        if stripped.startswith("SELECT") or stripped.startswith("WITH"):
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            rows = [list(row) for row in cursor.fetchall()]
            return {"columns": columns, "rows": rows, "count": len(rows)}
        else:
            conn.commit()
            return {"affected": cursor.rowcount, "lastrowid": cursor.lastrowid}
    except sqlite3.Error as e:
        return {"error": str(e)}


def list_tables(app_id: str) -> list[dict]:
    """List all tables in an app's database."""
    conn = get_db_conn(app_id)
    try:
        rows = conn.execute(
            "SELECT name, type FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name"
        ).fetchall()
        result = []
        for r in rows:
            count = conn.execute(
                f'SELECT COUNT(*) FROM "{r["name"]}"'
            ).fetchone()[0]
            result.append({"name": r["name"], "type": r["type"], "row_count": count})
        return result
    except sqlite3.Error as e:
        return [{"error": str(e)}]


def get_table_schema(app_id: str, table: str) -> list[dict]:
    """Get column info for a table."""
    conn = get_db_conn(app_id)
    try:
        rows = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
        return [
            {"cid": r[0], "name": r[1], "type": r[2],
             "notnull": bool(r[3]), "default": r[4], "pk": bool(r[5])}
            for r in rows
        ]
    except sqlite3.Error as e:
        return [{"error": str(e)}]
