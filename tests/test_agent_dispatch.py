import os
import shutil
from fastapi.testclient import TestClient

from app.gateway import app
from config import AGENTS_DIR

client = TestClient(app)


def test_agent_endpoints():
    # 1. Test listing agents
    resp = client.get("/agents/list")
    assert resp.status_code == 200
    data = resp.json()
    assert "agents" in data
    assert "orchestrator" in data["agents"]

    # 2. Test fetching agent details (existing agent)
    resp = client.get("/agents/detail?key=developer")
    assert resp.status_code == 200
    data = resp.json()
    assert "name" in data
    assert "Codex" in data["name"]
    assert "system_prompt" in data
    assert "You are Codex" in data["system_prompt"]

    # 3. Test saving a new custom agent
    test_key = "test_agent_runner"
    test_payload = {
        "key": test_key,
        "name": "Runner",
        "role": "expert at running tests",
        "model": "runner-model",
        "skills": "run_command",
        "system_prompt": "You are Runner, an expert agent designed to execute commands."
      }

    resp = client.post("/agents/save", json=test_payload)
    assert resp.status_code == 200
    assert resp.json()["status"] == "saved"
    assert resp.json()["key"] == test_key

    # Verify file was written to profiles/agents/
    filepath = os.path.join(AGENTS_DIR, f"{test_key}.md")
    assert os.path.exists(filepath)

    # 4. Test fetching details of the newly created agent
    resp = client.get(f"/agents/detail?key={test_key}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Runner"
    assert data["role"] == "expert at running tests"
    assert data["model"] == "runner-model"
    assert data["skills"] == "run_command"
    assert data["system_prompt"] == "You are Runner, an expert agent designed to execute commands."

    # 5. Clean up the written file
    try:
        if os.path.exists(filepath):
            os.remove(filepath)
    except Exception:
        pass

    # Reload agents to restore baseline state
    client.post("/agents/reload")
