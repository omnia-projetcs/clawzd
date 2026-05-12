import os
import sys
import sqlite3
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from app.database import init_db
from config import DB_PATH

init_db()
print("✓ Database schema up to date")

# --- Migration: Message branching columns ---
print("--- Migrating message branching columns ---")
try:
    conn = sqlite3.connect(DB_PATH)
    for col, col_type, default in [
        ("parent_message_id", "INTEGER", "NULL"),
        ("branch_id", "TEXT", "'main'"),
    ]:
        try:
            conn.execute(f"ALTER TABLE messages ADD COLUMN {col} {col_type} DEFAULT {default}")
            conn.commit()
            print(f"  ✓ Added messages.{col}")
        except sqlite3.OperationalError as e:
            if "duplicate column" in str(e).lower():
                print(f"  • messages.{col} already exists")
            else:
                print(f"  ✗ Warning: {e}")
    # Add branch index if missing
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_branch ON messages(session_id, branch_id)")
        conn.commit()
        print("  ✓ Branch index created")
    except Exception as e:
        print(f"  • Branch index: {e}")
    conn.close()
except Exception as e:
    print(f"  ✗ Branching migration failed: {e}")

# --- Legacy: Memory file migration (if save_memory_entries still exists) ---
try:
    from app.database import save_memory_entries
    memories_dir = os.path.join("data", "memories")
    user_file = os.path.join(memories_dir, "USER.md")
    memory_file = os.path.join(memories_dir, "MEMORY.md")

    for target, file_path in [("user", user_file), ("memory", memory_file)]:
        if os.path.exists(file_path):
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            entries = [e.strip() for e in content.split("§") if e.strip()]
            if entries:
                save_memory_entries(target, entries)
                print(f"Migrated {len(entries)} entries for {target}")
except ImportError:
    pass  # Memory system may have been refactored

print("Migration complete")
