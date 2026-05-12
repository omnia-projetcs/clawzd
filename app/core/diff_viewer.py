"""
Clawzd — Inline Diff Viewer backend.

Provides structured git diff data for the frontend diff viewer.
Supports both workspace and project-specific diffs.
"""
import os
import subprocess
import logging

logger = logging.getLogger("clawzd.diff_viewer")


def _run_git(args: list[str], cwd: str) -> tuple[int, str, str]:
    """Run a git command and return (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=15,
        )
        return result.returncode, result.stdout, result.stderr
    except FileNotFoundError:
        return -1, "", "git not installed"
    except subprocess.TimeoutExpired:
        return -2, "", "git command timed out"


def is_git_repo(path: str) -> bool:
    """Check if a directory is inside a git repository."""
    code, _, _ = _run_git(["rev-parse", "--is-inside-work-tree"], path)
    return code == 0


def get_diff(project_path: str, staged: bool = False) -> dict:
    """Get the git diff for a project.

    Returns structured diff data with file-level hunks.

    Args:
        project_path: path to the git repository
        staged: if True, show staged changes only (--cached)
    """
    if not os.path.isdir(project_path):
        return {"error": f"Path not found: {project_path}"}

    if not is_git_repo(project_path):
        return {"error": "Not a git repository", "path": project_path}

    # Get diff
    diff_args = ["diff", "--no-color", "--unified=3"]
    if staged:
        diff_args.append("--cached")
    code, stdout, stderr = _run_git(diff_args, project_path)
    if code != 0:
        return {"error": f"git diff failed: {stderr}"}

    # Get status summary
    code2, status_out, _ = _run_git(["status", "--porcelain"], project_path)
    status_files = []
    if code2 == 0:
        for line in status_out.strip().split("\n"):
            if line.strip():
                status_code = line[:2].strip()
                fname = line[3:].strip()
                status_files.append({
                    "status": status_code,
                    "file": fname,
                })

    # Parse diff into structured format
    files = _parse_diff(stdout) if stdout.strip() else []

    # Stats
    total_additions = sum(f.get("additions", 0) for f in files)
    total_deletions = sum(f.get("deletions", 0) for f in files)

    return {
        "path": project_path,
        "staged": staged,
        "files": files,
        "status_files": status_files,
        "stats": {
            "files_changed": len(files),
            "additions": total_additions,
            "deletions": total_deletions,
        },
        "raw_diff": stdout[:50000] if len(stdout) > 50000 else stdout,
    }


def _parse_diff(raw_diff: str) -> list[dict]:
    """Parse unified diff output into structured file-level data."""
    files = []
    current_file = None
    current_hunks = []
    current_hunk = None

    for line in raw_diff.split("\n"):
        if line.startswith("diff --git"):
            # Save previous file
            if current_file:
                if current_hunk:
                    current_hunks.append(current_hunk)
                current_file["hunks"] = current_hunks
                files.append(current_file)

            # Parse file name
            parts = line.split(" b/")
            fname = parts[-1] if len(parts) > 1 else line
            current_file = {
                "file": fname,
                "hunks": [],
                "additions": 0,
                "deletions": 0,
            }
            current_hunks = []
            current_hunk = None

        elif line.startswith("@@") and current_file:
            if current_hunk:
                current_hunks.append(current_hunk)
            current_hunk = {
                "header": line,
                "lines": [],
            }

        elif current_hunk is not None:
            if line.startswith("+") and not line.startswith("+++"):
                current_hunk["lines"].append({"type": "add", "content": line[1:]})
                if current_file:
                    current_file["additions"] += 1
            elif line.startswith("-") and not line.startswith("---"):
                current_hunk["lines"].append({"type": "del", "content": line[1:]})
                if current_file:
                    current_file["deletions"] += 1
            else:
                current_hunk["lines"].append({"type": "ctx", "content": line.lstrip(" ")})

    # Save last file
    if current_file:
        if current_hunk:
            current_hunks.append(current_hunk)
        current_file["hunks"] = current_hunks
        files.append(current_file)

    return files


def stage_file(project_path: str, file_path: str) -> dict:
    """Stage a specific file."""
    code, _, stderr = _run_git(["add", file_path], project_path)
    if code != 0:
        return {"error": f"git add failed: {stderr}"}
    return {"status": "staged", "file": file_path}


def unstage_file(project_path: str, file_path: str) -> dict:
    """Unstage a specific file."""
    code, _, stderr = _run_git(["reset", "HEAD", file_path], project_path)
    if code != 0:
        return {"error": f"git reset failed: {stderr}"}
    return {"status": "unstaged", "file": file_path}


def revert_file(project_path: str, file_path: str) -> dict:
    """Revert a file to its last committed state."""
    code, _, stderr = _run_git(["checkout", "--", file_path], project_path)
    if code != 0:
        return {"error": f"git checkout failed: {stderr}"}
    return {"status": "reverted", "file": file_path}
