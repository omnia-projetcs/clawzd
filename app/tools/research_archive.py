"""
Clawzd — Research Strategy Archive.
Inspired by HyperAgents' archive.jsonl + select_next_parent mechanism.

Stores the best research strategies (action sequences + outcomes) across
all projects, enabling score-proportional warm-start for new research.
"""
import json
import math
import os
import random
import uuid
import logging
from datetime import datetime, timezone

from config import DATA_DIR

logger = logging.getLogger("clawzd.research.archive")

ARCHIVE_PATH = os.path.join(DATA_DIR, "research", "strategy_archive.jsonl")


# ── Query Domain Classifier ──────────────────────────────────────────────────

_DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "technology":   ["ai", "machine learning", "software", "hardware", "tech", "code",
                     "programming", "algorithm", "framework", "api", "cloud"],
    "science":      ["research", "study", "experiment", "biology", "chemistry", "physics",
                     "quantum", "genome", "climate", "medicine", "clinical"],
    "finance":      ["market", "stock", "crypto", "investment", "economy", "financial",
                     "trading", "fund", "valuation", "revenue", "budget"],
    "security":     ["security", "vulnerability", "exploit", "audit", "threat", "malware",
                     "cyberattack", "pentest", "cve", "breach", "firewall"],
    "business":     ["startup", "company", "strategy", "product", "customer", "growth",
                     "competitor", "industry", "brand", "marketing", "sales"],
    "geopolitics":  ["politics", "government", "war", "country", "policy", "election",
                     "sanctions", "diplomacy", "international", "treaty"],
    "society":      ["social", "culture", "education", "health", "welfare", "public",
                     "community", "demographic", "population", "behavior"],
}


def classify_query_domain(query: str) -> str:
    """Classify a research query into a broad domain for archive lookup."""
    q_lower = query.lower()
    best_domain = "general"
    best_count = 0
    for domain, keywords in _DOMAIN_KEYWORDS.items():
        count = sum(1 for kw in keywords if kw in q_lower)
        if count > best_count:
            best_count = count
            best_domain = domain
    return best_domain


# ── Archive I/O ──────────────────────────────────────────────────────────────

def _load_archive() -> list[dict]:
    """Load all entries from the strategy archive."""
    if not os.path.isfile(ARCHIVE_PATH):
        return []
    entries = []
    with open(ARCHIVE_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except Exception:
                pass
    return entries


def save_strategy(
    query: str,
    domain: str,
    action_sequence: list[dict],
    scores_per_iteration: list[float],
    final_score: float,
    num_iterations: int,
    profile_id: str = "",
):
    """
    Persist a successful research strategy to the global archive.

    Only saves if the final_score is worth learning from (≥ 0.5).
    """
    if final_score < 0.5:
        return  # Not worth archiving low-quality strategies

    os.makedirs(os.path.dirname(ARCHIVE_PATH), exist_ok=True)
    entry = {
        "id": uuid.uuid4().hex[:8],
        "query_snippet": query[:80],
        "domain": domain,
        "profile_id": profile_id,
        "action_sequence": action_sequence[:20],   # Last 20 actions
        "scores_per_iteration": scores_per_iteration,
        "final_score": round(final_score, 3),
        "num_iterations": num_iterations,
        "efficiency": round(final_score / max(num_iterations, 1), 4),  # Score per iter
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(ARCHIVE_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    logger.info(
        "Strategy archived: domain=%s score=%.0f%% iter=%d",
        domain, final_score * 100, num_iterations,
    )


# ── Score-Proportional Strategy Selection (HyperAgents-style) ────────────────

def _softmax_weights(scores: list[float], temperature: float = 0.3) -> list[float]:
    """Compute softmax weights with temperature for score-proportional selection."""
    if not scores:
        return []
    max_s = max(scores)
    exps = [math.exp((s - max_s) / temperature) for s in scores]
    total = sum(exps)
    return [e / total for e in exps]


def get_best_strategy_for_domain(
    domain: str,
    min_score: float = 0.6,
    max_candidates: int = 10,
) -> dict | None:
    """
    Retrieve a high-performing strategy for the given domain.

    Uses score-proportional (softmax) selection — similar to HyperAgents'
    select_next_parent — so the best strategy is favoured but not always
    chosen, maintaining exploratory diversity.

    Returns the strategy dict or None if no good match.
    """
    entries = _load_archive()
    candidates = [
        e for e in entries
        if e.get("domain") == domain and e.get("final_score", 0) >= min_score
    ]
    if not candidates:
        # Try any domain with high score
        candidates = [e for e in entries if e.get("final_score", 0) >= min_score]
    if not candidates:
        return None

    # Limit to most recent high-scoring candidates
    candidates = sorted(candidates, key=lambda e: e.get("final_score", 0), reverse=True)
    candidates = candidates[:max_candidates]

    scores = [c["final_score"] for c in candidates]
    weights = _softmax_weights(scores)

    # Weighted random selection
    r = random.random()
    cumsum = 0.0
    for candidate, w in zip(candidates, weights):
        cumsum += w
        if cumsum >= r:
            return candidate
    return candidates[0]


def get_archive_stats() -> dict:
    """Return summary statistics about the strategy archive."""
    entries = _load_archive()
    if not entries:
        return {"total": 0, "domains": {}, "avg_score": 0.0}

    by_domain: dict[str, list[float]] = {}
    for e in entries:
        d = e.get("domain", "general")
        by_domain.setdefault(d, []).append(e.get("final_score", 0))

    return {
        "total": len(entries),
        "domains": {
            d: {
                "count": len(scores),
                "avg_score": round(sum(scores) / len(scores), 3),
                "best_score": round(max(scores), 3),
            }
            for d, scores in by_domain.items()
        },
        "avg_score": round(
            sum(e.get("final_score", 0) for e in entries) / len(entries), 3
        ),
    }
