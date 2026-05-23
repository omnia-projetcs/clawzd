"""
Clawzd — My Clone engine.

AI agent that mimics the user's communication style using a personal
knowledge base. Manages profile, knowledge files, connectors, auto-reply
settings, interaction logs, and a test sandbox.

Knowledge files: profiles/clone/  (markdown profile & knowledge base)
Runtime data:    data/clone/      (logs, settings, connectors)
"""
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, UploadFile, File

from config import DATA_DIR, PROFILES_DIR

router = APIRouter()
logger = logging.getLogger("clawzd.clone")

CLONE_DIR = os.path.join(DATA_DIR, "clone")
KNOWLEDGE_DIR = os.path.join(PROFILES_DIR, "clone")
LOGS_DIR = os.path.join(CLONE_DIR, "logs")
CONNECTORS_FILE = os.path.join(CLONE_DIR, "connectors.json")
SETTINGS_FILE = os.path.join(CLONE_DIR, "settings.json")
ONBOARDING_FILE = os.path.join(CLONE_DIR, "onboarding.json")

for d in [CLONE_DIR, KNOWLEDGE_DIR, LOGS_DIR,
          os.path.join(KNOWLEDGE_DIR, "expertise"),
          os.path.join(KNOWLEDGE_DIR, "projects")]:
    os.makedirs(d, exist_ok=True)

DEFAULT_SETTINGS = {
    "auto_mode": False,
    "confidence_threshold": 0.85,
    "review_mode": "human-in-loop",
    "daily_limit": 50,
    "working_hours": {"timezone": "Europe/Paris", "from": "09:00", "to": "18:00"},
    "replies_today": 0,
    "last_reset": None,
}

INTENT_LABELS = ["question", "request", "feedback", "spam", "urgent", "unknown"]
SAFETY_KEYWORDS = re.compile(
    r"(urgent|payment|wire transfer|bank account|ssn|password|credit card"
    r"|medical advice|legal advice|financial advice)",
    re.IGNORECASE,
)


# ── Helpers ──

def _read_file(path: str) -> str:
    """Read a text file, return empty string if missing."""
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return ""


def _write_file(path: str, content: str):
    """Write text to file, creating parent dirs."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def _load_json(path: str, default=None):
    """Load JSON file or return default."""
    if os.path.isfile(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return default if default is not None else {}


def _save_json(path: str, data):
    """Save data as JSON."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _list_knowledge_tree(base: str, prefix: str = "") -> list:
    """Recursively list .md files in knowledge directory."""
    items = []
    try:
        for entry in sorted(os.listdir(base)):
            full = os.path.join(base, entry)
            rel = os.path.join(prefix, entry) if prefix else entry
            if os.path.isdir(full):
                children = _list_knowledge_tree(full, rel)
                items.append({"name": entry, "path": rel, "type": "dir",
                              "children": children})
            elif entry.endswith(".md"):
                size = os.path.getsize(full)
                items.append({"name": entry, "path": rel, "type": "file",
                              "size": size})
    except Exception as e:
        logger.error("Knowledge tree error: %s", e)
    return items


def _load_all_knowledge() -> str:
    """Load and concatenate all .md files for context injection."""
    parts = []
    
    # Include global user profile and memory
    user_dir = os.path.join(PROFILES_DIR, "user")
    for global_file in ["USER.md", "MEMORY.md"]:
        path = os.path.join(user_dir, global_file)
        if os.path.isfile(path):
            content = _read_file(path)
            if content.strip():
                parts.append(f"--- user/{global_file} ---\n{content}")

    for root, _dirs, files in os.walk(KNOWLEDGE_DIR):
        for fname in sorted(files):
            if fname.endswith(".md"):
                rel = os.path.relpath(os.path.join(root, fname), KNOWLEDGE_DIR)
                content = _read_file(os.path.join(root, fname))
                if content.strip():
                    parts.append(f"--- clone/{rel} ---\n{content}")
    return "\n\n".join(parts)


def _get_settings() -> dict:
    """Load clone settings with defaults."""
    settings = dict(DEFAULT_SETTINGS)
    saved = _load_json(SETTINGS_FILE, {})
    settings.update(saved)
    # Reset daily counter if date changed
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if settings.get("last_reset") != today:
        settings["replies_today"] = 0
        settings["last_reset"] = today
        _save_json(SETTINGS_FILE, settings)
    return settings


def _log_interaction(entry: dict):
    """Append an interaction to today's log file."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    log_file = os.path.join(LOGS_DIR, f"{today}.json")
    logs = _load_json(log_file, [])
    if not isinstance(logs, list):
        logs = []
    entry["timestamp"] = datetime.now(timezone.utc).isoformat()
    logs.append(entry)
    _save_json(log_file, logs)


# ── Profile & Knowledge CRUD ──

@router.get("/profile")
async def get_profile():
    """Return all profile files."""
    return {
        "profile": _read_file(os.path.join(KNOWLEDGE_DIR, "profile.md")),
        "style": _read_file(os.path.join(KNOWLEDGE_DIR, "communication_style.md")),
        "rules": _read_file(os.path.join(KNOWLEDGE_DIR, "rules.md")),
        "faq": _read_file(os.path.join(KNOWLEDGE_DIR, "faq.md")),
    }


@router.post("/profile")
async def save_profile(request: Request):
    """Save profile files (partial update)."""
    data = await request.json()
    mapping = {
        "profile": "profile.md",
        "style": "communication_style.md",
        "rules": "rules.md",
        "faq": "faq.md",
    }
    for key, fname in mapping.items():
        if key in data:
            _write_file(os.path.join(KNOWLEDGE_DIR, fname), data[key])
    return {"status": "saved"}


@router.get("/knowledge")
async def list_knowledge():
    """List knowledge file tree."""
    return {"tree": _list_knowledge_tree(KNOWLEDGE_DIR)}


@router.get("/knowledge/{path:path}")
async def get_knowledge_file(path: str):
    """Read a specific knowledge file."""
    full = os.path.join(KNOWLEDGE_DIR, path)
    if not os.path.isfile(full) or not full.startswith(KNOWLEDGE_DIR):
        raise HTTPException(404, "File not found")
    return {"path": path, "content": _read_file(full)}


@router.put("/knowledge/{path:path}")
async def put_knowledge_file(path: str, request: Request):
    """Create or update a knowledge file."""
    data = await request.json()
    content = data.get("content", "")
    full = os.path.join(KNOWLEDGE_DIR, path)
    if not full.startswith(KNOWLEDGE_DIR):
        raise HTTPException(400, "Invalid path")
    _write_file(full, content)
    return {"status": "saved", "path": path}


@router.delete("/knowledge/{path:path}")
async def delete_knowledge_file(path: str):
    """Delete a knowledge file."""
    full = os.path.join(KNOWLEDGE_DIR, path)
    if not full.startswith(KNOWLEDGE_DIR) or not os.path.isfile(full):
        raise HTTPException(404, "File not found")
    # Protect core files from deletion
    protected = {"profile.md", "communication_style.md", "rules.md", "faq.md"}
    if path in protected:
        raise HTTPException(400, "Cannot delete core profile files")
    if os.path.isdir(full):
        import shutil
        shutil.rmtree(full)
    else:
        os.remove(full)
    return {"status": "deleted", "path": path}


# ── Connectors ──

# Communication/publish node types exposed to the Clone Studio
_CLONE_CONNECTOR_CATEGORIES = {"communication", "publish"}


def _get_automation_connectors() -> list:
    """Return connectors from Automation NODE_TYPES (communication + publish)."""
    try:
        from app.tools_automation import NODE_TYPES
        result = []
        for key, defn in NODE_TYPES.items():
            if defn.get("category") in _CLONE_CONNECTOR_CATEGORIES:
                result.append({
                    "key": key,
                    "label": defn.get("label", key),
                    "icon": defn.get("icon", "link"),
                    "color": defn.get("color", "#6b7280"),
                    "category": defn.get("category", "communication"),
                    "params": defn.get("params", []),
                })
        return result
    except Exception as e:
        logger.error("Failed to load automation connectors: %s", e)
        return []


@router.get("/available-connectors")
async def get_available_connectors():
    """Return all connectors available from the Automation engine."""
    return {"connectors": _get_automation_connectors()}


@router.get("/connectors")
async def get_connectors():
    """Return connector configurations merged with automation-discovered defaults."""
    # Build default structure from automation NODE_TYPES
    default: dict = {}
    for conn in _get_automation_connectors():
        key = conn["key"]
        default[key] = {
            "enabled": False,
            "params": {},          # user-configured param values
            "auto_reply": False,
            "allowed_senders": [],
            "last_activity": None,
        }
    # Fallback in case automation import fails
    if not default:
        for key in ("email_send", "whatsapp_send", "signal_send", "telegram_send"):
            default[key] = {"enabled": False, "params": {}, "auto_reply": False,
                            "allowed_senders": [], "last_activity": None}
    saved = _load_json(CONNECTORS_FILE, {})
    for ch in default:
        if ch in saved:
            default[ch].update(saved[ch])
    return {"connectors": default}


@router.post("/connectors")
async def save_connectors(request: Request):
    """Save connector configurations."""
    data = await request.json()
    connectors = data.get("connectors", {})
    _save_json(CONNECTORS_FILE, connectors)
    return {"status": "saved"}


@router.post("/connectors/{connector_key}/test")
async def test_connector(connector_key: str, request: Request):
    """Test a connector by sending a test message through the Automation engine."""
    data = await request.json()
    params = data.get("params", {})
    message = data.get("message", "🤖 Clone connector test message")

    # Load saved params and merge with provided ones
    saved = _load_json(CONNECTORS_FILE, {})
    saved_params = saved.get(connector_key, {}).get("params", {})
    merged_params = {**saved_params, **params}

    # Inject message into the right param key for each connector type
    msg_key_map = {
        "email_send": ("body", "subject"),
        "discord_send": ("message", None),
        "signal_send": ("message", None),
        "telegram_send": ("message", None),
        "whatsapp_send": ("message", None),
        "medium_publish": ("content", "title"),
        "twitter_publish": ("text", None),
        "linkedin_publish": ("text", None),
        "export_email": ("body", "subject"),
    }
    if connector_key in msg_key_map:
        body_key, title_key = msg_key_map[connector_key]
        if body_key and body_key not in merged_params:
            merged_params[body_key] = message
        if title_key and title_key not in merged_params:
            merged_params[title_key] = "Clone Test"

    try:
        from app.tools_automation import _exec_node
        node = {"id": "clone_test", "type": connector_key, "params": merged_params}
        result = await _exec_node(node, {}, {}, testing_mode=False)
        return {"status": "sent", "result": result}
    except Exception as e:
        logger.error("Connector test failed for %s: %s", connector_key, e)
        return {"status": "error", "error": str(e)}


# ── Settings ──

@router.get("/settings")
async def get_settings():
    """Return auto-mode settings."""
    return {"settings": _get_settings()}


@router.post("/settings")
async def save_settings(request: Request):
    """Save auto-mode settings."""
    data = await request.json()
    settings = _get_settings()
    for k in ("auto_mode", "confidence_threshold", "review_mode",
              "daily_limit", "working_hours"):
        if k in data:
            settings[k] = data[k]
    _save_json(SETTINGS_FILE, settings)
    return {"status": "saved", "settings": settings}


# ── Logs ──

@router.delete("/logs")
async def clear_logs():
    """Clear all interaction logs."""
    try:
        files = os.listdir(LOGS_DIR)
        for fname in files:
            if fname.endswith(".json"):
                os.remove(os.path.join(LOGS_DIR, fname))
        return {"status": "cleared"}
    except Exception as e:
        logger.error("Failed to clear logs: %s", e)
        raise HTTPException(500, "Failed to clear logs")


@router.get("/logs")
async def get_logs(limit: int = 50):
    """Return recent interactions across all days."""
    all_logs = []
    try:
        files = sorted(os.listdir(LOGS_DIR), reverse=True)
        for fname in files:
            if not fname.endswith(".json"):
                continue
            entries = _load_json(os.path.join(LOGS_DIR, fname), [])
            if isinstance(entries, list):
                all_logs.extend(entries)
            if len(all_logs) >= limit:
                break
    except Exception:
        pass
    all_logs.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return {"logs": all_logs[:limit]}


@router.get("/stats")
async def get_stats():
    """Dashboard statistics."""
    settings = _get_settings()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today_logs = _load_json(os.path.join(LOGS_DIR, f"{today}.json"), [])
    if not isinstance(today_logs, list):
        today_logs = []
    confidences = [e.get("confidence", 0) for e in today_logs if "confidence" in e]
    return {
        "replies_today": settings.get("replies_today", 0),
        "daily_limit": settings.get("daily_limit", 50),
        "interactions_today": len(today_logs),
        "avg_confidence": round(sum(confidences) / len(confidences), 2) if confidences else 0,
        "auto_mode": settings.get("auto_mode", False),
    }


# ── Clone AI Engine ──

@router.post("/test")
async def test_clone_reply(request: Request):
    """Test sandbox: generate a clone reply for a sample message."""
    data = await request.json()
    message = data.get("message", "")
    channel = data.get("channel", "test")
    if not message.strip():
        raise HTTPException(400, "Message is required")

    knowledge = _load_all_knowledge()
    result = await _generate_reply(message, channel, knowledge)

    _log_interaction({
        "channel": channel, "direction": "test",
        "message": message, "reply": result["reply"],
        "intent": result["intent"], "confidence": result["confidence"],
        "flagged": result.get("flagged", False),
    })
    return result


async def _generate_reply(message: str, channel: str, knowledge: str) -> dict:
    """Core clone reply generation pipeline."""
    from app.llm_provider import get_llm_provider
    provider = get_llm_provider()

    # Step 1 — Classify intent
    intent = await _classify_intent(message, provider)

    # Step 2 — Check safety
    flagged = bool(SAFETY_KEYWORDS.search(message))

    # Step 2.5 — Search Knowledge Vault for relevant context
    vault_ctx = _search_clone_vault(message, k=3)
    if vault_ctx:
        knowledge += f"\n\n=== VAULT CONTEXT (vectorized documents) ===\n{vault_ctx}\n=== END VAULT ===\n"

    # Step 3 — Generate reply
    system = (
        "You are the exact person described in the profile below. You are NOT an AI assistant or language model. "
        "You must reply EXACTLY as this person, matching their tone, vocabulary, "
        "formality, and style precisely. Never break character. Never mention you are an AI or an intelligence artificielle.\n\n"
        f"=== KNOWLEDGE BASE ===\n{knowledge[:8000]}\n"
        "=== END KNOWLEDGE BASE ===\n\n"
        "Rules:\n"
        "- Reply naturally as this person would.\n"
        "- If you don't have relevant knowledge, say so honestly, but do so in character.\n"
        "- Never invent facts.\n"
        "- Keep the reply concise unless the profile says otherwise.\n"
        f"- The message arrived via: {channel}\n"
        f"- Detected intent: {intent}\n"
    )

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": message},
    ]

    reply = ""
    async for tok in provider.chat_stream(messages):
        reply += tok

    # Clean LLM artifacts
    reply = re.sub(r"<think>.*?</think>", "", reply, flags=re.DOTALL).strip()

    # Step 4 — Confidence scoring (simple heuristic)
    confidence = _compute_confidence(reply, knowledge, message)

    return {
        "reply": reply,
        "intent": intent,
        "confidence": round(confidence, 2),
        "channel": channel,
        "flagged": flagged,
        "auto_sendable": confidence >= _get_settings().get(
            "confidence_threshold", 0.85) and not flagged,
    }


async def _classify_intent(message: str, provider) -> str:
    """Classify message intent using LLM."""
    prompt = (
        f"Classify this message into ONE of: {', '.join(INTENT_LABELS)}.\n"
        f"Message: {message}\n"
        "Reply with ONLY the label, nothing else."
    )
    result = ""
    async for tok in provider.chat_stream([{"role": "user", "content": prompt}]):
        result += tok
    result = result.strip().lower()
    for label in INTENT_LABELS:
        if label in result:
            return label
    return "unknown"


def _compute_confidence(reply: str, knowledge: str, message: str) -> float:
    """Heuristic confidence score for the generated reply."""
    score = 0.5
    # Boost if knowledge base has content
    if len(knowledge) > 200:
        score += 0.15
    # Boost if reply is reasonably sized
    if 20 < len(reply) < 2000:
        score += 0.1
    # Boost if message words appear in knowledge
    words = set(message.lower().split())
    kb_lower = knowledge.lower()
    matches = sum(1 for w in words if len(w) > 3 and w in kb_lower)
    if matches > 2:
        score += 0.15
    # Penalize very short replies
    if len(reply) < 10:
        score -= 0.2
    # Penalize "I don't know" type replies
    if any(p in reply.lower() for p in ["i don't know", "je ne sais pas",
                                         "no relevant", "pas d'information"]):
        score -= 0.25
    return max(0.0, min(1.0, score))


# ── Knowledge Vault (RAG vectorized store — shared with global RAG) ──

def _get_vault():
    """Return the global RAG collection & encoder.

    The vault shares the same ``knowledge_base`` ChromaDB collection used
    by the global RAG system so documents are available everywhere.
    """
    from app.ai_models.rag import _get_rag
    return _get_rag()  # returns (collection, encoder)


def _search_clone_vault(query: str, k: int = 3, threshold: float = 0.4) -> Optional[str]:
    """Search the clone vault for relevant context. Returns formatted text or None."""
    try:
        vault_col, encoder = _get_vault()
        if vault_col.count() == 0:
            return None
        query_emb = encoder.encode(query).tolist()
        results = vault_col.query(
            query_embeddings=[query_emb], n_results=k,
            include=["documents", "metadatas", "distances"],
        )
        docs = results.get("documents", [[]])[0]
        distances = results.get("distances", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        if not docs:
            return None
        parts = []
        for doc, dist, meta in zip(docs, distances, metadatas):
            if dist < threshold:
                src = (meta or {}).get("source", "?")
                parts.append(f"[{src}] {doc}")
        return "\n\n---\n\n".join(parts) if parts else None
    except Exception as e:
        logger.debug("Clone vault search skipped: %s", e)
        return None


@router.post("/vault/upload")
async def vault_upload(files: list[UploadFile] = File(...)):
    """Upload files to the Clone Knowledge Vault and index them."""
    from app.ai_models.rag import _extract_text, _chunk_text, _get_file_type
    vault_col, encoder = _get_vault()
    results = []
    for file in files:
        try:
            content = await file.read()
            fname = file.filename or "unknown"
            text = _extract_text(content, fname)
            chunks = _chunk_text(text)
            if not chunks:
                results.append({"status": "empty", "filename": fname, "chunks": 0})
                continue
            file_type = _get_file_type(fname)
            for idx, chunk in enumerate(chunks):
                emb = encoder.encode(chunk).tolist()
                doc_id = f"vault_{fname}_{idx}"
                vault_col.upsert(
                    documents=[chunk], embeddings=[emb], ids=[doc_id],
                    metadatas=[{
                        "source": fname, "chunk_index": idx,
                        "file_type": file_type,
                        "indexed_at": datetime.now(timezone.utc).isoformat(),
                    }],
                )
            results.append({"status": "indexed", "filename": fname,
                            "chunks": len(chunks), "file_type": file_type})
            logger.info("Vault: indexed %s (%d chunks)", fname, len(chunks))
        except Exception as e:
            results.append({"status": "error", "filename": file.filename, "error": str(e)})
    return {"results": results, "total": len(results),
            "indexed": sum(1 for r in results if r.get("status") == "indexed")}


@router.get("/vault/sources")
async def vault_sources():
    """List all indexed sources with chunk counts."""
    vault_col, _ = _get_vault()
    all_data = vault_col.get(include=["metadatas"])
    sources: dict[str, dict] = {}
    for m in (all_data.get("metadatas") or []):
        src = (m or {}).get("source", "unknown")
        if src not in sources:
            sources[src] = {
                "name": src, "chunks": 0,
                "file_type": (m or {}).get("file_type", "unknown"),
                "indexed_at": (m or {}).get("indexed_at", ""),
            }
        sources[src]["chunks"] += 1
    return {"sources": sorted(sources.values(), key=lambda x: x["name"])}


@router.delete("/vault/source/{source_name:path}")
async def vault_delete_source(source_name: str):
    """Delete all chunks for a specific source."""
    vault_col, _ = _get_vault()
    all_data = vault_col.get(include=["metadatas"])
    ids_to_delete = [
        doc_id for doc_id, meta
        in zip(all_data.get("ids", []), all_data.get("metadatas", []))
        if (meta or {}).get("source") == source_name
    ]
    if not ids_to_delete:
        raise HTTPException(404, f"Source '{source_name}' not found")
    vault_col.delete(ids=ids_to_delete)
    logger.info("Vault: deleted %d chunks from '%s'", len(ids_to_delete), source_name)
    return {"status": "deleted", "source": source_name, "chunks_removed": len(ids_to_delete)}


@router.get("/vault/search")
async def vault_search(query: str, k: int = 5):
    """Semantic search across the clone vault."""
    vault_col, encoder = _get_vault()
    if vault_col.count() == 0:
        return {"documents": [], "metadatas": [], "scores": []}
    emb = encoder.encode(query).tolist()
    results = vault_col.query(
        query_embeddings=[emb], n_results=k,
        include=["documents", "metadatas", "distances"],
    )
    docs = results.get("documents", [[]])[0]
    distances = results.get("distances", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]
    scores = [round((1.0 - d) * 100, 1) for d in distances]
    return {"documents": docs, "metadatas": metadatas, "scores": scores}


@router.get("/vault/stats")
async def vault_stats():
    """Return vault statistics."""
    try:
        vault_col, _ = _get_vault()
        count = vault_col.count()
        all_meta = vault_col.get(include=["metadatas"])
        sources = set()
        for m in (all_meta.get("metadatas") or []):
            sources.add((m or {}).get("source", "unknown"))
        return {"total_chunks": count, "source_count": len(sources)}
    except Exception:
        return {"total_chunks": 0, "source_count": 0}


@router.get("/vault/graph")
async def vault_graph():
    """Return a graph structure for knowledge visualization.

    Nodes = unique sources, Edges = pairs of sources sharing
    semantic similarity above a threshold.
    """
    try:
        vault_col, encoder = _get_vault()
        if vault_col.count() == 0:
            return {"nodes": [], "edges": []}

        all_data = vault_col.get(include=["metadatas", "embeddings"])
        ids = all_data.get("ids", [])
        metadatas = all_data.get("metadatas", [])
        embeddings = all_data.get("embeddings", [])

        # Build per-source average embeddings
        import numpy as np
        source_embs: dict[str, list] = {}
        source_meta: dict[str, dict] = {}
        for doc_id, meta, emb in zip(ids, metadatas, embeddings):
            src = (meta or {}).get("source", "unknown")
            ft = (meta or {}).get("file_type", "")
            if src not in source_embs:
                source_embs[src] = []
                source_meta[src] = {"file_type": ft, "chunks": 0}
            source_embs[src].append(emb)
            source_meta[src]["chunks"] += 1

        # Average embeddings per source
        src_names = list(source_embs.keys())
        avg_embs = []
        for src in src_names:
            avg = np.mean(source_embs[src], axis=0)
            avg_embs.append(avg / (np.linalg.norm(avg) + 1e-10))

        # Build nodes
        type_colors = {
            "PDF": "#ef4444", "Word": "#3b82f6", "Excel": "#10b981",
            "CSV": "#06b6d4", "Markdown": "#8b5cf6", "Text": "#6b7280",
            "PowerPoint": "#f59e0b", "Archive": "#78716c",
        }
        nodes = []
        for i, src in enumerate(src_names):
            ft = source_meta[src]["file_type"]
            color = type_colors.get(ft, "#a855f7")
            if ft.startswith("Code"):
                color = "#22d3ee"
            nodes.append({
                "id": src, "label": src.split("/")[-1] if "/" in src else src,
                "file_type": ft, "chunks": source_meta[src]["chunks"],
                "color": color,
            })

        # Build edges (cosine similarity > threshold, keeping top 3 relations per node to avoid hairballs)
        edges = []
        sim_threshold = 0.60
        
        # Construct relationships for each node
        node_relations = {src: [] for src in src_names}
        for i in range(len(src_names)):
            for j in range(len(src_names)):
                if i == j:
                    continue
                sim = float(np.dot(avg_embs[i], avg_embs[j]))
                if sim > sim_threshold:
                    node_relations[src_names[i]].append((sim, src_names[j]))
        
        # Prune to unique undirected top-3 edges
        seen_edges = set()
        for src, rels in node_relations.items():
            rels.sort(key=lambda x: x[0], reverse=True)
            for sim, target in rels[:3]:
                edge_key = tuple(sorted([src, target]))
                if edge_key not in seen_edges:
                    seen_edges.add(edge_key)
                    edges.append({
                        "source": edge_key[0],
                        "target": edge_key[1],
                        "weight": round(sim, 3),
                    })

        return {"nodes": nodes, "edges": edges}
    except Exception as e:
        logger.error("Vault graph error: %s", e)
        return {"nodes": [], "edges": []}


@router.delete("/vault/clear")
async def vault_clear():
    """Clear the entire vault."""
    vault_col, _ = _get_vault()
    all_ids = vault_col.get().get("ids", [])
    if all_ids:
        vault_col.delete(ids=all_ids)
    logger.info("Vault: cleared %d chunks", len(all_ids))
    return {"status": "cleared", "chunks_removed": len(all_ids)}


# ── Onboarding ──

@router.get("/onboarding")
async def get_onboarding():
    """Return onboarding state."""
    default = {"completed": False, "current_step": 1, "steps_done": []}
    saved = _load_json(ONBOARDING_FILE, default)
    
    if not saved.get("completed"):
        profile_path = os.path.join(KNOWLEDGE_DIR, "profile.md")
        has_profile = os.path.exists(profile_path) and os.path.getsize(profile_path) > 10
        connectors = _load_json(CONNECTORS_FILE, {})
        has_connector = any(c.get("enabled") for c in connectors.values())
        if has_profile or has_connector:
            saved["completed"] = True
            _save_json(ONBOARDING_FILE, saved)
            
    return {"onboarding": saved}


@router.post("/onboarding")
async def update_onboarding(request: Request):
    """Update onboarding state."""
    data = await request.json()
    state = _load_json(ONBOARDING_FILE, {"completed": False,
                                          "current_step": 1,
                                          "steps_done": []})
    if "current_step" in data:
        state["current_step"] = data["current_step"]
    if "step_done" in data:
        step = data["step_done"]
        if step not in state["steps_done"]:
            state["steps_done"].append(step)
    if len(state["steps_done"]) >= 5:
        state["completed"] = True
    if "completed" in data:
        state["completed"] = data["completed"]
    _save_json(ONBOARDING_FILE, state)
    return {"onboarding": state}
