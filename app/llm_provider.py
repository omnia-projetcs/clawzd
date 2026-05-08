"""
Clawzd — LLM Provider abstraction layer.
Supports Google Gemini, Grok (xAI), Groq, HuggingFace, Mistral, Ollama, OpenAI, and OpenRouter.
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
async def _get_local_models() -> list[dict]:
    """Build local model list dynamically from Ollama."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{OLLAMA_HOST}/api/tags", timeout=3)
        if resp.status_code == 200:
            data = resp.json()
            models = []
            for m in data.get("models", []):
                name = m.get("name", "unknown")
                size_gb = round(m.get("size", 0) / (1024**3), 1)
                label = f"{name} ({size_gb} GB)"
                models.append({"id": name, "label": label})
            if models:
                # Sort models alphabetically by label
                models.sort(key=lambda x: x["label"].lower())
                return models
    except Exception as e:
        logger.warning("Failed to fetch local models from Ollama: %s", e)
    # Fallback: show configured model
    from config import OLLAMA_MODEL
    return [{"id": OLLAMA_MODEL, "label": f"{OLLAMA_MODEL} (Ollama)"}]


async def _get_provider_models() -> dict:
    """Return provider models dict with dynamic local model list.
    
    Providers and models within each provider are sorted alphabetically.
    """
    local_models = await _get_local_models()
    return {
        "google": PROVIDER_MODELS_STATIC["google"],
        "grok": PROVIDER_MODELS_STATIC["grok"],
        "groq": PROVIDER_MODELS_STATIC["groq"],
        "huggingface": PROVIDER_MODELS_STATIC["huggingface"],
        "mistral": PROVIDER_MODELS_STATIC["mistral"],
        "ollama": local_models,
        "openai": PROVIDER_MODELS_STATIC["openai"],
        "openrouter": PROVIDER_MODELS_STATIC["openrouter"],
    }


PROVIDER_MODELS_STATIC = {
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
        {"id": "anthropic/claude-3.5-sonnet", "label": "Claude 3.5 Sonnet"},
        {"id": "google/gemini-pro-1.5", "label": "Gemini Pro 1.5"},
        {"id": "openai/gpt-4o", "label": "GPT-4o"},
        {"id": "openai/gpt-4o-mini", "label": "GPT-4o Mini"},
        {"id": "meta-llama/llama-3.1-70b-instruct", "label": "Llama 3.1 70B"},
    ],
}


class LLMProvider(ABC):
    """Abstract base class for all LLM providers."""

    @abstractmethod
    async def chat_stream(
        self, messages: list[dict], model: str | None = None, **kwargs
    ) -> AsyncGenerator[str, None]:
        """Stream tokens from a chat completion request."""
        pass  # pragma: no cover


class OllamaLLM(LLMProvider):
    """Local LLM via Ollama's OpenAI-compatible API."""

    def __init__(self):
        self.client = openai.AsyncOpenAI(
            base_url=f"{OLLAMA_HOST}/v1",
            api_key="ollama",  # required but ignored by Ollama
        )

    async def _is_ollama_running(self) -> bool:
        """Quick check if Ollama server is reachable."""
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(f"{OLLAMA_HOST}/api/tags", timeout=2.0)
            return resp.status_code == 200
        except Exception:
            return False

    async def chat_stream(self, messages, model=None, **kwargs):
        if not await self._is_ollama_running():
            yield (
                "⚠️ **Ollama is not running.**\n\n"
                "Start it with:\n```bash\nollama serve\n```\n\n"
                "Or check that it's listening on "
                f"`{OLLAMA_HOST}`."
            )
            return

        model = model or OLLAMA_MODEL
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
                    f"(`{OLLAMA_HOST}`).\n\n"
                    "Make sure Ollama is running: `ollama serve`"
                )
                return


class GoogleLLM(LLMProvider):
    """Google Gemini via the google-genai SDK."""

    def __init__(self):
        import google.genai as genai
        from google.genai import types  # noqa: F401
        self._genai = genai
        self._types = types
        self.client = genai.Client(api_key=GOOGLE_API_KEY)

    async def chat_stream(self, messages, model="gemini-2.0-flash", **kwargs):
        t0 = time.perf_counter()
        tokens = 0

        # Extract system messages into system_instruction (Gemini-native)
        system_parts = []
        contents = []
        for m in messages:
            if m["role"] == "system":
                system_parts.append(m["content"])
            else:
                role = "user" if m["role"] == "user" else "model"
                contents.append(
                    self._types.Content(role=role, parts=[self._types.Part(text=m["content"])])
                )

        # Build config with system_instruction if present
        config_kwargs = {}
        if system_parts:
            config_kwargs["system_instruction"] = "\n".join(system_parts)
        config = self._types.GenerateContentConfig(**config_kwargs) if config_kwargs else None

        gen_kwargs = {"model": model, "contents": contents}
        if config:
            gen_kwargs["config"] = config

        response = self.client.models.generate_content_stream(**gen_kwargs, **kwargs)
        for chunk in response:
            if chunk.text:
                tokens += 1
                yield chunk.text
        logger.info("Google [%s]: %d tokens in %.1fs", model, tokens, time.perf_counter() - t0)


class GrokLLM(LLMProvider):
    """Grok (xAI) API — OpenAI-compatible."""

    def __init__(self):
        self.client = openai.AsyncOpenAI(
            base_url="https://api.x.ai/v1",
            api_key=GROK_API_KEY,
        )

    async def chat_stream(self, messages, model="grok-3-mini", **kwargs):
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

    def __init__(self):
        self.client = openai.AsyncOpenAI(
            base_url="https://api.groq.com/openai/v1",
            api_key=GROQ_API_KEY,
        )

    async def chat_stream(self, messages, model="llama3-70b-8192", **kwargs):
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

    def __init__(self):
        self.client = openai.AsyncOpenAI(
            base_url="https://api.mistral.ai/v1",
            api_key=MISTRAL_API_KEY,
        )

    async def chat_stream(self, messages, model="mistral-small-latest", **kwargs):
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

    def __init__(self):
        self.client = openai.AsyncOpenAI(
            api_key=OPENAI_API_KEY,
        )

    async def chat_stream(self, messages, model="gpt-4o-mini", **kwargs):
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

    def __init__(self):
        self.client = openai.AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=OPENROUTER_API_KEY,
            default_headers={"HTTP-Referer": "http://localhost", "X-Title": "Clawzd"},
        )

    async def chat_stream(self, messages, model="openai/gpt-4o-mini", **kwargs):
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