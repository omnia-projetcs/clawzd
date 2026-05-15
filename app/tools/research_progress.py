"""
Clawzd — Research Progress Tracker & Cost Monitor.
Inspired by GPT-Researcher's ResearchProgress + cost_callback pattern.

Provides:
  - ResearchProgress: structured real-time tracking of depth/breadth/phase
  - ResearchCostTracker: per-session LLM call cost estimation (USD)
  - ProgressSerializer: JSON serialization for SSE emission
"""
import time
import logging
from dataclasses import dataclass, field, asdict

logger = logging.getLogger("clawzd.research.progress")


# ── Research Phase Constants ──────────────────────────────────────────────────

class ResearchPhase:
    BRIEF        = "brief"          # Generating structured research brief
    PERSPECTIVES = "perspectives"   # STORM perspective decomposition
    PARALLEL     = "parallel"       # Parallel perspective branches
    SEARCH       = "search"         # Iterative search loop
    EVALUATE     = "evaluate"       # Multi-criteria evaluation
    REFLECT      = "reflect"        # Inter-iteration reflection
    CONDENSE     = "condense"       # Context condensation (IterResearch)
    REPORT       = "report"         # Final report generation
    DONE         = "done"           # Complete


# ── Progress Dataclass ────────────────────────────────────────────────────────

@dataclass
class ResearchProgress:
    """
    Structured progress tracker for the CLAWZD research loop.

    Inspired by GPT-Researcher's ResearchProgress class, extended with:
      - phase tracking (brief → perspectives → search → report)
      - live quality score from the multi-criteria evaluator
      - elapsed time tracking
      - cost estimation

    Emitted as JSON via SSE so the frontend can render a precise
    progress bar and live statistics panel.
    """
    # Phase
    phase: str = ResearchPhase.BRIEF
    phase_label: str = "Initialisation..."

    # Depth / breadth (GPT-Researcher style)
    current_depth: int = 0
    total_depth: int = 2
    current_breadth: int = 0
    total_breadth: int = 5

    # Query tracking
    current_query: str = ""
    completed_queries: int = 0
    total_queries: int = 0

    # Iteration tracking
    current_iteration: int = 0
    max_iterations: int = 10

    # Quality
    quality_score: float = 0.0
    target_score: float = 0.7
    weakest_axis: str = ""

    # Timing
    start_time: float = field(default_factory=time.time)
    elapsed_seconds: float = 0.0
    estimated_remaining_seconds: float = -1.0

    # Cost tracking
    total_cost_usd: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0

    # Source counts
    search_results_count: int = 0
    assets_count: int = 0
    sources_scraped: int = 0

    def update_elapsed(self) -> None:
        """Refresh elapsed time."""
        self.elapsed_seconds = round(time.time() - self.start_time, 1)

    def estimate_remaining(self) -> None:
        """Estimate time remaining based on iteration velocity."""
        if self.current_iteration < 2 or self.elapsed_seconds < 5:
            self.estimated_remaining_seconds = -1.0
            return
        secs_per_iter = self.elapsed_seconds / max(self.current_iteration, 1)
        remaining_iters = max(0, self.max_iterations - self.current_iteration)
        self.estimated_remaining_seconds = round(secs_per_iter * remaining_iters, 0)

    def set_phase(self, phase: str, label: str = "") -> None:
        """Update the current phase and its display label."""
        self.phase = phase
        self.phase_label = label or _default_phase_label(phase)
        self.update_elapsed()
        logger.debug("Research phase: %s — %s", phase, self.phase_label)

    def to_dict(self) -> dict:
        """Serialize to a JSON-safe dict for SSE emission."""
        self.update_elapsed()
        self.estimate_remaining()
        d = asdict(self)
        # Remove internal start_time (not needed on client)
        d.pop("start_time", None)
        # Add computed progress percentage
        if self.total_queries > 0:
            d["query_progress_pct"] = round(
                self.completed_queries / self.total_queries * 100
            )
        else:
            d["query_progress_pct"] = 0
        if self.max_iterations > 0:
            d["iteration_progress_pct"] = round(
                self.current_iteration / self.max_iterations * 100
            )
        else:
            d["iteration_progress_pct"] = 0
        return d


def _default_phase_label(phase: str) -> str:
    labels = {
        ResearchPhase.BRIEF:        "📋 Generating research brief...",
        ResearchPhase.PERSPECTIVES: "🔭 Decomposing perspectives (STORM)...",
        ResearchPhase.PARALLEL:     "🔬 Parallel multi-perspective research...",
        ResearchPhase.SEARCH:       "🔍 Iterative research...",
        ResearchPhase.EVALUATE:     "📊 Multi-criteria evaluation...",
        ResearchPhase.REFLECT:      "🪞 Strategic reflection...",
        ResearchPhase.CONDENSE:     "🗜️ Condensing context...",
        ResearchPhase.REPORT:       "✍️ Generating final report...",
        ResearchPhase.DONE:         "✅ Research complete",
    }
    return labels.get(phase, phase)


# ── Cost Tracker ──────────────────────────────────────────────────────────────

# Token pricing per 1M tokens (input / output) in USD — as of 2025
# Used only for estimation when no exact cost is available from the provider.
_MODEL_PRICING: dict[str, tuple[float, float]] = {
    # OpenAI
    "gpt-4o":              (2.50,  10.00),
    "gpt-4o-mini":         (0.15,   0.60),
    "gpt-4-turbo":         (10.00, 30.00),
    "o3-mini":             (1.10,   4.40),
    "o1":                  (15.00, 60.00),
    # Anthropic
    "claude-3-5-sonnet":   (3.00,  15.00),
    "claude-3-5-haiku":    (0.80,   4.00),
    "claude-3-opus":       (15.00, 75.00),
    # Google
    "gemini-2.0-flash":    (0.10,   0.40),
    "gemini-1.5-pro":      (1.25,   5.00),
    # Mistral
    "mistral-large":       (2.00,   6.00),
    "mistral-nemo":        (0.15,   0.15),
    # Local / Ollama (effectively free — near-zero cost)
    "ollama":              (0.00,   0.00),
    "default":             (0.50,   1.50),   # Conservative estimate
}


class ResearchCostTracker:
    """
    Per-session LLM cost estimator.

    Tracks cumulative token counts and estimates USD spend based on
    known provider pricing tables. Updated automatically via _llm_call
    in tools_research.py when integrated.

    Usage:
        tracker = ResearchCostTracker()
        tracker.add_call(input_tokens=1200, output_tokens=400, model="gpt-4o-mini")
        print(tracker.get_summary())  # {"total_usd": 0.0006, "calls": 1, ...}
    """

    def __init__(self):
        self._calls: int = 0
        self._total_input: int = 0
        self._total_output: int = 0
        self._total_usd: float = 0.0
        self._model_breakdown: dict[str, dict] = {}

    def add_call(
        self,
        input_tokens: int,
        output_tokens: int,
        model: str = "",
        provider: str = "",
    ) -> float:
        """
        Record one LLM API call and return the estimated cost in USD.

        Args:
            input_tokens: Number of prompt tokens consumed.
            output_tokens: Number of completion tokens generated.
            model: Model name (used for pricing lookup).
            provider: Provider name (used as fallback for local detection).

        Returns:
            Estimated cost for this call in USD.
        """
        model_key = _resolve_model_key(model, provider)
        price_in, price_out = _MODEL_PRICING.get(model_key, _MODEL_PRICING["default"])

        cost = (input_tokens * price_in + output_tokens * price_out) / 1_000_000

        self._calls += 1
        self._total_input += input_tokens
        self._total_output += output_tokens
        self._total_usd += cost

        # Per-model breakdown
        if model_key not in self._model_breakdown:
            self._model_breakdown[model_key] = {
                "calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0
            }
        self._model_breakdown[model_key]["calls"] += 1
        self._model_breakdown[model_key]["input_tokens"] += input_tokens
        self._model_breakdown[model_key]["output_tokens"] += output_tokens
        self._model_breakdown[model_key]["cost_usd"] += cost

        return cost

    def get_summary(self) -> dict:
        """Return a JSON-safe cost summary."""
        return {
            "total_usd": round(self._total_usd, 6),
            "total_usd_display": f"${self._total_usd:.4f}",
            "calls": self._calls,
            "total_input_tokens": self._total_input,
            "total_output_tokens": self._total_output,
            "total_tokens": self._total_input + self._total_output,
            "by_model": {
                k: {**v, "cost_usd": round(v["cost_usd"], 6)}
                for k, v in self._model_breakdown.items()
            },
        }

    def get_total_usd(self) -> float:
        return round(self._total_usd, 6)

    def reset(self) -> None:
        self.__init__()


def _resolve_model_key(model: str, provider: str) -> str:
    """Map a model name to a pricing table key (most specific match wins)."""
    if not model:
        if provider and ("ollama" in provider.lower() or "local" in provider.lower()):
            return "ollama"
        return "default"

    model_lower = model.lower()

    # Local / Ollama models — check provider first
    if provider and "ollama" in provider.lower():
        return "ollama"
    if any(x in model_lower for x in ["llama", "mistral-7b", "phi", "gemma", "qwen", "glm"]):
        if not any(x in model_lower for x in ["api", "cloud"]):
            return "ollama"

    # Explicit checks: most specific first
    if "gpt-4o-mini" in model_lower:
        return "gpt-4o-mini"
    if "claude-3-5" in model_lower and "haiku" in model_lower:
        return "claude-3-5-haiku"
    if "claude-3-5" in model_lower:
        return "claude-3-5-sonnet"
    if "gemini-2" in model_lower:
        return "gemini-2.0-flash"
    if "gemini" in model_lower:
        return "gemini-1.5-pro"
    if "o3-mini" in model_lower:
        return "o3-mini"
    if "gpt-4" in model_lower:
        return "gpt-4o"
    if "mistral" in model_lower:
        return "mistral-large"

    # Prefix match fallback (longest key first = most specific)
    for key in sorted(_MODEL_PRICING.keys(), key=len, reverse=True):
        if model_lower.startswith(key.lower()):
            return key

    return "default"
