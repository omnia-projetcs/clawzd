"""
Clawzd — Research Studio module.
Autonomous research bot with iterative improvement, auto-evaluation,
web scraping, asset downloading, and multi-format report export.
V2: Multi-phase process, editable Markdown process, research profiles,
sandbox execution with venv, chat-to-research integration.
"""
import os, json, uuid, logging, asyncio, hashlib, shutil, subprocess, sys
from datetime import datetime, timezone
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from sse_starlette.sse import EventSourceResponse
from config import DATA_DIR
from app.tools.research_profiles import (
    list_profiles, get_profile, create_profile, delete_profile,
    render_process_md, DEFAULT_PROCESS_MD,
)
from app.tools.research_engine import (
    generate_perspectives, generate_sub_questions,
    deep_research_branch, flatten_branch_results,
    flatten_branch_summaries, evaluate_structured,
    reflect_on_iteration, generate_report_with_citations,
)
from app.tools.research_scraper import batch_scrape, smart_scrape
from app.core.tokens import count_tokens

router = APIRouter()
logger = logging.getLogger("clawzd.research")

RESEARCH_DIR = os.path.join(DATA_DIR, "research")
os.makedirs(RESEARCH_DIR, exist_ok=True)

# In-memory state for running research tasks
_running: dict[str, asyncio.Task] = {}
_sse_queues: dict[str, asyncio.Queue] = {}


def _get_dev_profile_summary() -> str:
    """Load a condensed dev best practices summary for research script generation."""
    try:
        from app.preprompts import _load_dev_profile
        profile = _load_dev_profile()
        if profile:
            # Return a condensed version to save tokens in the planning prompt
            return profile[:1500]
    except Exception:
        pass
    return ""


# ── Helpers ──

def _proj_dir(pid: str) -> str:
    d = os.path.join(RESEARCH_DIR, pid)
    os.makedirs(d, exist_ok=True)
    os.makedirs(os.path.join(d, "assets"), exist_ok=True)
    return d

def _load(pid: str) -> dict | None:
    p = os.path.join(_proj_dir(pid), "project.json")
    if os.path.exists(p):
        with open(p) as f:
            return json.load(f)
    return None

def _save(proj: dict):
    proj["updated_at"] = datetime.now(timezone.utc).isoformat()
    with open(os.path.join(_proj_dir(proj["id"]), "project.json"), "w") as f:
        json.dump(proj, f, indent=2, ensure_ascii=False)

def _new_project(
    query: str, provider: str = "", model: str = "",
    profile_id: str = "", profile_data: dict | None = None,
) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    pid = uuid.uuid4().hex[:8]
    target_score = 0.7
    max_iterations = 10
    sources = "Web"
    if profile_data:
        target_score = profile_data.get("target_score", target_score)
        max_iterations = profile_data.get("max_iterations", max_iterations)
        sources = profile_data.get("sources", sources)
    proj = {
        "id": pid,
        "title": query[:80],
        "query": query,
        "status": "idle",
        "created_at": now,
        "updated_at": now,
        "iterations": [],
        "current_score": 0.0,
        "target_score": target_score,
        "max_iterations": max_iterations,
        "report_md": "",
        "assets": [],
        "search_results": [],
        "provider": provider,
        "model": model,
        "profile_id": profile_id,
        "phase_models": profile_data.get("phase_models", {}) if profile_data else {},
    }
    # Generate initial process.md
    tmpl = (profile_data or {}).get("process_template", DEFAULT_PROCESS_MD)
    process_md = render_process_md(
        tmpl, query=query, model=model or "System Default",
        provider=provider or "System Default", sources=sources,
        target_score=target_score, max_iterations=max_iterations,
    )
    pdir = _proj_dir(pid)
    with open(os.path.join(pdir, "process.md"), "w", encoding="utf-8") as f:
        f.write(process_md)
    return proj

def _list_projects() -> list:
    projects = []
    if not os.path.isdir(RESEARCH_DIR):
        return projects
    for name in os.listdir(RESEARCH_DIR):
        pf = os.path.join(RESEARCH_DIR, name, "project.json")
        if os.path.isfile(pf):
            try:
                with open(pf) as f:
                    d = json.load(f)
                projects.append({
                    "id": d["id"], "title": d.get("title", ""),
                    "status": d.get("status", "idle"),
                    "current_score": d.get("current_score", 0),
                    "iteration_count": len(d.get("iterations", [])),
                    "updated_at": d.get("updated_at", ""),
                    "profile_id": d.get("profile_id", ""),
                })
            except Exception:
                pass
    return sorted(projects, key=lambda x: x.get("updated_at", ""), reverse=True)


def _read_process(pid: str) -> str:
    """Read the process.md for a project."""
    path = os.path.join(_proj_dir(pid), "process.md")
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            return f.read()
    return ""


def _write_process(pid: str, content: str):
    """Write the process.md for a project."""
    path = os.path.join(_proj_dir(pid), "process.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def _ensure_venv(pid: str) -> str:
    """Create a Python venv for a project sandbox if it doesn't exist."""
    venv_dir = os.path.join(_proj_dir(pid), ".venv")
    if not os.path.isdir(venv_dir):
        subprocess.run(
            [sys.executable, "-m", "venv", venv_dir],
            capture_output=True, timeout=60,
        )
    return venv_dir


def _venv_python(pid: str) -> str:
    """Return path to the venv's python executable."""
    venv = _ensure_venv(pid)
    return os.path.join(venv, "bin", "python")


async def _emit(pid: str, event_type: str, data: dict):
    q = _sse_queues.get(pid)
    if q:
        await q.put(json.dumps({"type": event_type, **data}))


# ── Research Loop Engine ──

async def _do_web_search(query: str, max_results: int = 50) -> list[dict]:
    """Search using Tavily, DuckDuckGo, Google Scholar, Reddit, Twitter/X, and News in parallel."""
    from config import TAVILY_API_KEY
    from app.tools_web import _scrape_scholar

    async def _tavily_search() -> list[dict]:
        if not TAVILY_API_KEY:
            return []
        try:
            from tavily import AsyncTavilyClient
            client = AsyncTavilyClient(api_key=TAVILY_API_KEY)
            response = await client.search(query, max_results=max_results)
            return [
                {"title": r.get("title", ""), "snippet": r.get("content", ""),
                 "url": r.get("url", ""), "score": r.get("score", 0), "source": "tavily"}
                for r in response.get("results", [])
            ]
        except Exception as e:
            logger.warning("Tavily search failed: %s", e)
            return []

    async def _ddg_search() -> list[dict]:
        try:
            from ddgs import DDGS
            results = await asyncio.to_thread(
                lambda: list(DDGS().text(query, max_results=max_results))
            )
            return [{"title": r.get("title",""), "snippet": r.get("body",""),
                     "url": r.get("href",""), "source": "duckduckgo"} for r in results]
        except Exception as e:
            logger.warning("DuckDuckGo search failed: %s", e)
            return []

    async def _scholar_search() -> list[dict]:
        try:
            res = await asyncio.to_thread(_scrape_scholar, query, max_results)
            res_labs = await asyncio.to_thread(
                _scrape_scholar, query, max_results,
                "https://scholar.google.com/scholar_labs/search",
            )
            combined = res + res_labs
            return [{"title": r.get("title",""), "snippet": r.get("snippet",""),
                     "url": r.get("url",""), "source": "scholar"} for r in combined]
        except Exception as e:
            logger.warning("Google Scholar search failed: %s", e)
            return []

    async def _reddit_search() -> list[dict]:
        """Search Reddit discussions via DuckDuckGo site-scoped query."""
        try:
            from ddgs import DDGS
            reddit_query = f"site:reddit.com {query}"
            results = await asyncio.to_thread(
                lambda: list(DDGS().text(reddit_query, max_results=min(max_results, 20)))
            )
            return [{"title": f"[Reddit] {r.get('title','')}", "snippet": r.get("body",""),
                     "url": r.get("href",""), "source": "reddit"} for r in results]
        except Exception as e:
            logger.warning("Reddit search failed: %s", e)
            return []

    async def _twitter_search() -> list[dict]:
        """Search Twitter/X using the existing tools_twitter module."""
        try:
            from app.tools_twitter import search_tweets
            tweets = await search_tweets(query, max_results=min(max_results, 20))
            return [{"title": f"[X] @{t.get('author_username','unknown')}: {t.get('text','')[:80]}",
                     "snippet": t.get("text", ""),
                     "url": t.get("url", ""),
                     "source": "twitter"} for t in tweets]
        except Exception as e:
            logger.warning("Twitter/X search failed: %s", e)
            return []

    async def _news_search() -> list[dict]:
        """Search news articles via DuckDuckGo News API."""
        try:
            from ddgs import DDGS
            results = await asyncio.to_thread(
                lambda: list(DDGS().news(query, max_results=min(max_results, 25)))
            )
            return [{"title": f"[News] {r.get('title','')}", "snippet": r.get("body",""),
                     "url": r.get("url",""), "source": "news",
                     "date": r.get("date", "")} for r in results]
        except Exception as e:
            logger.warning("News search failed: %s", e)
            return []

    # Run ALL sources in parallel
    (tavily_results, ddg_results, scholar_results,
     reddit_results, twitter_results, news_results) = await asyncio.gather(
        _tavily_search(), _ddg_search(), _scholar_search(),
        _reddit_search(), _twitter_search(), _news_search(),
    )

    # Merge & deduplicate by URL
    # Priority order: Tavily > News > Twitter > Reddit > Scholar > DDG
    seen_urls = set()
    merged = []
    for r in (tavily_results + news_results + twitter_results
              + reddit_results + scholar_results + ddg_results):
        url = r.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            merged.append(r)
    return merged


async def _scrape_url(url: str) -> str:
    try:
        import httpx
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"
            })
            if resp.status_code != 200:
                return ""
            ct = resp.headers.get("content-type", "")
            if "html" in ct:
                from html.parser import HTMLParser
                class TextExtractor(HTMLParser):
                    def __init__(self):
                        super().__init__()
                        self.text = []
                        self._skip = False
                    def handle_starttag(self, tag, attrs):
                        if tag in ("script","style","nav","footer","header"):
                            self._skip = True
                    def handle_endtag(self, tag):
                        if tag in ("script","style","nav","footer","header"):
                            self._skip = False
                    def handle_data(self, data):
                        if not self._skip and data.strip():
                            # Append with a space to prevent words from sticking together
                            self.text.append(data.strip() + " ")
                parser = TextExtractor()
                parser.feed(resp.text)
                return "".join(parser.text).replace("  ", " ")[:8000]
            return resp.text[:8000]
    except Exception as e:
        logger.warning("Scrape failed for %s: %s", url, e)
        return ""


async def _download_asset(url: str, pid: str) -> dict | None:
    try:
        import httpx
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                return None
            ct = resp.headers.get("content-type", "")
            ext = ".bin"
            if "pdf" in ct: ext = ".pdf"
            elif "png" in ct: ext = ".png"
            elif "jpeg" in ct or "jpg" in ct: ext = ".jpg"
            elif "gif" in ct: ext = ".gif"
            elif "svg" in ct: ext = ".svg"
            elif "webp" in ct: ext = ".webp"
            name = f"asset_{uuid.uuid4().hex[:6]}{ext}"
            path = os.path.join(_proj_dir(pid), "assets", name)
            with open(path, "wb") as f:
                f.write(resp.content)
            return {"name": name, "path": path, "type": ext.lstrip("."),
                    "url": url, "size": len(resp.content)}
    except Exception as e:
        logger.warning("Download failed for %s: %s", url, e)
        return None


async def _save_text_asset(title: str, text: str, source_type: str, url_or_ref: str, pid: str) -> dict:
    name = f"asset_{uuid.uuid4().hex[:6]}.md"
    path = os.path.join(_proj_dir(pid), "assets", name)
    content = f"# {title}\n\n**Source**: {url_or_ref}\n**Type**: {source_type}\n\n{text}"
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return {"name": name, "path": path, "type": "md", "url": url_or_ref, "size": len(content)}


async def _llm_call(messages: list[dict], provider: str = "", model: str = "", pid: str = "") -> str:
    from app.llm_provider import get_llm_provider
    from app.metrics import get_metrics
    import time
    prov = get_llm_provider(provider or None)
    kwargs = {}
    if model:
        kwargs["model"] = model

    # Estimate input tokens using tiktoken
    input_text = "".join(m.get("content", "") for m in messages)
    input_tokens = max(1, count_tokens(input_text, model or ""))

    result = ""
    t0 = time.time()
    async for token in prov.chat_stream(messages, **kwargs):
        result += token
    elapsed = time.time() - t0

    # Estimate output tokens using tiktoken
    output_tokens = max(1, count_tokens(result, model or ""))

    # Record in metrics
    get_metrics().record_llm_call(
        provider=provider or "default",
        model=model or "default",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_s=elapsed,
        session_id=pid or "",
    )

    # Emit token usage via SSE if a project is active
    if pid:
        await _emit(pid, "token_usage", {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "latency_s": round(elapsed, 2),
        })

    return result


async def _research_loop(pid: str):
    from app.tools.task_manager import register_task, unregister_task
    proj = _load(pid)
    if not proj:
        return
    proj["status"] = "running"
    _save(proj)
    await _emit(pid, "status", {"status": "running"})
    register_task(pid, "research", proj.get("title", pid)[:60])

    provider = proj.get("provider", "")
    model = proj.get("model", "")
    query = proj["query"]

    # --- Project Management Tracking ---
    from app import tools_project as pm
    pm_pid = proj.get("pm_project_id")
    if not pm_pid:
        pm_proj = pm._new_project(name=f"Research: {query[:40]}", description=f"Automated tracking for research on: {query}")
        now = datetime.now(timezone.utc).isoformat()
        pm_proj["tasks"] = [
            {"id": "t1", "title": "Perspective Decomposition", "status": "To Do", "progress": 0, "order": 0, "created_at": now},
            {"id": "t2", "title": "Data Gathering & Search", "status": "To Do", "progress": 0, "order": 1, "created_at": now},
            {"id": "t3", "title": "Multi-criteria Evaluation", "status": "To Do", "progress": 0, "order": 2, "created_at": now},
            {"id": "t4", "title": "Final Report Generation", "status": "To Do", "progress": 0, "order": 3, "created_at": now},
        ]
        pm._save_proj(pm_proj)
        proj["pm_project_id"] = pm_proj["id"]
        _save(proj)
        pm_pid = pm_proj["id"]

    def _update_pm_task(idx, status, progress):
        try:
            p = pm._load_proj(pm_pid)
            if p and len(p.get("tasks", [])) > idx:
                p["tasks"][idx]["status"] = status
                p["tasks"][idx]["progress"] = progress
                pm._save_proj(p)
        except Exception:
            pass
    # -----------------------------------

    # Wrap _llm_call with project ID bound for token tracking
    async def _project_llm_call(messages, prov="", mdl=""):
        return await _llm_call(messages, prov, mdl, pid=pid)

    # Deep research state
    perspectives = []
    sub_questions = []
    uncovered_questions = []
    branch_summaries = ""
    last_eval = {}

    async def _emit_log(msg: str, extra: dict | None = None):
        payload = {"msg": msg}
        if extra:
            payload.update(extra)
        await _emit(pid, "log", payload)

    try:
        # ── Phase 0: Perspective Decomposition (STORM-style) ──
        _update_pm_task(0, "In Progress", 50)
        await _emit_log("🔭 Generating research perspectives...")
        perspectives = await generate_perspectives(
            query, _project_llm_call, provider, model,
        )
        if perspectives:
            proj["perspectives"] = [
                {"perspective": p["perspective"], "description": p["description"]}
                for p in perspectives
            ]
            _save(proj)
            names = [p["perspective"] for p in perspectives]
            await _emit_log(f"📐 {len(perspectives)} perspectives: {', '.join(names)}")

            sub_questions = await generate_sub_questions(
                query, perspectives, _project_llm_call, provider, model,
            )
            uncovered_questions = list(sub_questions)
            await _emit_log(f"❓ {len(sub_questions)} sub-questions generated")
            _update_pm_task(0, "Done", 100)

        # ── Iteration Loop ──
        for iteration in range(len(proj["iterations"]), proj["max_iterations"]):
            if pid not in _running:
                proj["status"] = "paused"
                _save(proj)
                await _emit(pid, "status", {"status": "paused"})
                return

            iter_num = iteration + 1
            iter_data = {
                "num": iter_num,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "actions": [], "score": 0, "evaluation": "",
                "scores_detail": {},
            }
            await _emit(pid, "iteration_start", {"iteration": iter_num})
            _update_pm_task(1, "In Progress", int((iter_num - 1) / proj["max_iterations"] * 100))

            # ── 1. Planning (reflection-guided after first iteration) ──
            actions = []
            if iter_num > 1 and last_eval:
                await _emit_log(f"🪞 Reflecting on iteration {iter_num - 1}...")
                reflection = await reflect_on_iteration(
                    query, iter_num, proj["max_iterations"],
                    last_eval, uncovered_questions,
                    _project_llm_call, provider, model,
                )
                actions = reflection.get("priority_actions", [])
                # Mark covered questions
                for cq in reflection.get("covered_questions", []):
                    if cq in uncovered_questions:
                        uncovered_questions.remove(cq)
                if not actions:
                    for fq in reflection.get("focus_queries", [])[:3]:
                        actions.append({"action": "web_search", "params": {"query": fq}})

            if not actions:
                # Standard planning with perspective context
                existing = json.dumps(proj["search_results"][-20:], ensure_ascii=False)[:3000]
                persp_ctx = "\n".join(
                    f"- {p['perspective']}: {p.get('description', '')}"
                    for p in perspectives
                ) if perspectives else "No specific perspectives"
                uncov_ctx = "\n".join(
                    f"- {q}" for q in uncovered_questions[:8]
                ) if uncovered_questions else "All questions covered"

                plan_prompt = [
                    {"role": "system", "content": (
                        "You are an autonomous research assistant. Plan the next actions.\n"
                        "Available actions: web_search, scrape_url, deep_dive, "
                        "download_asset, write_script, query_rag, smart_scrape, ask_model\n"
                        "- web_search: searches Tavily, DDG, Scholar, Reddit, X, News in parallel\n"
                        "- deep_dive: recursive deep research on a sub-topic (params: {topic, depth, breadth})\n"
                        "- smart_scrape: scrape + LLM extraction of relevant content (params: {urls: [...]})\n"
                        "- ask_model: exploit the AI model's internal knowledge (params: {question: \"...\"})\n"
                        "Return JSON array of actions.\n"
                        "Return ONLY valid JSON array, no markdown fences.\n"
                        + _get_dev_profile_summary()
                    )},
                    {"role": "user", "content": (
                        f"Research topic: {query}\n"
                        f"Iteration: {iter_num}/{proj['max_iterations']}\n"
                        f"Current score: {proj['current_score']}\n\n"
                        f"Perspectives to cover:\n{persp_ctx}\n\n"
                        f"Uncovered questions:\n{uncov_ctx}\n\n"
                        f"Previous results: {existing[:2000]}\n"
                        f"Plan 2-5 actions to improve research quality."
                    )},
                ]
                await _emit_log(f"🧠 Planning iteration {iter_num}...")
                plan_text = await _project_llm_call(plan_prompt, provider, model)
                try:
                    s = plan_text.find("[")
                    e = plan_text.rfind("]")
                    if s != -1 and e != -1:
                        actions = json.loads(plan_text[s:e+1])
                except Exception:
                    actions = [{"action": "web_search", "params": {"query": query}}]

            # ── 2. Execute actions ──
            for act in actions[:5]:
                action_type = act.get("action", "")
                params = act.get("params", {})
                await _emit_log(f"⚡ {action_type} — {json.dumps(params)[:100]}")

                if action_type == "web_search":
                    results = await _do_web_search(params.get("query", query))
                    proj["search_results"].extend(results)
                    urls = [r.get("url") for r in results if r.get("url")]
                    iter_data["actions"].append({"type": "web_search", "count": len(results), "urls": urls, "params": params})
                    await _emit_log(f"   Found {len(results)} results", extra={"urls": urls})

                elif action_type == "deep_dive":
                    topic = params.get("topic", query)
                    depth = min(int(params.get("depth", 3)), 4)
                    breadth = min(int(params.get("breadth", 4)), 5)
                    branch = await deep_research_branch(
                        topic, query, depth, breadth,
                        _do_web_search, _scrape_url, _project_llm_call,
                        provider, model, _emit_log,
                    )
                    branch_results = flatten_branch_results(branch)
                    proj["search_results"].extend(branch_results)
                    branch_summaries += "\n\n" + flatten_branch_summaries(branch)
                    iter_data["actions"].append({
                        "type": "deep_dive", "topic": topic,
                        "branches": len(branch.get("sub_branches", [])),
                        "results": len(branch_results),
                    })
                    await _emit_log(
                        f"   🌿 Deep dive: {len(branch_results)} results, "
                        f"{len(branch.get('sub_branches', []))} branches"
                    )

                elif action_type == "smart_scrape":
                    urls = params.get("urls", [])
                    if isinstance(urls, str):
                        urls = [urls]
                    if urls:
                        scraped = await batch_scrape(
                            urls[:5], query, _scrape_url, _project_llm_call,
                            provider, model,
                        )
                        for s in scraped:
                            proj["search_results"].append({
                                "title": f"Smart-scraped: {s['url'][:60]}",
                                "snippet": s["relevant_extract"][:500],
                                "url": s["url"],
                                "full_text": s["relevant_extract"],
                                "key_facts": s.get("key_facts", []),
                                "source": "smart_scrape",
                            })
                            asset = await _save_text_asset(f"Smart Scrape: {s['url'][:60]}", s["relevant_extract"], "smart_scrape", s["url"], pid)
                            proj["assets"].append(asset)
                        
                        scraped_urls = [s["url"] for s in scraped if s.get("url")]
                        iter_data["actions"].append({"type": "smart_scrape", "count": len(scraped), "urls": scraped_urls})
                        await _emit_log(f"   🔍 Smart-scraped {len(scraped)} pages", extra={"urls": scraped_urls})

                elif action_type == "scrape_url":
                    url = params.get("url", "")
                    if url:
                        text = await _scrape_url(url)
                        if text:
                            proj["search_results"].append({
                                "title": f"Scraped: {url[:60]}",
                                "snippet": text[:500], "url": url,
                                "full_text": text,
                            })
                            asset = await _save_text_asset(f"Scraped: {url[:60]}", text, "scrape", url, pid)
                            proj["assets"].append(asset)
                            iter_data["actions"].append({"type": "scrape", "url": url})
                            await _emit_log(f"   Scraped {len(text)} chars")

                elif action_type == "download_asset":
                    url = params.get("url", "")
                    if url:
                        asset = await _download_asset(url, pid)
                        if asset:
                            proj["assets"].append(asset)
                            iter_data["actions"].append({"type": "download", "name": asset["name"]})
                            await _emit_log(f"   Downloaded: {asset['name']}")

                elif action_type == "query_rag":
                    try:
                        from app.rag import explicit_rag_search
                        rag_q = params.get("query", query)
                        rag_ctx = explicit_rag_search(rag_q, k=3)
                        if rag_ctx:
                            proj["search_results"].append({
                                "title": f"RAG: {rag_q[:50]}",
                                "snippet": rag_ctx[:500], "url": "rag://local",
                            })
                            asset = await _save_text_asset(f"RAG Context: {rag_q[:50]}", rag_ctx, "rag_context", "local", pid)
                            proj["assets"].append(asset)
                            iter_data["actions"].append({"type": "rag", "query": rag_q})
                            await _emit_log(f"   RAG returned context")
                    except Exception:
                        pass

                elif action_type == "write_script":
                    script_code = params.get("code", "")
                    if script_code:
                        try:
                            script_path = os.path.join(_proj_dir(pid), "temp_script.py")
                            with open(script_path, "w") as f:
                                f.write(script_code)
                            result = await asyncio.to_thread(
                                subprocess.run, ["python3", script_path],
                                capture_output=True, text=True, timeout=30,
                                cwd=_proj_dir(pid),
                            )
                            output = result.stdout[:2000]
                            proj["search_results"].append({
                                "title": f"🧪 Experiment: {params.get('description', 'script')[:50]}",
                                "snippet": output[:500],
                                "url": "sandbox://experiment",
                                "full_text": output,
                                "source": "experiment",
                                "code": script_code[:500],
                            })
                            asset = await _save_text_asset(f"Script Experiment", f"Code:\n```python\n{script_code}\n```\n\nOutput:\n```\n{output}\n```", "script_experiment", "sandbox", pid)
                            proj["assets"].append(asset)
                            iter_data["actions"].append({"type": "script", "output": output[:200]})
                            await _emit_log(f"   Script output: {output[:200]}")
                        except Exception as e:
                            await _emit_log(f"   Script error: {e}")

                elif action_type == "ask_model":
                    question = params.get("question", params.get("query", query))
                    knowledge_prompt = [
                        {"role": "system", "content": (
                            "You are a knowledgeable expert. Answer the question "
                            "using your training knowledge. Provide detailed, factual "
                            "information with specific data points, dates, names. "
                            "If uncertain, say so. Be thorough (500-1000 words)."
                        )},
                        {"role": "user", "content": (
                            f"Research context: {query}\n\n"
                            f"Question: {question}"
                        )},
                    ]
                    knowledge = await _project_llm_call(knowledge_prompt, provider, model)
                    if knowledge:
                        proj["search_results"].append({
                            "title": f"🤖 Model Knowledge: {question[:60]}",
                            "snippet": knowledge[:500],
                            "url": "model://internal-knowledge",
                            "full_text": knowledge,
                            "source": "model_knowledge",
                        })
                        asset = await _save_text_asset(f"Model Knowledge: {question[:60]}", knowledge, "model_knowledge", "internal", pid)
                        proj["assets"].append(asset)
                        iter_data["actions"].append({"type": "ask_model", "question": question[:100]})
                        await _emit_log(f"   🤖 Model knowledge: {len(knowledge)} chars")

            # ── 3. Structured Evaluation ──
            _update_pm_task(1, "In Progress", int((iter_num - 0.5) / proj["max_iterations"] * 100))
            _update_pm_task(2, "In Progress", int((iter_num - 1) / proj["max_iterations"] * 100))
            await _emit_log("📊 Multi-criteria evaluation...")
            last_eval = await evaluate_structured(
                query, perspectives, proj["search_results"],
                len(proj["assets"]), _project_llm_call, provider, model,
            )
            proj["current_score"] = last_eval["overall"]
            iter_data["score"] = last_eval["overall"]
            iter_data["evaluation"] = last_eval.get("evaluation", "")
            iter_data["scores_detail"] = last_eval.get("scores", {})

            scores_display = " | ".join(
                f"{ax}: {v:.0%}" for ax, v in last_eval.get("scores", {}).items()
            )
            await _emit_log(f"   {scores_display} → Overall: {last_eval['overall']:.0%}")
            if last_eval.get("gaps"):
                await _emit_log(f"   Gaps: {', '.join(last_eval['gaps'][:3])}")

            iter_data["completed_at"] = datetime.now(timezone.utc).isoformat()
            proj["iterations"].append(iter_data)
            _save(proj)
            _update_pm_task(2, "In Progress", int(iter_num / proj["max_iterations"] * 100))
            await _emit(pid, "iteration_end", {
                "iteration": iter_num, "score": proj["current_score"],
                "evaluation": iter_data.get("evaluation", ""),
                "scores_detail": iter_data.get("scores_detail", {}),
            })

            # ── 4. Check if done ──
            if proj["current_score"] >= proj["target_score"]:
                await _emit_log(
                    f"✅ Target score reached ({proj['current_score']:.0%}). "
                    "Generating report..."
                )
                _update_pm_task(1, "Done", 100)
                _update_pm_task(2, "Done", 100)
                break

            await asyncio.sleep(1)

        # ── Generate final report with citations ──
        _update_pm_task(1, "Done", 100)
        _update_pm_task(2, "Done", 100)
        _update_pm_task(3, "In Progress", 10)
        await _generate_report(pid, provider, model, perspectives, branch_summaries)
        _update_pm_task(3, "Done", 100)
        proj = _load(pid)
        proj["status"] = "completed"
        _save(proj)
        await _emit(pid, "status", {"status": "completed"})
        await _emit_log("🎉 Research completed!")
        unregister_task(pid)

    except asyncio.CancelledError:
        proj = _load(pid) or proj
        proj["status"] = "paused"
        _save(proj)
        await _emit(pid, "status", {"status": "paused"})
        unregister_task(pid)
    except Exception as e:
        logger.error("Research loop error for %s: %s", pid, e, exc_info=True)
        proj = _load(pid) or proj
        proj["status"] = "error"
        proj["error_msg"] = str(e)
        _save(proj)
        await _emit(pid, "status", {"status": "error"})
        await _emit(pid, "log", {"msg": f"❌ Error: {e}"})
        unregister_task(pid)
    finally:
        _running.pop(pid, None)


async def _generate_report(
    pid: str, provider: str = "", model: str = "",
    perspectives: list[dict] | None = None,
    branch_summaries: str = "",
):
    proj = _load(pid)
    if not proj:
        return
    await _emit(pid, "log", {"msg": "📝 Generating report with citations..."})

    # Project-bound LLM call for token tracking
    async def _report_llm_call(messages, prov="", mdl=""):
        return await _llm_call(messages, prov, mdl, pid=pid)

    report = await generate_report_with_citations(
        query=proj["query"],
        results=proj["search_results"],
        assets=proj.get("assets", []),
        perspectives=perspectives or proj.get("perspectives", []),
        branch_summaries=branch_summaries,
        score=proj.get("current_score", 0),
        num_iterations=len(proj.get("iterations", [])),
        llm_call=_report_llm_call,
        provider=provider,
        model=model,
    )
    proj["report_md"] = report
    report_path = os.path.join(_proj_dir(pid), "report.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    _save(proj)
    await _emit(pid, "report_ready", {"length": len(report)})


# ── API Endpoints ──

@router.get("/profiles")
async def api_list_profiles():
    return {"profiles": list_profiles()}

@router.post("/profiles")
async def api_create_profile(request: Request):
    data = await request.json()
    prof = create_profile(data)
    return {"status": "created", "profile": prof}

@router.delete("/profiles/{pid}")
async def api_delete_profile(pid: str):
    if delete_profile(pid):
        return {"status": "deleted"}
    raise HTTPException(400, "Cannot delete profile")

@router.get("/projects/{pid}/process")
async def api_get_process(pid: str):
    if not _load(pid):
        raise HTTPException(404, "Project not found")
    return {"process_md": _read_process(pid)}

@router.put("/projects/{pid}/process")
async def api_update_process(pid: str, request: Request):
    if not _load(pid):
        raise HTTPException(404, "Project not found")
    data = await request.json()
    _write_process(pid, data.get("process_md", ""))
    return {"status": "updated"}

@router.post("/projects/{pid}/sandbox")
async def api_sandbox_execute(pid: str, request: Request):
    if not _load(pid):
        raise HTTPException(404, "Project not found")
    data = await request.json()
    code = data.get("code", "")
    if not code:
        raise HTTPException(400, "Code is required")
    
    script_path = os.path.join(_proj_dir(pid), "sandbox_script.py")
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(code)
    
    python_exe = _venv_python(pid)
    try:
        proc = await asyncio.create_subprocess_exec(
            python_exe, script_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=_proj_dir(pid)
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60.0)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return {"status": "error", "stderr": "Execution timed out after 60 seconds", "stdout": "", "exit_code": 124}
            
        return {
            "status": "success" if proc.returncode == 0 else "error",
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
            "exit_code": proc.returncode
        }
    except Exception as e:
        return {"status": "error", "stderr": str(e), "stdout": "", "exit_code": -1}

@router.post("/projects/{pid}/install-deps")
async def api_sandbox_install(pid: str, request: Request):
    if not _load(pid):
        raise HTTPException(404, "Project not found")
    data = await request.json()
    packages = data.get("packages", [])
    if not packages:
        raise HTTPException(400, "Packages list is required")
    
    python_exe = _venv_python(pid)
    try:
        proc = await asyncio.create_subprocess_exec(
            python_exe, "-m", "pip", "install", *packages,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120.0)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return {"status": "error", "stderr": "Installation timed out after 120 seconds", "stdout": ""}
            
        return {
            "status": "success" if proc.returncode == 0 else "error",
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace")
        }
    except Exception as e:
        return {"status": "error", "stderr": str(e), "stdout": ""}

@router.get("/projects")
async def list_projects():
    return {"projects": _list_projects()}

@router.post("/projects")
async def create_project(request: Request):
    data = await request.json()
    query = data.get("query", "").strip()
    if not query:
        raise HTTPException(400, "Research query is required")
    proj = _new_project(query, data.get("provider",""), data.get("model",""))
    proj["target_score"] = float(data.get("target_score", 0.7))
    proj["max_iterations"] = int(data.get("max_iterations", 10))
    _save(proj)
    return {"status": "created", "project": proj}

@router.get("/projects/{pid}")
async def get_project(pid: str):
    proj = _load(pid)
    if not proj:
        raise HTTPException(404, "Project not found")
    return {"project": proj}

@router.delete("/projects/{pid}")
async def delete_project(pid: str):
    if pid in _running:
        _running[pid].cancel()
        _running.pop(pid, None)
    d = os.path.join(RESEARCH_DIR, pid)
    if os.path.isdir(d):
        shutil.rmtree(d)
    return {"status": "deleted"}

@router.post("/projects/{pid}/start")
async def start_research(pid: str):
    proj = _load(pid)
    if not proj:
        raise HTTPException(404, "Project not found")
    if pid in _running:
        return {"status": "already_running"}
    _sse_queues[pid] = asyncio.Queue()
    task = asyncio.create_task(_research_loop(pid))
    _running[pid] = task
    return {"status": "started"}

@router.post("/projects/{pid}/stop")
async def stop_research(pid: str):
    from app.tools.task_manager import unregister_task
    if pid in _running:
        _running[pid].cancel()
        _running.pop(pid, None)
    proj = _load(pid)
    if proj:
        proj["status"] = "paused"
        _save(proj)
    unregister_task(pid)
    return {"status": "stopped"}

@router.get("/projects/{pid}/status")
async def research_status_sse(pid: str):
    if pid not in _sse_queues:
        _sse_queues[pid] = asyncio.Queue()
    async def gen():
        q = _sse_queues[pid]
        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=30)
                yield {"data": msg}
            except asyncio.TimeoutError:
                yield {"data": json.dumps({"type": "ping"})}
            except Exception:
                break
    return EventSourceResponse(gen())

@router.post("/projects/{pid}/evaluate")
async def force_evaluate(pid: str):
    proj = _load(pid)
    if not proj:
        raise HTTPException(404, "Project not found")
    # Quick re-evaluation
    results_summary = "\n".join(
        f"- {r.get('title','')}: {r.get('snippet','')[:80]}"
        for r in proj["search_results"][-20:]
    )[:3000]
    eval_prompt = [
        {"role": "system", "content": "Evaluate research quality. Return JSON: {\"score\": 0.0-1.0, \"evaluation\": \"...\"} ONLY."},
        {"role": "user", "content": f"Topic: {proj['query']}\nResults:\n{results_summary}"}
    ]
    text = await _llm_call(eval_prompt, proj.get("provider",""), proj.get("model",""), pid=pid)
    try:
        s = text.find("{"); e = text.rfind("}")
        if s != -1 and e != -1:
            d = json.loads(text[s:e+1])
            proj["current_score"] = float(d.get("score", proj["current_score"]))
    except Exception:
        pass
    _save(proj)
    return {"score": proj["current_score"]}

@router.get("/projects/{pid}/report")
async def get_report(pid: str):
    proj = _load(pid)
    if not proj:
        raise HTTPException(404, "Project not found")
    return {"report": proj.get("report_md", ""), "title": proj.get("title", "")}

@router.post("/projects/{pid}/export")
async def export_report(pid: str, request: Request):
    proj = _load(pid)
    if not proj:
        raise HTTPException(404, "Project not found")
    data = await request.json()
    fmt = data.get("format", "md")
    report = proj.get("report_md", "")
    if not report:
        raise HTTPException(400, "No report generated yet")

    pdir = _proj_dir(pid)
    if fmt == "md":
        path = os.path.join(pdir, "report.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(report)
        return FileResponse(path, filename=f"research_{proj['title'][:30]}.md")
    elif fmt == "docx":
        try:
            from docx import Document
            path = os.path.join(pdir, "report.docx")
            def _gen_docx():
                doc = Document()
                doc.add_heading(proj.get("title", "Research Report"), 0)
                for line in report.split("\n"):
                    if line.startswith("# "):
                        doc.add_heading(line[2:], level=1)
                    elif line.startswith("## "):
                        doc.add_heading(line[3:], level=2)
                    elif line.startswith("### "):
                        doc.add_heading(line[4:], level=3)
                    elif line.strip():
                        doc.add_paragraph(line)
                doc.save(path)
            await asyncio.to_thread(_gen_docx)
            return FileResponse(path, filename=f"research_{proj['title'][:30]}.docx")
        except ImportError:
            raise HTTPException(500, "python-docx not installed")
    elif fmt == "pdf":
        try:
            from fpdf import FPDF
            path = os.path.join(pdir, "report.pdf")
            def _gen_pdf():
                pdf = FPDF()
                pdf.add_page()
                pdf.set_font("Arial", "B", 16)
                pdf.cell(0, 10, proj.get("title", "Research")[:80].encode("latin-1","replace").decode("latin-1"), ln=1)
                pdf.set_font("Arial", size=10)
                for line in report.split("\n"):
                    safe = line.encode("latin-1","replace").decode("latin-1")
                    pdf.multi_cell(0, 5, safe)
                pdf.output(path)
            await asyncio.to_thread(_gen_pdf)
            return FileResponse(path, filename=f"research_{proj['title'][:30]}.pdf")
        except ImportError:
            raise HTTPException(500, "fpdf2 not installed")
    elif fmt == "pptx":
        return await _export_research_pptx(proj, pdir)
    raise HTTPException(400, f"Unsupported format: {fmt}")


async def _export_research_pptx(proj: dict, pdir: str) -> FileResponse:
    """Export research report as a professional PPTX presentation.

    Parses the markdown report into structured slides:
    - Title slide with research query and metadata
    - One slide per H2 section
    - Bullet points for content
    """
    try:
        from pptx import Presentation
        from pptx.util import Inches, Pt
        from pptx.enum.text import PP_ALIGN
        from pptx.dml.color import RGBColor
    except ImportError:
        raise HTTPException(500, "python-pptx not installed")

    report = proj.get("report_md", "")
    title = proj.get("title", "Research Report")

    prs = Presentation()
    prs.slide_width = Inches(13.33)
    prs.slide_height = Inches(7.5)

    # --- Title Slide ---
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    txBox = slide.shapes.add_textbox(Inches(1), Inches(2), Inches(11), Inches(2))
    tf = txBox.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = title
    p.font.size = Pt(36)
    p.font.bold = True
    p.font.color.rgb = RGBColor(30, 30, 30)
    p.alignment = PP_ALIGN.CENTER
    # Subtitle
    p2 = tf.add_paragraph()
    score = proj.get("current_score", 0)
    iters = len(proj.get("iterations", []))
    p2.text = f"Score: {score:.0%} | {iters} iterations | Clawzd Research Studio"
    p2.font.size = Pt(18)
    p2.font.color.rgb = RGBColor(100, 100, 100)
    p2.alignment = PP_ALIGN.CENTER

    # --- Content Slides (one per H2 section) ---
    sections = _split_report_sections(report)
    for section_title, section_body in sections:
        slide = prs.slides.add_slide(prs.slide_layouts[6])

        # Section title
        txTitle = slide.shapes.add_textbox(
            Inches(0.5), Inches(0.3), Inches(12), Inches(1),
        )
        tf_title = txTitle.text_frame
        tf_title.word_wrap = True
        p_title = tf_title.paragraphs[0]
        p_title.text = section_title
        p_title.font.size = Pt(28)
        p_title.font.bold = True
        p_title.font.color.rgb = RGBColor(30, 30, 30)

        # Section content (bullet points)
        txBody = slide.shapes.add_textbox(
            Inches(0.5), Inches(1.5), Inches(12), Inches(5.5),
        )
        tf_body = txBody.text_frame
        tf_body.word_wrap = True

        lines = section_body.strip().split("\n")
        first_line = True
        for line in lines:
            # Skip marker lines (__CHART__, __TABLE__, etc.)
            if line.strip().startswith("__") and line.strip().endswith("__"):
                continue
            if not line.strip():
                continue

            if first_line:
                p = tf_body.paragraphs[0]
                first_line = False
            else:
                p = tf_body.add_paragraph()

            # Handle bullet points
            if line.strip().startswith("- "):
                p.text = "• " + line.strip()[2:]
                p.level = 1
            elif line.strip().startswith("### "):
                p.text = line.strip()[4:]
                p.font.bold = True
                p.font.size = Pt(18)
                continue
            else:
                p.text = line.strip()

            p.font.size = Pt(14)
            p.font.color.rgb = RGBColor(50, 50, 50)
            p.space_after = Pt(6)

    path = os.path.join(pdir, "report.pptx")
    def _save_pptx():
        prs.save(path)
    await asyncio.to_thread(_save_pptx)
    return FileResponse(
        path,
        filename=f"research_{proj['title'][:30]}.pptx",
    )


def _split_report_sections(report_md: str) -> list[tuple[str, str]]:
    """Split a markdown report into (title, body) sections at H2 boundaries."""
    sections = []
    current_title = ""
    current_body = []

    for line in report_md.split("\n"):
        if line.startswith("## "):
            if current_title or current_body:
                sections.append((current_title, "\n".join(current_body)))
            current_title = line[3:].strip()
            current_body = []
        elif line.startswith("# "):
            # H1 is the report title, skip it for slides
            continue
        else:
            current_body.append(line)

    if current_title or current_body:
        sections.append((current_title, "\n".join(current_body)))

    return sections


@router.post("/projects/{pid}/to-presentation")
async def research_to_presentation(pid: str, request: Request):
    """Convert research report directly to a professional presentation.

    Bridge between Research Studio and Presentation Studio.
    Takes the research report markdown and generates a PPTX file
    with structured slides, one per section.
    """
    proj = _load(pid)
    if not proj:
        raise HTTPException(404, "Project not found")
    report = proj.get("report_md", "")
    if not report:
        raise HTTPException(400, "No report available — run research first")

    pdir = _proj_dir(pid)
    return await _export_research_pptx(proj, pdir)

@router.get("/projects/{pid}/export-zip")
async def export_zip(pid: str):
    proj = _load(pid)
    if not proj:
        raise HTTPException(404, "Project not found")
    import zipfile, io
    pdir = _proj_dir(pid)
    # Ensure report.md exists
    report_path = os.path.join(pdir, "report.md")
    if proj.get("report_md") and not os.path.exists(report_path):
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(proj["report_md"])
    buf = io.BytesIO()
    def _make_zip():
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(pdir):
                for fname in files:
                    fpath = os.path.join(root, fname)
                    arcname = os.path.relpath(fpath, pdir)
                    zf.write(fpath, arcname)
    await asyncio.to_thread(_make_zip)
    buf.seek(0)
    safe_title = proj.get("title", "research")[:30].replace(" ", "_")
    return StreamingResponse(buf, media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="research_{safe_title}.zip"'})

@router.get("/projects/{pid}/assets")
async def list_assets(pid: str):
    proj = _load(pid)
    if not proj:
        raise HTTPException(404, "Project not found")
    return {"assets": proj.get("assets", [])}

@router.get("/projects/{pid}/iterations")
async def list_iterations(pid: str):
    proj = _load(pid)
    if not proj:
        raise HTTPException(404, "Project not found")
    return {"iterations": proj.get("iterations", [])}
