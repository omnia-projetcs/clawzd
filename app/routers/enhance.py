"""
Clawzd — Enhance Prompt API.
Takes a user prompt and refines it via LLM for clarity and context.
"""
import logging
from fastapi import APIRouter
from pydantic import BaseModel

from app.llm_provider import get_llm_provider

router = APIRouter()
logger = logging.getLogger("clawzd.enhance")

ENHANCE_SYSTEM_PROMPT = (
    "You are a prompt engineering expert. Your job is to take the user's rough "
    "prompt and rewrite it to be clearer, more specific, and more likely to "
    "produce excellent results from an AI assistant.\n\n"
    "RULES:\n"
    "- Reply with ONLY the enhanced prompt — no explanations, no quotes, no bullet points.\n"
    "- Preserve the user's original intent and language.\n"
    "- Add relevant context, constraints, and formatting instructions.\n"
    "- Make it more actionable and specific.\n"
    "- Keep the same language as the input (if French, reply in French).\n"
    "- Do NOT add greetings or meta-commentary.\n"
)


class EnhanceRequest(BaseModel):
    prompt: str
    provider: str | None = None
    model: str = ""


@router.post("/enhance")
async def enhance_prompt(req: EnhanceRequest):
    """Enhance a user prompt via LLM refinement."""
    if not req.prompt.strip():
        return {
            "enhanced": "",
            "message": "Type a prompt first, then click ✨ to enhance it.",
        }

    try:
        from config import LLM_PROVIDER
        prov_name = req.provider if req.provider else LLM_PROVIDER
        llm = get_llm_provider(prov_name)
        messages = [
            {"role": "system", "content": ENHANCE_SYSTEM_PROMPT},
            {"role": "user", "content": req.prompt},
        ]

        kwargs = {}
        if req.model:
            kwargs["model"] = req.model

        enhanced = ""
        async for token in llm.chat_stream(messages, **kwargs):
            enhanced += token

        enhanced = enhanced.strip().strip('"').strip("'")

        return {"enhanced": enhanced, "original": req.prompt}

    except Exception as e:
        logger.error("Enhance prompt failed: %s", e)
        return {"enhanced": req.prompt, "error": str(e)}
