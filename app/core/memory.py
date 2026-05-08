"""
Clawzd — Persistent Memory System.

Cross-session memory via bounded Markdown files (MEMORY.md for agent notes,
USER.md for user profile) in profiles/user/. Injected into the system prompt at session start.
The agent manages its own memory via a ``memory`` tool with add/replace/remove.
Includes a daily optimization task to keep these files concise.

Inspired by Hermes Agent's persistent memory architecture https://github.com/NousResearch/hermes-agent.
"""
import json
import logging
import os
import re
import threading
from typing import Optional

from fastapi import APIRouter, Request
from config import PROFILES_DIR

router = APIRouter()

logger = logging.getLogger("clawzd.memory")

# Directory for user profiles & memory
RAG_PROFIL_DIR = os.path.join(PROFILES_DIR, "user")
os.makedirs(RAG_PROFIL_DIR, exist_ok=True)

# Default character limits (approx ~800 and ~500 tokens respectively)
DEFAULT_MEMORY_CHAR_LIMIT = 2200
DEFAULT_USER_CHAR_LIMIT = 1375

# Section separator in memory entries
ENTRY_SEPARATOR = "§"

# Injection patterns to block (security scanning)
_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"system\s*:\s*you\s+are\s+now", re.IGNORECASE),
    re.compile(r"ssh\s+.*@", re.IGNORECASE),
    re.compile(r"curl\s+.*\|\s*bash", re.IGNORECASE),
    re.compile(r"(api[_-]?key|password|secret|token)\s*[=:]\s*\S{8,}", re.IGNORECASE),
]

_lock = threading.Lock()


class MemoryStore:
    """Manages memory entries stored in Markdown files in profiles/user/.

    Each target ('memory' or 'user') maps to a .md file (MEMORY.md, USER.md).
    Entries are plain strings — no structured format required.
    """

    def __init__(self, target: str, char_limit: int):
        self.target = target
        self.char_limit = char_limit
        self.filepath = os.path.join(RAG_PROFIL_DIR, f"{target.upper()}.md")

    def _read_raw(self) -> str:
        """Read the raw concatenated content."""
        if not os.path.exists(self.filepath):
            return ""
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            logger.error(f"Error reading {self.filepath}: {e}")
            return ""

    def _write_raw(self, content: str):
        """Write raw content to the markdown file."""
        try:
            with open(self.filepath, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception as e:
            logger.error(f"Error writing {self.filepath}: {e}")

    def get_entries(self) -> list[str]:
        """Return all memory entries as a list of strings."""
        raw = self._read_raw()
        return [e.strip() for e in raw.split(ENTRY_SEPARATOR) if e.strip()]

    def _save_entries(self, entries: list[str]):
        """Save entries back to file."""
        self._write_raw(ENTRY_SEPARATOR.join(entries))

    def get_usage(self) -> dict:
        """Return current usage stats."""
        raw = self._read_raw()
        current = len(raw)
        return {
            "current_chars": current,
            "max_chars": self.char_limit,
            "percentage": round(current / self.char_limit * 100, 1) if self.char_limit else 0,
            "entry_count": len(self.get_entries()),
        }

    def add(self, content: str) -> dict:
        """Add a new memory entry.

        Returns a status dict with success/error.
        """
        content = content.strip()
        if not content:
            return {"success": False, "error": "Empty content"}

        # Security scan
        blocked = _scan_for_injection(content)
        if blocked:
            return {"success": False, "error": f"Content blocked: {blocked}"}

        with _lock:
            entries = self.get_entries()

            # Duplicate check
            for existing in entries:
                if existing == content:
                    return {"success": True, "message": "Entry already exists (no duplicate added)"}

            # Capacity check
            raw = self._read_raw()
            new_total = len(raw) + len(ENTRY_SEPARATOR) + len(content)
            if new_total > self.char_limit:
                usage = self.get_usage()
                return {
                    "success": False,
                    "error": (
                        f"Memory at {usage['current_chars']:,}/{self.char_limit:,} chars. "
                        f"Adding this entry ({len(content)} chars) would exceed the limit. "
                        f"Replace or remove existing entries first."
                    ),
                    "current_entries": entries,
                    "usage": f"{usage['current_chars']:,}/{self.char_limit:,}",
                }

            entries.append(content)
            self._save_entries(entries)

        logger.info("Memory entry added to %s (%d chars)", self.target, len(content))
        return {"success": True, "message": "Entry added", "usage": self.get_usage()}

    def replace(self, old_text: str, new_content: str) -> dict:
        """Replace an entry identified by a unique substring.

        ``old_text`` is matched as a substring — it doesn't need to be the
        full entry text, just unique enough to identify exactly one entry.
        """
        old_text = old_text.strip()
        new_content = new_content.strip()
        if not old_text:
            return {"success": False, "error": "old_text is required"}
        if not new_content:
            return {"success": False, "error": "new content is required"}

        blocked = _scan_for_injection(new_content)
        if blocked:
            return {"success": False, "error": f"Content blocked: {blocked}"}

        with _lock:
            entries = self.get_entries()
            matches = [i for i, e in enumerate(entries) if old_text in e]

            if len(matches) == 0:
                return {
                    "success": False,
                    "error": f"No entry matches substring: '{old_text[:50]}'",
                    "current_entries": entries,
                }
            if len(matches) > 1:
                return {
                    "success": False,
                    "error": (
                        f"Ambiguous: '{old_text[:50]}' matches {len(matches)} entries. "
                        f"Use a more specific substring."
                    ),
                    "current_entries": entries,
                }

            idx = matches[0]
            old_entry = entries[idx]

            # Capacity check for replacement
            size_diff = len(new_content) - len(old_entry)
            if size_diff > 0:
                raw = self._read_raw()
                if len(raw) + size_diff > self.char_limit:
                    return {
                        "success": False,
                        "error": f"Replacement would exceed limit by {size_diff} chars",
                    }

            entries[idx] = new_content
            self._save_entries(entries)

        logger.info("Memory entry replaced in %s (old: %d chars → new: %d chars)", self.target, len(old_entry), len(new_content))
        return {"success": True, "message": "Entry replaced", "usage": self.get_usage()}

    def remove(self, old_text: str) -> dict:
        """Remove an entry identified by a unique substring."""
        old_text = old_text.strip()
        if not old_text:
            return {"success": False, "error": "old_text is required"}

        with _lock:
            entries = self.get_entries()
            matches = [i for i, e in enumerate(entries) if old_text in e]

            if len(matches) == 0:
                return {
                    "success": False,
                    "error": f"No entry matches: '{old_text[:50]}'",
                    "current_entries": entries,
                }
            if len(matches) > 1:
                return {
                    "success": False,
                    "error": f"Ambiguous: matches {len(matches)} entries",
                    "current_entries": entries,
                }

            removed = entries.pop(matches[0])
            self._save_entries(entries)

        logger.info("Memory entry removed from %s (%d chars)", self.target, len(removed))
        return {"success": True, "message": "Entry removed", "usage": self.get_usage()}


# ---------------------------------------------------------------------------
# Singleton stores
# ---------------------------------------------------------------------------

_memory_store: Optional[MemoryStore] = None
_user_store: Optional[MemoryStore] = None


def _get_memory_store() -> MemoryStore:
    global _memory_store
    if _memory_store is None:
        _memory_store = MemoryStore("memory", DEFAULT_MEMORY_CHAR_LIMIT)
    return _memory_store


def _get_user_store() -> MemoryStore:
    global _user_store
    if _user_store is None:
        _user_store = MemoryStore("user", DEFAULT_USER_CHAR_LIMIT)
    return _user_store


def _get_store(target: str) -> MemoryStore:
    """Get the appropriate store for a target ('memory' or 'user')."""
    if target == "user":
        return _get_user_store()
    return _get_memory_store()


# ---------------------------------------------------------------------------
# Memory tool handler (called by tool_executor)
# ---------------------------------------------------------------------------

def handle_memory_tool(params: dict) -> dict:
    """Handle a memory tool call from the LLM.

    Expected params:
        action: "add" | "replace" | "remove"
        target: "memory" | "user"
        content: str (for add/replace)
        old_text: str (for replace/remove)
    """
    action = params.get("action", "").strip().lower()
    target = params.get("target", "memory").strip().lower()

    if target not in ("memory", "user"):
        return {"success": False, "error": f"Invalid target: '{target}'. Use 'memory' or 'user'."}

    store = _get_store(target)

    if action == "add":
        content = params.get("content", "")
        return store.add(content)

    elif action == "replace":
        old_text = params.get("old_text", "")
        content = params.get("content", "")
        return store.replace(old_text, content)

    elif action == "remove":
        old_text = params.get("old_text", "")
        return store.remove(old_text)

    else:
        return {
            "success": False,
            "error": f"Unknown action: '{action}'. Use 'add', 'replace', or 'remove'.",
        }


# ---------------------------------------------------------------------------
# System prompt injection
# ---------------------------------------------------------------------------

def build_memory_prompt() -> str:
    """Build the memory block to inject into the system prompt.

    Returns a formatted string with MEMORY and USER PROFILE sections,
    or empty string if both are empty.
    """
    blocks = []

    mem_store = _get_memory_store()
    mem_entries = mem_store.get_entries()
    if mem_entries:
        usage = mem_store.get_usage()
        header = (
            f"{'═' * 20} MEMORY (your personal notes) "
            f"[{usage['percentage']}% — {usage['current_chars']:,}/{usage['max_chars']:,} chars] "
            f"{'═' * 20}"
        )
        body = ENTRY_SEPARATOR.join(mem_entries)
        blocks.append(f"{header}\n{body}")

    user_store = _get_user_store()
    user_entries = user_store.get_entries()
    if user_entries:
        usage = user_store.get_usage()
        header = (
            f"{'═' * 20} USER PROFILE "
            f"[{usage['percentage']}% — {usage['current_chars']:,}/{usage['max_chars']:,} chars] "
            f"{'═' * 20}"
        )
        body = ENTRY_SEPARATOR.join(user_entries)
        blocks.append(f"{header}\n{body}")

    return "\n\n".join(blocks)


# Memory management guidance injected into system prompts
MEMORY_GUIDANCE = (
    "\n\nYou have persistent memory across sessions. "
    "Use the `memory` tool to save important facts:\n"
    "- Save user preferences, environment details, project conventions\n"
    "- Save corrections and lessons learned\n"
    "- Use target='memory' for environment/project notes, target='user' for user preferences\n"
    "- Actions: add (new entry), replace (update via old_text substring match), remove (delete via old_text)\n"
    "- When memory is >80% full, consolidate entries before adding new ones\n"
    "- DO NOT save trivial, easily re-discovered, or session-specific information\n"
    "Tool format example: ```tool_call\n{\"tool\":\"memory\",\"params\":{\"action\":\"add\",\"target\":\"user\",\"content\":\"User prefers concise answers\"}}\n```\n"
)


# ---------------------------------------------------------------------------
# Security scanning
# ---------------------------------------------------------------------------

def _scan_for_injection(content: str) -> Optional[str]:
    """Scan content for injection and exfiltration patterns.

    Returns a description of the threat if found, or None if clean.
    """
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(content):
            return f"Suspicious pattern detected: {pattern.pattern[:50]}"
    # Check for invisible Unicode characters
    for ch in content:
        if ord(ch) in range(0x200B, 0x200F + 1) or ord(ch) == 0xFEFF:
            return "Invisible Unicode characters detected"
    return None

# ---------------------------------------------------------------------------
# Memory Optimization
# ---------------------------------------------------------------------------

async def optimize_memory_files():
    """Reads ALL .md files in the profiles/ directory tree, uses the LLM to compress them, and rewrites them."""
    from app.core.llm_provider import get_llm_provider
    from config import LLM_PROVIDER
    import glob

    provider = get_llm_provider(LLM_PROVIDER)

    logger.info("Starting background memory optimization for all profiles...")

    # Discover every .md file under profiles/
    md_files = sorted(glob.glob(os.path.join(PROFILES_DIR, "**", "*.md"), recursive=True))

    if not md_files:
        logger.info("No .md files found in %s — nothing to optimize.", PROFILES_DIR)
        return

    system_prompt = (
        "You are an expert at information compression and synthesis. "
        "Your task is to take the provided markdown content and rewrite it "
        "to be significantly more concise, removing redundancies while preserving "
        "all factual information, structure, and headings. "
        "Keep the separator character '§' if there are distinct sections, "
        "or consolidate related points into a single cohesive section. "
        "Output ONLY the optimized markdown content without any introductory text, markdown wrappers, or explanation."
    )

    optimized_count = 0
    for filepath in md_files:
        rel_path = os.path.relpath(filepath, PROFILES_DIR)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                raw_content = f.read()

            if not raw_content.strip():
                logger.debug("Skipping empty file: %s", rel_path)
                continue

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Optimize the following:\n\n{raw_content}"},
            ]
            response = await provider.chat(messages)
            optimized_content = response.strip()

            if optimized_content:
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(optimized_content)
                logger.info(
                    "Optimized %s (Old: %d chars → New: %d chars)",
                    rel_path, len(raw_content), len(optimized_content),
                )
                optimized_count += 1

        except Exception as e:
            logger.error("Failed to optimize %s: %s", rel_path, e)

    logger.info("Memory optimization complete — %d/%d files processed.", optimized_count, len(md_files))

# ---------------------------------------------------------------------------
# REST API routes (for frontend Settings UI)
# ---------------------------------------------------------------------------

@router.post("/memory/optimize")
async def trigger_optimization():
    """Trigger memory optimization manually from the UI."""
    import asyncio
    asyncio.create_task(optimize_memory_files())
    return {"success": True, "message": "Optimization started in background."}
