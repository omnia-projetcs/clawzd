"""
Clawzd — Spec-Driven Development Engine.
Implements OpenSpec-inspired change management with artifact dependency
graphs, AI generation, delta spec tracking, structured verification,
and archival with audit trail.
"""
import os
import json
import uuid
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Request, HTTPException

from config import DATA_DIR

router = APIRouter()
logger = logging.getLogger("clawzd.spec")

SPECS_BASE = os.path.join(DATA_DIR, "specs")
os.makedirs(SPECS_BASE, exist_ok=True)

# ── Artifact schema (spec-driven default) ──

SCHEMA_SPEC_DRIVEN = {
    "name": "spec-driven",
    "artifacts": [
        {"id": "proposal", "generates": "proposal.md", "requires": []},
        {"id": "specs", "generates": "specs.md", "requires": ["proposal"]},
        {"id": "design", "generates": "design.md", "requires": ["proposal"]},
        {"id": "tasks", "generates": "tasks.md", "requires": ["specs", "design"]},
    ],
}


# ── Helpers ──

def _proj_specs_dir(proj_id: str) -> str:
    d = os.path.join(SPECS_BASE, proj_id)
    os.makedirs(d, exist_ok=True)
    return d


def _changes_dir(proj_id: str) -> str:
    d = os.path.join(_proj_specs_dir(proj_id), "changes")
    os.makedirs(d, exist_ok=True)
    return d


def _archive_dir(proj_id: str) -> str:
    d = os.path.join(_proj_specs_dir(proj_id), "archive")
    os.makedirs(d, exist_ok=True)
    return d


def _main_specs_file(proj_id: str) -> str:
    return os.path.join(_proj_specs_dir(proj_id), "main_specs.md")


def _change_path(proj_id: str, change_id: str) -> str:
    return os.path.join(_changes_dir(proj_id), f"{change_id}.json")


def _load_change(proj_id: str, change_id: str) -> Optional[dict]:
    p = _change_path(proj_id, change_id)
    if os.path.exists(p):
        with open(p) as f:
            return json.load(f)
    return None


def _save_change(proj_id: str, change: dict):
    change["updated_at"] = datetime.now(timezone.utc).isoformat()
    with open(_change_path(proj_id, change["id"]), "w") as f:
        json.dump(change, f, indent=2, ensure_ascii=False)


def _new_change(name: str, description: str = "") -> dict:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "id": "chg-" + str(uuid.uuid4())[:8],
        "name": name,
        "description": description,
        "status": "draft",
        "schema": "spec-driven",
        "created_at": now,
        "updated_at": now,
        "artifacts": {
            "proposal": {"status": "ready", "content": ""},
            "specs": {"status": "blocked", "content": ""},
            "design": {"status": "blocked", "content": ""},
            "tasks": {"status": "blocked", "content": ""},
        },
        "verification": None,
        "archived_at": None,
    }


# ── DAG Engine ──

def _compute_dag_status(artifacts: dict) -> dict:
    """Recompute artifact statuses based on dependency graph."""
    schema = SCHEMA_SPEC_DRIVEN["artifacts"]
    dep_map = {a["id"]: a["requires"] for a in schema}
    updated = dict(artifacts)

    for art_def in schema:
        aid = art_def["id"]
        art = updated.get(aid, {"status": "blocked", "content": ""})
        if art.get("content"):
            art["status"] = "done"
        else:
            deps = dep_map.get(aid, [])
            all_done = all(
                updated.get(d, {}).get("content") for d in deps
            )
            art["status"] = "ready" if (not deps or all_done) else "blocked"
        updated[aid] = art

    return updated


# ── Change CRUD ──

@router.get("/projects/{proj_id}/changes")
async def list_changes(proj_id: str):
    """List all active changes for a project."""
    d = _changes_dir(proj_id)
    changes = []
    for fname in os.listdir(d):
        if fname.endswith(".json"):
            try:
                with open(os.path.join(d, fname)) as f:
                    data = json.load(f)
                    arts = data.get("artifacts", {})
                    done = sum(1 for a in arts.values() if a.get("content"))
                    changes.append({
                        "id": data["id"],
                        "name": data.get("name", ""),
                        "status": data.get("status", "draft"),
                        "artifacts_done": done,
                        "artifacts_total": len(arts),
                        "created_at": data.get("created_at", ""),
                        "updated_at": data.get("updated_at", ""),
                    })
            except Exception:
                pass
    changes.sort(key=lambda c: c.get("updated_at", ""), reverse=True)
    return {"changes": changes}


@router.post("/projects/{proj_id}/changes")
async def create_change(proj_id: str, request: Request):
    """Create a new change."""
    data = await request.json()
    change = _new_change(
        name=data.get("name", "New Change"),
        description=data.get("description", ""),
    )
    _save_change(proj_id, change)
    return {"status": "created", "change": change}


@router.get("/projects/{proj_id}/changes/{change_id}")
async def get_change(proj_id: str, change_id: str):
    """Get full change details."""
    change = _load_change(proj_id, change_id)
    if not change:
        raise HTTPException(404, "Change not found")
    change["artifacts"] = _compute_dag_status(change.get("artifacts", {}))
    return {"change": change}


@router.delete("/projects/{proj_id}/changes/{change_id}")
async def delete_change(proj_id: str, change_id: str):
    """Delete a change."""
    p = _change_path(proj_id, change_id)
    if os.path.exists(p):
        os.remove(p)
    return {"status": "deleted"}


# ── DAG Status ──

@router.get("/projects/{proj_id}/changes/{change_id}/status")
async def change_status(proj_id: str, change_id: str):
    """Get artifact dependency graph status."""
    change = _load_change(proj_id, change_id)
    if not change:
        raise HTTPException(404, "Change not found")

    artifacts = _compute_dag_status(change.get("artifacts", {}))
    schema = SCHEMA_SPEC_DRIVEN["artifacts"]
    dep_map = {a["id"]: a["requires"] for a in schema}

    graph = []
    for art_def in schema:
        aid = art_def["id"]
        art = artifacts.get(aid, {})
        graph.append({
            "id": aid,
            "status": art.get("status", "blocked"),
            "has_content": bool(art.get("content")),
            "requires": dep_map.get(aid, []),
        })

    return {"graph": graph, "change_status": change.get("status", "draft")}


# ── Artifact CRUD ──

@router.put("/projects/{proj_id}/changes/{change_id}/artifacts/{artifact}")
async def update_artifact(proj_id: str, change_id: str, artifact: str, request: Request):
    """Update an artifact's content."""
    change = _load_change(proj_id, change_id)
    if not change:
        raise HTTPException(404, "Change not found")

    valid_ids = {a["id"] for a in SCHEMA_SPEC_DRIVEN["artifacts"]}
    if artifact not in valid_ids:
        raise HTTPException(400, f"Invalid artifact: {artifact}")

    data = await request.json()
    content = data.get("content", "")

    change["artifacts"][artifact]["content"] = content
    change["artifacts"] = _compute_dag_status(change["artifacts"])

    # Update change status
    all_done = all(a.get("content") for a in change["artifacts"].values())
    if all_done:
        change["status"] = "ready"
    elif any(a.get("content") for a in change["artifacts"].values()):
        change["status"] = "in-progress"

    _save_change(proj_id, change)
    return {"status": "updated", "artifact": artifact}


# ── AI Generation ──

_GENERATION_PROMPTS = {
    "proposal": (
        "You are a project planning AI. Generate a structured PROPOSAL "
        "document in Markdown for the following change.\n\n"
        "Include these sections:\n"
        "1. ## Intent — What problem are we solving?\n"
        "2. ## Scope — In scope / Out of scope\n"
        "3. ## Approach — High-level approach\n\n"
        "Be concise but thorough. Return only the Markdown."
    ),
    "specs": (
        "You are a specification writer. Based on the PROPOSAL below, "
        "generate a SPECIFICATION document using the delta format.\n\n"
        "Use these sections:\n"
        "## ADDED Requirements\n"
        "### Requirement: [Name]\n"
        "Description with SHALL/MUST/SHOULD keywords.\n"
        "#### Scenario: [Name]\n"
        "- GIVEN ...\n- WHEN ...\n- THEN ...\n\n"
        "## MODIFIED Requirements (if applicable)\n"
        "## REMOVED Requirements (if applicable)\n\n"
        "Be precise and testable. Return only Markdown."
    ),
    "design": (
        "You are a technical architect. Based on the PROPOSAL and SPECS "
        "below, generate a DESIGN document.\n\n"
        "Include:\n"
        "1. ## Technical Approach\n"
        "2. ## Architecture Decisions (with rationale)\n"
        "3. ## Data Flow (use text diagrams)\n"
        "4. ## File Changes (list of files to create/modify)\n\n"
        "Return only Markdown."
    ),
    "tasks": (
        "You are a project manager. Based on the PROPOSAL, SPECS, and "
        "DESIGN below, generate a TASKS checklist.\n\n"
        "Format:\n"
        "## 1. [Group Name]\n"
        "- [ ] 1.1 Task description\n"
        "- [ ] 1.2 Task description\n\n"
        "Group related tasks. Use hierarchical numbering. "
        "Keep tasks small (1-2 hours each). Return only Markdown."
    ),
}


@router.post("/projects/{proj_id}/changes/{change_id}/generate/{artifact}")
async def generate_artifact(
    proj_id: str, change_id: str, artifact: str, request: Request,
):
    """AI-generate an artifact based on dependencies."""
    change = _load_change(proj_id, change_id)
    if not change:
        raise HTTPException(404, "Change not found")

    if artifact not in _GENERATION_PROMPTS:
        raise HTTPException(400, f"Invalid artifact: {artifact}")

    # Check dependencies
    schema = SCHEMA_SPEC_DRIVEN["artifacts"]
    dep_map = {a["id"]: a["requires"] for a in schema}
    deps = dep_map.get(artifact, [])

    for dep in deps:
        if not change["artifacts"].get(dep, {}).get("content"):
            raise HTTPException(
                400, f"Dependency '{dep}' must be completed first"
            )

    # Build context from dependencies
    context_parts = [f"# Change: {change['name']}"]
    if change.get("description"):
        context_parts.append(f"Description: {change['description']}")

    for dep in deps:
        dep_content = change["artifacts"][dep]["content"]
        context_parts.append(f"\n---\n## {dep.upper()}\n{dep_content}")

    # Also include existing main specs if available
    main_specs_path = _main_specs_file(proj_id)
    if os.path.exists(main_specs_path):
        with open(main_specs_path) as f:
            existing = f.read()
        if existing.strip():
            context_parts.append(
                f"\n---\n## EXISTING PROJECT SPECS\n{existing[:3000]}"
            )

    from app.llm_provider import get_llm_provider

    data = await request.json() if request.headers.get("content-type") == "application/json" else {}
    provider_key = data.get("provider", "")
    model_key = data.get("model", "")

    provider = get_llm_provider(provider_key or None)

    messages = [
        {"role": "system", "content": _GENERATION_PROMPTS[artifact]},
        {"role": "user", "content": "\n\n".join(context_parts)},
    ]

    kwargs = {}
    if model_key:
        kwargs["model"] = model_key

    input_text = "\n".join(m["content"] for m in messages)
    input_tokens = max(1, len(input_text) // 4)
    t0 = time.time()

    response_text = ""
    async for chunk in provider.chat_stream(messages, **kwargs):
        response_text += chunk

    elapsed = time.time() - t0
    output_tokens = max(1, len(response_text) // 4)

    # Record in metrics
    from app.metrics import get_metrics
    get_metrics().record_llm_call(
        provider=provider_key or "default",
        model=model_key or "default",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_s=elapsed,
        session_id=f"spec:{proj_id}",
    )

    # Save the generated content
    change["artifacts"][artifact]["content"] = response_text
    change["artifacts"] = _compute_dag_status(change["artifacts"])

    all_done = all(a.get("content") for a in change["artifacts"].values())
    if all_done:
        change["status"] = "ready"
    else:
        change["status"] = "in-progress"

    _save_change(proj_id, change)

    return {
        "status": "generated",
        "artifact": artifact,
        "content": response_text,
        "token_usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "latency_s": round(elapsed, 2),
        },
    }


# ── Structured Verification ──

@router.post("/projects/{proj_id}/changes/{change_id}/verify")
async def verify_change(proj_id: str, change_id: str, request: Request):
    """Verify implementation against artifacts (completeness, correctness, coherence)."""
    change = _load_change(proj_id, change_id)
    if not change:
        raise HTTPException(404, "Change not found")

    arts = change.get("artifacts", {})

    from app.llm_provider import get_llm_provider

    data = await request.json() if request.headers.get("content-type") == "application/json" else {}
    provider_key = data.get("provider", "")
    model_key = data.get("model", "")

    # Build verification context
    context_parts = []
    for aid in ["proposal", "specs", "design", "tasks"]:
        content = arts.get(aid, {}).get("content", "")
        if content:
            context_parts.append(f"## {aid.upper()}\n{content}")

    if not context_parts:
        return {"verification": {
            "completeness": {"score": 0, "issues": ["No artifacts created"]},
            "correctness": {"score": 0, "issues": ["Nothing to verify"]},
            "coherence": {"score": 0, "issues": ["No content"]},
            "overall": "not_ready",
            "critical": 1, "warnings": 0, "suggestions": 0,
        }}

    provider = get_llm_provider(provider_key or None)

    verify_prompt = (
        "You are a quality assurance expert. Verify this change's artifacts "
        "for completeness, correctness, and coherence.\n\n"
        "Return ONLY valid JSON:\n"
        '{"completeness": {"score": 0.0-1.0, "issues": ["..."]}, '
        '"correctness": {"score": 0.0-1.0, "issues": ["..."]}, '
        '"coherence": {"score": 0.0-1.0, "issues": ["..."]}, '
        '"critical_issues": ["..."], "warnings": ["..."], '
        '"suggestions": ["..."]}\n\n'
        "Score guide:\n"
        "- completeness: all required sections present, tasks defined\n"
        "- correctness: specs match proposal intent, no contradictions\n"
        "- coherence: design matches specs, tasks cover design\n"
    )

    messages = [
        {"role": "system", "content": verify_prompt},
        {"role": "user", "content": "\n\n".join(context_parts)},
    ]

    kwargs = {}
    if model_key:
        kwargs["model"] = model_key

    input_text = "\n".join(m["content"] for m in messages)
    input_tokens = max(1, len(input_text) // 4)
    t0 = time.time()

    raw = ""
    async for chunk in provider.chat_stream(messages, **kwargs):
        raw += chunk

    elapsed = time.time() - t0
    output_tokens = max(1, len(raw) // 4)

    # Record in metrics
    from app.metrics import get_metrics
    get_metrics().record_llm_call(
        provider=provider_key or "default",
        model=model_key or "default",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_s=elapsed,
        session_id=f"spec:{proj_id}",
    )

    # Parse JSON response
    try:
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end > start:
            result = json.loads(raw[start:end + 1])
        else:
            result = {}
    except json.JSONDecodeError:
        result = {}

    # Normalize
    verification = {
        "completeness": result.get("completeness", {"score": 0.5, "issues": []}),
        "correctness": result.get("correctness", {"score": 0.5, "issues": []}),
        "coherence": result.get("coherence", {"score": 0.5, "issues": []}),
        "critical_issues": result.get("critical_issues", []),
        "warnings": result.get("warnings", []),
        "suggestions": result.get("suggestions", []),
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }

    # Determine overall readiness
    scores = [
        verification["completeness"].get("score", 0),
        verification["correctness"].get("score", 0),
        verification["coherence"].get("score", 0),
    ]
    avg = sum(scores) / len(scores) if scores else 0
    verification["overall_score"] = round(avg, 2)
    verification["overall"] = (
        "ready" if avg >= 0.7 and not verification["critical_issues"]
        else "needs_work"
    )

    change["verification"] = verification
    change["status"] = "verified" if verification["overall"] == "ready" else change["status"]
    _save_change(proj_id, change)

    return {
        "verification": verification,
        "token_usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "latency_s": round(elapsed, 2),
        },
    }


# ── Archive ──

@router.post("/projects/{proj_id}/changes/{change_id}/archive")
async def archive_change(proj_id: str, change_id: str):
    """Archive a change and merge delta specs into main specs."""
    change = _load_change(proj_id, change_id)
    if not change:
        raise HTTPException(404, "Change not found")

    # Merge delta specs into main specs
    specs_content = change.get("artifacts", {}).get("specs", {}).get("content", "")
    if specs_content:
        main_path = _main_specs_file(proj_id)
        existing = ""
        if os.path.exists(main_path):
            with open(main_path) as f:
                existing = f.read()

        # Append with date marker
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        merged = existing
        if merged and not merged.endswith("\n\n"):
            merged += "\n\n"
        merged += (
            f"---\n\n"
            f"<!-- Merged from: {change['name']} ({date_str}) -->\n\n"
            f"{specs_content}\n"
        )

        with open(main_path, "w") as f:
            f.write(merged)

    # Move to archive
    now = datetime.now(timezone.utc)
    change["status"] = "archived"
    change["archived_at"] = now.isoformat()

    archive_id = f"{now.strftime('%Y-%m-%d')}-{change['name']}"
    archive_path = os.path.join(_archive_dir(proj_id), f"{archive_id}.json")

    with open(archive_path, "w") as f:
        json.dump(change, f, indent=2, ensure_ascii=False)

    # Remove from active changes
    active_path = _change_path(proj_id, change_id)
    if os.path.exists(active_path):
        os.remove(active_path)

    return {
        "status": "archived",
        "archive_id": archive_id,
        "specs_merged": bool(specs_content),
    }


# ── Archive History ──

@router.get("/projects/{proj_id}/archive")
async def list_archive(proj_id: str):
    """List archived changes."""
    d = _archive_dir(proj_id)
    entries = []
    for fname in sorted(os.listdir(d), reverse=True):
        if fname.endswith(".json"):
            try:
                with open(os.path.join(d, fname)) as f:
                    data = json.load(f)
                    entries.append({
                        "id": data.get("id", ""),
                        "name": data.get("name", ""),
                        "archived_at": data.get("archived_at", ""),
                        "created_at": data.get("created_at", ""),
                    })
            except Exception:
                pass
    return {"archive": entries}


@router.get("/projects/{proj_id}/archive/{archive_name}")
async def get_archived_change(proj_id: str, archive_name: str):
    """Get full details of an archived change."""
    path = os.path.join(_archive_dir(proj_id), f"{archive_name}.json")
    if not os.path.exists(path):
        raise HTTPException(404, "Archived change not found")
    with open(path) as f:
        return {"change": json.load(f)}


# ── Main Specs ──

@router.get("/projects/{proj_id}/specs")
async def get_main_specs(proj_id: str):
    """Get the project's main specs (source of truth)."""
    path = _main_specs_file(proj_id)
    content = ""
    if os.path.exists(path):
        with open(path) as f:
            content = f.read()
    return {"specs": content}


@router.put("/projects/{proj_id}/specs")
async def update_main_specs(proj_id: str, request: Request):
    """Update the project's main specs."""
    data = await request.json()
    content = data.get("content", "")
    path = _main_specs_file(proj_id)
    with open(path, "w") as f:
        f.write(content)
    return {"status": "updated"}
