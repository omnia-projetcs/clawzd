"""
Clawzd — Cron router.
Migrated from app/tools_cron.py for structure compliance.
"""

import os
import json
import uuid
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Request, HTTPException

from app.tools_cron import (
    _load_jobs, _save_jobs, _get_scheduler, _run_cron_job, _notify_cron_completion,
    CRON_FILE, _jobs, logger
)

router = APIRouter()
logger = logging.getLogger("clawzd.cron")


@router.post("/jobs")
async def create_job(request: Request):
    """Create a new cron job."""
    data = await request.json()
    job_id = data.get("id") or f"job_{uuid.uuid4().hex[:8]}"
    job = {
        "id": job_id,
        "prompt": data.get("prompt", ""),
        "preprompt": data.get("preprompt", "default"),
        "provider": data.get("provider", "local"),
        "model": data.get("model", ""),
        "schedule": data.get("schedule", "interval:60"),
        "enabled": data.get("enabled", True),
        "reactions": data.get("reactions", []),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    jobs = _load_jobs()
    jobs.append(job)
    _save_jobs(jobs)

    try:
        scheduler = _get_scheduler()
        if job["enabled"]:
            scheduler.add_job(
                _run_cron_job,
                trigger="interval",
                seconds=60,  # simplified
                id=job_id,
                args=[job_id, job["prompt"], job["preprompt"], job["provider"], job["model"], job.get("reactions")],
                replace_existing=True,
            )
    except Exception as e:
        logger.warning("Failed to schedule cron job %s: %s", job_id, e)

    return {"status": "created", "job": job}


@router.get("/jobs")
async def list_jobs():
    """List all cron jobs."""
    return {"jobs": _load_jobs()}


@router.delete("/jobs/{job_id}")
async def delete_job(job_id: str):
    """Delete a cron job."""
    jobs = _load_jobs()
    jobs = [j for j in jobs if j["id"] != job_id]
    _save_jobs(jobs)
    try:
        scheduler = _get_scheduler()
        scheduler.remove_job(job_id)
    except Exception:
        pass
    return {"status": "deleted"}


@router.post("/jobs/{job_id}/toggle")
async def toggle_job(job_id: str):
    """Enable or disable a cron job."""
    jobs = _load_jobs()
    for j in jobs:
        if j["id"] == job_id:
            j["enabled"] = not j["enabled"]
            try:
                scheduler = _get_scheduler()
                if j["enabled"]:
                    scheduler.resume_job(job_id)
                else:
                    scheduler.pause_job(job_id)
            except Exception as e:
                logger.warning("Failed to toggle cron job %s in scheduler: %s", job_id, e)
            _save_jobs(jobs)
            return {"status": "toggled", "enabled": j["enabled"]}
    raise HTTPException(404, "Job not found")
