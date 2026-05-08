"""
Clawzd — Playbook Engine.

Playbooks are multi-step workflows defined in YAML/Markdown files.
They automate repeatable engineering tasks (commit, refactor, audit, etc.)
with optional human validation gates.

Inspired by OpenMonoAgent.ai's Playbook architecture.

File format: PLAYBOOK.md with YAML frontmatter + Markdown body.
Storage: data/playbooks/<name>/PLAYBOOK.md
State:   data/playbook_state/<name>_<session>.json
"""
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from config import DATA_DIR, WORKSPACE_DIR

logger = logging.getLogger("clawzd.playbook")

PLAYBOOKS_DIR = os.path.join(DATA_DIR, "playbooks")
STATE_DIR = os.path.join(DATA_DIR, "playbook_state")

os.makedirs(PLAYBOOKS_DIR, exist_ok=True)
os.makedirs(STATE_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

class PlaybookStep:
    """A single step inside a playbook."""

    def __init__(
        self,
        index: int,
        title: str,
        instruction: str,
        gate: Optional[str] = None,
        constraints: Optional[List[str]] = None,
    ):
        self.index = index
        self.title = title
        self.instruction = instruction
        self.gate = gate  # None, "Confirm", "Review", "Approve"
        self.constraints = constraints or []

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "title": self.title,
            "instruction": self.instruction,
            "gate": self.gate,
            "constraints": self.constraints,
        }


class Playbook:
    """A parsed playbook definition."""

    def __init__(
        self,
        name: str,
        version: str,
        description: str,
        parameters: List[Dict[str, Any]],
        steps: List[PlaybookStep],
        path: str,
    ):
        self.name = name
        self.version = version
        self.description = description
        self.parameters = parameters
        self.steps = steps
        self.path = path

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "parameters": self.parameters,
            "steps": [s.to_dict() for s in self.steps],
            "total_steps": len(self.steps),
        }


# ---------------------------------------------------------------------------
# Loader — parse PLAYBOOK.md files
# ---------------------------------------------------------------------------

class PlaybookLoader:
    """Parse YAML frontmatter + Markdown body from PLAYBOOK.md files."""

    _FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)

    def load(self, path: str) -> Optional[Playbook]:
        """Load a single PLAYBOOK.md file."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()

            # Parse YAML frontmatter
            match = self._FRONTMATTER_RE.match(content)
            if not match:
                logger.warning("No YAML frontmatter in %s", path)
                return None

            meta = yaml.safe_load(match.group(1)) or {}
            body = content[match.end():]

            name = meta.get("name", Path(path).parent.name)
            version = str(meta.get("version", "1.0"))
            description = meta.get("description", "")
            parameters = meta.get("parameters", [])

            # Parse steps from Markdown body (## Step N: Title)
            steps = self._parse_steps(body)

            return Playbook(
                name=name,
                version=version,
                description=description,
                parameters=parameters,
                steps=steps,
                path=path,
            )
        except Exception as e:
            logger.error("Failed to load playbook %s: %s", path, e)
            return None

    def _parse_steps(self, body: str) -> List[PlaybookStep]:
        """Extract steps from Markdown headings.

        Format:
          ## Step 1: Title
          [gate: Confirm]

          Instructions here...
        """
        step_re = re.compile(
            r"^##\s+(?:Step\s+)?(\d+)\s*[:\-–]\s*(.+)$",
            re.MULTILINE | re.IGNORECASE,
        )
        matches = list(step_re.finditer(body))
        steps = []

        for i, m in enumerate(matches):
            idx = int(m.group(1))
            title = m.group(2).strip()

            # Content runs from after this heading to before the next
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
            content = body[start:end].strip()

            # Extract optional gate
            gate = None
            gate_match = re.search(
                r"\[gate:\s*(Confirm|Review|Approve)\]",
                content,
                re.IGNORECASE,
            )
            if gate_match:
                gate = gate_match.group(1).capitalize()
                content = content[:gate_match.start()] + content[gate_match.end():]
                content = content.strip()

            # Extract constraints
            constraints = []
            constraint_re = re.compile(r"^>\s*CONSTRAINT:\s*(.+)$", re.MULTILINE)
            for cm in constraint_re.finditer(content):
                constraints.append(cm.group(1).strip())

            steps.append(PlaybookStep(
                index=idx,
                title=title,
                instruction=content,
                gate=gate,
                constraints=constraints,
            ))

        return steps


# ---------------------------------------------------------------------------
# Template engine — resolve variables
# ---------------------------------------------------------------------------

class TemplateEngine:
    """Resolve template variables in playbook step instructions.

    Supported:
      {{parameters.target}}  — from user-provided params
      {{state.analysis}}     — from playbook execution state
      {{env.GIT_BRANCH}}     — from environment variables
    """

    _VAR_RE = re.compile(r"\{\{(\w+)\.(\w+)\}\}")

    def render(
        self,
        text: str,
        parameters: Dict[str, Any],
        state: Dict[str, Any],
    ) -> str:
        def replacer(m: re.Match) -> str:
            namespace = m.group(1)
            key = m.group(2)
            if namespace == "parameters":
                return str(parameters.get(key, f"<missing:{key}>"))
            elif namespace == "state":
                return str(state.get(key, f"<pending:{key}>"))
            elif namespace == "env":
                return os.environ.get(key, f"<env:{key}>")
            return m.group(0)

        return self._VAR_RE.sub(replacer, text)


# ---------------------------------------------------------------------------
# Executor — run a playbook step-by-step
# ---------------------------------------------------------------------------

class PlaybookExecutor:
    """Execute playbook steps with state persistence and gate support."""

    def __init__(self):
        self._loader = PlaybookLoader()
        self._template = TemplateEngine()

    def _state_path(self, name: str, session_id: str) -> str:
        safe = re.sub(r"[^\w\-]", "_", f"{name}_{session_id}")
        return os.path.join(STATE_DIR, f"{safe}.json")

    def _load_state(self, name: str, session_id: str) -> Dict:
        path = self._state_path(name, session_id)
        if os.path.exists(path):
            with open(path, "r") as f:
                return json.load(f)
        return {
            "current_step": 0,
            "status": "pending",
            "parameters": {},
            "results": {},
            "started_at": None,
        }

    def _save_state(self, name: str, session_id: str, state: Dict):
        path = self._state_path(name, session_id)
        with open(path, "w") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)

    async def start(
        self,
        playbook: Playbook,
        session_id: str,
        parameters: Dict[str, Any],
    ) -> Dict:
        """Start (or resume) a playbook execution.

        Returns the instruction for the current step, or the gate
        information if a gate is pending.
        """
        state = self._load_state(playbook.name, session_id)
        state["parameters"] = parameters
        state["status"] = "running"
        state["started_at"] = state.get("started_at") or datetime.now(timezone.utc).isoformat()
        self._save_state(playbook.name, session_id, state)
        return self._next_step(playbook, session_id, state)

    async def advance(
        self,
        playbook: Playbook,
        session_id: str,
        step_result: str = "",
        gate_response: str = "approved",
    ) -> Dict:
        """Advance to the next step after completing the current one.

        Stores the step result and moves forward. If a gate is pending and
        not approved, the playbook stays on the current step.
        """
        state = self._load_state(playbook.name, session_id)
        current = state["current_step"]

        # Store result
        state["results"][str(current)] = {
            "output": step_result[:5000],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Check gate
        if current < len(playbook.steps):
            step = playbook.steps[current]
            if step.gate and gate_response != "approved":
                state["status"] = f"gate_pending:{step.gate}"
                self._save_state(playbook.name, session_id, state)
                return {
                    "status": "gate_pending",
                    "gate": step.gate,
                    "step": step.to_dict(),
                    "message": f"Step {step.index} requires {step.gate} before continuing.",
                }

        # Advance
        state["current_step"] = current + 1
        self._save_state(playbook.name, session_id, state)
        return self._next_step(playbook, session_id, state)

    def _next_step(self, playbook: Playbook, session_id: str, state: Dict) -> Dict:
        """Return the instruction for the current step."""
        idx = state["current_step"]
        if idx >= len(playbook.steps):
            state["status"] = "completed"
            self._save_state(playbook.name, session_id, state)
            return {
                "status": "completed",
                "message": f"Playbook '{playbook.name}' completed all {len(playbook.steps)} steps.",
                "results": state["results"],
            }

        step = playbook.steps[idx]

        # Render template variables
        rendered = self._template.render(
            step.instruction,
            state["parameters"],
            state["results"],
        )

        # Build constraint string
        constraint_str = ""
        if step.constraints:
            constraint_str = "\n\nCONSTRAINTS:\n" + "\n".join(
                f"- {c}" for c in step.constraints
            )

        return {
            "status": "step_ready",
            "step_index": step.index,
            "step_title": step.title,
            "instruction": rendered + constraint_str,
            "gate": step.gate,
            "total_steps": len(playbook.steps),
            "progress": f"{idx + 1}/{len(playbook.steps)}",
        }

    def get_status(self, name: str, session_id: str) -> Dict:
        """Get the current status of a playbook execution."""
        state = self._load_state(name, session_id)
        return {
            "name": name,
            "status": state["status"],
            "current_step": state["current_step"],
            "started_at": state.get("started_at"),
            "results_count": len(state.get("results", {})),
        }


# ---------------------------------------------------------------------------
# Discovery — scan data/playbooks/ for available playbooks
# ---------------------------------------------------------------------------

def discover_playbooks() -> List[Dict]:
    """Scan data/playbooks/ and return metadata for each playbook."""
    loader = PlaybookLoader()
    playbooks = []

    for entry in sorted(os.listdir(PLAYBOOKS_DIR)):
        pb_dir = os.path.join(PLAYBOOKS_DIR, entry)
        if not os.path.isdir(pb_dir):
            continue
        pb_file = os.path.join(pb_dir, "PLAYBOOK.md")
        if not os.path.isfile(pb_file):
            continue

        pb = loader.load(pb_file)
        if pb:
            playbooks.append(pb.to_dict())

    return playbooks


def load_playbook(name: str) -> Optional[Playbook]:
    """Load a specific playbook by name."""
    pb_file = os.path.join(PLAYBOOKS_DIR, name, "PLAYBOOK.md")
    if not os.path.isfile(pb_file):
        return None
    return PlaybookLoader().load(pb_file)


# ---------------------------------------------------------------------------
# Singleton executor
# ---------------------------------------------------------------------------

playbook_executor = PlaybookExecutor()


# ---------------------------------------------------------------------------
# FastAPI Router
# ---------------------------------------------------------------------------

from fastapi import APIRouter, HTTPException, Request

router = APIRouter()


@router.get("/list")
async def list_playbooks():
    """List all available playbooks."""
    return {"playbooks": discover_playbooks()}


@router.post("/run")
async def run_playbook(request: Request):
    """Start or resume a playbook execution."""
    data = await request.json()
    name = data.get("name", "")
    session_id = data.get("session_id", "default")
    parameters = data.get("parameters", {})

    if not name:
        raise HTTPException(400, "Playbook name is required")

    pb = load_playbook(name)
    if not pb:
        raise HTTPException(404, f"Playbook '{name}' not found")

    result = await playbook_executor.start(pb, session_id, parameters)
    return result


@router.post("/advance")
async def advance_playbook(request: Request):
    """Advance to the next step of a running playbook."""
    data = await request.json()
    name = data.get("name", "")
    session_id = data.get("session_id", "default")
    step_result = data.get("result", "")
    gate_response = data.get("gate_response", "approved")

    if not name:
        raise HTTPException(400, "Playbook name is required")

    pb = load_playbook(name)
    if not pb:
        raise HTTPException(404, f"Playbook '{name}' not found")

    result = await playbook_executor.advance(
        pb, session_id, step_result, gate_response
    )
    return result


@router.post("/gate-response")
async def gate_response(request: Request):
    """Respond to a playbook gate (Confirm/Review/Approve)."""
    data = await request.json()
    name = data.get("name", "")
    session_id = data.get("session_id", "default")
    response = data.get("response", "approved")

    if not name:
        raise HTTPException(400, "Playbook name is required")

    pb = load_playbook(name)
    if not pb:
        raise HTTPException(404, f"Playbook '{name}' not found")

    # Advance with gate approval
    result = await playbook_executor.advance(
        pb, session_id, "", response
    )
    return result


@router.get("/status/{name}")
async def playbook_status(name: str, session_id: str = "default"):
    """Get the status of a running playbook."""
    return playbook_executor.get_status(name, session_id)
