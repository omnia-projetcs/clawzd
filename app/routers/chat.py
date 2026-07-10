"""
Clawzd — Additional Chat routes (upload, humanize, etc.).
Extracted from gateway to slim the monolith.
"""

import time

from fastapi import APIRouter, Request, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse

from app.core.llm_provider import get_llm_provider
from app.core.metrics import get_metrics
from app.core.preprompts import PREPROMPTS
from app.core.tokens import count_tokens
from config import DATA_DIR

router = APIRouter(tags=["chat"])


def _sanitize_input(text: str) -> str:
    """Basic input sanitization."""
    if not text:
        return ""
    import re
    text = re.sub(r"<script.*?>.*?</script>", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    return text.strip()


@router.post("/chat/upload-image")
async def upload_image(file: UploadFile = File(...)):
    """Upload an image for vision chat."""
    import os
    import uuid
    from PIL import Image
    import io

    allowed = {"image/jpeg", "image/png", "image/webp", "image/gif"}
    if file.content_type not in allowed:
        raise HTTPException(400, "Unsupported image type")

    content = await file.read()
    if len(content) > 10 * 1024 * 1024:  # 10MB
        raise HTTPException(400, "Image too large")

    # Basic validation
    try:
        img = Image.open(io.BytesIO(content))
        img.verify()
    except Exception:
        raise HTTPException(400, "Invalid image")

    # Save
    ext = file.filename.split(".")[-1] if "." in file.filename else "png"
    filename = f"upload_{uuid.uuid4().hex[:12]}.{ext}"
    upload_dir = os.path.join(DATA_DIR, "images")
    os.makedirs(upload_dir, exist_ok=True)
    path = os.path.join(upload_dir, filename)
    with open(path, "wb") as f:
        f.write(content)

    return {"filename": filename, "url": f"/data/images/{filename}"}


@router.post("/chat/humanize")
async def humanize_text(request: Request):
    """Rewrite AI-generated text to sound more natural and human."""
    data = await request.json()
    text = data.get("text", "")
    if not text.strip():
        raise HTTPException(400, "No text provided")

    if len(text) > 20_000:
        text = text[:20_000] + "\n\n... (truncated)"

    provider_key = data.get("provider", "")
    model_key = data.get("model", "")
    provider = get_llm_provider(provider_key or None)

    humanizer_prompt = PREPROMPTS.get("humanizer", {}).get("system_prompt", "Make this text sound more human and natural.")

    messages = [
        {"role": "system", "content": humanizer_prompt},
        {"role": "user", "content": f"Humanize this text:\n\n{text}"},
    ]

    kwargs = {}
    if model_key:
        kwargs["model"] = model_key

    t0 = time.time()
    result = ""
    async for chunk in provider.chat_stream(messages, **kwargs):
        result += chunk
    elapsed = time.time() - t0

    input_tokens = count_tokens(text, model=model_key or "")
    output_tokens = count_tokens(result, model=model_key or "")
    get_metrics().record_llm_call(
        provider=provider_key or "default",
        model=model_key or "default",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_s=elapsed,
        session_id="humanize",
    )

    return {
        "humanized": result,
        "original_length": len(text),
        "humanized_length": len(result),
        "latency_s": round(elapsed, 2),
    }
