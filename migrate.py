import os
import sys
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from app.database import init_db

init_db()
print("✓ Database schema up to date (branching columns auto-migrated)")

# --- Verify new features are accessible ---
try:
    from app.database import clear_session_messages
    print("✓ clear_session_messages available (chat reset feature)")
except ImportError:
    print("WARNING: clear_session_messages not found — chat reset may not work")

try:
    from app.tools.contracts import _TOOL_SCHEMAS
    new_tools = ["apply_patch", "write_file", "grep_code", "webfetch"]
    missing = [t for t in new_tools if t not in _TOOL_SCHEMAS]
    if missing:
        print(f"WARNING: Missing OpenCode tool schemas: {missing}")
    else:
        print(f"✓ OpenCode tools registered ({', '.join(new_tools)})")
except ImportError:
    print("WARNING: Could not verify tool schemas")

try:
    from app.tools.patch_parser import parse_patch, apply_patch
    print("✓ Patch parser module available")
except ImportError:
    print("WARNING: patch_parser module not found — apply_patch tool may not work")

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

