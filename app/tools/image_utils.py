"""
Clawzd — Image / Media utilities.
Extracted from the monolithic tools_image.py to reduce size and improve maintainability.
Contains GPU checks, pipeline helpers, media capabilities, common prompt utils.
"""
import os
import logging
import warnings
from typing import Any, Optional

from config import DATA_DIR, ENABLE_CLOUD_MODELS, HUGGINGFACE_API_KEY

logger = logging.getLogger("clawzd.image_utils")

IMAGES_DIR = os.path.join(DATA_DIR, "images")
os.makedirs(IMAGES_DIR, exist_ok=True)

# GPU capability check (lazy)
_gpu_ok: Optional[bool] = None

def _check_gpu() -> bool:
    """Lazy GPU capability check. Cached after first successful evaluation."""
    global _gpu_ok
    if _gpu_ok is not None:
        return _gpu_ok

    try:
        import torch
        if torch.cuda.is_available():
            arch_list = torch.cuda.get_arch_list() if hasattr(torch.cuda, "get_arch_list") else []
            cap = torch.cuda.get_device_capability()
            cap_str = f"sm_{cap[0]}{cap[1]}0" if cap else ""
            if not arch_list or cap_str in arch_list or any(a.startswith(f"sm_{cap[0]}") for a in arch_list):
                _gpu_ok = True
                logger.info("GPU OK for image generation: %s (cap %s)", torch.cuda.get_device_name(), cap)
            else:
                _gpu_ok = False
                logger.warning(
                    "GPU %s (cap %s) not in PyTorch arch_list %s — will use API fallback",
                    torch.cuda.get_device_name(), cap_str, arch_list,
                )
        else:
            _gpu_ok = False
            logger.info("CUDA not available — will use API fallback for image generation")
    except Exception as e:
        _gpu_ok = False
        logger.info("PyTorch not available (%s) — will use API fallback", e)

    return _gpu_ok

# Run initial check
try:
    _check_gpu()
except Exception:
    pass

# Image style models config (moved from tools_image.py)
_IMAGE_STYLE_MODELS: dict[str, dict[str, Any]] = {
    "none": {"repo": "Tongyi-MAI/Z-Image-Turbo", "is_lora": False, "pipeline": "zimage"},
    "flux2_klein": {"repo": "black-forest-labs/FLUX.2-klein-9B", "is_lora": False},
    "photorealistic": {"repo": "RunDiffusion/Juggernaut-XL-v9", "is_lora": False},
    "realvis": {"repo": "SG161222/RealVisXL_V4.0", "is_lora": False},
    "pixel_art": {"repo": "nerijs/pixel-art-xl", "is_lora": True},
    "z_image_turbo": {"repo": "Tongyi-MAI/Z-Image-Turbo", "is_lora": False, "pipeline": "zimage"},
    "z_image": {"repo": "Tongyi-MAI/Z-Image", "is_lora": False, "pipeline": "zimage"},
    "hidream_o1": {"repo": "HiDream-ai/HiDream-O1-Image", "is_lora": False},
    "flux2_klein_4b": {"repo": "black-forest-labs/FLUX.2-klein-4B", "is_lora": False},
    # add more as needed
}

def get_style_models() -> dict:
    return _IMAGE_STYLE_MODELS

def get_media_capabilities() -> dict:
    """Build media capabilities dict (simplified version)."""
    openai_ready = bool(ENABLE_CLOUD_MODELS and HUGGINGFACE_API_KEY)  # approx
    return {
        "gpu_available": _check_gpu(),
        "local_models": list(_IMAGE_STYLE_MODELS.keys()),
        "cloud_enabled": ENABLE_CLOUD_MODELS,
    }

# Add more common functions here in future splits (prompt building, resolution logic, etc.)

_generation_progress = {
    "active": False,
    "type": "",       # 'image', 'video', 'audio'
    "step": 0,
    "total_steps": 0,
    "current": 0,
    "message": "",
    "task_id": None,
}

def get_progress() -> dict:
    return _generation_progress.copy()

def set_progress(**kwargs):
    _generation_progress.update(kwargs)

def _cancel_generation(task_id: str):
    """Signal to cancel an in-progress generation."""
    if _generation_progress.get("task_id") == task_id:
        _generation_progress["active"] = False
        _generation_progress["message"] = "Cancelled by user"
        logger.info("Generation cancelled: %s", task_id)

def _classify_prompt(prompt: str) -> str:
    """Classify prompt type for model selection."""
    p = prompt.lower()
    if any(k in p for k in ["pixel", "8bit", "retro", "arcade"]):
        return "pixel_art"
    if any(k in p for k in ["photo", "realistic", "portrait", "person"]):
        return "photorealistic"
    if any(k in p for k in ["art", "painting", "illustration"]):
        return "none"
    return "z_image_turbo"

def _detect_non_english(text: str) -> bool:
    """Simple heuristic for non-English detection."""
    try:
        ascii_ratio = sum(1 for c in text if ord(c) < 128) / max(len(text), 1)
        return ascii_ratio < 0.7
    except Exception:
        return False

def _clean_llm_output(text: str) -> str:
    """Strip common LLM artifacts."""
    for marker in ["<|endoftext|>", "<|im_start|>", "<|im_end|>", "<|eot_id|>", "</s>", "<|end|>", "```", "'''"]:
        text = text.replace(marker, "")
    return text.strip()


def _should_use_local_files(repo_id: str) -> bool:
    gated = ["black-forest-labs", "ideogram", "hi-dream"]
    return any(g in (repo_id or "").lower() for g in gated)


class HfProgressTqdm:
    def __init__(self, *a, **k): pass
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def update(self, *a): pass

    @classmethod
    def set_lock(cls, *a, **k): pass

    @classmethod
    def get_lock(cls, *a, **k):
        import threading
        return threading.RLock()

    @classmethod
    def write(cls, *a, **k): pass


def _get_hf_token():
    from config import HUGGINGFACE_API_KEY
    return HUGGINGFACE_API_KEY or None


def _configured(value: str | None) -> bool:
    return bool(value and str(value).strip())

def _release_pipeline():
    """Release the pipeline and free VRAM."""
    # Note: actual globals _pipeline etc are in tools_image, this is for future
    import gc, torch
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

_IMAGE_STYLES = {
    "photorealistic": {
        "positive": "masterpiece, best quality, ultra-detailed, photorealistic, RAW photo, 8k uhd, dslr, soft lighting, high quality, intricate details",
        "negative": "lowres, bad anatomy, bad hands, text, error, missing fingers, extra digit, fewer digits, cropped, worst quality, low quality, normal quality, jpeg artifacts, signature, watermark, username, blurry, illustration, painting, cartoon, anime, 3d render",
    },
    "anime": {
        "positive": "masterpiece, best quality, ultra-detailed, anime style, colorful, studio ghibli, makoto shinkai, beautifully drawn, highly detailed",
        "negative": "photorealistic, 3d render, realistic, ugly, distorted, poorly drawn, lowres, bad anatomy, bad hands, error, missing fingers, worst quality, low quality, watermark",
    },
    "pixel_art": {
        "positive": "masterpiece, best quality, pixel art, 16-bit, retro, highly detailed, colorful, crisp, sharp",
        "negative": "high resolution, smooth, realistic, 3d, vector, ugly, blurry, blurry pixels, jpeg artifacts, worst quality, low quality",
    },
    "logo": {
        "positive": "masterpiece, best quality, vector logo, flat design, minimalist, clean lines, solid colors, corporate identity, isolated on white background, sharp edges",
        "negative": "photorealistic, 3d, realistic, photo, complex, gradients, messy, ugly, text, watermark, low quality, worst quality, blurry",
    },
    # Z-Image and Qwen-Image use natural language prompts; no style keyword injection needed.
    # These entries provide negative prompts only.
    "z_image_turbo": {
        "positive": "",
        "negative": "lowres, bad anatomy, bad hands, text, error, worst quality, low quality, watermark, blurry",
    },
    "z_image": {
        "positive": "",
        "negative": "lowres, bad anatomy, bad hands, text, error, worst quality, low quality, watermark, blurry",
    },
    "ideogram_4_nf4": {
        "positive": "",
        "negative": "",
    },
}


_SVG_KEYWORDS = {
    "svg", "vector", "icon", "logo", "diagram", "flowchart", "chart", "graph", "line art", "flat design", "minimal", "outline", "wireframe", "schematic", "blueprint"
}

_RASTER_KEYWORDS = {
    "photo", "photorealistic", "realistic", "photograph", "painting", "watercolor", "oil",
    "3d", "render", "texture", "landscape", "portrait", "face", "person",
    "animal", "nature", "scenery", "cinematic", "detailed", "complex",
    "intricate", "hdr", "4k", "8k",
}

def _media_cloud_reason(mode: str, openai_ready: bool, hf_ready: bool, cloud_enabled: bool) -> str:
    if not cloud_enabled:
        return "Cloud media providers are disabled by ENABLE_CLOUD_MODELS."
    if mode == "video" and not openai_ready:
        return "OPENAI_API_KEY is required for cloud video generation."
    if mode == "audio" and not openai_ready:
        return "OPENAI_API_KEY is required for OpenAI TTS."
    if mode == "image" and not (openai_ready or hf_ready):
        return "OPENAI_API_KEY or HUGGINGFACE_API_KEY is required for cloud image generation."
    return ""

def _build_media_capabilities() -> dict:
    """Build media capabilities for frontend."""
    openai_ready = bool(ENABLE_CLOUD_MODELS and HUGGINGFACE_API_KEY)  # rough
    hf_ready = True  # assume
    cloud_enabled = ENABLE_CLOUD_MODELS
    return {
        "gpu_available": _check_gpu(),
        "local_models": list(get_style_models().keys()),
        "cloud_enabled": cloud_enabled,
        "reason": _media_cloud_reason("auto", openai_ready, hf_ready, cloud_enabled),
    }

