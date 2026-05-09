"""
Clawzd — OpenAI-Compatible API Endpoint.
Exposes Clawzd as an OpenAI-compatible inference server so external tools
(Claude Code, Cursor, VS Code, Continue.dev) can use it as a backend.

Endpoints:
  - POST /v1/chat/completions  — Chat completion (streaming + non-streaming)
  - GET  /v1/models            — List available models
  - GET  /v1/models/{model_id} — Get specific model info
"""
import json
import logging
import time
import uuid

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.llm_provider import get_llm_provider, _get_provider_models
from config import API_SECRET_TOKEN, LLM_PROVIDER, OLLAMA_MODEL

router = APIRouter()
logger = logging.getLogger("clawzd.openai_api")


# ---------------------------------------------------------------------------
# Pydantic models matching the OpenAI API spec
# ---------------------------------------------------------------------------
class ChatMessage(BaseModel):
    role: str
    content: str | list | None = None
    name: str | None = None


class FunctionDef(BaseModel):
    name: str
    description: str | None = None
    parameters: dict | None = None


class ToolDef(BaseModel):
    type: str = "function"
    function: FunctionDef


class ChatCompletionRequest(BaseModel):
    model: str = ""
    messages: list[ChatMessage]
    stream: bool = False
    temperature: float | None = None
    max_tokens: int | None = None
    top_p: float | None = None
    frequency_penalty: float | None = None
    presence_penalty: float | None = None
    stop: str | list[str] | None = None
    tools: list[ToolDef] | None = None
    tool_choice: str | dict | None = None


# ---------------------------------------------------------------------------
# Authentication helper
# ---------------------------------------------------------------------------
def _check_auth(authorization: str | None):
    """Validate Bearer token if API_SECRET_TOKEN is configured."""
    if not API_SECRET_TOKEN:
        return  # No auth required
    if not authorization:
        raise HTTPException(401, "Missing Authorization header")
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(401, "Invalid Authorization header format")
    if parts[1] != API_SECRET_TOKEN:
        raise HTTPException(403, "Invalid API key")


# ---------------------------------------------------------------------------
# Provider + model resolution
# ---------------------------------------------------------------------------
def _resolve_provider_model(model_str: str) -> tuple[str, str]:
    """Resolve a model string into (provider_key, model_id).

    Supports formats:
      - "qwen3.5:9b"           → (default provider, "qwen3.5:9b")
      - "ollama/qwen3.5:9b"    → ("ollama", "qwen3.5:9b")
      - "google/gemini-2.0-flash" → ("google", "gemini-2.0-flash")
      - ""                      → (default provider, default model)
    """
    if not model_str:
        return LLM_PROVIDER, OLLAMA_MODEL

    # Check for "provider/model" format
    if "/" in model_str:
        parts = model_str.split("/", 1)
        provider_key = parts[0].lower()
        model_id = parts[1]

        # Map common provider aliases
        aliases = {
            "local": "ollama",
            "openai": "openai",
            "anthropic": "anthropic",
            "claude": "anthropic",
            "gemini": "google",
            "groq": "groq",
            "mistral": "mistral",
            "grok": "grok",
            "xai": "grok",
            "huggingface": "huggingface",
            "hf": "huggingface",
            "openrouter": "openrouter",
        }
        provider_key = aliases.get(provider_key, provider_key)
        return provider_key, model_id

    # No provider prefix — use default
    return LLM_PROVIDER, model_str


# ---------------------------------------------------------------------------
# GET /v1/models
# ---------------------------------------------------------------------------
@router.get("/models")
async def list_models(authorization: str | None = Header(None)):
    """List all available models across providers (OpenAI API-compatible)."""
    _check_auth(authorization)

    provider_models = await _get_provider_models()
    models = []
    for provider, model_list in provider_models.items():
        for m in model_list:
            models.append({
                "id": f"{provider}/{m['id']}",
                "object": "model",
                "created": int(time.time()),
                "owned_by": provider,
                "permission": [],
                "root": m["id"],
                "parent": None,
            })

    return {
        "object": "list",
        "data": models,
    }


# ---------------------------------------------------------------------------
# GET /v1/models/{model_id:path}
# ---------------------------------------------------------------------------
@router.get("/models/{model_id:path}")
async def get_model(
    model_id: str,
    authorization: str | None = Header(None),
):
    """Get info about a specific model."""
    _check_auth(authorization)

    return {
        "id": model_id,
        "object": "model",
        "created": int(time.time()),
        "owned_by": "clawzd",
        "permission": [],
        "root": model_id,
        "parent": None,
    }


# ---------------------------------------------------------------------------
# POST /v1/chat/completions
# ---------------------------------------------------------------------------
@router.post("/chat/completions")
async def chat_completions(
    req: ChatCompletionRequest,
    request: Request,
    authorization: str | None = Header(None),
):
    """OpenAI-compatible chat completion endpoint (streaming + non-streaming)."""
    _check_auth(authorization)

    provider_key, model_id = _resolve_provider_model(req.model)

    # Build messages list
    messages = []
    for m in req.messages:
        content = m.content
        # Handle multimodal content (list of parts with text/image_url)
        if isinstance(content, list):
            # Extract text parts, pass through for vision-capable providers
            text_parts = []
            for part in content:
                if isinstance(part, dict):
                    if part.get("type") == "text":
                        text_parts.append(part.get("text", ""))
                    elif part.get("type") == "image_url":
                        # Store image URL for vision providers
                        text_parts.append("[image]")
                elif isinstance(part, str):
                    text_parts.append(part)
            content = "\n".join(text_parts) if text_parts else ""

        messages.append({"role": m.role, "content": content or ""})

    # Build kwargs for the provider
    kwargs = {"model": model_id}
    if req.temperature is not None:
        kwargs["temperature"] = req.temperature
    if req.max_tokens is not None:
        kwargs["max_tokens"] = req.max_tokens

    request_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"

    try:
        provider = get_llm_provider(provider_key)
    except ValueError:
        raise HTTPException(400, f"Unknown provider: {provider_key}")

    if req.stream:
        return StreamingResponse(
            _stream_response(provider, messages, kwargs, request_id, model_id),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # Non-streaming: collect full response
    full_response = ""
    t0 = time.perf_counter()
    async for token in provider.chat_stream(messages, **kwargs):
        full_response += token
    elapsed = time.perf_counter() - t0

    return {
        "id": request_id,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model_id,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": full_response,
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": sum(len(m["content"]) // 4 for m in messages),
            "completion_tokens": len(full_response) // 4,
            "total_tokens": (
                sum(len(m["content"]) // 4 for m in messages)
                + len(full_response) // 4
            ),
        },
    }


async def _stream_response(provider, messages, kwargs, request_id, model_id):
    """Generate SSE chunks matching the OpenAI streaming format."""
    t0 = time.perf_counter()

    # Initial chunk with role
    initial_chunk = {
        "id": request_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model_id,
        "choices": [
            {
                "index": 0,
                "delta": {"role": "assistant", "content": ""},
                "finish_reason": None,
            }
        ],
    }
    yield f"data: {json.dumps(initial_chunk)}\n\n"

    # Stream content chunks
    async for token in provider.chat_stream(messages, **kwargs):
        chunk = {
            "id": request_id,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model_id,
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": token},
                    "finish_reason": None,
                }
            ],
        }
        yield f"data: {json.dumps(chunk)}\n\n"

    # Final chunk with finish_reason
    final_chunk = {
        "id": request_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model_id,
        "choices": [
            {
                "index": 0,
                "delta": {},
                "finish_reason": "stop",
            }
        ],
    }
    yield f"data: {json.dumps(final_chunk)}\n\n"
    yield "data: [DONE]\n\n"

    elapsed = time.perf_counter() - t0
    logger.info(
        "OpenAI API [%s/%s]: completed in %.1fs",
        kwargs.get("model", "default"), model_id, elapsed,
    )
