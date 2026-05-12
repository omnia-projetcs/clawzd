"""
Clawzd — Research Analytics API.

Aggregates research project history, iteration performance, source
quality metrics, and strategy archive stats into dashboard-ready data.
"""
import os
import json
import logging
from config import DATA_DIR

logger = logging.getLogger("clawzd.research.analytics")

RESEARCH_DIR = os.path.join(DATA_DIR, "research")


def get_research_analytics() -> dict:
    """Aggregate analytics across all research projects.

    Returns a dashboard-ready dict with:
      - project_count, completed_count, avg_score
      - score_timeline: [{project, iteration, score, timestamp}]
      - source_breakdown: {source_type: count}
      - domain_stats: {domain: {count, avg_score}}
      - recent_projects: latest 10 projects with key metrics
      - performance: {avg_iterations, avg_time_to_completion, best_score}
    """
    projects = _load_all_projects()

    if not projects:
        return _empty_analytics()

    # Score timeline (all iterations across all projects)
    score_timeline = []
    source_breakdown: dict[str, int] = {}
    domain_stats: dict[str, dict] = {}
    total_iterations = 0
    completed_projects = []

    for proj in projects:
        pid = proj.get("id", "")
        title = proj.get("title", pid)[:40]
        domain = proj.get("query_domain", "general")
        status = proj.get("status", "idle")
        score = proj.get("current_score", 0)

        # Per-domain
        if domain not in domain_stats:
            domain_stats[domain] = {"count": 0, "scores": [], "completed": 0}
        domain_stats[domain]["count"] += 1
        if status == "completed":
            domain_stats[domain]["completed"] += 1
        domain_stats[domain]["scores"].append(score)

        # Iterations
        iterations = proj.get("iterations", [])
        total_iterations += len(iterations)
        for it in iterations:
            score_timeline.append({
                "project": title,
                "project_id": pid,
                "iteration": it.get("num", 0),
                "score": round(it.get("score", 0) * 100),
                "timestamp": it.get("started_at", ""),
            })

        # Sources
        for r in proj.get("search_results", []):
            src = r.get("source", "web")
            source_breakdown[src] = source_breakdown.get(src, 0) + 1

        if status == "completed":
            completed_projects.append(proj)

    # Compute domain averages
    domain_summary = {}
    for d, stats in domain_stats.items():
        scores = stats["scores"]
        domain_summary[d] = {
            "count": stats["count"],
            "completed": stats["completed"],
            "avg_score": round(sum(scores) / len(scores) * 100) if scores else 0,
            "best_score": round(max(scores) * 100) if scores else 0,
        }

    # Performance metrics
    avg_iterations = round(total_iterations / len(projects), 1) if projects else 0
    all_scores = [p.get("current_score", 0) for p in projects]
    avg_score = round(sum(all_scores) / len(all_scores) * 100) if all_scores else 0
    best_score = round(max(all_scores) * 100) if all_scores else 0

    # Recent projects (last 10)
    recent = sorted(projects, key=lambda p: p.get("updated_at", ""), reverse=True)[:10]
    recent_projects = [
        {
            "id": p.get("id", ""),
            "title": p.get("title", "")[:60],
            "status": p.get("status", "idle"),
            "score": round(p.get("current_score", 0) * 100),
            "iterations": len(p.get("iterations", [])),
            "domain": p.get("query_domain", "general"),
            "updated_at": p.get("updated_at", ""),
            "sources_count": len(p.get("search_results", [])),
        }
        for p in recent
    ]

    # Strategy archive stats
    archive_stats = {}
    try:
        from app.tools.research_archive import get_archive_stats
        archive_stats = get_archive_stats()
    except Exception:
        pass

    return {
        "project_count": len(projects),
        "completed_count": len(completed_projects),
        "total_iterations": total_iterations,
        "avg_score": avg_score,
        "best_score": best_score,
        "avg_iterations_per_project": avg_iterations,
        "score_timeline": score_timeline[-100:],  # Last 100 data points
        "source_breakdown": source_breakdown,
        "domain_stats": domain_summary,
        "recent_projects": recent_projects,
        "archive_stats": archive_stats,
    }


def _load_all_projects() -> list[dict]:
    """Load all project.json files from the research directory."""
    if not os.path.isdir(RESEARCH_DIR):
        return []
    projects = []
    for name in os.listdir(RESEARCH_DIR):
        pf = os.path.join(RESEARCH_DIR, name, "project.json")
        if os.path.isfile(pf):
            try:
                with open(pf, encoding="utf-8") as f:
                    projects.append(json.load(f))
            except Exception:
                pass
    return projects


def _empty_analytics() -> dict:
    return {
        "project_count": 0,
        "completed_count": 0,
        "total_iterations": 0,
        "avg_score": 0,
        "best_score": 0,
        "avg_iterations_per_project": 0,
        "score_timeline": [],
        "source_breakdown": {},
        "domain_stats": {},
        "recent_projects": [],
        "archive_stats": {"total": 0, "domains": {}, "avg_score": 0},
    }
