"""
Clawzd — Centralized metrics and monitoring.
Tracks LLM latency, request counts, token throughput, and system resources.
"""
import os
import time
import json
import logging
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Optional

from config import DATA_DIR

logger = logging.getLogger("clawzd.metrics")

METRICS_FILE = os.path.join(DATA_DIR, "metrics.jsonl")


class MetricsCollector:
    """Thread-safe metrics collector for LLM and request monitoring.

    Stores recent metrics in memory (ring buffer) and optionally
    appends to a JSONL file for persistence.
    """

    _instance: Optional["MetricsCollector"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "MetricsCollector":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialised = False
        return cls._instance

    def __init__(self):
        if getattr(self, '_initialised', False):
            return
        self._llm_calls: deque[dict] = deque(maxlen=500)
        self._requests: deque[dict] = deque(maxlen=1000)
        self._token_savings: deque[dict] = deque(maxlen=500)
        self._initialised = True
        self._load_persisted()

    # ------------------------------------------------------------------
    # LLM call tracking
    # ------------------------------------------------------------------

    def record_llm_call(
        self,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        latency_s: float,
        session_id: str = "",
    ):
        """Record an LLM call with timing and token counts."""
        # Resolve empty / placeholder model names to the actual configured model
        if not model or model in ("default", "unknown"):
            model = self._resolve_default_model(provider) or model or "unknown"

        entry = {
            "type": "llm_call",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "provider": provider,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "latency_s": round(latency_s, 3),
            "tokens_per_s": round(output_tokens / max(latency_s, 0.001), 1),
            "session_id": session_id,
        }
        with self._lock:
            self._llm_calls.append(entry)
        self._persist(entry)

    def _resolve_default_model(self, provider: str = "") -> str:
        """Resolve the actual default model name from settings or provider."""
        # 1. Try settings
        try:
            from app.core.settings import load_settings
            settings = load_settings()
            dm = settings.get("default_model", "")
            if dm:
                return dm
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Error loading settings in _resolve_default_model: {e}")

        # 2. Try the provider's default_model attribute
        if provider:
            try:
                from app.llm_provider import get_llm_provider
                prov = get_llm_provider(provider)
                dm = getattr(prov, "default_model", "") or getattr(prov, "model", "")
                if dm:
                    return dm
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"Error getting provider in _resolve_default_model: {e}")

        return ""

    # ------------------------------------------------------------------
    # Request tracking
    # ------------------------------------------------------------------

    def record_request(
        self,
        method: str,
        path: str,
        status_code: int,
        latency_s: float,
    ):
        """Record an HTTP request with timing."""
        entry = {
            "type": "request",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "method": method,
            "path": path,
            "status_code": status_code,
            "latency_s": round(latency_s, 3),
        }
        with self._lock:
            self._requests.append(entry)

    # ------------------------------------------------------------------
    # Token savings tracking (RTK-style analytics)
    # ------------------------------------------------------------------

    def record_token_savings(
        self,
        tool_name: str,
        original_chars: int,
        compressed_chars: int,
    ):
        """Record token savings from output compression."""
        savings_pct = (
            round((1 - compressed_chars / max(original_chars, 1)) * 100, 1)
        )
        entry = {
            "type": "token_savings",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tool": tool_name,
            "original_chars": original_chars,
            "compressed_chars": compressed_chars,
            "saved_chars": original_chars - compressed_chars,
            "savings_pct": savings_pct,
        }
        with self._lock:
            self._token_savings.append(entry)
        if savings_pct > 10:
            logger.info(
                "Token savings [%s]: %d → %d chars (%.0f%% saved)",
                tool_name, original_chars, compressed_chars, savings_pct,
            )

    # ------------------------------------------------------------------
    # System resources
    # ------------------------------------------------------------------

    @staticmethod
    def get_system_resources() -> dict:
        """Return current GPU VRAM and system RAM usage."""
        info = {
            "gpu_name": None,
            "vram_total_mib": None,
            "vram_used_mib": None,
            "vram_free_mib": None,
            "ram_total_mib": None,
            "ram_used_mib": None,
            "ram_free_mib": None,
        }

        # GPU info via nvidia-smi
        try:
            import subprocess
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total,memory.used,memory.free",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                parts = result.stdout.strip().split(", ")
                info["gpu_name"] = parts[0]
                info["vram_total_mib"] = int(parts[1])
                info["vram_used_mib"] = int(parts[2])
                info["vram_free_mib"] = int(parts[3])
        except Exception as e:
            logger.warning("Failed to get GPU resources: %s", e)

        # RAM info via /proc/meminfo
        try:
            with open("/proc/meminfo") as f:
                meminfo = {}
                for line in f:
                    key, val = line.split(":")
                    meminfo[key.strip()] = int(val.strip().split()[0])
            info["ram_total_mib"] = meminfo.get("MemTotal", 0) // 1024
            info["ram_free_mib"] = meminfo.get("MemAvailable", 0) // 1024
            info["ram_used_mib"] = info["ram_total_mib"] - info["ram_free_mib"]
        except Exception as e:
            logger.warning("Failed to get RAM resources: %s", e)

        return info

    # ------------------------------------------------------------------
    # Aggregation
    # ------------------------------------------------------------------

    def get_summary(self) -> dict:
        """Return aggregated metrics summary."""
        with self._lock:
            llm_calls = list(self._llm_calls)
            requests = list(self._requests)

        # LLM stats
        total_llm = len(llm_calls)
        total_tokens = sum(c.get("total_tokens", 0) for c in llm_calls)
        total_latency = sum(c.get("latency_s", 0) for c in llm_calls)
        avg_latency = total_latency / max(total_llm, 1)
        avg_tps = sum(c.get("tokens_per_s", 0) for c in llm_calls) / max(total_llm, 1)

        # Per-provider and per-model breakdown
        by_provider: dict[str, dict] = {}
        by_model: dict[str, dict] = {}
        for c in llm_calls:
            p = c.get("provider", "unknown")
            m = c.get("model", "unknown") or "unknown"
            if m in ("default", "unknown"):
                m = self._resolve_default_model(p) or m
            
            if p not in by_provider:
                by_provider[p] = {"calls": 0, "tokens": 0, "latency_sum": 0}
            by_provider[p]["calls"] += 1
            by_provider[p]["tokens"] += c.get("total_tokens", 0)
            by_provider[p]["latency_sum"] += c.get("latency_s", 0)

            if m not in by_model:
                by_model[m] = {"calls": 0, "tokens": 0, "latency_sum": 0, "provider": p}
            by_model[m]["calls"] += 1
            by_model[m]["tokens"] += c.get("total_tokens", 0)
            by_model[m]["latency_sum"] += c.get("latency_s", 0)

        for p, stats in by_provider.items():
            stats["avg_latency_s"] = round(stats["latency_sum"] / max(stats["calls"], 1), 3)
            del stats["latency_sum"]

        for m, stats in by_model.items():
            stats["avg_latency_s"] = round(stats["latency_sum"] / max(stats["calls"], 1), 3)
            del stats["latency_sum"]

        # Request stats
        total_req = len(requests)

        # Token savings stats
        with self._lock:
            savings = list(self._token_savings)
        total_saved_chars = sum(s.get("saved_chars", 0) for s in savings)
        total_original = sum(s.get("original_chars", 0) for s in savings)
        overall_savings_pct = (
            round((1 - (total_original - total_saved_chars) / max(total_original, 1)) * 100, 1)
            if total_original else 0
        )
        by_tool_savings: dict[str, dict] = {}
        for s in savings:
            t = s.get("tool", "unknown")
            if t not in by_tool_savings:
                by_tool_savings[t] = {"count": 0, "saved_chars": 0, "original_chars": 0}
            by_tool_savings[t]["count"] += 1
            by_tool_savings[t]["saved_chars"] += s.get("saved_chars", 0)
            by_tool_savings[t]["original_chars"] += s.get("original_chars", 0)
        for t, stats in by_tool_savings.items():
            stats["savings_pct"] = round(
                (1 - (stats["original_chars"] - stats["saved_chars"]) / max(stats["original_chars"], 1)) * 100, 1
            )

        return {
            "llm": {
                "total_calls": total_llm,
                "total_tokens": total_tokens,
                "avg_latency_s": round(avg_latency, 3),
                "avg_tokens_per_s": round(avg_tps, 1),
                "by_provider": by_provider,
                "by_model": by_model,
            },
            "requests": {
                "total": total_req,
            },
            "token_savings": {
                "total_compressions": len(savings),
                "total_original_chars": total_original,
                "total_saved_chars": total_saved_chars,
                "overall_savings_pct": overall_savings_pct,
                "by_tool": by_tool_savings,
            },
            "system": self.get_system_resources(),
            "recent_llm_calls": llm_calls[-10:],
        }

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load_persisted(self):
        """Load historical metrics from the JSONL file on startup."""
        if not os.path.exists(METRICS_FILE):
            return
        loaded = 0
        try:
            with open(METRICS_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except (json.JSONDecodeError, ValueError):
                        continue
                    entry_type = entry.get("type", "")
                    if entry_type == "llm_call":
                        self._llm_calls.append(entry)
                    elif entry_type == "token_savings":
                        self._token_savings.append(entry)
                    # requests are transient — not persisted/restored
                    loaded += 1
        except Exception as e:
            logger.error("Failed to load persisted metrics: %s", e)
        if loaded:
            logger.info(
                "Restored %d persisted metrics (%d LLM calls, %d token savings)",
                loaded, len(self._llm_calls), len(self._token_savings),
            )

    def _persist(self, entry: dict):
        """Append a metric entry to the JSONL file."""
        try:
            os.makedirs(os.path.dirname(METRICS_FILE), exist_ok=True)
            with open(METRICS_FILE, "a") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error("Failed to persist metrics: %s", e)


# Module-level singleton
_collector: Optional[MetricsCollector] = None


def get_metrics() -> MetricsCollector:
    """Return the global MetricsCollector singleton."""
    global _collector
    if _collector is None:
        _collector = MetricsCollector()
    return _collector
