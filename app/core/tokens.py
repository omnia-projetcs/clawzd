"""
Clawzd — Token counting utilities with Shadow Tokenization.
"""
import threading
import tiktoken
import logging
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("clawzd.tokens")

_encodings = {}

def get_encoding(model: str = "gpt-4o"):
    if model not in _encodings:
        try:
            _encodings[model] = tiktoken.encoding_for_model(model)
        except KeyError:
            _encodings[model] = tiktoken.get_encoding("cl100k_base")
    return _encodings[model]

# ─────────────────────────────────────────────
# 1. TOKEN CACHE  (LRU simple)
# ─────────────────────────────────────────────

class TokenCache:
    """
    Cache LRU des tokenisations déjà calculées.
    Évite de re-tokeniser le même texte (préfixes système, historique, etc.)
    """
    def __init__(self, max_size: int = 2048):
        self._cache: OrderedDict[str, int] = OrderedDict()  # Cache token counts to save memory
        self._max_size = max_size
        self._hits = 0
        self._misses = 0
        self._lock = threading.Lock()

    def get(self, text: str, model: str) -> Optional[int]:
        key = f"{model}:{text}"
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                self._hits += 1
                return self._cache[key]
            self._misses += 1
            return None

    def set(self, text: str, model: str, count: int) -> None:
        key = f"{model}:{text}"
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            else:
                if len(self._cache) >= self._max_size:
                    self._cache.popitem(last=False)
                self._cache[key] = count

    @property
    def hit_rate(self) -> float:
        total = self._hits + self._misses
        return self._hits / total if total else 0.0

    def stats(self) -> dict:
        return {
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": f"{self.hit_rate:.1%}",
            "cache_size": len(self._cache),
        }

# ─────────────────────────────────────────────
# 2. SHADOW TOKENIZER
# ─────────────────────────────────────────────

@dataclass
class PendingTokenisation:
    text: str
    model: str
    result: Optional[int] = field(default=None, init=False)
    ready: threading.Event = field(default_factory=threading.Event, init=False)
    error: Optional[Exception] = field(default=None, init=False)

class ShadowTokenizer:
    def __init__(self, cache_size: int = 2048, n_workers: int = 2):
        self._cache = TokenCache(max_size=cache_size)
        self._pending: dict[str, PendingTokenisation] = {}
        self._lock = threading.Lock()
        self._semaphore = threading.Semaphore(n_workers)

    def prefetch(self, text: str, model: str = "gpt-4o") -> None:
        if not text:
            return
        # Already cached
        if self._cache.get(text, model) is not None:
            return

        key = f"{model}:{text}"
        with self._lock:
            if key in self._pending:
                return
            pending = PendingTokenisation(text=text, model=model)
            self._pending[key] = pending

        thread = threading.Thread(
            target=self._worker,
            args=(pending,),
            daemon=True,
            name=f"shadow-tok-{id(pending)}",
        )
        thread.start()

    def get_token_count(self, text: str, model: str = "gpt-4o", timeout: float = 5.0) -> int:
        if not text:
            return 0
            
        cached = self._cache.get(text, model)
        if cached is not None:
            return cached

        key = f"{model}:{text}"
        with self._lock:
            pending = self._pending.get(key)

        if pending is not None:
            pending.ready.wait(timeout=timeout)
            if pending.error:
                # Fallback on error
                return self._sync_tokenize(text, model)
            if pending.result is not None:
                return pending.result

        # Fallback sync
        return self._sync_tokenize(text, model)

    def _sync_tokenize(self, text: str, model: str) -> int:
        try:
            enc = get_encoding(model)
            count = len(enc.encode(text, disallowed_special=()))
            self._cache.set(text, model, count)
            return count
        except Exception as e:
            logger.warning("Tokenize error: %s", e)
            return max(1, len(text) // 4)

    def _worker(self, pending: PendingTokenisation) -> None:
        with self._semaphore:
            try:
                enc = get_encoding(pending.model)
                count = len(enc.encode(pending.text, disallowed_special=()))
                self._cache.set(pending.text, pending.model, count)
                pending.result = count
            except Exception as exc:
                pending.error = exc
            finally:
                pending.ready.set()
                with self._lock:
                    key = f"{pending.model}:{pending.text}"
                    self._pending.pop(key, None)

    def cache_stats(self) -> dict:
        return self._cache.stats()

# Global shadow tokenizer instance
shadow_tokenizer = ShadowTokenizer()

def count_tokens(text: str, model: str = "gpt-4o") -> int:
    """Return the number of tokens in a text string using shadow cache."""
    return shadow_tokenizer.get_token_count(text, model)

def count_message_tokens(messages: list[dict], model: str = "gpt-4o") -> int:
    """Return the number of tokens used by a list of messages."""
    if not messages:
        return 0
    try:
        num_tokens = 0
        for message in messages:
            num_tokens += 3  # every message follows <|start|>{role/name}\n{content}<|end|>\n
            for key, value in message.items():
                val_str = str(value)
                if val_str:
                    num_tokens += shadow_tokenizer.get_token_count(val_str, model)
        num_tokens += 3  # every reply is primed with <|start|>assistant<|message|>
        return num_tokens
    except Exception as e:
        logger.warning("Failed to count message tokens: %s", e)
        return sum(max(1, len(str(m.get("content", ""))) // 4) for m in messages)
