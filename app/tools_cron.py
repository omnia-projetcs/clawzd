"""
Clawzd — Cron scheduler with pre-prompt support.
Uses APScheduler to run periodic LLM tasks with configurable pre-prompts.
"""
import os
import json
import uuid
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Request, HTTPException
from config import DATA_DIR

router = APIRouter()
logger = logging.getLogger("clawzd.cron")

CRON_FILE = os.path.join(DATA_DIR, "cron_jobs.json")
_scheduler = None
_jobs: dict = {}


def _load_jobs() -> list:
    if os.path.exists(CRON_FILE):
        try:
            with open(CRON_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return []


def _save_jobs(jobs: list):
    os.makedirs(os.path.dirname(CRON_FILE), exist_ok=True)
    with open(CRON_FILE, "w") as f:
        json.dump(jobs, f, indent=2)


def _get_scheduler():
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        _scheduler = AsyncIOScheduler()
        _scheduler.start()
        logger.info("APScheduler started")
        return _scheduler
    except ImportError:
        raise HTTPException(500, "APScheduler not installed. Run: pip install apscheduler")


async def _run_cron_job(job_id: str, prompt: str, preprompt: str, provider: str, model: str, reactions: list = None):
    """Execute a scheduled LLM prompt, log the result, and send notifications/trigger reactions."""
    from app.llm_provider import get_llm_provider
    from app.preprompts import get_preprompt
    from app.database import create_session, add_message

    session_id = f"cron-{job_id}-{datetime.now().strftime('%Y%m%d%H%M')}"
    create_session(session_id, title=f"[Cron] {prompt[:50]}", provider=provider, model=model, preprompt=preprompt)

    messages = []
    system = get_preprompt(preprompt)
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    add_message(session_id, "user", prompt)

    llm = get_llm_provider(provider)
    full = ""
    kwargs = {"model": model} if model else {}
    async for token in llm.chat_stream(messages, **kwargs):
        full += token

    add_message(session_id, "assistant", full, metadata={"cron_job_id": job_id})
    logger.info("Cron job %s completed: %d chars", job_id, len(full))

    # --- Send notifications ---
    await _notify_cron_completion(job_id, prompt, full, session_id, reactions)


async def _notify_cron_completion(job_id: str, prompt: str, result: str, session_id: str, reactions: list = None):
    """Send cron job completion notifications to configured channels."""
    summary = result[:500] + ("…" if len(result) > 500 else "")
    notification = f"🕐 Cron job `{job_id}` completed.\n\nPrompt: {prompt[:100]}\n\nResult:\n{summary}"

    # --- Telegram notification ---
    try:
        from config import DATA_DIR
        telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        telegram_ids = os.environ.get("TELEGRAM_ALLOWED_IDS", "")
        if telegram_token and telegram_ids:
            import httpx
            for chat_id in telegram_ids.split(","):
                chat_id = chat_id.strip()
                if not chat_id:
                    continue
                try:
                    async with httpx.AsyncClient(timeout=10) as http_client:
                        await http_client.post(
                            f"https://api.telegram.org/bot{telegram_token}/sendMessage",
                            json={"chat_id": chat_id, "text": notification, "parse_mode": "Markdown"},
                        )
                    logger.info("Cron notification sent to Telegram chat %s", chat_id)
                except Exception as e:
                    logger.warning("Telegram notification failed for %s: %s", chat_id, e)
    except Exception as e:
        logger.warning("Telegram notification setup failed: %s", e)

    # --- Discord notification ---
    try:
        discord_token = os.environ.get("DISCORD_BOT_TOKEN", "")
        channel_ids = os.environ.get("DISCORD_CHANNEL_IDS", "")
        if discord_token and channel_ids:
            import httpx
            headers = {"Authorization": f"Bot {discord_token}", "Content-Type": "application/json"}
            for ch_id in channel_ids.split(","):
                ch_id = ch_id.strip()
                if not ch_id:
                    continue
                try:
                    # Chunk message for Discord's 2000 char limit
                    msg = notification[:2000]
                    async with httpx.AsyncClient(timeout=10) as http_client:
                        await http_client.post(
                            f"https://discord.com/api/v10/channels/{ch_id}/messages",
                            headers=headers,
                            json={"content": msg},
                        )
                    logger.info("Cron notification sent to Discord channel %s", ch_id)
                except Exception as e:
                    logger.warning("Discord notification failed for %s: %s", ch_id, e)
    except Exception as e:
        logger.warning("Discord notification setup failed: %s", e)

    # --- Web notification (stored for UI retrieval) ---
    try:
        notif_file = os.path.join(DATA_DIR, "notifications.jsonl")
        os.makedirs(os.path.dirname(notif_file), exist_ok=True)
        entry = {
            "type": "cron_complete",
            "job_id": job_id,
            "session_id": session_id,
            "message": f"Cron job '{job_id}' completed",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "read": False,
        }
        with open(notif_file, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning("Web notification save failed: %s", e)

    # --- Trigger Reactions ---
    if reactions:
        from app.integrations_social import send_email, post_to_twitter, post_to_linkedin, post_to_medium, trigger_n8n_webhook
        for reaction in reactions:
            reaction = reaction.lower()
            try:
                if reaction == "email":
                    await send_email(f"Cron Job Completed: {job_id}", result)
                    logger.info("Triggered email reaction for cron job %s", job_id)
                elif reaction == "twitter":
                    await post_to_twitter(result[:280]) # Twitter limit
                    logger.info("Triggered twitter reaction for cron job %s", job_id)
                elif reaction == "linkedin":
                    await post_to_linkedin(result)
                    logger.info("Triggered linkedin reaction for cron job %s", job_id)
                elif reaction == "medium":
                    # For Medium, we need a title. We'll use the prompt or a default.
                    title = prompt[:50] if prompt else f"Automated Post {job_id}"
                    await post_to_medium(title, result)
                    logger.info("Triggered medium reaction for cron job %s", job_id)
                elif reaction == "n8n":
                    payload = {
                        "job_id": job_id,
                        "prompt": prompt,
                        "result": result,
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    }
                    await trigger_n8n_webhook(payload)
                    logger.info("Triggered n8n reaction for cron job %s", job_id)
                else:
                    logger.warning("Unknown reaction '%s' for cron job %s", reaction, job_id)
            except Exception as e:
                logger.error("Failed to execute reaction '%s' for cron job %s: %s", reaction, job_id, e)


@router.post("/jobs")
async def create_job(request: Request):
    """Create a new cron job with a prompt and schedule."""
    data = await request.json()
    prompt = data.get("prompt", "")
    if not prompt.strip():
        raise HTTPException(400, "Prompt is required")

    job_id = str(uuid.uuid4())[:8]
    job = {
        "id": job_id,
        "prompt": prompt,
        "preprompt": data.get("preprompt", "none"),
        "provider": data.get("provider", "local"),
        "model": data.get("model", ""),
        "schedule": {
            "type": data.get("schedule_type", "interval"),  # interval or cron
            "hours": data.get("hours", 24),
            "minutes": data.get("minutes", 0),
            "cron_expr": data.get("cron_expr", ""),  # e.g. "0 9 * * *"
        },
        "reactions": data.get("reactions", []), # e.g. ["twitter", "email"]
        "enabled": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "last_run": None,
    }

    # Schedule with APScheduler
    scheduler = _get_scheduler()
    sched = job["schedule"]
    if sched["type"] == "cron" and sched["cron_expr"]:
        from apscheduler.triggers.cron import CronTrigger
        parts = sched["cron_expr"].split()
        trigger = CronTrigger(minute=parts[0], hour=parts[1],
                              day=parts[2], month=parts[3], day_of_week=parts[4])
        scheduler.add_job(_run_cron_job, trigger, id=job_id,
                          args=[job_id, prompt, job["preprompt"], job["provider"], job["model"], job["reactions"]])
    else:
        scheduler.add_job(_run_cron_job, "interval",
                          hours=sched["hours"], minutes=sched["minutes"], id=job_id,
                          args=[job_id, prompt, job["preprompt"], job["provider"], job["model"], job["reactions"]])

    jobs = _load_jobs()
    jobs.append(job)
    _save_jobs(jobs)

    return {"status": "created", "job": job}


@router.get("/jobs")
async def list_jobs():
    """List all scheduled cron jobs."""
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
    except Exception as e:
        logger.warning("Failed to remove cron job %s from scheduler: %s", job_id, e)
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
