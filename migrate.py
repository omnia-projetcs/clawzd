import os
import sys
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from app.database import init_db, save_memory_entries

init_db()

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
print("Migration complete")
