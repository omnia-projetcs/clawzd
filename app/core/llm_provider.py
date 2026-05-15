"""
Clawzd — LLM Provider abstraction layer.
Supports Anthropic Claude, Google Gemini, Grok (xAI), Groq, HuggingFace,
Mistral, Ollama, OpenAI, and OpenRouter.
"""
import logging
import time
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator

import httpx
import openai

from config import (
    OLLAMA_HOST,
    OLLAMA_MODEL,
    OLLAMA_API_KEY,
    ANTHROPIC_API_KEY,
    GOOGLE_API_KEY,
    GROK_API_KEY,
    GROQ_API_KEY,
    HUGGINGFACE_API_KEY,
    MISTRAL_API_KEY,
    OPENAI_API_KEY,
    OPENROUTER_API_KEY,
)

logger = logging.getLogger("clawzd.llm")

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


async def _get_local_models() -> list[dict]:
    """Build local model list dynamically from Ollama."""
    ollama_host = _resolve_ollama_host()
    ollama_api_key = _resolve_ollama_api_key()
    try:
        headers = {"Authorization": f"Bearer {ollama_api_key}"} if ollama_api_key else {}
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{ollama_host}/api/tags", timeout=5, headers=headers)
        if resp.status_code == 200:
            data = resp.json()
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
    # Fallback: show configured model
    from config import OLLAMA_MODEL
    return [{"id": OLLAMA_MODEL, "label": f"{OLLAMA_MODEL} (Ollama)"}]


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

    # Ollama is always available (local, no API key required)
    result = {"ollama": local_models}

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
    """Local LLM via Ollama's OpenAI-compatible API."""
    
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
            async with httpx.AsyncClient() as client:
                resp = await client.get(f"{host}/api/tags", timeout=2.0, headers=headers)
            alive = resp.status_code == 200
        except Exception:
            alive = False
        self._health_cache["ok"] = alive
        self._health_cache["ts"] = now
        return alive

    async def chat_stream(self, messages, model=None, **kwargs):
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

        # Try the exact model name, then fall back to base:latest
        models_to_try = [model]
        if ":" in model and not model.endswith(":latest"):
            models_to_try.append(model.split(":")[0] + ":latest")
        elif ":" not in model:
            models_to_try.append(model + ":latest")

        for try_model in models_to_try:
            t0 = time.perf_counter()
            tokens = 0
            try:
                stream = await self.client.chat.completions.create(
                    model=try_model, messages=messages, stream=True, **kwargs
                )
                async for chunk in stream:
                    delta = chunk.choices[0].delta.content
                    if delta:
                        tokens += 1
                        yield delta
                elapsed = time.perf_counter() - t0
                logger.info("Ollama [%s]: %d tokens in %.1fs (%.0f tok/s)", try_model, tokens, elapsed, tokens / max(elapsed, 0.01))
                return  # success, stop trying
            except openai.NotFoundError:
                if try_model == models_to_try[-1]:
                    yield (
                        f"⚠️ **Model `{model}` not found in Ollama.**\n\n"
                        f"Install it with:\n```bash\nollama pull {model}\n```"
                    )
                    return
                logger.info("Model %s not found, trying %s...", try_model, models_to_try[-1])
                continue
            except openai.APIConnectionError:
                yield (
                    "⚠️ **Cannot connect to Ollama** "
                    f"(`{ollama_host}`).\n\n"
                    "Make sure Ollama is running: `ollama serve`"
                )
                return

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

        # Use Ollama's native /api/chat endpoint for vision
        ollama_host = _resolve_ollama_host()
        api_key = _resolve_ollama_api_key()
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        payload = {
            "model": model,
            "messages": ollama_messages,
            "stream": True,
        }

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
                async with client.stream(
                    "POST", f"{ollama_host}/api/chat",
                    json=payload, headers=headers,
                ) as resp:
                    async for line in resp.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            import json as _json
                            data = _json.loads(line)
                            chunk_text = data.get("message", {}).get("content", "")
                            if chunk_text:
                                tokens += 1
                                yield chunk_text
                            if data.get("done"):
                                break
                        except Exception:
                            continue
        except Exception as e:
            yield f"⚠️ **Vision error:** {e}"
            return

        elapsed = time.perf_counter() - t0
        logger.info("Ollama Vision [%s]: %d tokens in %.1fs", model, tokens, elapsed)


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
        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                tokens += 1
                yield delta
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
        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                tokens += 1
                yield delta
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
        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                tokens += 1
                yield delta
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
        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                tokens += 1
                yield delta
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
        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                tokens += 1
                yield delta
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
        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                tokens += 1
                yield delta
        logger.info("OpenRouter [%s]: %d tokens in %.1fs", model, tokens, time.perf_counter() - t0)


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