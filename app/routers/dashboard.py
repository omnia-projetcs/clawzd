"""
Clawzd — Analytics Dashboard Router.

Fleet overview, time-series analytics, and session history endpoints.
Inspired by OpenClaw Studio's runtime/summary architecture.
"""
import logging
from collections import defaultdict
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Query

logger = logging.getLogger("clawzd.dashboard_router")

router = APIRouter(tags=["dashboard"])


# ------------------------------------------------------------------
# Fleet Overview (live session status)
# ------------------------------------------------------------------

@router.get("/fleet")
async def fleet_overview():
    """Return live session/fleet overview with KPI totals."""
    from app.core.metrics import get_metrics

    mc = get_metrics()
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    with mc._lock:
        all_calls = list(mc._llm_calls)
        all_requests = list(mc._requests)
        all_savings = list(mc._token_savings)

    # Today's LLM calls
    today_calls = [
        c for c in all_calls
        if _parse_ts(c.get("timestamp", "")) >= today_start
    ]

    # Session aggregation from today's calls
    sessions: dict[str, dict] = {}
    for c in today_calls:
        sid = c.get("session_id", "unknown") or "default"
        if sid not in sessions:
            sessions[sid] = {
                "session_id": sid,
                "model": c.get("model", ""),
                "provider": c.get("provider", ""),
                "first_call": c.get("timestamp", ""),
                "last_call": c.get("timestamp", ""),
                "call_count": 0,
                "total_tokens": 0,
                "total_latency": 0,
            }
        s = sessions[sid]
        s["call_count"] += 1
        s["total_tokens"] += c.get("total_tokens", 0)
        s["total_latency"] += c.get("latency_s", 0)
        s["last_call"] = c.get("timestamp", s["last_call"])
        s["model"] = c.get("model", s["model"])

    # Compute per-session avg latency
    session_list = []
    for s in sessions.values():
        s["avg_latency_s"] = round(
            s["total_latency"] / max(s["call_count"], 1), 3
        )
        del s["total_latency"]
        session_list.append(s)

    # Sort by last_call descending
    session_list.sort(key=lambda x: x["last_call"], reverse=True)

    # KPI totals
    total_tokens_today = sum(c.get("total_tokens", 0) for c in today_calls)
    total_calls_today = len(today_calls)
    avg_latency = (
        round(
            sum(c.get("latency_s", 0) for c in today_calls) /
            max(total_calls_today, 1),
            3,
        )
    )
    avg_tps = (
        round(
            sum(c.get("tokens_per_s", 0) for c in today_calls) /
            max(total_calls_today, 1),
            1,
        )
    )

    # Token savings today
    today_savings = [
        s for s in all_savings
        if _parse_ts(s.get("timestamp", "")) >= today_start
    ]
    total_saved_chars = sum(s.get("saved_chars", 0) for s in today_savings)

    return {
        "timestamp": now.isoformat(),
        "sessions": session_list,
        "totals": {
            "active_sessions": len(session_list),
            "total_calls_today": total_calls_today,
            "total_tokens_today": total_tokens_today,
            "avg_latency_s": avg_latency,
            "avg_tokens_per_s": avg_tps,
            "total_saved_chars": total_saved_chars,
            "total_requests_today": len([
                r for r in all_requests
                if _parse_ts(r.get("timestamp", "")) >= today_start
            ]),
        },
    }


# ------------------------------------------------------------------
# Time-series analytics (for charts)
# ------------------------------------------------------------------

@router.get("/analytics/timeseries")
async def analytics_timeseries(
    hours: int = Query(24, ge=1, le=168),
    bucket_minutes: int = Query(60, ge=5, le=1440),
):
    """Return time-bucketed token usage and latency for chart rendering."""
    from app.core.metrics import get_metrics

    mc = get_metrics()
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours)

    with mc._lock:
        calls = [
            c for c in mc._llm_calls
            if _parse_ts(c.get("timestamp", "")) >= cutoff
        ]

    # Create time buckets
    buckets: dict[str, dict] = {}

    for c in calls:
        ts = _parse_ts(c.get("timestamp", ""))
        # Round down to the nearest bucket boundary (handles > 60 min buckets)
        epoch = int(ts.timestamp())
        bucket_secs = bucket_minutes * 60
        rounded_epoch = (epoch // bucket_secs) * bucket_secs
        bucket_ts = datetime.fromtimestamp(rounded_epoch, tz=timezone.utc)
        key = bucket_ts.isoformat()
        if key not in buckets:
            buckets[key] = {
                "timestamp": key,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "calls": 0,
                "latency_sum": 0,
                "tokens_per_s_sum": 0,
            }
        b = buckets[key]
        b["input_tokens"] += c.get("input_tokens", 0)
        b["output_tokens"] += c.get("output_tokens", 0)
        b["total_tokens"] += c.get("total_tokens", 0)
        b["calls"] += 1
        b["latency_sum"] += c.get("latency_s", 0)
        b["tokens_per_s_sum"] += c.get("tokens_per_s", 0)

    # Compute averages and sort
    result = []
    for b in buckets.values():
        b["avg_latency_s"] = round(
            b["latency_sum"] / max(b["calls"], 1), 3
        )
        b["avg_tokens_per_s"] = round(
            b["tokens_per_s_sum"] / max(b["calls"], 1), 1
        )
        del b["latency_sum"]
        del b["tokens_per_s_sum"]
        result.append(b)

    result.sort(key=lambda x: x["timestamp"])
    return {"buckets": result, "hours": hours, "bucket_minutes": bucket_minutes}


# ------------------------------------------------------------------
# Model performance breakdown
# ------------------------------------------------------------------

@router.get("/analytics/models")
async def analytics_models(hours: int = Query(24, ge=1, le=168)):
    """Return per-model performance stats for bar charts."""
    from app.core.metrics import get_metrics

    mc = get_metrics()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    with mc._lock:
        calls = [
            c for c in mc._llm_calls
            if _parse_ts(c.get("timestamp", "")) >= cutoff
        ]

    by_model: dict[str, dict] = {}
    for c in calls:
        model = c.get("model", "unknown") or "default"
        if model not in by_model:
            by_model[model] = {
                "model": model,
                "provider": c.get("provider", ""),
                "calls": 0,
                "total_tokens": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "latency_sum": 0,
                "tps_sum": 0,
            }
        m = by_model[model]
        m["calls"] += 1
        m["total_tokens"] += c.get("total_tokens", 0)
        m["input_tokens"] += c.get("input_tokens", 0)
        m["output_tokens"] += c.get("output_tokens", 0)
        m["latency_sum"] += c.get("latency_s", 0)
        m["tps_sum"] += c.get("tokens_per_s", 0)

    result = []
    for m in by_model.values():
        m["avg_latency_s"] = round(
            m["latency_sum"] / max(m["calls"], 1), 3
        )
        m["avg_tokens_per_s"] = round(
            m["tps_sum"] / max(m["calls"], 1), 1
        )
        del m["latency_sum"]
        del m["tps_sum"]
        result.append(m)

    result.sort(key=lambda x: x["calls"], reverse=True)
    return {"models": result, "hours": hours}


# ------------------------------------------------------------------
# Tool usage distribution
# ------------------------------------------------------------------

@router.get("/analytics/tools")
async def analytics_tools(hours: int = Query(24, ge=1, le=168)):
    """Return tool usage distribution for doughnut chart."""
    from app.core.metrics import get_metrics

    mc = get_metrics()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    with mc._lock:
        savings = [
            s for s in mc._token_savings
            if _parse_ts(s.get("timestamp", "")) >= cutoff
        ]

    by_tool: dict[str, dict] = {}
    for s in savings:
        tool = s.get("tool", "unknown")
        if tool not in by_tool:
            by_tool[tool] = {
                "tool": tool,
                "count": 0,
                "saved_chars": 0,
                "original_chars": 0,
            }
        t = by_tool[tool]
        t["count"] += 1
        t["saved_chars"] += s.get("saved_chars", 0)
        t["original_chars"] += s.get("original_chars", 0)

    result = []
    for t in by_tool.values():
        t["savings_pct"] = round(
            (1 - (t["original_chars"] - t["saved_chars"]) /
             max(t["original_chars"], 1)) * 100,
            1,
        )
        result.append(t)

    result.sort(key=lambda x: x["count"], reverse=True)
    return {"tools": result, "hours": hours}


# ------------------------------------------------------------------
# Activity heatmap (calls per hour for the last 7 days)
# ------------------------------------------------------------------

@router.get("/analytics/heatmap")
async def analytics_heatmap():
    """Return activity heatmap data (7 days × 24 hours)."""
    from app.core.metrics import get_metrics

    mc = get_metrics()
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)

    with mc._lock:
        calls = [
            c for c in mc._llm_calls
            if _parse_ts(c.get("timestamp", "")) >= cutoff
        ]

    # Build 7×24 grid (day_of_week × hour)
    grid: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    for c in calls:
        ts = _parse_ts(c.get("timestamp", ""))
        day_label = ts.strftime("%a")  # Mon, Tue, ...
        hour = ts.hour
        grid[day_label][hour] += 1

    # Convert to array format for frontend
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    heatmap = []
    for day in days:
        row = {"day": day, "hours": [grid[day][h] for h in range(24)]}
        heatmap.append(row)

    return {"heatmap": heatmap}


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _parse_ts(ts_str: str) -> datetime:
    """Parse an ISO timestamp string to a datetime, with fallback."""
    if not ts_str:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(ts_str)
    except (ValueError, TypeError):
        return datetime.min.replace(tzinfo=timezone.utc)
