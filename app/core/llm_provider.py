"""
Clawzd — LLM Provider abstraction layer.
Supports Anthropic Claude, Google Gemini, Grok (xAI), Groq, HuggingFace,
Mistral, Ollama, OpenAI, OpenRouter, and vLLM.
"""
import asyncio
import json as _json
import logging
import os
import time
from abc import ABC, abstractmethod
import re as _re
from collections.abc import AsyncGenerator

import httpx
import openai

from config import (
    OLLAMA_HOST,
    OLLAMA_MODEL,
    OLLAMA_API_KEY,
    OLLAMA_VERIFY_SSL,
    ANTHROPIC_API_KEY,
    GOOGLE_API_KEY,
    GROK_API_KEY,
    GROQ_API_KEY,
    HUGGINGFACE_API_KEY,
    MISTRAL_API_KEY,
    OPENAI_API_KEY,
    OPENROUTER_API_KEY,
    VLLM_HOST,
    VLLM_API_KEY,
    VLLM_MODEL,
)

logger = logging.getLogger("clawzd.llm")

# ---------------------------------------------------------------------------
# Global Ollama concurrency guard
# ---------------------------------------------------------------------------
# Prevents multiple concurrent Ollama inferences that saturate VRAM on remote
# servers and cause crashes / zombie processes.  Configurable via .env:
#   OLLAMA_MAX_CONCURRENT=1   (default, safe for single-GPU)
#   OLLAMA_MAX_CONCURRENT=2   (multi-GPU setups)

def _resolve_ollama_max_concurrent() -> int:
    """Read OLLAMA_MAX_CONCURRENT from .env at call-time."""
    from dotenv import dotenv_values as _dv
    _env = _dv(".env") if os.path.exists(".env") else {}
    raw = _env.get("OLLAMA_MAX_CONCURRENT", os.getenv("OLLAMA_MAX_CONCURRENT", "1"))
    try:
        return max(1, int(raw))
    except (ValueError, TypeError):
        return 1

_ollama_inference_semaphore: asyncio.Semaphore | None = None
_ollama_semaphore_lock = asyncio.Lock()

async def _get_ollama_semaphore() -> asyncio.Semaphore:
    """Lazy-init the semaphore (must be created inside a running event loop)."""
    global _ollama_inference_semaphore
    if _ollama_inference_semaphore is None:
        async with _ollama_semaphore_lock:
            if _ollama_inference_semaphore is None:
                _ollama_inference_semaphore = asyncio.Semaphore(_resolve_ollama_max_concurrent())
                logger.info("Ollama concurrency guard initialized (max_concurrent=%d)",
                            _resolve_ollama_max_concurrent())
    return _ollama_inference_semaphore

# --- Available models per provider ---

def _resolve_ollama_host() -> str:
    """Resolve OLLAMA_HOST at call time from .env, falling back to env/config.

    This ensures that when the user changes OLLAMA_HOST in .env (e.g. to a
    remote server), the new value is picked up immediately without a restart.
    """
    import os as _os
    from dotenv import dotenv_values as _dv
    _env = _dv(".env") if _os.path.exists(".env") else {}
    return _env.get("OLLAMA_HOST", _os.getenv("OLLAMA_HOST", "http://localhost:11434"))


def _resolve_ollama_api_key() -> str:
    """Resolve OLLAMA_API_KEY at call time from .env."""
    import os as _os
    from dotenv import dotenv_values as _dv
    _env = _dv(".env") if _os.path.exists(".env") else {}
    return _env.get("OLLAMA_API_KEY", _os.getenv("OLLAMA_API_KEY", ""))


def _resolve_ollama_verify() -> bool:
    """Resolve OLLAMA_VERIFY_SSL at call time from .env.

    This allows toggling verification (useful for self-signed certs)
    without restarting the server.
    """
    import os as _os
    from dotenv import dotenv_values as _dv
    _env = _dv(".env") if _os.path.exists(".env") else {}
    raw = _env.get("OLLAMA_VERIFY_SSL", _os.getenv("OLLAMA_VERIFY_SSL", "true"))
    return str(raw).lower() not in ("0", "false", "no", "off")


def _estimate_input_tokens(messages: list[dict]) -> int:
    """Rough token count for a list of messages (~4 chars per token)."""
    total = 0
    for m in messages:
        content = m.get("content", "")
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    total += len(part.get("text", ""))
                elif isinstance(part, str):
                    total += len(part)
        elif isinstance(content, str):
            total += len(content)
        total += 10  # per-message overhead (role, separators)
    return total // 4


def _compute_ollama_options(
    messages: list[dict],
    max_ctx: int = 0,
    num_predict_override: int = 0,
) -> dict:
    """Compute optimal Ollama inference options based on actual input size.

    Returns a dict with ``num_ctx`` and ``num_predict`` sized to the request
    instead of always using the model maximum, which wastes VRAM on the
    KV cache.

    Strategy:
      - Estimate input tokens from messages.
      - ``num_predict`` = generous response headroom (capped at 4096 for chat,
        unless overridden).  For short prompts the model rarely needs more
        than 2048 output tokens.
      - ``num_ctx`` = input_tokens + num_predict, rounded up to next 2048.
      - Clamped between a floor of 2048 and the model's max (if known).
    """
    from config import OLLAMA_NUM_CTX, OLLAMA_NUM_GPU

    input_tokens = _estimate_input_tokens(messages)

    # --- num_predict (max output tokens) ---
    if num_predict_override > 0:
        num_predict = num_predict_override
    elif input_tokens < 500:
        # Short prompt → moderate response budget
        num_predict = 2048
    else:
        # Longer conversation → larger budget, capped
        num_predict = min(4096, max(2048, int(input_tokens * 0.6)))

    # --- num_ctx (total context window) ---
    needed = input_tokens + num_predict
    # Round up to next 2048 boundary
    num_ctx = ((needed + 2047) // 2048) * 2048
    # Floor
    num_ctx = max(2048, num_ctx)
    # Ceiling from config (OLLAMA_NUM_CTX) or model max
    ceiling = max_ctx if max_ctx > 0 else (OLLAMA_NUM_CTX if OLLAMA_NUM_CTX > 0 else 0)
    if ceiling > 0:
        num_ctx = min(num_ctx, ceiling)

    options = {
        "num_ctx": num_ctx,
        "num_predict": num_predict,
        "num_gpu": OLLAMA_NUM_GPU,
    }
    logger.debug(
        "Ollama options: input≈%d tok → num_ctx=%d, num_predict=%d",
        input_tokens, num_ctx, num_predict,
    )
    return options


async def _get_local_models() -> list[dict]:
    """Build local model list dynamically from Ollama."""
    ollama_host = _resolve_ollama_host()
    ollama_api_key = _resolve_ollama_api_key()
    try:
        headers = {"Authorization": f"Bearer {ollama_api_key}"} if ollama_api_key else {}
        async with httpx.AsyncClient(verify=_resolve_ollama_verify()) as client:
            resp = await client.get(f"{ollama_host}/api/tags", timeout=10, headers=headers)
        if resp.status_code == 200:
            data = resp.json()
        else:
            body = resp.text[:1000] if resp.text else ""
            logger.warning("Ollama /api/tags returned HTTP %d from %s: %s", resp.status_code, ollama_host, body)
            data = {}
        models = []
        for m in data.get("models", []):
            raw_name = m.get("name", "unknown")
            
            # Clean up the name for the label (remove registry, namespace, tags)
            clean_name = raw_name
            if "/" in clean_name:
                clean_name = clean_name.split("/")[-1]
            if clean_name.endswith(":latest"):
                clean_name = clean_name[:-7]
            if "-GGUF" in clean_name:
                clean_name = clean_name.split("-GGUF")[0]
            elif "-gguf" in clean_name.lower():
                # Handle other cases like -gguf or -Gguf
                import re
                clean_name = re.sub(r'(?i)-gguf.*$', '', clean_name)
            
            size_gb = round(m.get("size", 0) / (1024**3), 1)
            label = f"{clean_name} ({size_gb} GB)"
            models.append({"id": raw_name, "label": label})
            
        if models:
            # Sort models alphabetically by label
            models.sort(key=lambda x: x["label"].lower())
            return models
    except Exception as e:
        logger.warning("Failed to fetch local models from Ollama at %s: %s", ollama_host, e)
        logger.debug("Exception details while fetching /api/tags", exc_info=True)
    # Fallback: show configured model
    from config import OLLAMA_MODEL
    return [{"id": OLLAMA_MODEL, "label": f"{OLLAMA_MODEL} (Ollama)"}]


async def _get_vllm_models() -> list[dict]:
    """Build local model list dynamically from vLLM."""
    import os as _os
    from dotenv import dotenv_values as _dv
    _env = _dv(".env") if _os.path.exists(".env") else {}
    vllm_host = _env.get("VLLM_HOST", _os.getenv("VLLM_HOST", "http://localhost:8000"))
    vllm_api_key = _env.get("VLLM_API_KEY", _os.getenv("VLLM_API_KEY", "")) or ""
    
    base_url = vllm_host
    if not base_url.endswith("/v1"):
        base_url = base_url.rstrip("/") + "/v1"
        
    try:
        headers = {"Authorization": f"Bearer {vllm_api_key}"} if vllm_api_key else {}
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{base_url}/models", timeout=5, headers=headers)
        if resp.status_code == 200:
            data = resp.json()
            models = []
            for m in data.get("data", []):
                raw_name = m.get("id", "unknown")
                models.append({"id": raw_name, "label": f"{raw_name} (vLLM)"})
            if models:
                models.sort(key=lambda x: x["label"].lower())
                return models
    except Exception as e:
        logger.warning("Failed to fetch local models from vLLM at %s: %s", vllm_host, e)

    # Fallback: use configured model or generic placeholder
    configured = _env.get("VLLM_MODEL", _os.getenv("VLLM_MODEL", ""))
    if configured:
        return [{"id": configured, "label": f"{configured} (vLLM)"}]
    return [{"id": "vllm-model", "label": "vLLM Active Model"}]



async def _get_provider_models() -> dict:
    """Return provider models dict with dynamic local model list.

    Cloud providers are filtered out when ENABLE_CLOUD_MODELS=false in .env.
    The UI toggle writes directly to .env (data/ is not in git), so .env is
    the single source of truth that persists across deployments.
    Ollama is always returned regardless of this setting.

    Providers and models within each provider are sorted alphabetically.
    """
    # Re-read from env at call time so changes written to .env take effect
    # without a full server restart (dotenv reload on each request is cheap).
    import os as _os
    from dotenv import dotenv_values as _dv
    _env = _dv(".env") if _os.path.exists(".env") else {}
    _raw = _env.get("ENABLE_CLOUD_MODELS", _os.getenv("ENABLE_CLOUD_MODELS", "true"))
    cloud_enabled = str(_raw).lower() not in ("0", "false", "no", "off")

    local_models = await _get_local_models()
    vllm_models = await _get_vllm_models()

    # Ollama and vLLM are always available (local)
    result = {
        "ollama": local_models,
        "vllm": vllm_models,
    }

    if cloud_enabled:
        result.update({
            "anthropic":   PROVIDER_MODELS_STATIC["anthropic"],
            "google":      PROVIDER_MODELS_STATIC["google"],
            "grok":        PROVIDER_MODELS_STATIC["grok"],
            "groq":        PROVIDER_MODELS_STATIC["groq"],
            "huggingface": PROVIDER_MODELS_STATIC["huggingface"],
            "mistral":     PROVIDER_MODELS_STATIC["mistral"],
            "openai":      PROVIDER_MODELS_STATIC["openai"],
            "openrouter":  PROVIDER_MODELS_STATIC["openrouter"],
        })

    return result


PROVIDER_MODELS_STATIC = {
    "anthropic": [
        {"id": "claude-3-5-haiku-latest", "label": "Claude 3.5 Haiku"},
        {"id": "claude-3-5-sonnet-latest", "label": "Claude 3.5 Sonnet"},
        {"id": "claude-sonnet-4-20250514", "label": "Claude Sonnet 4"},
        {"id": "claude-opus-4-20250514", "label": "Claude Opus 4"},
    ],
    "google": [
        {"id": "gemini-1.5-pro", "label": "Gemini 1.5 Pro"},
        {"id": "gemini-2.0-flash", "label": "Gemini 2.0 Flash"},
    ],
    "grok": [
        {"id": "grok-2", "label": "Grok 2"},
        {"id": "grok-2-mini", "label": "Grok 2 Mini"},
        {"id": "grok-3", "label": "Grok 3"},
        {"id": "grok-3-mini", "label": "Grok 3 Mini"},
    ],
    "groq": [
        {"id": "llama3-8b-8192", "label": "Llama 3 8B"},
        {"id": "llama3-70b-8192", "label": "Llama 3 70B"},
        {"id": "mixtral-8x7b-32768", "label": "Mixtral 8x7B"},
    ],
    "huggingface": [
        {"id": "meta-llama/Llama-3.1-70B-Instruct", "label": "Llama 3.1 70B Instruct"},
        {"id": "meta-llama/Llama-3.1-8B-Instruct", "label": "Llama 3.1 8B Instruct"},
        {"id": "mistralai/Mistral-7B-Instruct-v0.3", "label": "Mistral 7B Instruct"},
        {"id": "microsoft/Phi-3-mini-4k-instruct", "label": "Phi-3 Mini 4K"},
    ],
    "mistral": [
        {"id": "mistral-large-latest", "label": "Mistral Large"},
        {"id": "mistral-medium-latest", "label": "Mistral Medium"},
        {"id": "mistral-small-latest", "label": "Mistral Small"},
    ],
    "ollama": [],  # dynamic via _get_local_models()
    "openai": [
        {"id": "gpt-4.1", "label": "GPT-4.1"},
        {"id": "gpt-4.1-mini", "label": "GPT-4.1 Mini"},
        {"id": "gpt-4.1-nano", "label": "GPT-4.1 Nano"},
        {"id": "gpt-4o", "label": "GPT-4o"},
        {"id": "gpt-4o-mini", "label": "GPT-4o Mini"},
        {"id": "o3-mini", "label": "o3 Mini"},
    ],
    "openrouter": [
        # Research-grade models (DeepResearch-compatible)
        {"id": "alibaba/tongyi-deepresearch-30b-a3b", "label": "🔬 Tongyi DeepResearch 30B (Alibaba)"},
        {"id": "perplexity/sonar-reasoning-pro", "label": "🔬 Perplexity Sonar Reasoning Pro"},
        {"id": "openai/o3-mini", "label": "🧠 o3 Mini (High Reasoning)"},
        # General purpose
        {"id": "anthropic/claude-3.5-sonnet", "label": "Claude 3.5 Sonnet"},
        {"id": "anthropic/claude-3.5-haiku", "label": "Claude 3.5 Haiku"},
        {"id": "google/gemini-pro-1.5", "label": "Gemini Pro 1.5"},
        {"id": "google/gemini-2.0-flash-001", "label": "Gemini 2.0 Flash"},
        {"id": "openai/gpt-4o", "label": "GPT-4o"},
        {"id": "openai/gpt-4o-mini", "label": "GPT-4o Mini"},
        {"id": "meta-llama/llama-3.1-70b-instruct", "label": "Llama 3.1 70B"},
        {"id": "deepseek/deepseek-r1", "label": "DeepSeek R1"},
        {"id": "qwen/qwen3-235b-a22b", "label": "Qwen3 235B"},
    ],
}


# ---------------------------------------------------------------------------
# Vision / multimodal helpers
# ---------------------------------------------------------------------------

def _extract_images_from_messages(messages: list[dict]) -> list[dict]:
    """Extract base64 images from multimodal messages.

    Supports OpenAI-style content arrays:
      [{"type": "text", "text": "..."}, {"type": "image_url", "image_url": {"url": "data:..."}}]

    Also supports a simple "images" key (Ollama-native format).
    Returns the messages list unchanged — callers should check for image content.
    """
    return messages


def _has_images(messages: list[dict]) -> bool:
    """Check if any message contains image content."""
    for m in messages:
        content = m.get("content")
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "image_url":
                    return True
        if m.get("images"):
            return True
    return False


def _extract_base64_from_data_url(data_url: str) -> tuple[str, str]:
    """Extract (media_type, base64_data) from a data URL.

    Input:  'data:image/png;base64,iVBOR...'
    Output: ('image/png', 'iVBOR...')
    """
    if data_url.startswith("data:"):
        header, b64 = data_url.split(",", 1)
        media_type = header.split(":")[1].split(";")[0]
        return media_type, b64
    return "image/png", data_url  # assume raw base64


def _messages_to_text_only(messages: list[dict]) -> list[dict]:
    """Convert multimodal messages to text-only (for non-vision providers)."""
    result = []
    for m in messages:
        content = m.get("content")
        if isinstance(content, list):
            text_parts = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    text_parts.append(part["text"])
                elif isinstance(part, dict) and part.get("type") == "image_url":
                    text_parts.append("[Image uploaded by user]")
                elif isinstance(part, str):
                    text_parts.append(part)
            result.append({**m, "content": "\n".join(text_parts)})
        else:
            result.append(m)
    return result


# Sentinel token yielded at end of stream when the model finished normally
# (finish_reason=stop / done=true).  The gateway uses this to skip the
# _is_truncated heuristic and avoid spurious continuation rounds.
FINISH_STOP_SENTINEL = "__FINISH_STOP__"


class LLMProvider(ABC):
    """Abstract base class for all LLM providers."""

    @abstractmethod
    async def chat_stream(
        self, messages: list[dict], model: str | None = None, **kwargs
    ) -> AsyncGenerator[str, None]:
        """Stream tokens from a chat completion request."""
        pass  # pragma: no cover

    async def chat(
        self, messages: list[dict], **kwargs
    ) -> str:
        """Non-streaming wrapper: collects all tokens from chat_stream."""
        parts = []
        async for token in self.chat_stream(messages, **kwargs):
            parts.append(token)
        return "".join(parts)


class OllamaLLM(LLMProvider):
    """Local LLM via Ollama's native /api/chat with dynamic num_ctx/num_predict."""
    
    @property
    def default_model(self):
        from config import OLLAMA_MODEL
        return OLLAMA_MODEL

    def __init__(self):
        # Track which host the client was built for so we can recreate
        # it when the user changes OLLAMA_HOST in .env.
        self._current_host = _resolve_ollama_host()
        self._current_api_key = _resolve_ollama_api_key()
        self.client = openai.AsyncOpenAI(
            base_url=f"{self._current_host}/v1",
            api_key=self._current_api_key or "ollama",
        )

    def _ensure_client(self):
        """Recreate the OpenAI client if OLLAMA_HOST has changed in .env."""
        host = _resolve_ollama_host()
        api_key = _resolve_ollama_api_key()
        if host != self._current_host or api_key != self._current_api_key:
            logger.info("OLLAMA_HOST changed: %s → %s, recreating client", self._current_host, host)
            self._current_host = host
            self._current_api_key = api_key
            self.client = openai.AsyncOpenAI(
                base_url=f"{host}/v1",
                api_key=api_key or "ollama",
            )
            # Invalidate health cache since host changed
            self._health_cache = {"ok": False, "ts": 0.0}

    # Cached health-check state (avoid HTTP call on every inference)
    _health_cache: dict[str, float | bool] = {"ok": False, "ts": 0.0}
    _HEALTH_TTL = 60.0  # seconds

    async def _is_ollama_running(self) -> bool:
        """Quick check if Ollama server is reachable (cached 60s)."""
        import time as _time
        now = _time.monotonic()
        if self._health_cache["ok"] and now - self._health_cache["ts"] < self._HEALTH_TTL:
            return True
        host = _resolve_ollama_host()
        api_key = _resolve_ollama_api_key()
        try:
            headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
            async with httpx.AsyncClient(verify=_resolve_ollama_verify()) as client:
                resp = await client.get(f"{host}/api/tags", timeout=5.0, headers=headers)
            if resp.status_code == 200:
                alive = True
            else:
                alive = False
                logger.debug("Ollama health check non-200 from %s: %d %s", host, resp.status_code, resp.text[:500])
        except Exception:
            alive = False
            logger.debug("Ollama health check failed for %s", host, exc_info=True)
        self._health_cache["ok"] = alive
        self._health_cache["ts"] = now
        return alive

    async def chat_stream(self, messages, model=None, **kwargs):
        # Acquire the global semaphore to prevent concurrent Ollama inferences
        # that crash remote servers by saturating VRAM.
        sem = await _get_ollama_semaphore()
        if sem.locked():
            logger.info("Ollama semaphore busy — queuing request (model=%s)", model or OLLAMA_MODEL)
        async with sem:
            async for token in self._chat_stream_inner(messages, model, **kwargs):
                yield token

    async def chat(self, messages: list[dict], **kwargs) -> str:
        """Non-streaming wrapper with semaphore guard."""
        sem = await _get_ollama_semaphore()
        if sem.locked():
            logger.info("Ollama semaphore busy — queuing chat request")
        async with sem:
            parts = []
            async for token in self._chat_stream_inner(messages, **kwargs):
                parts.append(token)
            return "".join(parts)

    async def _chat_stream_inner(self, messages, model=None, **kwargs):
        """Stream via Ollama native /api/chat with dynamic num_ctx/num_predict.

        Uses the native API instead of the OpenAI-compatible endpoint so we
        can pass ``options.num_ctx`` and ``options.num_predict`` per request,
        right-sizing the KV cache to the actual input size.
        """
        # Re-check host on every request so .env changes are picked up
        self._ensure_client()
        ollama_host = self._current_host

        if not await self._is_ollama_running():
            yield (
                "⚠️ **Ollama is not running.**\n\n"
                "Start it with:\n```bash\nollama serve\n```\n\n"
                "Or check that it's listening on "
                f"`{ollama_host}`."
            )
            return

        model = model or OLLAMA_MODEL

        # --- Vision support: if messages contain images, use Ollama native API ---
        if _has_images(messages):
            async for token in self._chat_stream_vision(messages, model, **kwargs):
                yield token
            return

        # --- Build native /api/chat payload ---
        # Convert OpenAI-style messages to Ollama format (strip multimodal wrappers)
        ollama_messages = []
        for m in messages:
            content = m.get("content", "")
            if isinstance(content, list):
                text_parts = []
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        text_parts.append(part["text"])
                    elif isinstance(part, str):
                        text_parts.append(part)
                content = "\n".join(text_parts)
            ollama_messages.append({"role": m["role"], "content": content or ""})

        # Compute dynamic options (num_ctx, num_predict, num_gpu)
        num_predict_override = kwargs.pop("num_predict", 0)
        options = _compute_ollama_options(
            messages, num_predict_override=num_predict_override,
        )
        # Merge any caller-supplied options (e.g. temperature)
        if "temperature" in kwargs:
            options["temperature"] = kwargs.pop("temperature")

        api_key = _resolve_ollama_api_key()
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

        payload = {
            "model": model,
            "messages": ollama_messages,
            "stream": True,
            "options": options,
        }

        t0 = time.perf_counter()
        tokens = 0
        # --- <think> block filter for reasoning models (Qwen3, DeepSeek-R1…) ---
        _in_think = False
        _think_buf = ""

        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(300.0),
                verify=_resolve_ollama_verify(),
            ) as client:
                async with client.stream(
                    "POST", f"{ollama_host}/api/chat",
                    json=payload, headers=headers,
                ) as resp:
                    if resp.status_code == 404:
                        yield (
                            f"⚠️ **Model `{model}` not found in Ollama.**\n\n"
                            f"Install it with:\n```bash\nollama pull {model}\n```"
                        )
                        return
                    async for line in resp.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            data = _json.loads(line)
                            chunk_text = data.get("message", {}).get("content", "")
                            if chunk_text:
                                # Filter <think>…</think> reasoning blocks
                                if _in_think:
                                    if "</think>" in chunk_text:
                                        _in_think = False
                                        after = chunk_text.split("</think>", 1)[1]
                                        if after:
                                            tokens += 1
                                            yield after
                                    # else: still inside <think>, discard
                                elif "<think>" in chunk_text:
                                    before = chunk_text.split("<think>", 1)[0]
                                    if before:
                                        tokens += 1
                                        yield before
                                    remainder = chunk_text.split("<think>", 1)[1]
                                    if "</think>" in remainder:
                                        after = remainder.split("</think>", 1)[1]
                                        if after:
                                            tokens += 1
                                            yield after
                                    else:
                                        _in_think = True
                                else:
                                    tokens += 1
                                    yield chunk_text
                            if data.get("done"):
                                yield FINISH_STOP_SENTINEL
                                break
                        except _json.JSONDecodeError:
                            continue
        except httpx.ConnectError:
            yield (
                "⚠️ **Cannot connect to Ollama** "
                f"(`{ollama_host}`).\n\n"
                "Make sure Ollama is running: `ollama serve`"
            )
            return
        except Exception as e:
            yield f"⚠️ **Ollama error:** {e}"
            return

        elapsed = time.perf_counter() - t0
        logger.info(
            "Ollama [%s]: %d tokens in %.1fs (%.0f tok/s) "
            "[num_ctx=%d, num_predict=%d]",
            model, tokens, elapsed, tokens / max(elapsed, 0.01),
            options["num_ctx"], options["num_predict"],
        )

    async def _chat_stream_vision(self, messages, model, **kwargs):
        """Stream from Ollama's native /api/chat with images support."""
        t0 = time.perf_counter()
        tokens = 0

        # Convert OpenAI-style multimodal to Ollama format
        ollama_messages = []
        for m in messages:
            msg = {"role": m["role"]}
            content = m.get("content")

            if isinstance(content, list):
                text_parts = []
                images = []
                for part in content:
                    if isinstance(part, dict):
                        if part.get("type") == "text":
                            text_parts.append(part["text"])
                        elif part.get("type") == "image_url":
                            url = part.get("image_url", {}).get("url", "")
                            _, b64 = _extract_base64_from_data_url(url)
                            images.append(b64)
                    elif isinstance(part, str):
                        text_parts.append(part)
                msg["content"] = "\n".join(text_parts) if text_parts else "Describe this image."
                if images:
                    msg["images"] = images
            else:
                msg["content"] = content or ""
                if m.get("images"):
                    msg["images"] = m["images"]

            ollama_messages.append(msg)

        # Compute dynamic options (num_ctx, num_predict, num_gpu)
        options = _compute_ollama_options(messages)

        # Use Ollama's native /api/chat endpoint for vision
        ollama_host = _resolve_ollama_host()
        api_key = _resolve_ollama_api_key()
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        payload = {
            "model": model,
            "messages": ollama_messages,
            "stream": True,
            "options": options,
        }

        # --- <think> block filter for reasoning models (Qwen3, DeepSeek-R1…) ---
        _in_think = False

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(120.0), verify=_resolve_ollama_verify()) as client:
                async with client.stream(
                    "POST", f"{ollama_host}/api/chat",
                    json=payload, headers=headers,
                ) as resp:
                    async for line in resp.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            data = _json.loads(line)
                            chunk_text = data.get("message", {}).get("content", "")
                            if chunk_text:
                                # Filter <think>…</think> reasoning blocks
                                if _in_think:
                                    if "</think>" in chunk_text:
                                        _in_think = False
                                        after = chunk_text.split("</think>", 1)[1]
                                        if after:
                                            tokens += 1
                                            yield after
                                elif "<think>" in chunk_text:
                                    before = chunk_text.split("<think>", 1)[0]
                                    if before:
                                        tokens += 1
                                        yield before
                                    remainder = chunk_text.split("<think>", 1)[1]
                                    if "</think>" in remainder:
                                        after = remainder.split("</think>", 1)[1]
                                        if after:
                                            tokens += 1
                                            yield after
                                    else:
                                        _in_think = True
                                else:
                                    tokens += 1
                                    yield chunk_text
                            if data.get("done"):
                                yield FINISH_STOP_SENTINEL
                                break
                        except _json.JSONDecodeError:
                            continue
        except Exception as e:
            # Add actionable hint for TLS issues
            hint = ""
            try:
                if not _resolve_ollama_verify():
                    hint = " (SSL verification disabled via OLLAMA_VERIFY_SSL=false)"
            except Exception:
                pass
            yield f"⚠️ **Vision error contacting {ollama_host}:** {e}{hint}"
            return

        elapsed = time.perf_counter() - t0
        logger.info(
            "Ollama Vision [%s]: %d tokens in %.1fs [num_ctx=%d, num_predict=%d]",
            model, tokens, elapsed, options["num_ctx"], options["num_predict"],
        )


class AnthropicLLM(LLMProvider):
    """Anthropic Claude API via the official anthropic SDK."""
    default_model = "claude-sonnet-4-20250514"

    def __init__(self):
        import anthropic
        self.client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

    async def chat_stream(self, messages, model="claude-sonnet-4-20250514", **kwargs):
        if not ANTHROPIC_API_KEY:
            yield (
                "⚠️ **Anthropic API key not configured.**\n\n"
                "Set `ANTHROPIC_API_KEY` in your `.env` file.\n"
                "Get a key at https://console.anthropic.com/settings/keys"
            )
            return
        t0 = time.perf_counter()
        tokens = 0

        # Claude uses a separate system parameter (not in messages list)
        system_text = ""
        chat_messages = []
        for m in messages:
            if m["role"] == "system":
                content = m.get("content", "")
                if isinstance(content, list):
                    content = " ".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in content)
                system_text += ("\n" if system_text else "") + content
            else:
                # Convert multimodal content for Claude vision
                content = m.get("content", "")
                if isinstance(content, list):
                    claude_parts = []
                    for part in content:
                        if isinstance(part, dict):
                            if part.get("type") == "text":
                                claude_parts.append({"type": "text", "text": part["text"]})
                            elif part.get("type") == "image_url":
                                url = part.get("image_url", {}).get("url", "")
                                media_type, b64 = _extract_base64_from_data_url(url)
                                claude_parts.append({
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": media_type,
                                        "data": b64,
                                    }
                                })
                        elif isinstance(part, str):
                            claude_parts.append({"type": "text", "text": part})
                    chat_messages.append({"role": m["role"], "content": claude_parts})
                else:
                    chat_messages.append({"role": m["role"], "content": content})

        api_kwargs = {
            "model": model,
            "messages": chat_messages,
            "max_tokens": kwargs.pop("max_tokens", 4096),
        }
        if system_text:
            api_kwargs["system"] = system_text
        # Pass through any remaining kwargs (temperature, etc.)
        api_kwargs.update(kwargs)

        async with self.client.messages.stream(**api_kwargs) as stream:
            async for text in stream.text_stream:
                tokens += 1
                yield text
        # Anthropic streams always end with end_turn when complete
        yield FINISH_STOP_SENTINEL
        logger.info("Anthropic [%s]: %d tokens in %.1fs", model, tokens, time.perf_counter() - t0)


class GoogleLLM(LLMProvider):
    """Google Gemini via the google-genai SDK."""
    default_model = "gemini-2.0-flash"

    def __init__(self):
        import google.genai as genai
        from google.genai import types  # noqa: F401
        self._genai = genai
        self._types = types
        self.client = genai.Client(api_key=GOOGLE_API_KEY)

    async def chat_stream(self, messages, model="gemini-2.0-flash", **kwargs):
        if not GOOGLE_API_KEY:
            yield (
                "⚠️ **Google API key not configured.**\n\n"
                "Set `GOOGLE_API_KEY` in your `.env` file.\n"
                "Get a key at https://aistudio.google.com/app/apikey"
            )
            return
        t0 = time.perf_counter()
        tokens = 0

        # Extract system messages into system_instruction (Gemini-native)
        system_parts = []
        contents = []
        for m in messages:
            if m["role"] == "system":
                content = m.get("content", "")
                if isinstance(content, list):
                    content = " ".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in content)
                system_parts.append(content)
            else:
                role = "user" if m["role"] == "user" else "model"
                content = m.get("content", "")

                # Handle multimodal content (vision)
                if isinstance(content, list):
                    gemini_parts = []
                    for part in content:
                        if isinstance(part, dict):
                            if part.get("type") == "text":
                                gemini_parts.append(self._types.Part(text=part["text"]))
                            elif part.get("type") == "image_url":
                                import base64 as _b64
                                url = part.get("image_url", {}).get("url", "")
                                media_type, b64_data = _extract_base64_from_data_url(url)
                                gemini_parts.append(self._types.Part(
                                    inline_data=self._types.Blob(
                                        mime_type=media_type,
                                        data=_b64.b64decode(b64_data),
                                    )
                                ))
                        elif isinstance(part, str):
                            gemini_parts.append(self._types.Part(text=part))
                    contents.append(self._types.Content(role=role, parts=gemini_parts))
                else:
                    contents.append(
                        self._types.Content(role=role, parts=[self._types.Part(text=content)])
                    )

        # Map OpenAI-style kwargs to Google GenerateContentConfig
        max_tokens = kwargs.pop("max_tokens", None)
        temperature = kwargs.pop("temperature", None)

        config_kwargs = {}
        if system_parts:
            config_kwargs["system_instruction"] = "\n".join(system_parts)
        if max_tokens is not None:
            config_kwargs["max_output_tokens"] = max_tokens
        if temperature is not None:
            config_kwargs["temperature"] = temperature
        config = self._types.GenerateContentConfig(**config_kwargs) if config_kwargs else None

        gen_kwargs = {"model": model, "contents": contents}
        if config:
            gen_kwargs["config"] = config

        # Run the synchronous stream iterator in a thread to avoid blocking the event loop
        import asyncio

        sync_response = await asyncio.to_thread(
            self.client.models.generate_content_stream, **gen_kwargs
        )
        for chunk in sync_response:
            if chunk.text:
                tokens += 1
                yield chunk.text
        yield FINISH_STOP_SENTINEL
        logger.info("Google [%s]: %d tokens in %.1fs", model, tokens, time.perf_counter() - t0)


class GrokLLM(LLMProvider):
    """Grok (xAI) API — OpenAI-compatible."""
    default_model = "grok-3-mini"

    def __init__(self):
        self.client = openai.AsyncOpenAI(
            base_url="https://api.x.ai/v1",
            api_key=GROK_API_KEY,
        )

    async def chat_stream(self, messages, model="grok-3-mini", **kwargs):
        if not GROK_API_KEY:
            yield (
                "⚠️ **Grok API key not configured.**\n\n"
                "Set `GROK_API_KEY` in your `.env` file.\n"
                "Get a key at https://console.x.ai/"
            )
            return
        t0 = time.perf_counter()
        tokens = 0
        stream = await self.client.chat.completions.create(
            model=model, messages=messages, stream=True, **kwargs
        )
        _finish_reason = None
        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                tokens += 1
                yield delta
            if chunk.choices[0].finish_reason:
                _finish_reason = chunk.choices[0].finish_reason
        if _finish_reason == "stop":
            yield FINISH_STOP_SENTINEL
        logger.info("Grok [%s]: %d tokens in %.1fs", model, tokens, time.perf_counter() - t0)


class GroqLLM(LLMProvider):
    """Groq inference API."""
    default_model = "llama3-70b-8192"

    def __init__(self):
        self.client = openai.AsyncOpenAI(
            base_url="https://api.groq.com/openai/v1",
            api_key=GROQ_API_KEY,
        )

    async def chat_stream(self, messages, model="llama3-70b-8192", **kwargs):
        if not GROQ_API_KEY:
            yield (
                "⚠️ **Groq API key not configured.**\n\n"
                "Set `GROQ_API_KEY` in your `.env` file.\n"
                "Get a free key at https://console.groq.com/keys"
            )
            return
        t0 = time.perf_counter()
        tokens = 0
        stream = await self.client.chat.completions.create(
            model=model, messages=messages, stream=True, **kwargs
        )
        _finish_reason = None
        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                tokens += 1
                yield delta
            if chunk.choices[0].finish_reason:
                _finish_reason = chunk.choices[0].finish_reason
        if _finish_reason == "stop":
            yield FINISH_STOP_SENTINEL
        logger.info("Groq [%s]: %d tokens in %.1fs", model, tokens, time.perf_counter() - t0)


class HuggingFaceLLM(LLMProvider):
    """HuggingFace Inference API (serverless)."""
    default_model = "meta-llama/Llama-3.1-8B-Instruct"

    def __init__(self):
        self.client = openai.AsyncOpenAI(
            base_url="https://api-inference.huggingface.co/v1",
            api_key=HUGGINGFACE_API_KEY or "not-configured",
        )

    async def chat_stream(self, messages, model="meta-llama/Llama-3.1-8B-Instruct", **kwargs):
        if not HUGGINGFACE_API_KEY:
            yield (
                "⚠️ **HuggingFace API key not configured.**\n\n"
                "Set `HUGGINGFACE_API_KEY` in your `.env` file.\n"
                "Get a free key at https://huggingface.co/settings/tokens"
            )
            return
        t0 = time.perf_counter()
        tokens = 0
        stream = await self.client.chat.completions.create(
            model=model, messages=messages, stream=True, **kwargs
        )
        _finish_reason = None
        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                tokens += 1
                yield delta
            if chunk.choices[0].finish_reason:
                _finish_reason = chunk.choices[0].finish_reason
        if _finish_reason == "stop":
            yield FINISH_STOP_SENTINEL
        logger.info("HuggingFace [%s]: %d tokens in %.1fs", model, tokens, time.perf_counter() - t0)


class MistralLLM(LLMProvider):
    """Mistral AI API."""
    default_model = "mistral-small-latest"

    def __init__(self):
        self.client = openai.AsyncOpenAI(
            base_url="https://api.mistral.ai/v1",
            api_key=MISTRAL_API_KEY,
        )

    async def chat_stream(self, messages, model="mistral-small-latest", **kwargs):
        if not MISTRAL_API_KEY:
            yield (
                "⚠️ **Mistral API key not configured.**\n\n"
                "Set `MISTRAL_API_KEY` in your `.env` file.\n"
                "Get a key at https://console.mistral.ai/api-keys"
            )
            return
        t0 = time.perf_counter()
        tokens = 0
        stream = await self.client.chat.completions.create(
            model=model, messages=messages, stream=True, **kwargs
        )
        _finish_reason = None
        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                tokens += 1
                yield delta
            if chunk.choices[0].finish_reason:
                _finish_reason = chunk.choices[0].finish_reason
        if _finish_reason == "stop":
            yield FINISH_STOP_SENTINEL
        logger.info("Mistral [%s]: %d tokens in %.1fs", model, tokens, time.perf_counter() - t0)


class OpenAILLM(LLMProvider):
    """OpenAI API (GPT-4o, GPT-4.1, o3, etc.)."""
    default_model = "gpt-4o-mini"

    def __init__(self):
        self.client = openai.AsyncOpenAI(
            api_key=OPENAI_API_KEY,
        )

    async def chat_stream(self, messages, model="gpt-4o-mini", **kwargs):
        if not OPENAI_API_KEY:
            yield (
                "⚠️ **OpenAI API key not configured.**\n\n"
                "Set `OPENAI_API_KEY` in your `.env` file.\n"
                "Get a key at https://platform.openai.com/api-keys"
            )
            return
        t0 = time.perf_counter()
        tokens = 0
        stream = await self.client.chat.completions.create(
            model=model, messages=messages, stream=True, **kwargs
        )
        _finish_reason = None
        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                tokens += 1
                yield delta
            if chunk.choices[0].finish_reason:
                _finish_reason = chunk.choices[0].finish_reason
        if _finish_reason == "stop":
            yield FINISH_STOP_SENTINEL
        logger.info("OpenAI [%s]: %d tokens in %.1fs", model, tokens, time.perf_counter() - t0)


class OpenRouterLLM(LLMProvider):
    """OpenRouter multi-model gateway."""
    default_model = "openai/gpt-4o-mini"

    def __init__(self):
        self.client = openai.AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=OPENROUTER_API_KEY,
            default_headers={"HTTP-Referer": "http://localhost", "X-Title": "Clawzd"},
        )

    async def chat_stream(self, messages, model="openai/gpt-4o-mini", **kwargs):
        if not OPENROUTER_API_KEY:
            yield (
                "⚠️ **OpenRouter API key not configured.**\n\n"
                "Set `OPENROUTER_API_KEY` in your `.env` file.\n"
                "Get a key at https://openrouter.ai/keys"
            )
            return
        t0 = time.perf_counter()
        tokens = 0
        stream = await self.client.chat.completions.create(
            model=model, messages=messages, stream=True, **kwargs
        )
        _finish_reason = None
        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                tokens += 1
                yield delta
            if chunk.choices[0].finish_reason:
                _finish_reason = chunk.choices[0].finish_reason
        if _finish_reason == "stop":
            yield FINISH_STOP_SENTINEL
        logger.info("OpenRouter [%s]: %d tokens in %.1fs", model, tokens, time.perf_counter() - t0)


class VllmLLM(LLMProvider):
    """Local or remote vLLM instance (OpenAI compatible)."""

    @property
    def default_model(self):
        from config import VLLM_MODEL
        return VLLM_MODEL or "vllm-model"

    def __init__(self):
        import os as _os
        from dotenv import dotenv_values as _dv
        _env = _dv(".env") if _os.path.exists(".env") else {}
        self._current_host = _env.get("VLLM_HOST", _os.getenv("VLLM_HOST", "http://localhost:8000"))
        # The openai SDK raises "Missing credentials" if api_key is empty.
        # vLLM servers typically don't require auth, so use "EMPTY" as a
        # safe placeholder when no key is configured.
        raw_key = _env.get("VLLM_API_KEY", _os.getenv("VLLM_API_KEY", ""))
        self._current_api_key = raw_key or "EMPTY"
        
        base_url = self._current_host
        if not base_url.endswith("/v1"):
            base_url = base_url.rstrip("/") + "/v1"
            
        self.client = openai.AsyncOpenAI(
            base_url=base_url,
            api_key=self._current_api_key,
        )

    async def chat_stream(self, messages, model=None, **kwargs):
        import os as _os
        from dotenv import dotenv_values as _dv
        _env = _dv(".env") if _os.path.exists(".env") else {}
        host = _env.get("VLLM_HOST", _os.getenv("VLLM_HOST", "http://localhost:8000"))
        raw_key = _env.get("VLLM_API_KEY", _os.getenv("VLLM_API_KEY", ""))
        api_key = raw_key or "EMPTY"
        
        if host != self._current_host or api_key != self._current_api_key:
            self._current_host = host
            self._current_api_key = api_key
            base_url = host
            if not base_url.endswith("/v1"):
                base_url = base_url.rstrip("/") + "/v1"
            self.client = openai.AsyncOpenAI(
                base_url=base_url,
                api_key=api_key,
            )

        t0 = time.perf_counter()
        tokens = 0

        # Resolve model: use explicit config, then dynamic detection
        if not model or model == "vllm-model":
            import os as _os2
            from dotenv import dotenv_values as _dv2
            _env2 = _dv2(".env") if _os2.path.exists(".env") else {}
            configured = _env2.get("VLLM_MODEL", _os2.getenv("VLLM_MODEL", ""))
            if configured:
                model = configured
            else:
                try:
                    models_response = await self.client.models.list()
                    if models_response.data:
                        model = models_response.data[0].id
                except Exception as e:
                    logger.warning(f"Failed to fetch vLLM models: {e}")
                    model = "vllm-model"

        try:
            stream = await self.client.chat.completions.create(
                model=model, messages=messages, stream=True, **kwargs
            )
            _in_think = False
            _finish_reason = None
            async for chunk in stream:
                if chunk.choices and len(chunk.choices) > 0:
                    chunk_text = chunk.choices[0].delta.content
                    if chunk.choices[0].finish_reason:
                        _finish_reason = chunk.choices[0].finish_reason
                    if chunk_text:
                        # Filter <think>…</think> reasoning blocks
                        if _in_think:
                            if "</think>" in chunk_text:
                                _in_think = False
                                after = chunk_text.split("</think>", 1)[1]
                                if after:
                                    tokens += 1
                                    yield after
                        elif "<think>" in chunk_text:
                            before = chunk_text.split("<think>", 1)[0]
                            if before:
                                tokens += 1
                                yield before
                            remainder = chunk_text.split("<think>", 1)[1]
                            if "</think>" in remainder:
                                after = remainder.split("</think>", 1)[1]
                                if after:
                                    tokens += 1
                                    yield after
                            else:
                                _in_think = True
                        else:
                            tokens += 1
                            yield chunk_text
            if _finish_reason == "stop":
                yield FINISH_STOP_SENTINEL
        except Exception as e:
            yield f"⚠️ **vLLM error:** {e}\n\nMake sure vLLM is running at `{self._current_host}`."
            return

        logger.info("vLLM [%s]: %d tokens in %.1fs", model, tokens, time.perf_counter() - t0)



# --- Provider registry (cached singletons) ---
_provider_cache: dict[str, LLMProvider] = {}

PROVIDER_CLASSES = {
    "anthropic": AnthropicLLM,
    "google": GoogleLLM,
    "grok": GrokLLM,
    "groq": GroqLLM,
    "huggingface": HuggingFaceLLM,
    "local": OllamaLLM,     # backward compat alias → Ollama
    "mistral": MistralLLM,
    "ollama": OllamaLLM,
    "openai": OpenAILLM,
    "openrouter": OpenRouterLLM,
    "vllm": VllmLLM,
}


def get_llm_provider(provider: str | None = None) -> LLMProvider:
    """
    Return a cached LLM provider instance.
    If provider is None, uses the default from config.
    """
    if provider is None:
        from config import LLM_PROVIDER
        provider = LLM_PROVIDER

    if provider not in _provider_cache:
        cls = PROVIDER_CLASSES.get(provider)
        if cls is None:
            raise ValueError(f"Unknown LLM provider: {provider}")
        _provider_cache[provider] = cls()

    return _provider_cache[provider]