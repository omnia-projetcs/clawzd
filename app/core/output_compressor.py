"""
Clawzd — Output Compression Engine.

Implements RTK-style token optimization (https://github.com/rtk-ai/rtk) as
pure Python functions applied to tool results before they enter LLM context.

Four strategies applied per output type:
  1. Smart Filtering — Remove noise (ANSI, whitespace, boilerplate)
  2. Grouping — Aggregate similar items (files by dir, errors by type)
  3. Truncation — Head+tail with ellipsis for long outputs
  4. Deduplication — Collapse repeated lines with counts
"""
import re
import logging
from collections import Counter

logger = logging.getLogger("clawzd.compressor")

# ---------------------------------------------------------------------------
# Shared utilities
# ---------------------------------------------------------------------------

# ANSI escape code pattern
_ANSI_RE = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]')

# Progress bar patterns (pip, npm, cargo, etc.)
_PROGRESS_RE = re.compile(r'[\|/\-\\]?\s*\d+%\s*[\|█▓▒░]*')

# Spinner/loading patterns
_SPINNER_RE = re.compile(r'^[\s]*[⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏|/\-\\]+\s*', re.MULTILINE)


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text."""
    return _ANSI_RE.sub('', text)


def _deduplicate_lines(lines: list[str], threshold: int = 2) -> list[str]:
    """Collapse consecutive identical lines into a single line with count.

    E.g. 5 identical "Installing foo..." → "(×5) Installing foo..."
    """
    if not lines:
        return lines

    result = []
    i = 0
    while i < len(lines):
        line = lines[i]
        count = 1
        while i + count < len(lines) and lines[i + count] == line:
            count += 1

        if count >= threshold:
            result.append(f"(×{count}) {line}")
        else:
            for _ in range(count):
                result.append(line)
        i += count

    return result


def _head_tail_truncate(
    lines: list[str],
    max_lines: int = 80,
    head: int = 40,
    tail: int = 30,
) -> list[str]:
    """Keep the first `head` and last `tail` lines, ellipsis in between."""
    if len(lines) <= max_lines:
        return lines
    hidden = len(lines) - head - tail
    return lines[:head] + [f"[... {hidden} lines hidden ...]"] + lines[-tail:]


def _strip_blank_lines(text: str) -> str:
    """Collapse multiple blank lines into a single one."""
    return re.sub(r'\n{3,}', '\n\n', text)


def _char_truncate(text: str, max_chars: int, tail_chars: int = 300) -> str:
    """Truncate text by character count, keeping head and tail."""
    if len(text) <= max_chars:
        return text
    head_chars = max_chars - tail_chars - 40
    return (
        text[:head_chars]
        + f"\n[... {len(text) - head_chars - tail_chars} chars hidden ...]\n"
        + text[-tail_chars:]
    )


# ---------------------------------------------------------------------------
# Command output compression (run_command)
# ---------------------------------------------------------------------------

# Git command patterns for compact output
_GIT_VERBOSE_PATTERNS = [
    # git push/pull progress
    re.compile(r'^(Enumerating|Counting|Compressing|Writing|Total|Delta|remote:)\s', re.MULTILINE),
    # git fetch progress
    re.compile(r'^(Unpacking|Receiving|Resolving)\s', re.MULTILINE),
]

# Package manager install patterns
_PKG_INSTALL_RE = re.compile(
    r'^\s*(Installing|Collecting|Downloading|Using cached|'
    r'Building wheel|Successfully built|'
    r'Requirement already|added \d+|'
    r'npm warn|npm notice)\s',
    re.IGNORECASE | re.MULTILINE,
)

# Test runner patterns
_TEST_SUMMARY_RE = re.compile(
    r'(\d+)\s+(passed|failed|error|skipped|warning)',
    re.IGNORECASE,
)


def compress_command_output(
    stdout: str,
    stderr: str = "",
    returncode: int = 0,
    command: str = "",
) -> str:
    """Compress shell command output using RTK strategies.

    Applies: ANSI stripping, dedup, grouping, truncation.
    Special handling for git, pip, npm, test runners.
    """
    stdout = _strip_ansi(stdout).strip()
    stderr = _strip_ansi(stderr).strip()

    # Detect the command base
    cmd_base = command.split()[0].split("/")[-1] if command else ""

    # --- Git compact output ---
    if cmd_base == "git" or command.startswith("git "):
        return _compress_git(stdout, stderr, returncode, command)

    # --- Package managers compact output ---
    if cmd_base in ("pip", "pip3", "npm", "pnpm", "yarn", "cargo", "bundle"):
        return _compress_package_manager(stdout, stderr, returncode, command)

    # --- Test runners ---
    if cmd_base in ("pytest", "jest", "vitest", "rspec") or "test" in command.lower():
        return _compress_test_output(stdout, stderr, returncode)

    # --- Docker commands ---
    if cmd_base in ("docker", "docker-compose", "kubectl"):
        return _compress_docker(stdout, stderr, returncode)

    # --- Generic command ---
    return _compress_generic_command(stdout, stderr, returncode)


def _compress_git(stdout: str, stderr: str, returncode: int, command: str) -> str:
    """RTK-style git output compression."""
    full = f"{stdout}\n{stderr}".strip()

    # git add/commit/push/pull → 1-line summary
    if "git push" in command or "git push" in command:
        # Extract branch name
        branch_match = re.search(r'(?:->|\.\.)\s*(\S+)', full)
        branch = branch_match.group(1) if branch_match else "main"
        if returncode == 0:
            return f"ok {branch}"
        return f"FAILED push to {branch}: {stderr[:200]}"

    if "git add" in command:
        return "ok" if returncode == 0 else f"FAILED: {stderr[:200]}"

    if "git commit" in command:
        sha_match = re.search(r'\[[\w/]+\s+([a-f0-9]+)\]', full)
        sha = sha_match.group(1) if sha_match else "?"
        if returncode == 0:
            return f"ok {sha}"
        return f"FAILED: {stderr[:200]}"

    if "git pull" in command:
        files_match = re.search(r'(\d+)\s+files?\s+changed', full)
        ins_match = re.search(r'(\d+)\s+insertions?', full)
        del_match = re.search(r'(\d+)\s+deletions?', full)
        files = files_match.group(1) if files_match else "0"
        ins = ins_match.group(1) if ins_match else "0"
        dels = del_match.group(1) if del_match else "0"
        if returncode == 0:
            if "Already up to date" in full:
                return "ok (already up to date)"
            return f"ok {files} files +{ins} -{dels}"
        return f"FAILED: {stderr[:200]}"

    # git status → compact
    if "git status" in command:
        return _compress_git_status(full)

    # git log → one-line per commit
    if "git log" in command:
        return _compress_git_log(full)

    # git diff → condensed
    if "git diff" in command:
        return _compress_diff(full)

    # Other git commands — generic compression
    return _compress_generic_command(stdout, stderr, returncode)


def _compress_git_status(text: str) -> str:
    """Compress git status to compact format."""
    lines = text.strip().split("\n")
    staged = []
    modified = []
    untracked = []
    current_section = None

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if "Changes to be committed" in line:
            current_section = "staged"
            continue
        if "Changes not staged" in line or "Changed but not updated" in line:
            current_section = "modified"
            continue
        if "Untracked files" in line:
            current_section = "untracked"
            continue
        if stripped.startswith("(use") or stripped.startswith("On branch") or stripped.startswith("Your branch"):
            # Keep branch info but skip help hints
            if stripped.startswith("On branch"):
                branch = stripped.replace("On branch ", "")
                modified.insert(0, f"branch: {branch}")
            continue

        # Extract the filename
        fname_match = re.search(r'(?:new file|modified|deleted|renamed):\s*(.+)', stripped)
        if fname_match:
            fname = fname_match.group(1).strip()
            if current_section == "staged":
                staged.append(fname)
            elif current_section == "modified":
                modified.append(fname)
        elif current_section == "untracked" and not stripped.startswith("("):
            untracked.append(stripped)

    parts = []
    if staged:
        parts.append(f"staged: {', '.join(staged[:10])}" + (f" +{len(staged)-10} more" if len(staged) > 10 else ""))
    if modified:
        parts.append(f"modified: {', '.join(modified[:10])}" + (f" +{len(modified)-10} more" if len(modified) > 10 else ""))
    if untracked:
        parts.append(f"untracked: {', '.join(untracked[:10])}" + (f" +{len(untracked)-10} more" if len(untracked) > 10 else ""))

    if not parts:
        return "clean (nothing to commit)"

    return "\n".join(parts)


def _compress_git_log(text: str) -> str:
    """Compress git log to one-line-per-commit format."""
    commits = []
    sha_re = re.compile(r'^commit\s+([a-f0-9]{7,})', re.MULTILINE)
    author_re = re.compile(r'^Author:\s+(.+)', re.MULTILINE)
    date_re = re.compile(r'^Date:\s+(.+)', re.MULTILINE)

    # Split into commit blocks
    blocks = re.split(r'^(?=commit\s+[a-f0-9])', text, flags=re.MULTILINE)
    for block in blocks:
        if not block.strip():
            continue
        sha_m = sha_re.search(block)
        sha = sha_m.group(1)[:7] if sha_m else "?"

        # Extract the commit message (first non-empty line after headers)
        msg_lines = []
        past_headers = False
        for line in block.split("\n"):
            if not past_headers:
                if line.strip() == "" and sha_m:
                    past_headers = True
                continue
            if line.strip():
                msg_lines.append(line.strip())
                break

        msg = msg_lines[0][:80] if msg_lines else "?"
        commits.append(f"{sha} {msg}")

    return "\n".join(commits[:20])  # Max 20 commits


def _compress_diff(text: str) -> str:
    """Compress diff output — keep file headers and changed lines only."""
    lines = text.split("\n")
    result = []
    file_stats = {}

    current_file = None
    for line in lines:
        if line.startswith("diff --git"):
            file_match = re.search(r'b/(.+)$', line)
            current_file = file_match.group(1) if file_match else "?"
            file_stats[current_file] = {"adds": 0, "dels": 0}
            result.append(f"\n--- {current_file} ---")
        elif line.startswith("@@"):
            result.append(line[:80])
        elif line.startswith("+") and not line.startswith("+++"):
            if current_file and current_file in file_stats:
                file_stats[current_file]["adds"] += 1
            result.append(line[:120])
        elif line.startswith("-") and not line.startswith("---"):
            if current_file and current_file in file_stats:
                file_stats[current_file]["dels"] += 1
            result.append(line[:120])

    # Add summary header
    total_adds = sum(f["adds"] for f in file_stats.values())
    total_dels = sum(f["dels"] for f in file_stats.values())
    header = f"{len(file_stats)} files changed, +{total_adds} -{total_dels}"

    # Truncate if very long
    output = header + "\n" + "\n".join(result)
    return _char_truncate(output, 3000)


def _compress_package_manager(
    stdout: str, stderr: str, returncode: int, command: str
) -> str:
    """Compress pip/npm/cargo install output to summary."""
    full = f"{stdout}\n{stderr}".strip()
    lines = full.split("\n")

    # Count installed packages
    installed = sum(1 for l in lines if re.match(r'^\s*(Installing|Successfully installed|added)', l, re.I))
    warnings = sum(1 for l in lines if "warn" in l.lower())

    if returncode == 0:
        parts = [f"ok ({installed} packages)" if installed else "ok"]
        if warnings:
            parts.append(f"{warnings} warnings")
        return " ".join(parts)

    # Failed — keep error lines only
    error_lines = [l for l in lines if any(kw in l.lower() for kw in ("error", "failed", "not found", "conflict"))]
    return "FAILED:\n" + "\n".join(error_lines[:10])


def _compress_test_output(stdout: str, stderr: str, returncode: int) -> str:
    """Compress test runner output — summary + failures only."""
    full = f"{stdout}\n{stderr}".strip()
    lines = full.split("\n")

    # Extract test summary line
    summary_match = _TEST_SUMMARY_RE.findall(full)
    if summary_match:
        summary = ", ".join(f"{count} {status}" for count, status in summary_match)
    else:
        # Count pass/fail manually
        passed = sum(1 for l in lines if re.search(r'\bPASS(ED)?\b|✓|ok\b', l, re.I))
        failed = sum(1 for l in lines if re.search(r'\bFAIL(ED)?\b|✗|ERRORS?\b', l, re.I))
        summary = f"{passed} passed, {failed} failed"

    if returncode == 0:
        return f"PASS: {summary}"

    # Failed — extract failure details
    failure_lines = []
    in_failure = False
    for line in lines:
        if re.search(r'FAIL|ERROR|AssertionError|assert|panic', line, re.I):
            in_failure = True
        if in_failure:
            failure_lines.append(line)
            if len(failure_lines) >= 30:
                break
        if in_failure and line.strip() == "":
            in_failure = False

    return f"FAILED: {summary}\n" + "\n".join(failure_lines[:30])


def _compress_docker(stdout: str, stderr: str, returncode: int) -> str:
    """Compress docker/kubectl output."""
    full = f"{stdout}\n{stderr}".strip()
    lines = full.split("\n")

    # Strip progress bars and pull layers
    lines = [l for l in lines if not re.match(r'^\s*[a-f0-9]+:\s*(Pulling|Waiting|Download|Extracting|Pull complete)', l)]

    # Deduplicate and truncate
    lines = _deduplicate_lines(lines)
    lines = _head_tail_truncate(lines, max_lines=40, head=20, tail=15)

    return "\n".join(lines)


def _compress_generic_command(stdout: str, stderr: str, returncode: int) -> str:
    """Generic command output compression."""
    full = stdout.strip()
    if stderr.strip():
        full += f"\n[stderr]: {stderr.strip()[:300]}"

    # Strip progress bars
    full = _PROGRESS_RE.sub('', full)
    full = _SPINNER_RE.sub('', full)

    lines = full.split("\n")
    # Truncate but keep it large enough
    lines = _head_tail_truncate(lines, max_lines=400, head=200, tail=150)

    result = "\n".join(lines)
    return result


# ---------------------------------------------------------------------------
# Search results compression
# ---------------------------------------------------------------------------

def compress_search_results(results: list[dict], max_results: int = 12) -> str:
    """Compress search results — keep a reasonable number of results and lengths."""
    if not results:
        return "No results."

    lines = []
    for i, r in enumerate(results[:max_results], 1):
        title = r.get("title", "N/A")[:150]
        snippet = r.get("snippet", "")[:500]
        url = r.get("url", "")
        lines.append(f"{i}. {title} ({url})")
        if snippet:
            lines.append(f"   {snippet}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# File content compression
# ---------------------------------------------------------------------------

def compress_file_content(content: str, file_path: str = "") -> str:
    """Compress file reading results based on file type."""
    ext = file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""

    # JSON files — show structure for large files
    if ext == "json" and len(content) > 2000:
        return _compress_json_structure(content)

    # Log files — dedup + tail
    if ext in ("log", "out"):
        return _compress_log_file(content)

    # Generic — head+tail, keeping a large window
    lines = content.split("\n")
    lines = _head_tail_truncate(lines, max_lines=1000, head=500, tail=400)
    return "\n".join(lines)


def _compress_json_structure(content: str) -> str:
    """Show JSON structure (keys + types) without values for large files."""
    import json
    try:
        data = json.loads(content)
        return _summarize_json_structure(data, max_depth=3)
    except json.JSONDecodeError:
        # Not valid JSON, fall back to truncation
        return _char_truncate(content, 2000)


def _summarize_json_structure(obj, depth: int = 0, max_depth: int = 3) -> str:
    """Recursively summarize JSON structure."""
    indent = "  " * depth
    if depth >= max_depth:
        if isinstance(obj, dict):
            return f"{{{len(obj)} keys}}"
        elif isinstance(obj, list):
            return f"[{len(obj)} items]"
        return str(type(obj).__name__)

    if isinstance(obj, dict):
        if not obj:
            return "{}"
        parts = []
        for k, v in list(obj.items())[:15]:  # Max 15 keys shown
            val_summary = _summarize_json_structure(v, depth + 1, max_depth)
            parts.append(f'{indent}  "{k}": {val_summary}')
        result = "{\n" + ",\n".join(parts)
        if len(obj) > 15:
            result += f"\n{indent}  ... +{len(obj)-15} more keys"
        result += f"\n{indent}}}"
        return result

    if isinstance(obj, list):
        if not obj:
            return "[]"
        if len(obj) == 1:
            return f"[{_summarize_json_structure(obj[0], depth + 1, max_depth)}]"
        first = _summarize_json_structure(obj[0], depth + 1, max_depth)
        return f"[{first}, ... ({len(obj)} items)]"

    if isinstance(obj, str):
        if len(obj) > 50:
            return f'"{obj[:30]}..." ({len(obj)} chars)'
        return f'"{obj}"'

    return str(obj)


def _compress_log_file(content: str) -> str:
    """Compress log files — dedup repeated lines, keep tail."""
    lines = content.split("\n")
    # Deduplicate
    lines = _deduplicate_lines(lines, threshold=3)
    # Keep tail (most recent entries are most relevant)
    if len(lines) > 60:
        return "[... older entries hidden ...]\n" + "\n".join(lines[-50:])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Browse web compression
# ---------------------------------------------------------------------------

# HTML boilerplate patterns to strip
_WEB_NOISE_PATTERNS = [
    re.compile(r'(Cookie|Privacy|Terms|GDPR|Accept all|Reject all|We use cookies)[^\n]*', re.I),
    re.compile(r'(Sign in|Sign up|Log in|Register|Subscribe)[^\n]*', re.I),
    re.compile(r'(©|Copyright|All rights reserved)[^\n]*', re.I),
    re.compile(r'^\s*(Home|About|Contact|FAQ|Help|Support)\s*$', re.I | re.MULTILINE),
    re.compile(r'^\s*\|\s*$', re.MULTILINE),  # separator pipes
]


def compress_browse_result(text: str, max_chars: int = 2000) -> str:
    """Compress browse_web result — strip boilerplate, truncate."""
    if not text:
        return ""

    # Strip noise patterns
    for pattern in _WEB_NOISE_PATTERNS:
        text = pattern.sub('', text)

    # Collapse whitespace
    text = _strip_blank_lines(text)
    text = re.sub(r'[ \t]{3,}', '  ', text)

    # Remove very short lines (nav items, menu items)
    lines = text.split("\n")
    lines = [l for l in lines if len(l.strip()) > 5 or l.strip() == ""]

    text = "\n".join(lines)
    return _char_truncate(text, max_chars)


# ---------------------------------------------------------------------------
# Code execution compression
# ---------------------------------------------------------------------------

def compress_code_execution(
    stdout: str,
    stderr: str = "",
    images: list = None,
    returncode: int = 0,
) -> str:
    """Compress execute_python results."""
    stdout = _strip_ansi(stdout).strip()
    stderr = _strip_ansi(stderr).strip()

    if returncode != 0:
        # Error — keep full stderr but truncate
        error = stderr or stdout
        return f"ERROR (exit {returncode}):\n{_char_truncate(error, 1500)}"

    parts = []

    if stdout:
        lines = stdout.split("\n")
        # Deduplicate
        lines = _deduplicate_lines(lines)
        # Truncate
        lines = _head_tail_truncate(lines, max_lines=50, head=25, tail=15)
        parts.append("\n".join(lines))

    if stderr:
        parts.append(f"[stderr]: {stderr[:300]}")

    if images:
        parts.append(f"{len(images)} chart(s) generated.")

    return "\n".join(parts) if parts else "ok (no output)"


# ---------------------------------------------------------------------------
# Generic compression fallback
# ---------------------------------------------------------------------------

def compress_generic(text: str, max_chars: int = 1500) -> str:
    """Generic fallback compression for any tool result."""
    if not text or len(text) <= max_chars:
        return text

    text = _strip_ansi(text)
    lines = text.split("\n")
    lines = [l for l in lines if l.strip()]
    lines = _deduplicate_lines(lines)
    lines = _head_tail_truncate(lines, max_lines=60, head=30, tail=20)

    result = "\n".join(lines)
    return _char_truncate(result, max_chars)
