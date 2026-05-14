"""
Clawzd — Research Profiles management.
Provides built-in and custom research profiles, each containing a
process-template Markdown, iteration/score defaults, and model hints.
"""
import os
import json
import uuid
import logging
from datetime import datetime, timezone
from config import RESEARCH_DIR

logger = logging.getLogger("clawzd.research.profiles")

PROFILES_DIR = os.path.join(RESEARCH_DIR, "profiles")
os.makedirs(PROFILES_DIR, exist_ok=True)

# ── Root profiles directory (contains .md templates) ──
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
_TEMPLATES_DIR = os.path.join(_PROJECT_ROOT, "profiles")


def _load_template(filename: str) -> str:
    """Load a process template .md file from the profiles/ directory."""
    path = os.path.join(_TEMPLATES_DIR, filename)
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        logger.warning("Template file not found: %s", path)
        return ""


# ── Load templates from .md files ──

DEFAULT_PROCESS_MD = _load_template("research_default.md")

# ── Built-in profiles ──

BUILTIN_PROFILES: list[dict] = [
    {
        "id": "quick_explore",
        "name": "🔍 Quick Exploration",
        "description": "Fast web research — 3 iterations, target score 0.5",
        "icon": "search",
        "target_score": 0.5,
        "max_iterations": 3,
        "allowed_actions": ["web_search", "scrape_url"],
        "sources": "Web",
        "recommended_provider": "",
        "phase_models": {},
        "builtin": True,
        "process_template_file": "research_quick_explore.md",
    },
    {
        "id": "technical_analysis",
        "name": "🔬 Technical Analysis",
        "description": "In-depth analysis — 8 iterations, scraping + sandbox code",
        "icon": "code",
        "target_score": 0.8,
        "max_iterations": 8,
        "allowed_actions": [
            "web_search", "scrape_url", "download_asset",
            "write_script", "query_rag",
        ],
        "sources": "Web, Scraping, Code Sandbox, RAG",
        "recommended_provider": "",
        "phase_models": {},
        "builtin": True,
        "process_template_file": "research_technical_analysis.md",
    },
    {
        "id": "market_watch",
        "name": "📊 Market Watch",
        "description": "Sector monitoring — 5 iterations, web + RAG",
        "icon": "trending-up",
        "target_score": 0.7,
        "max_iterations": 5,
        "allowed_actions": ["web_search", "scrape_url", "query_rag"],
        "sources": "Web, RAG",
        "recommended_provider": "",
        "phase_models": {},
        "builtin": True,
        "process_template_file": "research_market_watch.md",
    },
    {
        "id": "security_audit",
        "name": "🛡️ Security Audit",
        "description": "Comprehensive audit — 10 iterations, target score 0.9, all actions",
        "icon": "shield",
        "target_score": 0.9,
        "max_iterations": 10,
        "allowed_actions": [
            "web_search", "scrape_url", "download_asset",
            "write_script", "query_rag",
        ],
        "sources": "Web, Scraping, Code Sandbox, RAG, Assets",
        "recommended_provider": "",
        "phase_models": {},
        "builtin": True,
        "process_template_file": "research_security_audit.md",
    },
    {
        "id": "academic",
        "name": "📚 Academic Research",
        "description": "Deep research — 10 iterations, long synthesis",
        "icon": "book-open",
        "target_score": 0.85,
        "max_iterations": 10,
        "allowed_actions": [
            "web_search", "scrape_url", "download_asset", "query_rag",
        ],
        "sources": "Web, Scraping, RAG, Assets",
        "recommended_provider": "",
        "phase_models": {},
        "builtin": True,
        "process_template_file": "research_academic.md",
    },
    {
        "id": "deep_research",
        "name": "🧠 Deep Research",
        "description": (
            "Maximum depth — recursive sub-topic exploration, "
            "multi-perspective analysis, smart scraping, citations"
        ),
        "icon": "brain",
        "target_score": 0.85,
        "max_iterations": 20,
        "allowed_actions": [
            "web_search", "scrape_url", "download_asset",
            "write_script", "query_rag", "deep_dive", "smart_scrape",
            "ask_model",
        ],
        "sources": "Web, Scraping, Deep Dive, Smart Scrape, RAG, Assets, Model Knowledge",
        "recommended_provider": "",
        "phase_models": {},
        "builtin": True,
        "process_template_file": "research_deep_research.md",
    },
    {
        "id": "blog_article",
        "name": "✍️ Article & Blog Writer",
        "description": "Rich content creation — generates .md articles with Mermaid, tables, and illustrations.",
        "icon": "pen-tool",
        "target_score": 0.8,
        "max_iterations": 6,
        "allowed_actions": ["web_search", "scrape_url", "query_rag"],
        "sources": "Web, RAG",
        "recommended_provider": "",
        "phase_models": {},
        "builtin": True,
        "process_template_file": "research_blog_article.md",
    },
]

# Resolve process_template from file at load time
for _profile in BUILTIN_PROFILES:
    _file = _profile.pop("process_template_file", "")
    _profile["process_template"] = _load_template(_file) if _file else DEFAULT_PROCESS_MD


def list_profiles() -> list[dict]:
    """Return built-in + custom profiles."""
    profiles = list(BUILTIN_PROFILES)
    # Load custom profiles from disk
    for fname in sorted(os.listdir(PROFILES_DIR)):
        if not fname.endswith(".json"):
            continue
        try:
            with open(os.path.join(PROFILES_DIR, fname)) as f:
                p = json.load(f)
            p["builtin"] = False
            profiles.append(p)
        except Exception:
            pass
    return profiles


def get_profile(profile_id: str) -> dict | None:
    """Return a single profile by ID."""
    for p in BUILTIN_PROFILES:
        if p["id"] == profile_id:
            return p
    fpath = os.path.join(PROFILES_DIR, f"{profile_id}.json")
    if os.path.isfile(fpath):
        try:
            with open(fpath) as f:
                p = json.load(f)
            p["builtin"] = False
            return p
        except Exception:
            return None
    return None


def create_profile(data: dict) -> dict:
    """Create a new custom profile."""
    pid = data.get("id") or uuid.uuid4().hex[:8]
    profile = {
        "id": pid,
        "name": data.get("name", "Custom Profile"),
        "description": data.get("description", ""),
        "icon": data.get("icon", "settings"),
        "target_score": float(data.get("target_score", 0.7)),
        "max_iterations": int(data.get("max_iterations", 5)),
        "allowed_actions": data.get("allowed_actions", ["web_search"]),
        "sources": data.get("sources", "Web"),
        "recommended_provider": data.get("recommended_provider", ""),
        "phase_models": data.get("phase_models", {}),
        "process_template": data.get("process_template", DEFAULT_PROCESS_MD),
        "builtin": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(os.path.join(PROFILES_DIR, f"{pid}.json"), "w") as f:
        json.dump(profile, f, indent=2, ensure_ascii=False)
    return profile


def delete_profile(profile_id: str) -> bool:
    """Delete a custom profile (built-in profiles cannot be deleted)."""
    for p in BUILTIN_PROFILES:
        if p["id"] == profile_id:
            return False  # Cannot delete built-in
    fpath = os.path.join(PROFILES_DIR, f"{profile_id}.json")
    if os.path.isfile(fpath):
        os.remove(fpath)
        return True
    return False


def render_process_md(template: str, **kwargs) -> str:
    """Render a process template with project-specific values."""
    return template.format(
        query=kwargs.get("query", ""),
        model=kwargs.get("model", "System Default"),
        provider=kwargs.get("provider", "System Default"),
        sources=kwargs.get("sources", "Web"),
        target_score=kwargs.get("target_score", 0.7),
        max_iterations=kwargs.get("max_iterations", 10),
    )
