"""
Clawzd — Semantic cache for LLM responses.
Avoids redundant LLM calls for identical or near-identical queries.
Uses a TTL-based cache keyed by a hash of the conversation messages.
"""
import hashlib
import logging
from typing import Optional

from cachetools import TTLCache

logger = logging.getLogger("clawzd.cache")

# Cache up to 200 responses, expire after 30 minutes
_cache: TTLCache = TTLCache(maxsize=200, ttl=1800)


def _make_cache_key(messages: list[dict], provider: str, model: str) -> str:
    """Create a deterministic cache key from messages + provider + model.

    Only considers the last 3 messages (system + user context) to allow
    cache hits even when early conversation history differs.
    """
    # Take system prompt + last 2 messages for the key
    relevant = []
    for m in messages:
        if m["role"] == "system":
            relevant.append(("system", m["content"][:500]))  # truncate system prompt
    # Add last 2 non-system messages
    non_system = [m for m in messages if m["role"] != "system"]
    for m in non_system[-2:]:
        relevant.append((m["role"], m["content"]))

    raw = f"{provider}:{model}:" + str(relevant)
    return hashlib.sha256(raw.encode()).hexdigest()


def get_cached_response(
    messages: list[dict], provider: str, model: str
) -> Optional[str]:
    """Check if a cached response exists for the given messages.

    Returns the cached response string, or None if not cached.
    """
    key = _make_cache_key(messages, provider, model)
    hit = _cache.get(key)
    if hit is not None:
        logger.info("Cache HIT (key=%s…)", key[:12])
    return hit


def cache_response(
    messages: list[dict], provider: str, model: str, response: str
):
    """Store a response in the cache.

    Only caches responses that are substantial (>50 chars) to avoid
    caching error messages or empty responses.
    """
    if len(response.strip()) < 50:
        return  # Don't cache trivial responses

    key = _make_cache_key(messages, provider, model)
    _cache[key] = response
    logger.info("Cache STORE (key=%s…, %d chars)", key[:12], len(response))


def clear_cache():
    """Clear all cached responses."""
    _cache.clear()
    logger.info("Cache cleared")


def cache_stats() -> dict:
    """Return cache statistics."""
    return {
        "size": len(_cache),
        "maxsize": _cache.maxsize,
        "ttl": _cache.ttl,
    }
