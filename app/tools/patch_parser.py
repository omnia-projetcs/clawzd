"""
Clawzd — OpenCode-style Patch Parser & Applicator.

Parses the OpenCode patch format:
    *** Begin Patch
    *** Add File: <path>
    +line1
    +line2
    *** Update File: <path>
    @@ context line
    -old line
    +new line
    *** Delete File: <path>
    *** End Patch

And applies the operations to workspace files.
"""
import os
import re
import logging
from dataclasses import dataclass, field

logger = logging.getLogger("clawzd.patch_parser")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class PatchChunk:
    """A single update chunk within an Update File hunk."""
    context: list[str] = field(default_factory=list)
    deletions: list[str] = field(default_factory=list)
    additions: list[str] = field(default_factory=list)


@dataclass
class PatchHunk:
    """One file operation in a patch."""
    type: str  # "add" | "update" | "delete"
    path: str
    move_path: str | None = None
    content: str = ""  # For 'add': full file content
    chunks: list[PatchChunk] = field(default_factory=list)  # For 'update'


@dataclass
class PatchResult:
    """Result of applying a patch."""
    success: bool
    operations: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def parse_patch(patch_text: str) -> list[PatchHunk]:
    """Parse OpenCode-style patch text into a list of PatchHunks.

    Raises ValueError if the patch is malformed.
    """
    lines = patch_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    hunks: list[PatchHunk] = []

    # Find *** Begin Patch
    start_idx = -1
    for i, line in enumerate(lines):
        if line.strip() == "*** Begin Patch":
            start_idx = i
            break

    if start_idx < 0:
        raise ValueError("Missing '*** Begin Patch' marker")

    # Find *** End Patch
    end_idx = -1
    for i in range(len(lines) - 1, start_idx, -1):
        if lines[i].strip() == "*** End Patch":
            end_idx = i
            break

    if end_idx < 0:
        raise ValueError("Missing '*** End Patch' marker")

    # Parse between markers
    i = start_idx + 1
    while i < end_idx:
        line = lines[i]

        # --- Add File ---
        m = re.match(r"\*\*\* Add File:\s*(.+)", line)
        if m:
            path = m.group(1).strip()
            content_lines = []
            i += 1
            while i < end_idx and not lines[i].startswith("*** "):
                ln = lines[i]
                if ln.startswith("+"):
                    content_lines.append(ln[1:])
                elif ln.strip() == "":
                    content_lines.append("")
                else:
                    content_lines.append(ln)
                i += 1
            hunks.append(PatchHunk(
                type="add",
                path=path,
                content="\n".join(content_lines),
            ))
            continue

        # --- Delete File ---
        m = re.match(r"\*\*\* Delete File:\s*(.+)", line)
        if m:
            path = m.group(1).strip()
            hunks.append(PatchHunk(type="delete", path=path))
            i += 1
            continue

        # --- Update File ---
        m = re.match(r"\*\*\* Update File:\s*(.+)", line)
        if m:
            path = m.group(1).strip()
            move_path = None
            i += 1

            # Check for *** Move to:
            if i < end_idx:
                mm = re.match(r"\*\*\* Move to:\s*(.+)", lines[i])
                if mm:
                    move_path = mm.group(1).strip()
                    i += 1

            # Parse chunks
            chunks: list[PatchChunk] = []
            current_chunk: PatchChunk | None = None

            while i < end_idx and not lines[i].startswith("*** "):
                ln = lines[i]

                # Context line (starts with @@ or is a plain line)
                if ln.startswith("@@"):
                    # New chunk — the @@ line IS the context
                    if current_chunk is not None:
                        chunks.append(current_chunk)
                    current_chunk = PatchChunk()
                    # Extract context text after @@
                    ctx = ln[2:].strip()
                    if ctx:
                        current_chunk.context.append(ctx)
                elif ln.startswith("-"):
                    if current_chunk is None:
                        current_chunk = PatchChunk()
                    current_chunk.deletions.append(ln[1:])
                elif ln.startswith("+"):
                    if current_chunk is None:
                        current_chunk = PatchChunk()
                    current_chunk.additions.append(ln[1:])
                elif ln.strip() == "":
                    # Empty line in context — treat as context
                    if current_chunk is not None:
                        current_chunk.context.append("")
                else:
                    # Plain context line (no prefix)
                    if current_chunk is None:
                        current_chunk = PatchChunk()
                    current_chunk.context.append(ln)

                i += 1

            if current_chunk is not None:
                chunks.append(current_chunk)

            hunks.append(PatchHunk(
                type="update",
                path=path,
                move_path=move_path,
                chunks=chunks,
            ))
            continue

        # Unknown line — skip
        i += 1

    return hunks


# ---------------------------------------------------------------------------
# Applicator
# ---------------------------------------------------------------------------

def _apply_chunk(content: str, chunk: PatchChunk) -> str:
    """Apply a single update chunk to file content.

    Uses context lines to find the location, then removes deletions
    and inserts additions.
    """
    content_lines = content.split("\n")

    if not chunk.context and not chunk.deletions:
        # No context, no deletions — just append additions
        content_lines.extend(chunk.additions)
        return "\n".join(content_lines)

    # Find the anchor point using context lines
    anchor = -1
    search_lines = chunk.context if chunk.context else chunk.deletions

    if search_lines:
        search_text = search_lines[0].strip()
        for idx, line in enumerate(content_lines):
            if search_text and search_text in line.strip():
                anchor = idx
                break

    if anchor < 0 and chunk.deletions:
        # Try matching by deletion content
        del_text = chunk.deletions[0].strip()
        for idx, line in enumerate(content_lines):
            if del_text and del_text in line.strip():
                anchor = idx
                break

    if anchor < 0:
        # Fallback: append to end
        logger.warning("Could not find context anchor, appending to end")
        content_lines.extend(chunk.additions)
        return "\n".join(content_lines)

    # Position after context lines
    edit_pos = anchor + len(chunk.context)

    # Remove deletion lines starting from edit_pos
    if chunk.deletions:
        to_delete = list(chunk.deletions)
        scan_pos = edit_pos
        indices_to_remove = []

        while to_delete and scan_pos < len(content_lines):
            line_stripped = content_lines[scan_pos].strip()
            del_stripped = to_delete[0].strip()
            if line_stripped == del_stripped:
                indices_to_remove.append(scan_pos)
                to_delete.pop(0)
            scan_pos += 1
            # Don't scan too far
            if scan_pos > edit_pos + len(chunk.deletions) * 3:
                break

        # Remove matched lines in reverse order to preserve indices
        for idx in reversed(indices_to_remove):
            content_lines.pop(idx)

    # Insert addition lines at the edit position
    for j, add_line in enumerate(chunk.additions):
        content_lines.insert(edit_pos + j, add_line)

    return "\n".join(content_lines)


def apply_patch(
    patch_text: str,
    workspace_dir: str,
    snapshot_fn=None,
) -> PatchResult:
    """Parse and apply an OpenCode-style patch to workspace files.

    Args:
        patch_text: The full patch text.
        workspace_dir: Absolute path to the workspace root.
        snapshot_fn: Optional callback(path, old_content, new_content) for undo.

    Returns:
        PatchResult with operation summaries and any errors.
    """
    result = PatchResult(success=True)

    try:
        hunks = parse_patch(patch_text)
    except ValueError as e:
        return PatchResult(success=False, errors=[str(e)])

    if not hunks:
        return PatchResult(success=False, errors=["Empty patch — no file operations found"])

    real_ws = os.path.realpath(workspace_dir)

    for hunk in hunks:
        # Security: ensure path stays within workspace
        full_path = os.path.realpath(os.path.join(workspace_dir, hunk.path))
        if not full_path.startswith(real_ws):
            result.errors.append(f"Path '{hunk.path}' escapes workspace — skipped")
            continue

        try:
            if hunk.type == "add":
                # Create parent directories
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                old_content = ""
                if os.path.exists(full_path):
                    with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                        old_content = f.read()

                new_content = hunk.content
                if not new_content.endswith("\n"):
                    new_content += "\n"

                if snapshot_fn:
                    snapshot_fn(hunk.path, old_content, new_content)

                with open(full_path, "w", encoding="utf-8") as f:
                    f.write(new_content)

                result.operations.append({
                    "type": "add",
                    "path": hunk.path,
                    "status": "created",
                })
                logger.info("Patch: Added file %s", hunk.path)

            elif hunk.type == "delete":
                old_content = ""
                if os.path.exists(full_path):
                    with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                        old_content = f.read()
                    if snapshot_fn:
                        snapshot_fn(hunk.path, old_content, "")
                    os.remove(full_path)
                    result.operations.append({
                        "type": "delete",
                        "path": hunk.path,
                        "status": "deleted",
                    })
                    logger.info("Patch: Deleted file %s", hunk.path)
                else:
                    result.errors.append(f"File '{hunk.path}' not found for deletion")

            elif hunk.type == "update":
                if not os.path.exists(full_path):
                    result.errors.append(f"File '{hunk.path}' not found for update")
                    continue

                with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                    old_content = f.read()

                new_content = old_content
                for chunk in hunk.chunks:
                    new_content = _apply_chunk(new_content, chunk)

                if snapshot_fn:
                    snapshot_fn(hunk.path, old_content, new_content)

                # Handle move
                target_path = full_path
                if hunk.move_path:
                    target_path = os.path.realpath(
                        os.path.join(workspace_dir, hunk.move_path)
                    )
                    if not target_path.startswith(real_ws):
                        result.errors.append(
                            f"Move target '{hunk.move_path}' escapes workspace"
                        )
                        continue

                os.makedirs(os.path.dirname(target_path), exist_ok=True)
                with open(target_path, "w", encoding="utf-8") as f:
                    f.write(new_content)

                # Delete original if moved
                if hunk.move_path and full_path != target_path:
                    os.remove(full_path)

                op_type = "move" if hunk.move_path else "update"
                result.operations.append({
                    "type": op_type,
                    "path": hunk.path,
                    "target": hunk.move_path or hunk.path,
                    "status": "updated",
                })
                logger.info("Patch: Updated file %s", hunk.path)

        except Exception as e:
            result.errors.append(f"Failed to apply {hunk.type} on '{hunk.path}': {e}")
            result.success = False

    if result.errors and not result.operations:
        result.success = False

    return result
