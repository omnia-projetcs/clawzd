"""
Clawzd — Continuous improvement: feedback loop and enrichment.
Manages user feedback collection and uses it to improve future responses.
"""
import os
import json
from datetime import datetime, timezone
from fastapi import APIRouter, Request
from config import DATA_DIR

router = APIRouter()

FEEDBACK_FILE = os.path.join(DATA_DIR, "feedback.jsonl")


@router.post("/feedback")
async def add_feedback(request: Request):
    """Record user feedback for a specific response.

    When feedback is negative (rating <= 2) and a correction is provided,
    the correction is automatically indexed into the RAG knowledge base
    to improve future responses (continuous improvement loop).
    """
    data = await request.json()
    entry = {
        "session_id": data.get("session_id", ""),
        "message_index": data.get("message_index", -1),
        "rating": data.get("rating", 0),
        "comment": data.get("comment", ""),
        "correction": data.get("correction", ""),
        "original_query": data.get("original_query", ""),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    os.makedirs(os.path.dirname(FEEDBACK_FILE), exist_ok=True)
    with open(FEEDBACK_FILE, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # --- Continuous improvement: index corrections into RAG ---
    enriched = False
    if entry["rating"] <= 2 and entry["correction"].strip():
        try:
            from app.rag import _get_rag
            collection, encoder = _get_rag()
            correction_text = (
                f"User question: {entry['original_query']}\n\n"
                f"Corrected answer: {entry['correction']}"
            )
            embedding = encoder.encode(correction_text).tolist()
            doc_id = f"feedback_correction_{entry['timestamp']}"
            collection.upsert(
                documents=[correction_text],
                embeddings=[embedding],
                ids=[doc_id],
                metadatas=[{
                    "source": "user_feedback",
                    "session_id": entry["session_id"],
                    "type": "correction",
                }],
            )
            enriched = True
        except Exception:
            pass  # Non-critical — don't fail the feedback recording

    return {"status": "feedback recorded", "enriched_rag": enriched}


@router.get("/feedback/stats")
async def feedback_stats():
    """Return aggregate feedback statistics."""
    if not os.path.exists(FEEDBACK_FILE):
        return {"total": 0, "average_rating": 0, "positive": 0, "negative": 0}

    total = 0
    rating_sum = 0
    positive = 0
    negative = 0
    with open(FEEDBACK_FILE) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                total += 1
                r = entry.get("rating", 0)
                rating_sum += r
                if r >= 4:
                    positive += 1
                elif r <= 2:
                    negative += 1
            except json.JSONDecodeError:
                continue

    return {
        "total": total,
        "average_rating": round(rating_sum / max(total, 1), 2),
        "positive": positive,
        "negative": negative,
    }