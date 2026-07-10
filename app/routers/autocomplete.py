"""
Clawzd — Code autocomplete & transcription router.

Extracted from gateway.py. Handles inline IDE code completion
(FIM, local Ollama, external providers) and audio transcription.
"""
import logging
import re

import httpx
from fastapi import APIRouter, Request, UploadFile, File

from app.core.llm_provider import get_llm_provider

logger = logging.getLogger("clawzd.autocomplete")
router = APIRouter()

# FIM tokens for common code models
_FIM_MODELS = {"codellama", "deepseek-coder", "starcoder", "codegemma", "qwen2.5-coder", "stable-code"}


def _is_fim_model(model_name: str) -> bool:
    """Check if a model likely supports Fill-in-the-Middle."""
    base = model_name.split(":")[0].lower()
    return any(f in base for f in _FIM_MODELS)


def _clean_completion(text: str, prefix: str, intent: str = "continuation") -> str:
    """Clean up a raw LLM completion for inline display."""
    if not text:
        return ""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]
        text = "\n".join(lines)
    if text.endswith("```"):
        text = text[:-3].rstrip()
    text = text.strip("\n")
    if not text:
        return ""
    lines = text.split("\n")
    cleaned = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("//") and any(w in stripped.lower() for w in
            ["here", "the following", "complete", "continuation", "rest of",
             "this function", "this code", "implementation"]):
            continue
        if stripped.startswith("#") and any(w in stripped.lower() for w in
            ["here", "the following", "complete", "continuation", "rest of",
             "this function", "this code", "implementation"]):
            continue
        if stripped in ("...", "…", "# ...", "// ...", "# TODO", "// TODO"):
            continue
        if stripped.startswith("Note:") or stripped.startswith("Explanation:"):
            continue
        cleaned.append(line)
    text = "\n".join(cleaned).strip("\n")
    if not text:
        return ""
    max_lines = 20 if intent == "comment_generate" else 8
    lines = text.split("\n")
    if len(lines) > max_lines:
        text = "\n".join(lines[:max_lines])
    last_prefix_line = prefix.rstrip().split("\n")[-1].strip() if prefix.strip() else ""
    if last_prefix_line and text.strip() == last_prefix_line:
        return ""
    if last_prefix_line and text.startswith(last_prefix_line):
        text = text[len(last_prefix_line):]
    return text.rstrip()


def _build_local_prompt(intent: str, context_prefix: str, suffix_preview: str,
                        file_path: str, language: str) -> tuple[str, list[str]]:
    """Build prompt and stop tokens for Ollama based on intent."""
    if intent == "comment_generate":
        prompt = (
            f"# File: {file_path} [{language}]\n"
            f"# Read the comment(s) above the cursor and generate the corresponding code.\n"
            f"# Output ONLY the implementation code. No explanations. No repeating the comment.\n\n"
            f"{context_prefix}"
        )
        stop_tokens = ["\n\n\n", "# File:", "# Task:", "# Rules:", "```"]
    elif intent == "correction":
        prompt = (
            f"# File: {file_path} [{language}]\n"
            f"# The user is editing code mid-line. Complete or fix the expression at the cursor.\n"
            f"# Output ONLY the missing part to make the line correct. No explanations.\n\n"
            f"{context_prefix}"
        )
        if suffix_preview:
            prompt += f"{{{{CURSOR}}}}{suffix_preview}"
        stop_tokens = ["\n\n", "# File:", "# Task:", "# Rules:", "```"]
    else:
        prompt = (
            f"# File: {file_path} [{language}]\n"
            f"# Continue the code naturally. Output ONLY code, no explanations.\n\n"
            f"{context_prefix}"
        )
        stop_tokens = ["\n\n\n", "# File:", "# Task:", "# Rules:"]
    return prompt, stop_tokens


def _build_external_messages(intent: str, context_prefix: str, suffix_preview: str,
                             file_path: str, language: str) -> list[dict]:
    """Build chat messages for external providers based on intent."""
    if intent == "comment_generate":
        system_msg = (
            "You are an inline code generator embedded in an IDE. "
            "The user has written a comment describing what code they want. "
            "Your job is to generate the implementation code that fulfills the comment. "
            "Rules:\n"
            "- Output ONLY raw code. No markdown. No fences. No backticks.\n"
            "- Do NOT repeat the comment. Start with the code directly.\n"
            "- Generate a complete, working implementation (function, class, or block).\n"
            "- Match the existing code style and indentation.\n"
            "- Output up to 20 lines.\n"
            "- If you're unsure, output nothing."
        )
    elif intent == "correction":
        system_msg = (
            "You are an inline code correction engine embedded in an IDE. "
            "The user is editing code mid-line and needs help completing or fixing the current expression. "
            "Rules:\n"
            "- Output ONLY the missing code fragment to complete/fix the expression.\n"
            "- No markdown. No fences. No backticks. No explanations.\n"
            "- Output should seamlessly connect the text before and after the cursor.\n"
            "- Output 1-3 lines maximum.\n"
            "- If you're unsure, output nothing.\n"
            "- Do NOT repeat code that's already written."
        )
    else:
        system_msg = (
            "You are an inline code completion engine embedded in an IDE. "
            "Your ONLY job is to predict what code comes next at the cursor position. "
            "Rules:\n"
            "- Output ONLY raw code. No markdown. No fences. No backticks.\n"
            "- No explanations. No comments about what the code does.\n"
            "- Continue naturally from the last line, maintaining the same style and indentation.\n"
            "- Output 1-6 lines maximum.\n"
            "- If you're unsure, output nothing.\n"
            "- Do NOT repeat code that's already written."
        )
    user_msg = f"[{language}] {file_path}\n\n{context_prefix}"
    if suffix_preview:
        user_msg += f"\n{{{{CURSOR}}}}\n{suffix_preview}"
    else:
        user_msg += "\n{{CURSOR}}"
    if intent == "comment_generate":
        user_msg += "\n\nGenerate the code described in the comment above {{CURSOR}}:"
    elif intent == "correction":
        user_msg += "\n\nComplete/fix the expression at {{CURSOR}}:"
    else:
        user_msg += "\n\nComplete the code at {{CURSOR}}:"
    return [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_msg},
    ]


@router.post("/autocomplete")
async def api_autocomplete(request: Request):
    """Provide inline code completion using the LLM."""
    data = await request.json()
    prefix = data.get("prefix", "")
    suffix = data.get("suffix", "")
    language = data.get("language", "")
    file_path = data.get("file_path", "")
    intent = data.get("intent", "continuation")
    max_tokens = min(data.get("max_tokens", 120), 300)
    if not prefix.strip():
        return {"completion": ""}
    provider_key = data.get("provider", "local")
    model_key = data.get("model", "")
    temperature = 0.1 if intent == "correction" else 0.2 if intent == "comment_generate" else 0.15

    if provider_key in ("local", "ollama"):
        try:
            from config import OLLAMA_HOST, OLLAMA_MODEL
            prefix_lines = prefix.split("\n")
            context_prefix = "\n".join(prefix_lines[-40:])
            suffix_preview = "\n".join(suffix.split("\n")[:8]) if suffix.strip() else ""
            if _is_fim_model(model_key or ""):
                prompt = f"<|fim_prefix|>{context_prefix}<|fim_suffix|>{suffix_preview}<|fim_middle|>"
                stop_tokens = ["<|fim_pad|>", "<|endoftext|>", "<|fim_prefix|>",
                               "<|fim_suffix|>", "<|fim_middle|>", "\n\n\n"]
                payload = {
                    "model": model_key or OLLAMA_MODEL, "prompt": prompt, "raw": True, "stream": False,
                    "options": {"num_predict": max_tokens, "temperature": temperature, "top_p": 0.9, "repeat_penalty": 1.1, "stop": stop_tokens},
                }
            else:
                prompt, stop_tokens = _build_local_prompt(intent, context_prefix, suffix_preview, file_path, language)
                payload = {
                    "model": model_key or OLLAMA_MODEL,
                    "prompt": f"/no_think\n{prompt}",
                    "system": "You are a code completion assistant. Output ONLY the raw code. No markdown, no explanations.",
                    "raw": False, "stream": False,
                    "options": {"num_predict": max_tokens, "temperature": temperature, "top_p": 0.9, "repeat_penalty": 1.1, "stop": stop_tokens},
                }
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(f"{OLLAMA_HOST}/api/generate", json=payload)
                if resp.status_code == 200:
                    raw = resp.json().get("response", "")
                    result = _clean_completion(raw, prefix, intent)
                    logger.info("Autocomplete [%s/%s]: %d→%d chars", model_key, intent, len(raw), len(result))
                    return {"completion": result}
                else:
                    logger.warning("Ollama autocomplete HTTP %s: %s", resp.status_code, resp.text[:200])
        except Exception as e:
            logger.warning("Ollama autocomplete error: %s", e)
        return {"completion": ""}

    # External providers
    prefix_lines = prefix.split("\n")
    context_prefix = "\n".join(prefix_lines[-40:])
    suffix_preview = "\n".join(suffix.split("\n")[:8]) if suffix.strip() else ""
    messages = _build_external_messages(intent, context_prefix, suffix_preview, file_path, language)
    max_stream_lines = 20 if intent == "comment_generate" else 8
    try:
        provider = get_llm_provider(provider_key)
        kwargs = {"max_tokens": max_tokens, "temperature": temperature}
        if model_key:
            kwargs["model"] = model_key
        result = ""
        async for token in provider.chat_stream(messages, **kwargs):
            result += token
            if result.count("\n") > max_stream_lines or len(result) > 600:
                break
        result = _clean_completion(result, prefix, intent)
        return {"completion": result}
    except Exception as e:
        logger.warning("Autocomplete error: %s", e)
        return {"completion": ""}


# --- Audio Transcription API ---
_whisper_model = None


@router.post("/transcribe")
async def api_transcribe(file: UploadFile = File(...)):
    """Transcribe audio using local openai-whisper model."""
    import tempfile
    import os
    try:
        import whisper
    except ImportError:
        logger.error("openai-whisper is not installed in the python environment.")
        return {"error": "openai-whisper is not installed on this system. Please run 'pip install openai-whisper'."}
    global _whisper_model
    if _whisper_model is None:
        try:
            logger.info("Loading local Whisper model (base)...")
            _whisper_model = whisper.load_model("base")
        except Exception as e:
            logger.error("Failed to load Whisper model: %s", e)
            return {"error": f"Model load failed: {e}"}
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name
        result = _whisper_model.transcribe(tmp_path)
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        return {"text": result["text"]}
    except Exception as e:
        logger.error("Transcription error: %s", e)
        return {"error": str(e)}
