import json

from app.tools import task_manager as tm


def _use_tmp_store(tmp_path):
    with tm._store_lock:
        tm._TASKS_DIR = str(tmp_path)
        tm._TASKS_PATH = str(tmp_path / "tasks.json")
        tm._active_tasks.clear()
        tm._task_history.clear()
        tm._persist_locked()


def test_task_lifecycle_persists_history(tmp_path):
    _use_tmp_store(tmp_path)

    task = tm.register_task("task_1", "image", "Generate image", {"style": "none"})
    assert task["active"] is True
    assert task["status"] == "running"

    tm.update_task("task_1", progress=42, stage="generating", metadata={"model": "fast"})
    active = tm.get_active_tasks()
    assert len(active) == 1
    assert active[0]["progress"] == 42
    assert active[0]["metadata"]["model"] == "fast"

    done = tm.unregister_task("task_1", status="completed", result={"filename": "x.png"})
    assert done["active"] is False
    assert done["status"] == "completed"
    assert done["result"]["filename"] == "x.png"
    assert tm.get_active_tasks() == []

    history = tm.get_task_history()
    assert len(history) == 1
    assert history[0]["id"] == "task_1"

    payload = json.loads((tmp_path / "tasks.json").read_text(encoding="utf-8"))
    assert payload["active"] == []
    assert payload["history"][0]["id"] == "task_1"


def test_load_store_marks_stale_active_tasks_interrupted(tmp_path):
    tm._TASKS_DIR = str(tmp_path)
    tm._TASKS_PATH = str(tmp_path / "tasks.json")
    payload = {
        "version": 1,
        "active": [
            {
                "id": "stale_1",
                "type": "research",
                "label": "Old research",
                "status": "running",
                "active": True,
                "started_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
                "metadata": {},
                "events": [],
                "event_count": 0,
            }
        ],
        "history": [],
    }
    (tmp_path / "tasks.json").write_text(json.dumps(payload), encoding="utf-8")

    tm._load_store()

    assert tm.get_active_tasks() == []
    history = tm.get_task_history()
    assert len(history) == 1
    assert history[0]["id"] == "stale_1"
    assert history[0]["status"] == "interrupted"
    assert history[0]["active"] is False


def test_summary_counts_active_and_history(tmp_path):
    _use_tmp_store(tmp_path)

    tm.register_task("audio_1", "audio", "Narrate")
    tm.register_task("video_1", "video", "Animate")
    tm.unregister_task("audio_1", status="failed", error="boom")

    summary = tm.get_task_summary()
    assert summary["active"] == 1
    assert summary["history"] == 1
    assert summary["by_type"]["audio"] == 1
    assert summary["by_type"]["video"] == 1
    assert summary["by_status"]["failed"] == 1
    assert summary["by_status"]["running"] == 1
