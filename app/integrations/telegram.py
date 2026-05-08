"""
Clawzd — Telegram webhook integration.
Receives messages via Telegram Bot API webhook and responds via LLM.
"""
import os, logging, hmac, hashlib
from fastapi import APIRouter, Request, HTTPException
from config import DATA_DIR

router = APIRouter()
logger = logging.getLogger("clawzd.telegram")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
# Comma-separated list of allowed Telegram user IDs (empty = allow all)
_raw_ids = os.getenv("TELEGRAM_ALLOWED_IDS", "").strip()
TELEGRAM_ALLOWED_IDS: set[str] = {
    uid.strip() for uid in _raw_ids.split(",") if uid.strip()
} if _raw_ids else set()


@router.post("/webhook")
async def receive_webhook(request: Request):
    """Receive and process Telegram messages."""
    data = await request.json()

    # Telegram sends updates with a "message" field
    message = data.get("message")
    if not message:
        return {"status": "ok"}

    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "")
    sender = message.get("from", {})
    sender_id = str(sender.get("id", ""))

    if not text or not chat_id:
        return {"status": "ok"}

    # Reject unauthorized users if allowlist is configured
    if TELEGRAM_ALLOWED_IDS and sender_id not in TELEGRAM_ALLOWED_IDS:
        logger.warning("Telegram msg from unauthorized user %s — ignored", sender_id)
        return {"status": "unauthorized"}

    logger.info("Telegram msg from %s: %s", sender_id, text[:50])

    # Generate response
    from app.llm_provider import get_llm_provider
    from app.preprompts import get_preprompt
    from app.database import create_session, add_message
    import uuid

    session_id = f"tg-{sender_id}-{uuid.uuid4().hex[:6]}"
    create_session(session_id, title=f"[Telegram] {text[:40]}")
    add_message(session_id, "user", text)

    messages = [
        {"role": "system", "content": get_preprompt("enrichment") or ""},
        {"role": "user", "content": text},
    ]
    provider = get_llm_provider()
    full = ""
    async for token in provider.chat_stream(messages):
        full += token
    add_message(session_id, "assistant", full)

    # Reply via Telegram Bot API
    await _send_telegram_reply(chat_id, full[:4096])

    return {"status": "ok"}


async def _send_telegram_reply(chat_id: int, text: str):
    """Send a text reply via Telegram Bot API."""
    if not TELEGRAM_BOT_TOKEN:
        logger.warning("No TELEGRAM_BOT_TOKEN, cannot reply")
        return
    import httpx
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
    }
    async with httpx.AsyncClient() as client:
        r = await client.post(url, json=payload)
        if r.status_code != 200:
            logger.error("Telegram reply failed: %s", r.text)
