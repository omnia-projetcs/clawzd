"""
Clawzd — AI Battle Arena router.
Extracted from the monolithic gateway.py.
Handles multi-model generation, streaming, and automated judging.
"""

import asyncio
import json
import re
import time
import uuid
from typing import Dict

from fastapi import APIRouter, Request, HTTPException
from sse_starlette.sse import EventSourceResponse

from app.core.llm_provider import get_llm_provider
from app.core.metrics import get_metrics
from app.core.tokens import count_tokens, count_message_tokens
from config import LLM_PROVIDER

router = APIRouter(tags=["arena"])

# Per-model timeout for Arena generation (seconds)
_ARENA_MODEL_TIMEOUT = 300  # 5 minutes max per model

# In-memory queues for arena streams (per stream_id)
_arena_queues: Dict[str, asyncio.Queue] = {}


def _sanitize_input(text: str) -> str:
    """Basic sanitization (duplicated from gateway for extraction; consider centralizing)."""
    if not text:
        return ""
    # Strip script tags, control chars, etc.
    text = re.sub(r"<script.*?>.*?</script>", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    return text.strip()


async def _unload_ollama_model(model_name: str):
    """Unload a specific Ollama model to free up VRAM and prevent saturation."""
    from app.core.llm_provider import _resolve_ollama_host, _resolve_ollama_api_key, _resolve_ollama_verify
    import httpx
    if not model_name:
        return
    try:
        ollama_host = _resolve_ollama_host()
        ollama_key = _resolve_ollama_api_key()
        headers = {"Authorization": f"Bearer {ollama_key}"} if ollama_key else {}
        async with httpx.AsyncClient(verify=_resolve_ollama_verify()) as client:
            await client.post(
                f"{ollama_host}/api/generate",
                json={"model": model_name, "keep_alive": 0},
                headers=headers,
                timeout=30.0
            )
            # logger would need import, but for now use print or assume logger
    except Exception:
        pass  # silent in extraction for simplicity; original had logger


@router.post("/arena/send")
async def arena_send(request: Request):
    """Start generation for multiple models in the Arena.

    Ollama/local models are executed **sequentially** in a single coordinator
    task to prevent VRAM saturation on remote servers (DGx10).  Each Ollama
    model is unloaded after completion with a pause to let VRAM flush.

    Cloud providers run in parallel since they don't share GPU resources.
    """
    data = await request.json()
    user_msg = _sanitize_input(data.get("message", "").strip())
    models = data.get("models", [])

    if not user_msg:
        raise HTTPException(400, "Message is required")
    if not models or len(models) > 10:
        raise HTTPException(400, "1 to 10 models required")

    streams = []
    # Separate Ollama models from cloud providers
    ollama_entries: list[dict] = []
    cloud_entries: list[dict] = []

    for m in models:
        provider_key = m.get("provider", "local")
        model_key = m.get("model", "")
        stream_id = str(uuid.uuid4())
        _arena_queues[stream_id] = asyncio.Queue()
        entry = {
            "stream_id": stream_id,
            "provider": provider_key,
            "model": model_key,
        }
        streams.append(entry)
        if provider_key in ("ollama", "local"):
            ollama_entries.append(entry)
        else:
            cloud_entries.append(entry)

    # Shared per-model generation coroutine
    async def _generate_single(s_id: str, p_key: str, m_key: str):
        """Generate tokens for one model and push them into its queue."""
        queue = _arena_queues.get(s_id)
        if queue is None:
            return
        try:
            t0 = time.perf_counter()
            tokens_count = 0

            provider = get_llm_provider(p_key)
            kwargs: dict = {}
            if m_key:
                kwargs["model"] = m_key
            kwargs["max_tokens"] = 8192

            messages = [
                {"role": "system", "content": "You are a helpful and detailed AI assistant. Provide complete and comprehensive answers. Do NOT truncate your response."},
                {"role": "user", "content": user_msg},
            ]

            async for token in provider.chat_stream(messages, **kwargs):
                if any(marker in token for marker in ["<|endoftext|>", "<|im_start|>", "<|im_end|>", "<|eot_id|>", "</s>", "<|end|>"]):
                    for marker in ["<|endoftext|>", "<|im_start|>", "<|im_end|>", "<|eot_id|>", "</s>", "<|end|>"]:
                        token = token.replace(marker, "")
                    if not token:
                        continue
                tokens_count += 1
                await queue.put(token)

            total_time = time.perf_counter() - t0
            tps = tokens_count / total_time if total_time > 0 else 0
            stats_msg = f'\n\n__STATS__{json.dumps({"time": round(total_time, 2), "tokens": tokens_count, "tps": round(tps, 1)})}__STATS__\n\n'
            await queue.put(stats_msg)

            input_tokens = count_tokens(user_msg, model=m_key or "")
            get_metrics().record_llm_call(
                provider=p_key,
                model=m_key or getattr(provider, "default_model", "unknown"),
                input_tokens=input_tokens,
                output_tokens=tokens_count,
                latency_s=total_time,
                session_id="arena",
            )
        except Exception as e:
            await queue.put(f"\n\n❌ **Error**: {e}")
        finally:
            await queue.put(None)

    # Cloud provider tasks — parallel
    for entry in cloud_entries:
        async def _cloud_wrapper(e=entry):
            try:
                await asyncio.wait_for(
                    _generate_single(e["stream_id"], e["provider"], e["model"]),
                    timeout=_ARENA_MODEL_TIMEOUT,
                )
            except asyncio.TimeoutError:
                q = _arena_queues.get(e["stream_id"])
                if q:
                    await q.put("\n\n⏱️ **Timeout** — model took too long.")
                    await q.put(None)
        asyncio.create_task(_cloud_wrapper())

    # Ollama coordinator — sequential with unload
    if ollama_entries:
        async def _ollama_coordinator():
            for entry in ollama_entries:
                s_id = entry["stream_id"]
                m_key = entry["model"]
                try:
                    await asyncio.wait_for(
                        _generate_single(s_id, entry["provider"], m_key),
                        timeout=_ARENA_MODEL_TIMEOUT,
                    )
                except asyncio.TimeoutError:
                    q = _arena_queues.get(s_id)
                    if q:
                        await q.put(f"\n\n⏱️ **Timeout** — `{m_key}` took over {_ARENA_MODEL_TIMEOUT}s.")
                        await q.put(None)
                except Exception:
                    pass
                finally:
                    try:
                        await _unload_ollama_model(m_key)
                    except Exception:
                        pass
                    await asyncio.sleep(3)

        asyncio.create_task(_ollama_coordinator())

    return {"status": "processing", "streams": streams}


@router.get("/arena/stream/{stream_id}")
async def arena_stream(stream_id: str):
    """SSE endpoint for Arena columns."""
    if stream_id not in _arena_queues:
        raise HTTPException(404, "Stream not found")

    async def event_generator():
        queue = _arena_queues[stream_id]
        try:
            while True:
                try:
                    token = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield {"event": "keepalive", "data": ""}
                    continue

                if token is None:
                    yield {"data": "[DONE]"}
                    break
                yield {"data": token}
        finally:
            _arena_queues.pop(stream_id, None)

    return EventSourceResponse(event_generator())


@router.post("/arena/evaluate")
async def arena_evaluate(request: Request):
    """Judge the models' responses."""
    data = await request.json()
    prompt = data.get("prompt", "")
    responses = data.get("responses", {})  # dict of stream_id -> text

    provider_key = LLM_PROVIDER
    provider = get_llm_provider(provider_key)
    model_key = getattr(provider, "default_model", "")

    if not prompt or not responses:
        raise HTTPException(400, "Prompt and responses required")

    kwargs = {}
    if model_key:
        kwargs["model"] = model_key

    if provider_key in ("ollama", "local"):
        kwargs["response_format"] = {"type": "json_object"}

    sys_prompt = "You are an impartial AI judge. Your task is to evaluate an AI response to a given prompt. Score it out of 10 and give a 1-sentence explanation."

    final_ratings = {}

    try:
        for s_id, text in responses.items():
            try:
                user_prompt = f"PROMPT:\n{prompt}\n\nRESPONSE TO EVALUATE:\n{text}\n\n"
                user_prompt += "Evaluate the response above. Format your output strictly as a JSON object with EXACTLY two keys: 'score' (number from 0 to 10) and 'rationale' (string, 1 short sentence). DO NOT wrap the JSON in markdown blocks or output any extra text. Example: {\"score\": 8, \"rationale\": \"...\"}"

                t0 = time.perf_counter()
                result_text = ""
                async for token in provider.chat_stream([
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": user_prompt}
                ], **kwargs):
                    result_text += token

                latency_s = time.perf_counter() - t0
                input_tokens = count_message_tokens([{"role": "system", "content": sys_prompt}, {"role": "user", "content": user_prompt}])
                output_tokens = count_tokens(result_text)

                get_metrics().record_llm_call(
                    provider=provider_key,
                    model=model_key or getattr(provider, "default_model", "unknown"),
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    latency_s=latency_s,
                    session_id="arena_eval"
                )

                clean_text = re.sub(r'```json\s*', '', result_text, flags=re.IGNORECASE)
                clean_text = re.sub(r'```\s*', '', clean_text)
                clean_text = clean_text.strip()

                parsed = {}
                parse_success = False

                try:
                    match = re.search(r'\{[\s\S]*\}', clean_text)
                    if match:
                        parsed = json.loads(match.group(0))
                    else:
                        parsed = json.loads(clean_text)
                    parse_success = True
                except json.JSONDecodeError:
                    pass

                score_val = None
                rationale_val = None

                if parse_success and isinstance(parsed, dict):
                    score_val = parsed.get("score", parsed.get("Score", parsed.get("note", parsed.get("Note", parsed.get("rating", parsed.get("rating"))))))
                    rationale_val = parsed.get("rationale", parsed.get("Rationale", parsed.get("justification", parsed.get("Justification", parsed.get("explanation", parsed.get("reasoning"))))))

                    if score_val is None and "ratings" in parsed and isinstance(parsed["ratings"], dict):
                        first_val = list(parsed["ratings"].values())[0] if parsed["ratings"] else {}
                        score_val = first_val.get("score", first_val.get("Score", first_val.get("note")))
                        rationale_val = first_val.get("rationale", first_val.get("Rationale", first_val.get("justification")))

                if score_val is None or rationale_val is None:
                    score_match = re.search(r'(?:score|note|évaluation|rating)[\s"\'=:]*(\d+(?:\.\d+)?)(?:/10)?', clean_text, re.IGNORECASE)
                    if score_match:
                        score_val = float(score_match.group(1))
                    else:
                        any_num = re.search(r'\b([0-9](?:\.[0-9]+)?|10)\b\s*(?:/|sur)\s*10', clean_text)
                        score_val = float(any_num.group(1)) if any_num else "-"

                    rat_match = re.search(r'(?:rationale|justification|explanation|raison)[\s"\'=:]*([^"\'\n\{\}]+)', clean_text, re.IGNORECASE)
                    if rat_match:
                        rationale_val = rat_match.group(1).strip()
                    else:
                        clean_no_json = re.sub(r'["\{\}\[\]]', '', clean_text).strip()
                        if re.search(r'^(?:score|note)', clean_no_json, re.IGNORECASE):
                            clean_no_json = re.sub(r'^(?:score|note).*?\d+.*?\n', '', clean_no_json, flags=re.IGNORECASE).strip()
                        rationale_val = clean_no_json[:250] + "..." if len(clean_no_json) > 250 else clean_no_json

                try:
                    if score_val != "-":
                        score_val = float(score_val)
                        if score_val > 10: score_val = 10.0
                        if score_val < 0: score_val = 0.0
                except (ValueError, TypeError):
                    score_val = "-"

                if rationale_val is None or str(rationale_val).strip() == "":
                    rationale_val = clean_text[:250] + "..." if len(clean_text) > 250 else clean_text

                error_flag = False
                if score_val == "-":
                    error_flag = True
                    if not rationale_val or rationale_val == "..." or rationale_val.strip() == "":
                        rationale_val = "The model was unable to evaluate the response (unreadable format)."

                final_ratings[s_id] = {"score": score_val, "rationale": str(rationale_val).strip(), "error": error_flag}
            except Exception as e:
                final_ratings[s_id] = {"score": "-", "rationale": f"Generation error: {str(e)[:150]}", "error": True}

        return {"ratings": final_ratings}
    except Exception as e:
        raise HTTPException(500, detail="The AI judge failed to return a valid evaluation JSON (timeout or format error).")
    finally:
        if provider_key in ("ollama", "local"):
            try:
                await _unload_ollama_model(model_key)
            except Exception:
                pass
