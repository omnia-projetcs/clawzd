"""
Clawzd — Workspace Git operations router.

Extracted from gateway.py. Handles git status, log, show, diff,
clone, add, commit, push, pull, and ZIP export.
"""
import io
import os
import subprocess as _sp
import zipfile
import logging

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse

from config import WORKSPACE_DIR

logger = logging.getLogger("clawzd.workspace_git")
router = APIRouter()

_WORKSPACE_DIR = WORKSPACE_DIR


def _safe_workspace_path(rel_path: str) -> str:
    base = os.path.realpath(_WORKSPACE_DIR)
    full = os.path.realpath(os.path.join(base, rel_path))
    if not full.startswith(base):
        raise HTTPException(403, "Path traversal not allowed")
    return full


def _git_run(args, cwd=None, timeout=30, env_extra=None):
    """Run a git command in workspace and return (ok, stdout, stderr)."""
    base = os.path.realpath(_WORKSPACE_DIR)
    work = cwd or base
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    if env_extra:
        env.update(env_extra)
    try:
        r = _sp.run(["git"] + args, capture_output=True, text=True,
                     timeout=timeout, cwd=work, env=env)
        return r.returncode == 0, r.stdout.strip(), r.stderr.strip()
    except _sp.TimeoutExpired:
        return False, "", "Command timed out"
    except FileNotFoundError:
        return False, "", "git is not installed"
    except Exception as e:
        return False, "", str(e)


def _find_git_root():
    """Find the first git repo inside workspace (or workspace itself)."""
    base = os.path.realpath(_WORKSPACE_DIR)
    if os.path.isdir(os.path.join(base, ".git")):
        return base
    for d in sorted(os.listdir(base)):
        full = os.path.join(base, d)
        if os.path.isdir(full) and os.path.isdir(os.path.join(full, ".git")):
            return full
    return None


@router.post("/git-clone")
async def workspace_git_clone(request: Request):
    """Clone a git repository into the workspace."""
    data = await request.json()
    url = data.get("url", "").strip()
    folder = data.get("folder", "").strip()
    branch = data.get("branch", "").strip()
    username = data.get("username", "").strip()
    token = data.get("token", "").strip()
    if not url:
        raise HTTPException(400, "Repository URL is required")
    base = os.path.realpath(_WORKSPACE_DIR)
    os.makedirs(base, exist_ok=True)
    clone_url = url
    if username and token and url.startswith("https://"):
        clone_url = url.replace("https://", f"https://{username}:{token}@", 1)
    elif token and url.startswith("https://"):
        clone_url = url.replace("https://", f"https://{token}@", 1)
    cmd = ["git", "clone", "--progress"]
    if branch:
        cmd += ["-b", branch]
    cmd.append(clone_url)
    if folder:
        folder = folder.replace("..", "").replace("/", "_").strip()
        cmd.append(folder)
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    try:
        result = _sp.run(cmd, capture_output=True, text=True, timeout=120, cwd=base, env=env)
        if result.returncode != 0:
            error_msg = result.stderr or result.stdout or "Unknown git error"
            if token:
                error_msg = error_msg.replace(token, "***")
            if username:
                error_msg = error_msg.replace(f"{username}:", "***:")
            return {"status": "error", "error": error_msg.strip()}
        output = (result.stdout + "\n" + result.stderr).strip()
        if token:
            output = output.replace(token, "***")
        return {"status": "ok", "message": "Repository cloned successfully", "output": output}
    except _sp.TimeoutExpired:
        return {"status": "error", "error": "Clone timed out after 120s"}
    except FileNotFoundError:
        return {"status": "error", "error": "git is not installed on this system"}
    except Exception as e:
        msg = str(e)
        if token:
            msg = msg.replace(token, "***")
        return {"status": "error", "error": msg}


@router.get("/git-status")
async def workspace_git_status():
    """Get git status: branch, changed files, ahead/behind."""
    repo = _find_git_root()
    if not repo:
        return {"has_repo": False}
    base = os.path.realpath(_WORKSPACE_DIR)
    repo_name = os.path.relpath(repo, base) if repo != base else "."
    ok, branch, _ = _git_run(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo)
    if not ok:
        branch = "unknown"
    _, remote_url, _ = _git_run(["remote", "get-url", "origin"], cwd=repo)
    ahead, behind = 0, 0
    ok2, ab, _ = _git_run(["rev-list", "--left-right", "--count", f"HEAD...origin/{branch}"], cwd=repo)
    if ok2 and ab:
        parts = ab.split()
        if len(parts) == 2:
            ahead, behind = int(parts[0]), int(parts[1])
    _, status_out, _ = _git_run(["status", "--porcelain", "-u"], cwd=repo)
    files = []
    for line in status_out.split("\n"):
        if not line.strip():
            continue
        xy = line[:2]
        path = line[3:]
        idx = xy[0] if xy[0] != " " else ""
        staged = idx in ("M", "A", "D", "R", "C")
        status = "modified"
        if "A" in xy or "?" in xy:
            status = "added"
        elif "D" in xy:
            status = "deleted"
        elif "R" in xy:
            status = "renamed"
        files.append({"path": path, "status": status, "staged": staged, "index": idx, "working": xy[1] if xy[1] != " " else ""})
    return {"has_repo": True, "repo": repo_name, "branch": branch, "remote_url": remote_url or "", "ahead": ahead, "behind": behind, "files": files}


@router.get("/git-log")
async def workspace_git_log(limit: int = 60):
    """Get commit log with parent info for graph rendering."""
    repo = _find_git_root()
    if not repo:
        return {"commits": []}
    fmt = "%H|%h|%P|%an|%ai|%s|%D"
    ok, out, _ = _git_run(["log", f"-{limit}", f"--format={fmt}", "--all", "--topo-order"], cwd=repo, timeout=15)
    if not ok:
        return {"commits": []}
    commits = []
    for line in out.split("\n"):
        if not line.strip():
            continue
        parts = line.split("|", 6)
        if len(parts) < 7:
            continue
        parents = parts[2].split() if parts[2] else []
        refs_raw = parts[6].strip()
        refs = []
        if refs_raw:
            for ref in refs_raw.split(", "):
                ref = ref.strip()
                if ref.startswith("HEAD -> "):
                    refs.append({"type": "head", "name": ref[8:]})
                elif ref == "HEAD":
                    refs.append({"type": "head", "name": "HEAD"})
                elif ref.startswith("origin/"):
                    refs.append({"type": "remote", "name": ref})
                elif ref.startswith("tag: "):
                    refs.append({"type": "tag", "name": ref[5:]})
                else:
                    refs.append({"type": "branch", "name": ref})
        commits.append({"hash": parts[0], "short": parts[1], "parents": parents, "author": parts[3], "date": parts[4], "subject": parts[5], "refs": refs})
    _, branches_out, _ = _git_run(["branch", "-a", "--format=%(refname:short)"], cwd=repo)
    branches = [b.strip() for b in branches_out.split("\n") if b.strip()]
    return {"commits": commits, "branches": branches}


@router.get("/git-show")
async def workspace_git_show(commit: str = "HEAD"):
    """Get changed files and stats for a specific commit."""
    import re
    repo = _find_git_root()
    if not repo:
        return {"error": "No git repo"}
    if not re.match(r'^[a-fA-F0-9]{4,40}$', commit) and commit != 'HEAD':
        return {"error": "Invalid commit hash"}
    ok, out, _ = _git_run(["show", "--stat", "--format=%H|%h|%an|%ae|%ai|%s|%b", commit], cwd=repo, timeout=10)
    if not ok:
        return {"error": "Cannot read commit"}
    lines = out.strip().split("\n")
    if not lines:
        return {"error": "Empty output"}
    header = lines[0].split("|", 6)
    info = {"hash": header[0] if len(header) > 0 else "", "short": header[1] if len(header) > 1 else "", "author": header[2] if len(header) > 2 else "", "email": header[3] if len(header) > 3 else "", "date": header[4] if len(header) > 4 else "", "subject": header[5] if len(header) > 5 else "", "body": header[6].strip() if len(header) > 6 else ""}
    files = []
    for line in lines[1:]:
        line = line.strip()
        if not line or line.startswith("---"):
            continue
        if "|" in line:
            parts = line.split("|", 1)
            fname = parts[0].strip()
            stat = parts[1].strip() if len(parts) > 1 else ""
            adds = stat.count("+")
            dels = stat.count("-")
            num = ""
            for ch in stat:
                if ch.isdigit():
                    num += ch
                else:
                    break
            files.append({"name": fname, "changes": int(num) if num else 0, "additions": adds, "deletions": dels, "stat": stat})
        elif "changed" in line:
            info["summary"] = line
    info["files"] = files
    return info


@router.get("/git-file-diff")
async def workspace_git_file_diff(commit: str, path: str):
    """Get before/after content of a file for a specific commit."""
    import re
    repo = _find_git_root()
    if not repo:
        return {"error": "No git repo"}
    if not re.match(r'^[a-fA-F0-9]{4,40}$', commit) and commit != 'HEAD':
        return {"error": "Invalid commit hash"}
    ok_after, after_content, _ = _git_run(["show", f"{commit}:{path}"], cwd=repo, timeout=10)
    ok_before, before_content, _ = _git_run(["show", f"{commit}~1:{path}"], cwd=repo, timeout=10)
    ok_diff, diff_content, _ = _git_run(["diff", f"{commit}~1", commit, "--", path], cwd=repo, timeout=10)
    return {"path": path, "commit": commit, "before": before_content if ok_before else "", "after": after_content if ok_after else "", "diff": diff_content if ok_diff else "", "is_new": not ok_before, "is_deleted": not ok_after}


@router.post("/git-add")
async def workspace_git_add(request: Request):
    """Stage files for commit."""
    data = await request.json()
    paths = data.get("paths", [])
    all_flag = data.get("all", False)
    repo = _find_git_root()
    if not repo:
        return {"status": "error", "error": "No git repository found"}
    if all_flag:
        ok, out, err = _git_run(["add", "-A"], cwd=repo)
    else:
        ok, out, err = _git_run(["add", "--"] + paths, cwd=repo)
    return {"status": "ok" if ok else "error", "error": err if not ok else ""}


@router.post("/git-commit")
async def workspace_git_commit(request: Request):
    """Commit staged changes."""
    data = await request.json()
    message = data.get("message", "").strip()
    if not message:
        return {"status": "error", "error": "Commit message is required"}
    repo = _find_git_root()
    if not repo:
        return {"status": "error", "error": "No git repository found"}
    ok, out, err = _git_run(["commit", "-m", message], cwd=repo)
    return {"status": "ok" if ok else "error", "output": out, "error": err if not ok else ""}


@router.post("/git-push")
async def workspace_git_push(request: Request):
    """Push commits to remote."""
    data = await request.json()
    remote = data.get("remote", "origin")
    branch = data.get("branch", "")
    force = data.get("force", False)
    token = data.get("token", "").strip()
    username = data.get("username", "").strip()
    repo = _find_git_root()
    if not repo:
        return {"status": "error", "error": "No git repository found"}
    original_url = None
    if token:
        _, original_url, _ = _git_run(["remote", "get-url", remote], cwd=repo)
        if original_url and original_url.startswith("https://"):
            auth_url = original_url.replace("https://", f"https://{username}:{token}@" if username else f"https://{token}@", 1)
            _git_run(["remote", "set-url", remote, auth_url], cwd=repo)
    cmd = ["push", remote]
    if branch:
        cmd.append(branch)
    if force:
        cmd.append("--force")
    ok, out, err = _git_run(cmd, cwd=repo, timeout=60)
    if original_url and token:
        _git_run(["remote", "set-url", remote, original_url], cwd=repo)
    combined = (out + "\n" + err).strip()
    if token:
        combined = combined.replace(token, "***")
    return {"status": "ok" if ok else "error", "output": combined, "error": (err.replace(token, "***") if token else err) if not ok else ""}


@router.post("/git-pull")
async def workspace_git_pull(request: Request):
    """Pull from remote."""
    data = await request.json()
    remote = data.get("remote", "origin")
    branch = data.get("branch", "")
    token = data.get("token", "").strip()
    username = data.get("username", "").strip()
    repo = _find_git_root()
    if not repo:
        return {"status": "error", "error": "No git repository found"}
    original_url = None
    if token:
        _, original_url, _ = _git_run(["remote", "get-url", remote], cwd=repo)
        if original_url and original_url.startswith("https://"):
            auth_url = original_url.replace("https://", f"https://{username}:{token}@" if username else f"https://{token}@", 1)
            _git_run(["remote", "set-url", remote, auth_url], cwd=repo)
    cmd = ["pull", remote]
    if branch:
        cmd.append(branch)
    ok, out, err = _git_run(cmd, cwd=repo, timeout=60)
    if original_url and token:
        _git_run(["remote", "set-url", remote, original_url], cwd=repo)
    combined = (out + "\n" + err).strip()
    if token:
        combined = combined.replace(token, "***")
    return {"status": "ok" if ok else "error", "output": combined, "error": (err.replace(token, "***") if token else err) if not ok else ""}


@router.get("/git-diff")
async def workspace_git_diff(path: str = "", staged: bool = False):
    """Get diff for a specific file or all changes."""
    repo = _find_git_root()
    if not repo:
        return {"diff": "", "error": "No git repository found"}
    cmd = ["diff"]
    if staged:
        cmd.append("--cached")
    cmd += ["--no-color"]
    if path:
        cmd += ["--", path]
    ok, out, err = _git_run(cmd, cwd=repo, timeout=15)
    return {"diff": out, "error": err if not ok else ""}


@router.get("/export-zip")
async def workspace_export_zip(project: str = "."):
    """Bundle a project or the workspace into a downloadable ZIP archive."""
    base = os.path.realpath(_WORKSPACE_DIR)
    target_dir = base
    if project and project != ".":
        project = project.replace("..", "").replace("/", "_").replace("\\", "_").strip()
        target_dir = os.path.realpath(os.path.join(base, project))
        if not target_dir.startswith(base):
            raise HTTPException(403, "Invalid project path")
    if not os.path.isdir(target_dir):
        raise HTTPException(404, "Project directory not found")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(target_dir):
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            for file in files:
                if file.startswith('.'):
                    continue
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, target_dir)
                zf.write(full_path, rel_path)
    buf.seek(0)
    filename = f"{project if project != '.' else 'workspace'}_export.zip"
    return StreamingResponse(buf, media_type="application/zip", headers={"Content-Disposition": f"attachment; filename={filename}"})
