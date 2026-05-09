"""
Clawzd — Image generation tool.

Strategy (automatic fallback):
1. SVG via LLM (Ollama) — instant, vector, for simple images
2. Local GPU via diffusers (SDXL Turbo) — fast, ~2s, needs CUDA
3. HuggingFace Inference API — free, ~5-10s, needs internet
"""
import os
import re
import uuid
import base64
import logging
import warnings
from datetime import datetime

warnings.filterwarnings("ignore", category=UserWarning, message=".*local_dir_use_symlinks.*")
from fastapi import APIRouter, Request, HTTPException
from config import DATA_DIR

logger = logging.getLogger("clawzd.image")
router = APIRouter()

IMAGES_DIR = os.path.join(DATA_DIR, "images")
os.makedirs(IMAGES_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# GPU capability check (lazy — re-evaluated on first pipeline load)
# ---------------------------------------------------------------------------
_gpu_ok: bool | None = None  # None = not yet checked


def _check_gpu() -> bool:
    """Lazy GPU capability check. Cached after first successful evaluation.

    At import time, ``torch.cuda.is_available()`` can return False due to
    transient driver initialization issues. This function re-evaluates on
    demand, allowing CUDA to become available after the initial import.
    """
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


# Run initial check (non-blocking — sets _gpu_ok or leaves None for retry)
try:
    _check_gpu()
except Exception:
    pass

# ---------------------------------------------------------------------------
# Local pipeline (GPU)
# ---------------------------------------------------------------------------

# NOTE: Only free open-weights models from Hugging Face are allowed here.
_IMAGE_STYLE_MODELS = {
    "none": {"repo": "black-forest-labs/FLUX.2-klein-4b-fp8", "is_lora": False},
    "flux_schnell": {"repo": "black-forest-labs/FLUX.1-schnell", "is_lora": False},
    "flux2_klein": {"repo": "black-forest-labs/FLUX.2-klein-4b-fp8", "is_lora": False},
    "photorealistic": {"repo": "RunDiffusion/Juggernaut-XL-v9", "is_lora": False},
    "realvis": {"repo": "SG161222/RealVisXL_V4.0", "is_lora": False},
    "pixel_art": {"repo": "nerijs/pixel-art-xl", "is_lora": True},
    # Unsloth-curated models (using original HF repos via diffusers)
    "z_image_turbo": {"repo": "Tongyi-MAI/Z-Image-Turbo", "is_lora": False, "pipeline": "zimage"},
    "z_image": {"repo": "Tongyi-MAI/Z-Image", "is_lora": False, "pipeline": "zimage"},
}



_hf_download_state = {
    "active": False,
    "progress": 0.0,
    "repo": "",
}

# Shared generation progress state (image / video / audio)
_generation_progress = {
    "active": False,
    "type": "",       # 'image', 'video', 'audio'
    "step": 0,
    "total_steps": 0,
    "progress": 0.0,  # 0-100
    "stage": "",      # e.g. 'loading_model', 'generating', 'encoding'
}


def _should_use_local_files(repo_id: str) -> bool:
    """Whether to force local-only loading (no network).

    Always returns False: HuggingFace Hub's from_pretrained already uses
    the local cache when available and only downloads missing files.
    Forcing local_files_only=True on partially-downloaded models blocks
    downloads and causes silent pipeline failures.
    """
    return False

import tqdm
import tqdm.auto
orig_tqdm = tqdm.auto.tqdm

class HfProgressTqdm(orig_tqdm):
    def update(self, n=1):
        super().update(n)
        global _hf_download_state
        _hf_download_state["active"] = True
        total = getattr(self, "total", 0)
        if total:
            # We just want a rough estimate, so we'll just track the last active bar
            _hf_download_state["progress"] = min(100.0, (getattr(self, "n", 0) / total) * 100)

tqdm.auto.tqdm = HfProgressTqdm
tqdm.tqdm = HfProgressTqdm

try:
    import huggingface_hub.utils.tqdm
    huggingface_hub.utils.tqdm.tqdm = HfProgressTqdm
except ImportError:
    pass
try:
    import huggingface_hub.utils._progress
    huggingface_hub.utils._progress.tqdm = HfProgressTqdm
except ImportError:
    pass

_pipeline = None
_current_image_model = None
_current_is_lora = False

def _get_hf_token():
    hf_token = os.environ.get("HF_TOKEN", "").strip()
    if not hf_token:
        hf_token = os.environ.get("HUGGINGFACE_API_KEY", "").strip()
    if not hf_token:
        try:
            from config import HUGGINGFACE_API_KEY
            hf_token = HUGGINGFACE_API_KEY.strip()
        except ImportError:
            pass
    hf_token = hf_token.strip("'").strip('"')
    if not hf_token:
        try:
            import huggingface_hub
            hf_token = huggingface_hub.get_token() or ""
            hf_token = hf_token.strip().strip("'").strip('"')
        except ImportError:
            pass
    return hf_token if hf_token else None

def _get_pipeline(repo_id: str, is_lora: bool = False):
    """Lazy-load the image generation pipeline with CPU offload.

    Detects model-specific pipeline classes:
    - Z-Image family → ZImagePipeline
    - FLUX / SDXL / default → AutoPipelineForText2Image
    """
    global _pipeline, _current_image_model, _current_is_lora
    if _pipeline is not None and _current_image_model == repo_id and _current_is_lora == is_lora:
        return _pipeline

    _release_pipeline()

    import torch
    from diffusers import AutoPipelineForText2Image

    # Determine pipeline type from model catalog metadata
    _pipe_type = ""
    for _cfg in _IMAGE_STYLE_MODELS.values():
        if _cfg["repo"] == repo_id:
            _pipe_type = _cfg.get("pipeline", "")
            break

    # Z-Image / Qwen-Image / FLUX / SD3.5 all need bfloat16
    is_bf16_model = (
        "flux" in repo_id.lower()
        or "stable-diffusion-3" in repo_id.lower()
        or _pipe_type == "zimage"
    )
    if is_bf16_model:
        dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32
        variant = None
    else:
        dtype = torch.float16 if torch.cuda.is_available() else torch.float32
        variant = "fp16"

    logger.info(f"Loading image pipeline for {repo_id} (LoRA: {is_lora}, type: {_pipe_type or 'auto'})")

    try:
        global _hf_download_state
        _hf_download_state = {"active": True, "progress": 0.0, "repo": repo_id}
        hf_token = _get_hf_token()

        if is_lora:
            base_model = "stabilityai/stable-diffusion-xl-base-1.0"
            _pipeline = AutoPipelineForText2Image.from_pretrained(
                base_model, torch_dtype=dtype, variant=variant,
                local_files_only=_should_use_local_files(base_model), token=hf_token,
            )
            _pipeline.load_lora_weights(repo_id, token=hf_token)

        elif _pipe_type == "zimage":
            # Z-Image family (Turbo & Base) — uses ZImagePipeline
            from diffusers import ZImagePipeline
            _pipeline = ZImagePipeline.from_pretrained(
                repo_id, torch_dtype=dtype, low_cpu_mem_usage=False,
                local_files_only=_should_use_local_files(repo_id), token=hf_token,
            )

        elif repo_id.endswith(".gguf") or repo_id.startswith("http"):
            clean_url = repo_id.split("?")[0] if repo_id.startswith("http") else repo_id
            if "huggingface.co" in clean_url and "/resolve/main/" in clean_url:
                clean_url = clean_url.replace("/resolve/main/", "/blob/main/")
            from diffusers import StableDiffusionXLPipeline
            _pipeline = StableDiffusionXLPipeline.from_single_file(
                clean_url, torch_dtype=dtype,
                local_files_only=_should_use_local_files(repo_id), token=hf_token,
            )
        else:
            _pipeline = AutoPipelineForText2Image.from_pretrained(
                repo_id, torch_dtype=dtype, variant=variant,
                local_files_only=_should_use_local_files(repo_id), token=hf_token,
            )
    except Exception as e:
        if "variant" in str(e).lower() or "fp16" in str(e).lower() or "safetensors" in str(e).lower():
            logger.warning(f"Failed with variant {variant}, retrying without variant: {e}")
            if is_lora:
                base_model = "stabilityai/stable-diffusion-xl-base-1.0"
                _pipeline = AutoPipelineForText2Image.from_pretrained(
                    base_model, torch_dtype=dtype, variant=None,
                    local_files_only=_should_use_local_files(base_model), token=hf_token,
                )
                _pipeline.load_lora_weights(repo_id, token=hf_token)
            elif repo_id.endswith(".gguf") or repo_id.startswith("http"):
                clean_url = repo_id.split("?")[0] if repo_id.startswith("http") else repo_id
                if "huggingface.co" in clean_url and "/resolve/main/" in clean_url:
                    clean_url = clean_url.replace("/resolve/main/", "/blob/main/")
                from diffusers import StableDiffusionXLPipeline
                _pipeline = StableDiffusionXLPipeline.from_single_file(
                    clean_url, torch_dtype=dtype,
                    local_files_only=_should_use_local_files(repo_id), token=hf_token,
                )
            else:
                _pipeline = AutoPipelineForText2Image.from_pretrained(
                    repo_id, torch_dtype=dtype, variant=None,
                    local_files_only=_should_use_local_files(repo_id), token=hf_token,
                )
        else:
            _hf_download_state["active"] = False
            logger.error(f"Failed to load {repo_id}: {e}")
            raise RuntimeError(f"Pipeline failed to load: {e}")
    finally:
        _hf_download_state["active"] = False

    if torch.cuda.is_available():
        _pipeline.enable_model_cpu_offload()

    _current_image_model = repo_id
    _current_is_lora = is_lora
    return _pipeline


def _release_pipeline():
    """Release the pipeline and free VRAM."""
    global _pipeline, _current_image_model, _current_is_lora
    if _pipeline is not None:
        import gc, torch
        del _pipeline
        _pipeline = None
        _current_image_model = None
        _current_is_lora = False
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


_rembg_sessions = {}
def _remove_bg_enhanced(data_or_img, **kwargs):
    global _rembg_sessions
    from rembg import remove, new_session
    
    model_name = kwargs.pop("model_name", "isnet-general-use")
    if model_name not in _rembg_sessions:
        try:
            _rembg_sessions[model_name] = new_session(model_name)
        except Exception:
            # Fallback
            _rembg_sessions[model_name] = new_session("u2net")
            
    # Default to post_process_mask=True if not specified
    if "post_process_mask" not in kwargs:
        kwargs["post_process_mask"] = True
        
    return remove(data_or_img, session=_rembg_sessions[model_name], **kwargs)

_i2i_pipeline = None
_current_i2i_model = None
_current_i2i_lora = False

def _get_i2i_pipeline(repo_id: str, is_lora: bool = False):
    """Lazy-load the Stable Diffusion Image-to-Image pipeline with CPU offload."""
    global _i2i_pipeline, _current_i2i_model, _current_i2i_lora
    if _i2i_pipeline is not None and _current_i2i_model == repo_id and _current_i2i_lora == is_lora:
        return _i2i_pipeline

    _release_i2i_pipeline()

    import torch
    from diffusers import AutoPipelineForImage2Image

    # FLUX and SD3.5 need bfloat16; SDXL models use float16
    is_bf16_model = "flux" in repo_id.lower() or "stable-diffusion-3" in repo_id.lower()
    if is_bf16_model:
        dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32
        variant = None
    else:
        dtype = torch.float16 if torch.cuda.is_available() else torch.float32
        variant = "fp16"

    logger.info(f"Loading i2i pipeline for {repo_id} (LoRA: {is_lora})")

    try:
        global _hf_download_state
        _hf_download_state = {"active": True, "progress": 0.0, "repo": repo_id}
        hf_token = _get_hf_token()
        
        if is_lora:
            base_model = "stabilityai/stable-diffusion-xl-base-1.0"
            _i2i_pipeline = AutoPipelineForImage2Image.from_pretrained(
                base_model, torch_dtype=dtype, variant=variant, local_files_only=_should_use_local_files(base_model if "base_model" in locals() and "stabilityai" in base_model else repo_id), token=hf_token
            )
            _i2i_pipeline.load_lora_weights(repo_id, token=hf_token)
        else:
            if repo_id.endswith(".gguf") or repo_id.startswith("http"):
                clean_url = repo_id.split("?")[0] if repo_id.startswith("http") else repo_id
                if "huggingface.co" in clean_url and "/resolve/main/" in clean_url:
                    clean_url = clean_url.replace("/resolve/main/", "/blob/main/")
                from diffusers import StableDiffusionXLImg2ImgPipeline
                _i2i_pipeline = StableDiffusionXLImg2ImgPipeline.from_single_file(
                    clean_url, torch_dtype=dtype, local_files_only=_should_use_local_files(base_model if "base_model" in locals() and "stabilityai" in base_model else repo_id), token=hf_token
                )
            else:
                _i2i_pipeline = AutoPipelineForImage2Image.from_pretrained(
                    repo_id, torch_dtype=dtype, variant=variant, local_files_only=_should_use_local_files(base_model if "base_model" in locals() and "stabilityai" in base_model else repo_id), token=hf_token
                )
    except Exception as e:
        if "variant" in str(e).lower() or "fp16" in str(e).lower() or "safetensors" in str(e).lower():
            logger.warning(f"Failed with variant {variant}, retrying without variant: {e}")
            if is_lora:
                _i2i_pipeline = AutoPipelineForImage2Image.from_pretrained(base_model, torch_dtype=dtype, variant=None, local_files_only=_should_use_local_files(base_model if "base_model" in locals() and "stabilityai" in base_model else repo_id), token=hf_token)
                _i2i_pipeline.load_lora_weights(repo_id, token=hf_token)
            else:
                if repo_id.endswith(".gguf") or repo_id.startswith("http"):
                    clean_url = repo_id.split("?")[0] if repo_id.startswith("http") else repo_id
                    if "huggingface.co" in clean_url and "/resolve/main/" in clean_url:
                        clean_url = clean_url.replace("/resolve/main/", "/blob/main/")
                    from diffusers import StableDiffusionXLImg2ImgPipeline
                    _i2i_pipeline = StableDiffusionXLImg2ImgPipeline.from_single_file(clean_url, torch_dtype=dtype, local_files_only=_should_use_local_files(base_model if "base_model" in locals() and "stabilityai" in base_model else repo_id), token=hf_token)
                else:
                    _i2i_pipeline = AutoPipelineForImage2Image.from_pretrained(repo_id, torch_dtype=dtype, variant=None, local_files_only=_should_use_local_files(base_model if "base_model" in locals() and "stabilityai" in base_model else repo_id), token=hf_token)
        else:
            _hf_download_state["active"] = False
            logger.error(f"Failed to load i2i {repo_id}: {e}")
            raise RuntimeError(f"I2I Pipeline failed to load: {e}")
    finally:
        _hf_download_state["active"] = False

    if torch.cuda.is_available():
        _i2i_pipeline.enable_model_cpu_offload()

    _current_i2i_model = repo_id
    _current_i2i_lora = is_lora
    return _i2i_pipeline

def _release_i2i_pipeline():
    """Release the Image-to-Image pipeline and free VRAM."""
    global _i2i_pipeline, _current_i2i_model, _current_i2i_lora
    if _i2i_pipeline is not None:
        import gc, torch
        del _i2i_pipeline
        _i2i_pipeline = None
        _current_i2i_model = None
        _current_i2i_lora = False
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


# ---------------------------------------------------------------------------
# Local video pipeline (GPU)
# ---------------------------------------------------------------------------

# Video model catalog — maps UI keys to HuggingFace repo IDs and metadata
_VIDEO_MODELS = {
    "svd_xt": {
        "repo": "stabilityai/stable-video-diffusion-img2vid-xt",
        "i2v_repo": "stabilityai/stable-video-diffusion-img2vid-xt",
        "pipeline": "svd",
        "steps": 25,
        "guidance": 0.0,  # SVD doesn't use CFG
        "fps": 7,
        "max_frames": 25,
        "vram_gb": 6,
        "dtype": "float16",
    },
    "animatediff": {
        "repo": "ByteDance/AnimateDiff-Lightning",
        "base_model": "emilianJR/epiCRealism",
        "pipeline": "animatediff",
        "steps": 4,
        "guidance": 1.0,
        "fps": 8,
        "max_frames": 48,
        "vram_gb": 6,
        "dtype": "float16",
    },
    "wan_1_3b": {
        "repo": "Wan-AI/Wan2.1-T2V-1.3B-Diffusers",
        "pipeline": "wan",
        "steps": 15,
        "guidance": 6.0,
        "fps": 16,
        "max_frames": 129,
        "vram_gb": 8,
        "dtype": "bfloat16",
    },
    "cogvideox_2b": {
        "repo": "THUDM/CogVideoX-2b",
        "pipeline": "auto",
        "steps": 12,
        "guidance": 6.0,
        "fps": 8,
        "max_frames": 81,
        "vram_gb": 10,
        "dtype": "float16",
    },
    "ltx_video": {
        "repo": "Lightricks/LTX-Video-0.9.7-dev",
        "pipeline": "ltx",
        "steps": 25,
        "guidance": 1.0,
        "fps": 24,
        "max_frames": 257,
        "vram_gb": 10,
        "dtype": "bfloat16",
    },
    "ltx_23": {
        "repo": "Lightricks/LTX-2.3",
        "pipeline": "ltx",
        "steps": 25,
        "guidance": 1.0,
        "fps": 50,
        "max_frames": 257,
        "vram_gb": 20,
        "dtype": "bfloat16",
    },
    "ltx_23_distilled": {
        "repo": "Lightricks/LTX-2.3",
        "pipeline": "ltx",
        "steps": 8,
        "guidance": 1.0,
        "fps": 50,
        "max_frames": 257,
        "vram_gb": 16,
        "dtype": "bfloat16",
        "distilled": True,
    },
    "cogvideox": {
        "repo": "THUDM/CogVideoX-5b",
        "i2v_repo": "THUDM/CogVideoX-5b-I2V",
        "pipeline": "auto",
        "steps": 12,
        "guidance": 6.0,
        "fps": 8,
        "max_frames": 49,
        "vram_gb": 16,
        "dtype": "float16",
    },
    "hunyuanvideo": {
        "repo": "hunyuanvideo-community/HunyuanVideo",
        "pipeline": "auto",
        "steps": 20,
        "guidance": 6.0,
        "fps": 15,
        "max_frames": 61,
        "vram_gb": 14,
        "dtype": "bfloat16",
    },
    "wan22": {
        "repo": "Wan-AI/Wan2.2-T2V-A14B-Diffusers",
        "i2v_repo": "Wan-AI/Wan2.2-I2V-A14B-Diffusers",
        "pipeline": "wan",
        "steps": 20,
        "guidance": 5.0,
        "fps": 24,
        "max_frames": 81,
        "vram_gb": 20,
        "dtype": "bfloat16",
    },
}

_video_pipeline = None
_current_video_model = None

_i2v_pipeline = None
_current_i2v_model = None

def _get_video_pipeline(repo_id: str, model_key: str = ""):
    """Lazy-load the Text-to-Video pipeline.
    
    Detects the correct pipeline class based on the model_key or repo_id:
    - animatediff → AnimateDiffPipeline + MotionAdapter
    - ltx → LTXConditionPipeline
    - wan → WanPipeline
    - auto/default → DiffusionPipeline (generic)
    """
    global _video_pipeline, _current_video_model
    if _video_pipeline is not None and _current_video_model == repo_id:
        return _video_pipeline
        
    _release_video_pipeline()

    import torch

    # Determine pipeline type from model config
    model_cfg = _VIDEO_MODELS.get(model_key, {})
    pipeline_type = model_cfg.get("pipeline", "auto")
    dtype_str = model_cfg.get("dtype", "float16")
    dtype = torch.bfloat16 if dtype_str == "bfloat16" else (torch.float16 if torch.cuda.is_available() else torch.float32)

    try:
        logger.info("Loading video pipeline [%s] for %s", pipeline_type, repo_id)

        global _hf_download_state
        _hf_download_state = {"active": True, "progress": 0.0, "repo": repo_id}
        hf_token = _get_hf_token()

        # INT8 quantization for large models (requires bitsandbytes)
        quant_config = None
        quant_mode = model_cfg.get("quantize", "")
        if quant_mode == "int8":
            try:
                from diffusers import BitsAndBytesConfig
                quant_config = BitsAndBytesConfig(load_in_8bit=True)
                logger.info("INT8 quantization enabled for %s", repo_id)
            except ImportError:
                logger.warning("bitsandbytes not installed — loading %s without quantization", repo_id)

        if pipeline_type == "animatediff":
            # AnimateDiff Lightning — MotionAdapter + SD1.5 base
            from diffusers import AnimateDiffPipeline, MotionAdapter, EulerDiscreteScheduler
            from huggingface_hub import hf_hub_download
            from safetensors.torch import load_file

            steps = model_cfg.get("steps", 4)
            ckpt = f"animatediff_lightning_{steps}step_diffusers.safetensors"
            base_model = model_cfg.get("base_model", "emilianJR/epiCRealism")

            adapter = MotionAdapter().to("cuda" if torch.cuda.is_available() else "cpu", dtype)
            adapter.load_state_dict(
                load_file(hf_hub_download(repo_id, ckpt, token=hf_token),
                          device="cuda" if torch.cuda.is_available() else "cpu")
            )
            _video_pipeline = AnimateDiffPipeline.from_pretrained(
                base_model, motion_adapter=adapter, torch_dtype=dtype, token=hf_token
            )
            _video_pipeline.scheduler = EulerDiscreteScheduler.from_config(
                _video_pipeline.scheduler.config,
                timestep_spacing="trailing",
                beta_schedule="linear",
            )
            if torch.cuda.is_available():
                _video_pipeline.to("cuda")

        elif pipeline_type == "ltx":
            # LTX-Video — LTXConditionPipeline
            from diffusers import LTXConditionPipeline
            load_kwargs = dict(torch_dtype=dtype, token=hf_token)
            if quant_config:
                load_kwargs["quantization_config"] = quant_config
            _video_pipeline = LTXConditionPipeline.from_pretrained(
                repo_id, **load_kwargs,
            )
            if hasattr(_video_pipeline, 'vae') and hasattr(_video_pipeline.vae, 'enable_tiling'):
                _video_pipeline.vae.enable_tiling()
            if torch.cuda.is_available():
                _video_pipeline.enable_model_cpu_offload()

        elif pipeline_type == "wan":
            # Wan2.x — WanPipeline
            from diffusers import WanPipeline
            load_kwargs = dict(torch_dtype=dtype, token=hf_token)
            if quant_config:
                load_kwargs["quantization_config"] = quant_config
            _video_pipeline = WanPipeline.from_pretrained(
                repo_id, **load_kwargs,
            )
            if hasattr(_video_pipeline, 'vae') and hasattr(_video_pipeline.vae, 'enable_tiling'):
                _video_pipeline.vae.enable_tiling()
            if torch.cuda.is_available():
                _video_pipeline.enable_model_cpu_offload()

        else:
            # Generic DiffusionPipeline (CogVideoX, HunyuanVideo, etc.)
            from diffusers import DiffusionPipeline, DPMSolverMultistepScheduler
            load_kwargs = dict(torch_dtype=dtype, token=hf_token)
            if quant_config:
                load_kwargs["quantization_config"] = quant_config
            try:
                _video_pipeline = DiffusionPipeline.from_pretrained(
                    repo_id, variant="fp16",
                    local_files_only=_should_use_local_files(base_model if "base_model" in locals() and "stabilityai" in base_model else repo_id),
                    **load_kwargs,
                )
            except Exception:
                _video_pipeline = DiffusionPipeline.from_pretrained(
                    repo_id, variant=None,
                    local_files_only=_should_use_local_files(base_model if "base_model" in locals() and "stabilityai" in base_model else repo_id),
                    **load_kwargs,
                )
            if "damo" in repo_id:
                _video_pipeline.scheduler = DPMSolverMultistepScheduler.from_config(
                    _video_pipeline.scheduler.config
                )
            if hasattr(_video_pipeline, 'vae') and hasattr(_video_pipeline.vae, 'enable_tiling'):
                _video_pipeline.vae.enable_tiling()
            if torch.cuda.is_available():
                _video_pipeline.enable_model_cpu_offload()

        _current_video_model = repo_id
        _hf_download_state["active"] = False
        return _video_pipeline

    except Exception as e:
        _hf_download_state["active"] = False
        logger.error("Failed to load video pipeline [%s]: %s", pipeline_type, e)
        raise RuntimeError(f"Video pipeline failed to load: {e}")

def _release_video_pipeline():
    """Release the video pipeline and free VRAM."""
    global _video_pipeline, _current_video_model
    if _video_pipeline is not None:
        import gc, torch
        del _video_pipeline
        _video_pipeline = None
        _current_video_model = None
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

def _get_i2v_pipeline(repo_id: str, pipeline_type: str = "auto"):
    """Lazy-load the Image-to-Video pipeline.

    Args:
        repo_id: HuggingFace repo ID for the I2V model.
        pipeline_type: 'svd' for StableVideoDiffusionPipeline,
                       'wan' for WanImageToVideoPipeline,
                       otherwise CogVideoXImageToVideoPipeline.
    """
    global _i2v_pipeline, _current_i2v_model
    if _i2v_pipeline is not None and _current_i2v_model == repo_id:
        return _i2v_pipeline

    _release_i2v_pipeline()

    import torch

    try:
        logger.info("Loading image-to-video pipeline [%s] for %s", pipeline_type, repo_id)

        global _hf_download_state
        _hf_download_state = {"active": True, "progress": 0.0, "repo": repo_id}
        hf_token = _get_hf_token()

        if pipeline_type == "svd":
            # Stable Video Diffusion — lightweight I2V (~6GB)
            from diffusers import StableVideoDiffusionPipeline

            dtype = torch.float16 if torch.cuda.is_available() else torch.float32
            try:
                _i2v_pipeline = StableVideoDiffusionPipeline.from_pretrained(
                    repo_id, torch_dtype=dtype, variant="fp16", token=hf_token,
                )
            except Exception as ev:
                if "variant" in str(ev).lower() or "fp16" in str(ev).lower():
                    logger.warning("SVD: retrying without fp16 variant: %s", ev)
                    _i2v_pipeline = StableVideoDiffusionPipeline.from_pretrained(
                        repo_id, torch_dtype=dtype, variant=None, token=hf_token,
                    )
                else:
                    raise
            if torch.cuda.is_available():
                _i2v_pipeline.enable_model_cpu_offload()

        elif pipeline_type == "wan":
            from diffusers import WanImageToVideoPipeline, AutoencoderKLWan
            from transformers import CLIPVisionModel

            dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32

            # Load sub-components with float32 for quality
            image_encoder = CLIPVisionModel.from_pretrained(
                repo_id, subfolder="image_encoder",
                torch_dtype=torch.float32, token=hf_token,
            )
            vae = AutoencoderKLWan.from_pretrained(
                repo_id, subfolder="vae",
                torch_dtype=torch.float32, token=hf_token,
            )

            _i2v_pipeline = WanImageToVideoPipeline.from_pretrained(
                repo_id,
                vae=vae,
                image_encoder=image_encoder,
                torch_dtype=dtype,
                token=hf_token,
            )
            if torch.cuda.is_available():
                _i2v_pipeline.enable_model_cpu_offload()

        else:
            # CogVideoX family
            from diffusers import CogVideoXImageToVideoPipeline

            dtype = torch.float16 if torch.cuda.is_available() else torch.float32
            variant = "fp16"

            try:
                _i2v_pipeline = CogVideoXImageToVideoPipeline.from_pretrained(
                    repo_id,
                    torch_dtype=dtype,
                    variant=variant,
                    token=hf_token,
                )
            except Exception as ev:
                if "variant" in str(ev).lower() or "fp16" in str(ev).lower() or "safetensors" in str(ev).lower():
                    logger.warning("Failed with variant %s, retrying without: %s", variant, ev)
                    _i2v_pipeline = CogVideoXImageToVideoPipeline.from_pretrained(
                        repo_id, torch_dtype=dtype, variant=None, token=hf_token,
                    )
                else:
                    raise

            if torch.cuda.is_available():
                _i2v_pipeline.enable_model_cpu_offload()

        _current_i2v_model = repo_id
        _hf_download_state["active"] = False
        return _i2v_pipeline
    except Exception as e:
        _hf_download_state["active"] = False
        logger.error("Failed to load i2v pipeline: %s", e)
        raise RuntimeError(f"I2V pipeline failed to load: {e}")

def _release_i2v_pipeline():
    """Release the i2v pipeline and free VRAM."""
    global _i2v_pipeline, _current_i2v_model
    if _i2v_pipeline is not None:
        import gc, torch
        del _i2v_pipeline
        _i2v_pipeline = None
        _current_i2v_model = None
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

# ---------------------------------------------------------------------------
# SVG generation via LLM (Ollama)
# ---------------------------------------------------------------------------
_SVG_KEYWORDS = {
    # English
    "icon", "logo", "badge", "button", "arrow", "shape", "geometric",
    "symbol", "flat", "vector", "svg", "simple", "minimalist", "outline",
    "line art", "lineart", "wireframe", "diagram", "chart", "infographic",
    "pattern", "border", "divider", "separator", "banner", "emblem",
    "shield", "star", "circle", "square", "triangle", "hexagon",
    "checkmark", "cross", "plus", "minus", "heart", "flag",
}

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

}

# Keywords that strongly suggest raster (photorealistic) generation
_RASTER_KEYWORDS = {
    "photo", "photorealistic", "realistic", "photograph",
    "painting", "watercolor", "oil",
    "3d", "render", "texture", "landscape", "portrait", "face", "person",
    "animal", "nature", "scenery", "cinematic", "detailed", "complex",
    "intricate", "hdr", "4k", "8k",
}


def _classify_prompt(prompt: str) -> str:
    """Classify whether a prompt is better suited for SVG or raster.

    Returns 'svg' or 'raster'.
    """
    words = set(re.split(r"[\s,;:!?./()\[\]]+", prompt.lower()))
    # Also check bigrams (e.g. "line art", "flat design")
    prompt_lower = prompt.lower()

    svg_score = sum(1 for kw in _SVG_KEYWORDS if kw in prompt_lower)
    raster_score = sum(1 for kw in _RASTER_KEYWORDS if kw in prompt_lower)

    logger.info("Prompt classification: svg=%d, raster=%d", svg_score, raster_score)

    if svg_score > raster_score:
        return "svg"
    if raster_score > 0:
        return "raster"
    # Default: raster for ambiguous prompts
    return "raster"


async def _generate_svg(prompt: str) -> str:
    """Generate SVG markup using the local LLM (Ollama).

    Returns clean SVG string.
    """
    from app.llm_provider import get_llm_provider
    from config import LLM_PROVIDER

    svg_system = (
        "You are an expert SVG artist. Generate ONLY valid SVG code. "
        "Rules:\n"
        "- Output ONLY the <svg>...</svg> tag, absolutely NO other text, no markdown fences, no explanation.\n"
        "- Use viewBox=\"0 0 200 200\" unless the user specifies dimensions.\n"
        "- Use modern, clean, flat design with vibrant colors.\n"
        "- Use gradients (linearGradient/radialGradient) for visual depth.\n"
        "- Keep it simple, elegant, and professional.\n"
        "- Use rounded shapes (rx, ry) for a modern feel.\n"
        "- Include xmlns=\"http://www.w3.org/2000/svg\" in the svg tag.\n"
    )

    llm = get_llm_provider(LLM_PROVIDER)
    messages = [
        {"role": "system", "content": svg_system},
        {"role": "user", "content": f"Generate an SVG image for: {prompt}"}
    ]
    
    raw = ""
    try:
        async for token in llm.chat_stream(messages):
            raw += token
    except Exception as e:
        logger.error("Failed to generate SVG with LLM: %s", e)
        raise RuntimeError(f"SVG generation failed: {e}")

    # Extract SVG from response (LLM might wrap it in markdown fences)
    svg_match = re.search(r"(<svg[\s\S]*?</svg>)", raw, re.IGNORECASE)
    if svg_match:
        svg_content = svg_match.group(1).strip()
    else:
        raise RuntimeError(f"LLM did not produce valid SVG. Raw output: {raw[:500]}")

    # Basic validation
    if "<svg" not in svg_content or "</svg>" not in svg_content:
        raise RuntimeError("Generated SVG is malformed")

    # Ensure xmlns is present
    if 'xmlns=' not in svg_content:
        svg_content = svg_content.replace('<svg', '<svg xmlns="http://www.w3.org/2000/svg"', 1)

    logger.info("SVG generated: %d bytes", len(svg_content))
    return svg_content


def _detect_non_english(text: str) -> bool:
    """Heuristic to detect if text is likely NOT English.
    
    Returns True if the text appears to be in a non-English language.
    """
    # Check for non-ASCII characters (accented letters common in French, German, etc.)
    non_ascii_count = sum(1 for c in text if ord(c) > 127)
    if non_ascii_count > len(text) * 0.05 and non_ascii_count > 2:
        return True
    
    # Common French words/patterns have been removed to comply with English-only codebase rules.
    # We now rely primarily on the non-ASCII check above for detecting non-English languages.
    return False


async def _translate_prompt(prompt: str) -> str:
    """Translate a prompt to English using the local LLM (Ollama).
    
    This is a lightweight translation-only function (no enrichment).
    Only called when non-English text is detected.
    """
    from app.llm_provider import get_llm_provider
    from config import LLM_PROVIDER

    system_prompt = (
        "You are a translator. Translate the user's text to English. "
        "Output ONLY the English translation, nothing else. "
        "No explanation, no intro, no quotes, no markdown. "
        "Keep the meaning and intent exactly the same. "
        "If the text is already in English, output it unchanged."
    )

    llm = get_llm_provider(LLM_PROVIDER)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt}
    ]

    try:
        translated = ""
        async for token in llm.chat_stream(messages):
            translated += token
        translated = translated.strip()
            
        # Remove <think>...</think> block if present
        translated = _clean_llm_output(translated)
            
        if translated:
            logger.info("Prompt translated: '%s' -> '%s'", prompt, translated)
            return translated
    except Exception as e:
        logger.warning("Failed to translate prompt: %s", e)

    return prompt


def _clean_llm_output(text: str) -> str:
    """Clean common LLM artifacts from generated prompts.

    Handles reasoning-model leakage (DeepSeek, QwQ, etc.) where the model
    emits ``<think>…</think>`` blocks — sometimes without the opening tag,
    sometimes repeated dozens of times.
    """
    # 1. Strip full <think>…</think> blocks (greedy to catch nested repeats)
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    # 2. If an unclosed <think> remains, drop everything from it onward
    text = re.sub(r"<think>.*$", "", text, flags=re.DOTALL).strip()
    # 3. If only </think> tags remain (model started thinking implicitly),
    #    keep only the content AFTER the *last* </think>
    if "</think>" in text:
        text = text.rsplit("</think>", 1)[-1].strip()
    # 4. Remove any stray think tags that survived
    text = re.sub(r"</?think>", "", text).strip()

    # Remove conversational prefixes
    text = re.sub(
        r"^(here is .*?:|here's .*?:|enhanced prompt:|prompt:|\*\*prompt\*\*.*?:"
        r"|sure.*?:|of course.*?:|certainly.*?:|the enhanced.*?:|translated.*?:|result.*?:)\s*",
        "", text, flags=re.IGNORECASE
    ).strip()
    # Remove self-commentary (e.g. "43 words. English only. No intro/outro. …")
    text = re.sub(
        r"\b\d+\s*words\..*$", "", text, flags=re.IGNORECASE
    ).strip()
    # Remove enclosing quotes if any
    text = re.sub(r'^["\'](.*)["\']$', r'\1', text).strip()
    # Remove markdown bold/italic wrappers
    text = re.sub(r'^\*\*(.*?)\*\*$', r'\1', text).strip()
    text = re.sub(r'^\*(.*?)\*$', r'\1', text).strip()
    # Remove numbered list prefixes like "1. " or "- "
    text = re.sub(r'^[\d]+\.\s+', '', text).strip()
    text = re.sub(r'^[-•]\s+', '', text).strip()
    # Collapse multiple spaces/newlines
    text = re.sub(r'\s+', ' ', text).strip()

    # --- Hard cap: keep at most 80 words ---
    words = text.split()
    if len(words) > 80:
        text = " ".join(words[:80])

    return text


async def _enhance_prompt_with_llm(prompt: str, style: str = "none", model_repo: str = "") -> str:
    """Enhance a short image prompt using the local LLM (Ollama).

    Args:
        prompt: The user's raw prompt.
        style: The selected image style (e.g. 'none', 'photorealistic', 'anime').
        model_repo: The target diffusion model repo for context-aware enrichment.
    """
    from app.llm_provider import get_llm_provider
    from config import LLM_PROVIDER

    # --- Build model-aware instructions ---
    is_flux = "flux" in model_repo.lower() if model_repo else (style in ("none", "flux_schnell", "flux2_klein"))
    is_photo = style in ("photorealistic", "realvis") or "juggernaut" in model_repo.lower() or "realvis" in model_repo.lower()
    is_zimage = style in ("z_image_turbo", "z_image") or "z-image" in model_repo.lower()
    if is_zimage:
        model_guidance = (
            "TARGET MODEL: Z-Image (S3-DiT flow-matching model, 6B params). "
            "Z-Image excels at photorealism and text rendering. "
            "Use NATURAL LANGUAGE descriptions (30-60 words). "
            "Do NOT use quality tags — describe the scene, lighting, mood, composition, camera. "
            "If text should appear in the image, include it in quotes within the prompt. "
            "Focus on: subject, atmosphere, cinematic details, photo-like realism."
        )
    elif is_flux:
        model_guidance = (
            "TARGET MODEL: FLUX (flow-matching, distilled). "
            "FLUX works best with NATURAL LANGUAGE descriptions, not keyword lists. "
            "Write a clear, descriptive sentence (30-50 words). "
            "Do NOT add quality tags like 'masterpiece, best quality, 8k' — FLUX ignores them. "
            "Focus on: subject, scene, lighting, mood, composition, camera angle."
        )
    elif is_photo:
        model_guidance = (
            "TARGET MODEL: Photorealistic SDXL. "
            "Use dense, comma-separated keywords for photorealism: "
            "'RAW photo, 8k uhd, dslr, soft lighting, high quality'. "
            "Describe textures, materials, depth of field, lens type. "
            "Keep under 60 words."
        )
    else:
        model_guidance = (
            "TARGET MODEL: SDXL. "
            "Use comma-separated keywords with quality tags: "
            "'masterpiece, best quality, ultra-detailed'. "
            "Add visual details: lighting, composition, textures, colors, atmosphere. "
            "Keep under 60 words."
        )

    system_prompt = (
        "You are an expert prompt engineer for AI image generation. "
        "Your task is to take the user's input, TRANSLATE it to English (if not already), "
        "then ENRICH it for the target model.\n\n"
        f"{model_guidance}\n\n"
        "CRITICAL RULES:\n"
        "1. Output MUST be entirely in English.\n"
        "2. PRESERVE the core subject and intent — do NOT add subjects, characters, or elements the user did not ask for.\n"
        "3. Do NOT invent new subjects or dramatically change the scene.\n"
        "4. Output ONLY the final prompt. No intro, no explanation, no quotes, no markdown."
    )

    llm = get_llm_provider(LLM_PROVIDER)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt}
    ]

    try:
        raw_response = ""
        async for token in llm.chat_stream(messages):
            raw_response += token
        
        enhanced = _clean_llm_output(raw_response)
        if enhanced:
            logger.info("Prompt enhanced [%s]: '%s' -> '%s'", style, prompt, enhanced)
            return enhanced
    except Exception as e:
        logger.warning("Failed to enhance prompt with LLM: %s", e)

    return prompt


async def _enhance_video_prompt_with_llm(prompt: str, video_model: str = "cogvideox") -> str:
    """Enhance a video prompt using the local LLM (Ollama).
    
    Video prompts need different treatment than image prompts:
    - Describe motion, camera movement, temporal progression
    - Avoid static image keywords like 'masterpiece, best quality'
    - Be more descriptive about scene and action
    """
    from app.llm_provider import get_llm_provider
    from config import LLM_PROVIDER

    # --- Model-specific guidance ---
    model_hints = {
        "animatediff": "AnimateDiff Lightning: short clips, simple motion. Keep prompt under 40 words.",
        "wan_1_3b": "Wan 2.1 1.3B: lightweight model. Use clear, simple descriptions. Under 50 words.",
        "cogvideox_2b": "CogVideoX 2B: describe scene + single clear motion. Under 60 words.",
        "cogvideox": "CogVideoX 5B: can handle complex scenes. Describe motion + camera. Under 70 words.",
        "ltx_video": "LTX-Video: cinematic model. Use film language (tracking shot, dolly, rack focus). Under 70 words.",
        "ltx_23": "LTX 2.3: high-end cinematic with audio. Describe soundscape too. Under 80 words.",
        "hunyuanvideo": "HunyuanVideo: good at human motion. Describe body language, gestures. Under 70 words.",
        "wan22": "Wan 2.2 MoE 27B: premium model, can handle complex multi-subject scenes. Under 80 words.",
    }
    model_hint = model_hints.get(video_model, "Generic video model. Under 70 words.")

    system_prompt = (
        f"You are an expert prompt engineer for AI video generation.\n"
        f"TARGET MODEL: {model_hint}\n\n"
        "Your task is to take the user's input, TRANSLATE it to English (if not already), "
        "then ENRICH it for video generation.\n\n"
        "RULES:\n"
        "1. Output MUST be entirely in English.\n"
        "2. PRESERVE the core subject and intent — do NOT add elements the user didn't ask for.\n"
        "3. Describe MOTION: what moves, direction, speed, camera movement.\n"
        "4. Describe SCENE: environment, lighting, time of day, atmosphere.\n"
        "5. Use temporal language: 'slowly panning', 'gradually revealing', 'camera tracks'.\n"
        "6. Do NOT use static image keywords like 'masterpiece', 'best quality', '8k'.\n"
        "7. Output ONLY the final prompt. No intro, no explanation, no quotes, no markdown."
    )

    llm = get_llm_provider(LLM_PROVIDER)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt}
    ]

    try:
        raw_response = ""
        async for token in llm.chat_stream(messages):
            raw_response += token
            
        enhanced = _clean_llm_output(raw_response)
        if enhanced:
            logger.info("Video prompt enhanced [%s]: '%s' -> '%s'", video_model, prompt, enhanced)
            return enhanced
    except Exception as e:
        logger.warning("Failed to enhance video prompt with LLM: %s", e)

    return prompt

# ---------------------------------------------------------------------------
# HuggingFace Inference API fallback (no GPU needed)
# ---------------------------------------------------------------------------
async def _generate_via_hf_api(prompt: str, negative_prompt: str = "", repo_id: str = "stabilityai/sdxl-turbo", width: int = 1024, height: int = 1024) -> bytes:
    """Call HuggingFace Inference API for image generation (free tier).

    Uses the specified repo_id via the serverless inference endpoint.
    Returns raw PNG bytes.
    """
    import httpx

    hf_token = _get_hf_token()

    headers = {}
    if hf_token:
        headers["Authorization"] = f"Bearer {hf_token}"
    else:
        logger.warning("HF API: No HUGGINGFACE_API_KEY provided. Inference may fail with 401 Unauthorized.")

    models = [repo_id]
    if repo_id != "stabilityai/sdxl-turbo":
        models.append("stabilityai/sdxl-turbo") # Fallback

    payload = {"inputs": prompt}
    params = {}
    if negative_prompt:
        params["negative_prompt"] = negative_prompt
    if width and height:
        params["width"] = width
        params["height"] = height
    if params:
        payload["parameters"] = params

    last_error = None
    async with httpx.AsyncClient(timeout=60.0) as client:
        for model in models:
            url = f"https://router.huggingface.co/hf-inference/models/{model}"
            try:
                logger.info("HF API: trying %s ...", model)
                resp = await client.post(url, json=payload, headers=headers)

                if resp.status_code == 200:
                    content_type = resp.headers.get("content-type", "")
                    if "image" in content_type:
                        logger.info("HF API: success with %s (%d bytes)", model, len(resp.content))
                        return resp.content

                # Model loading (503) — wait and retry once
                if resp.status_code == 503:
                    import asyncio
                    est = resp.json().get("estimated_time", 20)
                    logger.info("HF API: %s loading, waiting %.0fs...", model, est)
                    await asyncio.sleep(min(est, 30))
                    resp = await client.post(url, json=payload, headers=headers)
                    if resp.status_code == 200 and "image" in resp.headers.get("content-type", ""):
                        return resp.content

                if resp.status_code == 401:
                    last_error = f"{model}: HTTP 401 Unauthorized - A valid Hugging Face Token (HUGGINGFACE_API_KEY) is required."
                else:
                    err_text = resp.text[:200].strip()
                    last_error = f"{model}: HTTP {resp.status_code} - {err_text}"
                logger.warning("HF API: %s", last_error)
            except Exception as e:
                last_error = f"{model}: {e}"
                logger.warning("HF API error: %s", last_error)

    if last_error and "401 Unauthorized" in last_error:
        raise RuntimeError(f"Hugging Face API requires authentication. Please set HUGGINGFACE_API_KEY in your .env file.")
    raise RuntimeError(f"All HF API models failed. Last error: {last_error}")


# ---------------------------------------------------------------------------
# Unified generation function
# ---------------------------------------------------------------------------
async def generate_image_core(
    prompt: str,
    negative_prompt: str = "blurry, low quality, distorted",
    width: int = 1024,
    height: int = 1024,
    steps: int = 4,
    guidance: float = 0.5,
    format: str = "auto",
    style: str = "none",
    enhance_prompt: bool = False,
    backend: str = "local",
    reference_image: str = None,
    strength: float = 0.5,
    stream_queue = None,
) -> dict:
    """Generate an image.

    Strategy order:
    - backend='local': SVG (LLM) or Local GPU only (no API fallback)
    - backend='api': SVG (LLM) or HuggingFace API only

    Args:
        format: 'auto' (classify prompt), 'svg' (force SVG), 'png' (force raster)
        backend: 'local' (default, uses GPU) or 'api' (uses HuggingFace)
        reference_image: filename of the image to use as starting point (Img2Img)
        strength: (0.1-1.0) how much to change the reference image
    """
    # --- Auto-translate non-English prompts (even without enhance_prompt) ---
    if not enhance_prompt and _detect_non_english(prompt):
        logger.info("Non-English prompt detected, auto-translating: '%s'", prompt)
        prompt = await _translate_prompt(prompt)

    if enhance_prompt:
        model_info = _IMAGE_STYLE_MODELS.get(style, _IMAGE_STYLE_MODELS["none"])
        prompt = await _enhance_prompt_with_llm(prompt, style=style, model_repo=model_info["repo"])
    elif _detect_non_english(prompt):
        # Safety net: if still non-English after translation attempt, try once more
        prompt = await _translate_prompt(prompt)

    # Preserve the user's core prompt before adding style keywords
    user_prompt = prompt

    if style in _IMAGE_STYLES:
        style_data = _IMAGE_STYLES[style]
        # Smart truncation: ensure user prompt is preserved, trim style keywords if needed
        user_words = user_prompt.split()
        style_words = style_data['positive'].split()
        max_style_words = max(10, 75 - len(user_words))  # Reserve space for user prompt
        if len(style_words) > max_style_words:
            style_words = style_words[:max_style_words]
            logger.info("Trimmed style keywords to %d words to preserve user prompt", max_style_words)
        prompt = f"{user_prompt}, {' '.join(style_words)}"
        negative_prompt = f"{negative_prompt}, {style_data['negative']}" if negative_prompt else style_data['negative']

    # Final safety truncation (should rarely trigger now)
    words = prompt.split()
    if len(words) > 77:
        logger.info("Final truncation: prompt from %d to 77 words", len(words))
        prompt = " ".join(words[:77])
    
    n_words = negative_prompt.split()
    if len(n_words) > 75:
        negative_prompt = " ".join(n_words[:75])

    # --- Strategy 0: SVG generation ---
    use_svg = (
        format == "svg"
        or (format == "auto" and _classify_prompt(prompt) == "svg")
    )

    if use_svg and not reference_image:
        try:
            svg_content = await _generate_svg(prompt)
            filename = f"gen_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.svg"
            filepath = os.path.join(IMAGES_DIR, filename)

            with open(filepath, "w", encoding="utf-8") as f:
                f.write(svg_content)
            with open(filepath + ".txt", "w", encoding="utf-8") as f:
                f.write(f"[{style}] {prompt}")

            return {
                "status": "ok",
                "method": "svg_llm",
                "format": "svg",
                "filename": filename,
                "path": filepath,
                "svg": svg_content,
                "prompt": prompt,
            }
        except Exception as e:
            logger.warning("SVG generation failed: %s — falling back to raster", e)

    filename = f"gen_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.png"
    filepath = os.path.join(IMAGES_DIR, filename)

    # --- Local GPU / CPU ---
    if backend == "local":
        try:
            model_info = _IMAGE_STYLE_MODELS.get(style, _IMAGE_STYLE_MODELS["none"])
            repo_id = model_info["repo"]
            is_lora = model_info["is_lora"]

            if steps <= 4 and guidance <= 1.0:
                if "turbo" not in repo_id.lower() and "schnell" not in repo_id.lower() and "lcm" not in repo_id.lower() and "klein" not in repo_id.lower():
                    steps = 12
                    guidance = 5.0
                    logger.info(f"Adjusted steps={steps} and guidance={guidance} for non-Turbo model {repo_id}")

            # FLUX.1-schnell REQUIRES guidance_scale=0.0 (distilled model, no CFG)
            if "flux" in repo_id.lower() and "schnell" in repo_id.lower():
                guidance = 0.0
                steps = min(steps, 4)
                logger.info(f"FLUX.1-schnell: forcing guidance=0.0, steps={steps}")

            # FLUX.2 Klein: fast distilled model, guidance=0.0, 4 steps max
            if "flux.2" in repo_id.lower() and "klein" in repo_id.lower():
                guidance = 0.0
                steps = 4
                logger.info(f"FLUX.2 Klein: forcing guidance=0.0, steps={steps}")

            # --- Unsloth model-specific parameter overrides ---
            _pipe_type = model_info.get("pipeline", "")
            _extra_kwargs = {}

            # Z-Image-Turbo: distilled, guidance=0.0, 9 steps (8 DiT forwards)
            if _pipe_type == "zimage" and "turbo" in repo_id.lower():
                guidance = 0.0
                if steps <= 4:
                    steps = 9
                logger.info(f"Z-Image-Turbo: forcing guidance=0.0, steps={steps}")

            # Z-Image (base): non-distilled, guidance=3.0-5.0, 28-50 steps, supports negative prompt
            elif _pipe_type == "zimage":
                if steps <= 4:
                    steps = 50
                if guidance <= 1.0:
                    guidance = 4.0
                _extra_kwargs["cfg_normalization"] = False
                logger.info(f"Z-Image: guidance={guidance}, steps={steps}")



            def step_callback(p, step_index, timestep, callback_kwargs):
                global _generation_progress
                pct = min(100.0, ((step_index + 1) / max(steps, 1)) * 100)
                _generation_progress = {
                    "active": True, "type": "image",
                    "step": step_index + 1, "total_steps": steps,
                    "progress": pct, "stage": "generating",
                }
                if stream_queue is not None:
                    latents = callback_kwargs.get("latents")
                    if latents is not None:
                        try:
                            import torch
                            with torch.no_grad():
                                vae_device = next(p.vae.parameters()).device
                                dec_latents = latents.to(vae_device, dtype=p.vae.dtype)
                                scaling = getattr(p.vae.config, "scaling_factor", None)
                                force_up = getattr(p.vae.config, "force_upcast", False)
                                needs_upcast = p.vae.dtype == torch.float16 and force_up
                                if needs_upcast and hasattr(p, "upcast_vae") and hasattr(p.vae, "post_quant_conv"):
                                    p.upcast_vae()
                                    dec_latents = dec_latents.to(next(iter(p.vae.post_quant_conv.parameters())).dtype)
                                
                                if scaling:
                                    dec_latents = dec_latents / scaling
                                image = p.vae.decode(dec_latents, return_dict=False)[0]
                                image = p.image_processor.postprocess(image, output_type="pil")[0]
                                
                                import io, base64
                                buf = io.BytesIO()
                                image.thumbnail((512, 512))
                                image.save(buf, format="JPEG", quality=60)
                                b64 = base64.b64encode(buf.getvalue()).decode()
                                stream_queue.put({"status": "generating", "step": step_index, "progress": pct, "base64": b64})
                        except Exception as e:
                            logger.warning(f"Stream preview error: {e}")
                    else:
                        stream_queue.put({"status": "generating", "step": step_index, "progress": pct})
                return callback_kwargs

            import asyncio
            # Distilled / flow-matching models don't support negative_prompt
            _no_neg = "flux" in repo_id.lower()  # FLUX.1, FLUX.2 family
            # Z-Image-Turbo is distilled — no negative prompt
            if _pipe_type == "zimage" and "turbo" in repo_id.lower():
                _no_neg = True

            if reference_image:
                    # Standard Img2Img
                    from PIL import Image
                    ref_path = os.path.join(IMAGES_DIR, os.path.basename(reference_image))
                    if not os.path.exists(ref_path):
                        raise RuntimeError(f"Reference image not found: {reference_image}")
                    init_img = Image.open(ref_path).convert("RGB")
                    init_img = init_img.resize((width, height), Image.LANCZOS)
                    
                    pipe = await asyncio.to_thread(_get_i2i_pipeline, repo_id, is_lora)
                    pipe_kwargs = dict(
                        prompt=prompt,
                        image=init_img,
                        strength=strength,
                        num_inference_steps=steps,
                        guidance_scale=guidance,
                        callback_on_step_end=step_callback,
                        **_extra_kwargs,
                    )
                    if not _no_neg:
                        pipe_kwargs["negative_prompt"] = negative_prompt
                    result = await asyncio.to_thread(pipe, **pipe_kwargs)
                    image = result.images[0]
            else:
                pipe = await asyncio.to_thread(_get_pipeline, repo_id, is_lora)
                pipe_kwargs = dict(
                    prompt=prompt,
                    width=width,
                    height=height,
                    num_inference_steps=steps,
                    guidance_scale=guidance,
                    callback_on_step_end=step_callback,
                    **_extra_kwargs,
                )
                if not _no_neg:
                    pipe_kwargs["negative_prompt"] = negative_prompt
                result = await asyncio.to_thread(pipe, **pipe_kwargs)
                image = result.images[0]

            if format == "transparent_png":
                try:
                    image = _remove_bg_enhanced(image)
                except ImportError:
                    logger.warning("rembg not installed, cannot remove background.")

            image.save(filepath)
            with open(filepath + ".txt", "w", encoding="utf-8") as f:
                f.write(f"[{style}] {prompt}")

            with open(filepath, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()

            _generation_progress["active"] = False
            return {
                "status": "ok",
                "method": "local_gpu",
                "format": "transparent_png" if format == "transparent_png" else "png",
                "filename": filename,
                "path": filepath,
                "base64": b64,
                "prompt": prompt,
            }
        except Exception as e:
            _generation_progress["active"] = False
            _release_pipeline()
            raise RuntimeError(f"Local GPU generation failed: {e}")

    # --- Remote API (HuggingFace) ---
    try:
        model_info = _IMAGE_STYLE_MODELS.get(style, _IMAGE_STYLE_MODELS["none"])
        repo_id = model_info["repo"]
        logger.info(f"Using HuggingFace API for image generation with {repo_id}")
        img_bytes = await _generate_via_hf_api(prompt, negative_prompt, repo_id=repo_id, width=width, height=height)

        if format == "transparent_png":
            try:
                img_bytes = _remove_bg_enhanced(img_bytes)
            except ImportError:
                logger.warning("rembg not installed, cannot remove background.")

        with open(filepath, "wb") as f:
            f.write(img_bytes)
        with open(filepath + ".txt", "w", encoding="utf-8") as f:
            f.write(f"[{style}] {prompt}")

        b64 = base64.b64encode(img_bytes).decode()
        return {
            "status": "ok",
            "method": "hf_api",
            "format": "transparent_png" if format == "transparent_png" else "png",
            "filename": filename,
            "path": filepath,
            "base64": b64,
            "prompt": prompt,
        }
    except Exception as e:
        raise RuntimeError(f"HuggingFace API generation failed: {e}")



async def generate_animation_core(
    prompt: str,
    negative_prompt: str = "blurry, low quality, distorted",
    format: str = "gif",
    duration: float = 2.0,
    fps: int = 8,
    width: int = 704,
    height: int = 480,
    video_model: str = "cogvideox",
    enhance_prompt: bool = False,
    backend: str = "local",
    reference_image: str = None,
) -> dict:
    """Generate a real video animation (gif or mp4) from a text prompt using a diffusion model.

    Args:
        duration: Duration in seconds (converted to num_frames via fps).
        fps: Frames per second (default 8).
        width: Video width in pixels (should be divisible by 32).
        height: Video height in pixels (should be divisible by 32).
        backend: 'local' (default, uses GPU pipeline) or 'api' (reserved for future use).
    """
    # --- ALWAYS translate non-English prompts for video models ---
    if _detect_non_english(prompt):
        logger.info("Non-English video prompt detected, translating: '%s'", prompt)
        prompt = await _translate_prompt(prompt)

    if enhance_prompt:
        # Use dedicated video enrichment (not image-oriented enrichment)
        prompt = await _enhance_video_prompt_with_llm(prompt, video_model=video_model)
    elif _detect_non_english(prompt):
        # Safety net: if still non-English after translation, try once more
        prompt = await _translate_prompt(prompt)

    # Get model config with defaults
    model_cfg = _VIDEO_MODELS.get(video_model, _VIDEO_MODELS["cogvideox"])
    repo_id = model_cfg["repo"]
    model_fps = model_cfg.get("fps", fps)
    max_frames = model_cfg.get("max_frames", 64)
    steps = model_cfg.get("steps", 15)
    guidance = model_cfg.get("guidance", 6.0)

    # Calculate num_frames respecting model limits
    num_frames = max(4, min(max_frames, int(duration * model_fps)))
    # Some models require frames divisible by 8+1
    pipeline_type = model_cfg.get("pipeline", "auto")
    if pipeline_type == "ltx":
        # LTX requires (frames - 1) % 8 == 0
        num_frames = ((num_frames - 1) // 8) * 8 + 1
        num_frames = max(9, num_frames)
    elif pipeline_type == "wan":
        # Wan prefers odd frame counts
        if num_frames % 2 == 0:
            num_frames += 1

    if backend == "api":
        raise RuntimeError("Remote API video generation is not yet supported. Please use local mode.")

    # SVD is I2V-only — require a reference image
    if pipeline_type == "svd" and not reference_image:
        raise RuntimeError("SVD is an Image-to-Video only model. Please provide a reference image or select a different model.")

    try:
        import asyncio
        
        from PIL import Image
        init_img = None

        if reference_image:
            # Check if model supports I2V — needs explicit i2v_repo
            i2v_repo = model_cfg.get("i2v_repo")
            if not i2v_repo:
                # Model does not have an I2V variant, fall back to text-to-video
                logger.warning("Model '%s' does not support I2V (no i2v_repo) — ignoring reference image", video_model)
                reference_image = None
                pipe = await asyncio.to_thread(_get_video_pipeline, repo_id, video_model)
                logger.info("Starting text-to-video [%s] for prompt: '%s' (%d frames, %.1fs)",
                            video_model, prompt, num_frames, duration)
            else:
                ref_path = os.path.join(IMAGES_DIR, os.path.basename(reference_image))
                if not os.path.exists(ref_path):
                    raise RuntimeError(f"Reference image not found: {reference_image}")
                init_img = Image.open(ref_path).convert("RGB")

                pipe = await asyncio.to_thread(_get_i2v_pipeline, i2v_repo, pipeline_type)
                logger.info("Starting image-to-video [%s] for prompt: '%s' (%d frames, %.1fs)",
                            video_model, prompt, num_frames, duration)
        else:
            pipe = await asyncio.to_thread(_get_video_pipeline, repo_id, video_model)
            logger.info("Starting text-to-video [%s] for prompt: '%s' (%d frames, %.1fs)",
                        video_model, prompt, num_frames, duration)

        # Enhance negative prompt to suppress watermarks
        anti_watermark = "watermark, shutterstock, text, logo, copyright, noisy, blurry, worst quality, low quality"
        if negative_prompt:
            if "watermark" not in negative_prompt.lower() and "shutterstock" not in negative_prompt.lower():
                negative_prompt = f"{negative_prompt}, {anti_watermark}"
        else:
            negative_prompt = anti_watermark

        # Video step callback for progress tracking
        def video_step_callback(p, step_index, timestep, callback_kwargs):
            global _generation_progress
            pct = min(100.0, ((step_index + 1) / max(steps, 1)) * 100)
            _generation_progress = {
                "active": True, "type": "video",
                "step": step_index + 1, "total_steps": steps,
                "progress": pct, "stage": "generating",
            }
            return callback_kwargs

        # Build model-specific inference kwargs
        gen_kwargs = {
            "prompt": prompt,
            "num_inference_steps": steps,
            "callback_on_step_end": video_step_callback,
        }

        # Ensure dimensions are divisible by 32
        width = (width // 32) * 32
        height = (height // 32) * 32

        global _generation_progress
        _generation_progress = {
            "active": True, "type": "video",
            "step": 0, "total_steps": steps,
            "progress": 0.0, "stage": "generating",
        }

        # AnimateDiff Lightning uses guidance_scale, not negative_prompt
        if pipeline_type == "svd":
            # SVD is image-only (no prompt) — will be set below with init_img
            gen_kwargs.pop("prompt", None)
            gen_kwargs["num_frames"] = min(num_frames, 25)
            gen_kwargs["decode_chunk_size"] = 4  # Low VRAM usage
            gen_kwargs["motion_bucket_id"] = 127
            gen_kwargs["noise_aug_strength"] = 0.02
        elif pipeline_type == "animatediff":
            gen_kwargs["guidance_scale"] = guidance
            gen_kwargs["num_frames"] = num_frames
            gen_kwargs["width"] = min(width, 512)
            gen_kwargs["height"] = min(height, 512)
        elif pipeline_type == "ltx":
            gen_kwargs["width"] = width
            gen_kwargs["height"] = height
            gen_kwargs["num_frames"] = num_frames
        elif pipeline_type == "wan":
            gen_kwargs["negative_prompt"] = negative_prompt
            gen_kwargs["guidance_scale"] = guidance
            gen_kwargs["num_frames"] = num_frames
            gen_kwargs["width"] = width
            gen_kwargs["height"] = height
        else:
            # CogVideoX / HunyuanVideo / generic
            gen_kwargs["negative_prompt"] = negative_prompt
            gen_kwargs["guidance_scale"] = guidance
            gen_kwargs["num_frames"] = num_frames
            gen_kwargs["width"] = width
            gen_kwargs["height"] = height

        if init_img:
            # Resize image to match exactly the target dimensions to avoid tensor mismatch errors
            target_w = gen_kwargs.get("width", width)
            target_h = gen_kwargs.get("height", height)
            
            if pipeline_type == "svd":
                # SVD native resolution
                target_w, target_h = 1024, 576
                gen_kwargs.pop("width", None)
                gen_kwargs.pop("height", None)
            elif "cogvideo" in (model_cfg.get("i2v_repo") or "").lower():
                target_w, target_h = 720, 480
                gen_kwargs.pop("width", None)
                gen_kwargs.pop("height", None)

            init_img = init_img.resize((target_w, target_h), Image.LANCZOS)
            gen_kwargs["image"] = init_img

        result = await asyncio.to_thread(pipe, **gen_kwargs)

        # Use model-specific fps for export
        fps = model_fps
        
        video_frames = result.frames[0]

        # Progress: encoding stage
        _generation_progress = {
            "active": True, "type": "video",
            "step": steps, "total_steps": steps,
            "progress": 95.0, "stage": "encoding",
        }

        base_name = f"anim_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

        from diffusers.utils import export_to_video
        from PIL import Image
        import numpy as np

        frame_duration_ms = int(1000 / fps)

        if format.lower() == "mp4":
            out_filename = f"{base_name}.mp4"
            out_filepath = os.path.join(IMAGES_DIR, out_filename)
            export_to_video(video_frames, out_filepath, fps=fps)
            with open(out_filepath + ".txt", "w", encoding="utf-8") as f:
                f.write(f"[{video_model}] {prompt}")

            with open(out_filepath, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()

            _release_video_pipeline()
            _release_i2v_pipeline()
            _generation_progress["active"] = False
            return {
                "status": "ok",
                "method": "diffusion_video_mp4",
                "format": "mp4",
                "filename": out_filename,
                "path": out_filepath,
                "base64": b64,
                "prompt": prompt,
                "duration": duration,
            }
        else:
            out_filename = f"{base_name}.gif"
            out_filepath = os.path.join(IMAGES_DIR, out_filename)

            if not isinstance(video_frames[0], Image.Image):
                video_frames = [Image.fromarray(np.uint8(f * 255)) if np.max(f) <= 1.0 else Image.fromarray(np.uint8(f)) for f in video_frames]

            video_frames[0].save(
                out_filepath,
                save_all=True,
                append_images=video_frames[1:],
                duration=frame_duration_ms,
                loop=0
            )
            with open(out_filepath + ".txt", "w", encoding="utf-8") as f:
                f.write(f"[{video_model}] {prompt}")

            with open(out_filepath, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()

            _release_video_pipeline()
            _release_i2v_pipeline()
            _generation_progress["active"] = False
            return {
                "status": "ok",
                "method": "diffusion_video_gif",
                "format": "gif",
                "filename": out_filename,
                "path": out_filepath,
                "base64": b64,
                "prompt": prompt,
                "duration": duration,
            }

    except ImportError as e:
        _generation_progress["active"] = False
        logger.error("Missing dependency for video: %s", e)
        raise RuntimeError("diffusers and accelerate are required for video generation. Please install them.")
    except Exception as e:
        _generation_progress["active"] = False
        logger.error("Video generation failed: %s", e)
        _release_video_pipeline()
        _release_i2v_pipeline()
        raise RuntimeError(f"Video generation failed: {e}")


@router.get("/check-model")
async def check_model(type: str = "image", style: str = "none", video_model: str = "cogvideox"):
    """Check if the local HuggingFace model is already downloaded in cache."""
    try:
        import os
        from huggingface_hub.constants import HF_HUB_CACHE
        
        if type == "image":
            model_info = _IMAGE_STYLE_MODELS.get(style, _IMAGE_STYLE_MODELS["none"])
            repo_id = model_info["repo"]
        else:
            model_cfg = _VIDEO_MODELS.get(video_model, _VIDEO_MODELS["cogvideox"])
            repo_id = model_cfg["repo"]
        
        if repo_id.startswith("http"):
            return {"downloaded": True, "model": repo_id}
            
        # Check the huggingface cache directory directly for instant response
        # format: models--author--repo_name
        safe_name = "models--" + repo_id.replace("/", "--")
        model_path = os.path.join(HF_HUB_CACHE, safe_name)
        
        # We consider it downloaded if the directory exists and has some files
        is_downloaded = False
        if os.path.exists(model_path):
            # Check if there are actual weights in the snapshots folder
            snapshots_dir = os.path.join(model_path, "snapshots")
            if os.path.exists(snapshots_dir) and os.listdir(snapshots_dir):
                is_downloaded = True
                
        return {"downloaded": is_downloaded, "model": repo_id}
    except Exception as e:
        logger.warning(f"Failed to check local cache for {repo_id}: {e}")
        return {"downloaded": True} # Fallback to assume true if check fails

@router.get("/download-status")
async def get_download_status():
    """Return the current progress of HuggingFace model download."""
    return _hf_download_state

@router.get("/generation-progress")
async def get_generation_progress():
    """Return the current generation progress (image/video)."""
    return _generation_progress

@router.post("/animate")
async def animate_image(request: Request):
    """Generate an animation (gif or mp4) from a text prompt.

    Returns an SSE stream with keepalive comments and progress events
    so the browser connection doesn't drop during long GPU inference.
    """
    data = await request.json()
    prompt = data.get("prompt", "")
    if not prompt.strip():
        raise HTTPException(400, "Prompt is required")

    fmt = data.get("format", "gif").lower()
    if fmt not in ("gif", "mp4"):
        fmt = "gif"

    enhance_prompt = data.get("enhance_prompt", False)
    backend = data.get("backend", "local").lower()
    if backend not in ("local", "api"):
        backend = "local"

    # Duration in seconds (default 2s, max 8s)
    duration = min(max(data.get("duration", 2.0), 0.5), 20.0)
    fps = data.get("fps", 8)

    video_model = data.get("video_model", "cogvideox").lower()
    if video_model not in _VIDEO_MODELS:
        video_model = "cogvideox"

    # Video resolution
    width = min(data.get("width", 704), 1920)
    height = min(data.get("height", 480), 1920)

    from fastapi.responses import StreamingResponse
    import asyncio
    import json
    import time as _time

    async def sse_generator():
        try:
            task = asyncio.create_task(
                generate_animation_core(
                    prompt=prompt,
                    negative_prompt=data.get("negative_prompt", "blurry, low quality, distorted"),
                    format=fmt,
                    duration=duration,
                    fps=fps,
                    width=width,
                    height=height,
                    video_model=video_model,
                    enhance_prompt=enhance_prompt,
                    backend=backend,
                    reference_image=data.get("reference_image", None),
                )
            )

            last_keepalive = _time.monotonic()
            last_progress = 0.0

            while not task.done():
                now = _time.monotonic()
                # Stream progress events from the shared state
                gp = _generation_progress
                if gp.get("active") and gp.get("progress", 0) != last_progress:
                    last_progress = gp["progress"]
                    yield f"data: {json.dumps({'status': 'progress', 'progress': last_progress, 'stage': gp.get('stage', ''), 'step': gp.get('step', 0), 'total_steps': gp.get('total_steps', 0)})}\n\n"
                    last_keepalive = now
                elif now - last_keepalive > 2.0:
                    # SSE comment keepalive to prevent connection drop
                    yield ": keepalive\n\n"
                    last_keepalive = now
                await asyncio.sleep(0.3)

            try:
                result = await task
                yield f"data: {json.dumps({'status': 'done', 'result': result})}\n\n"
            except RuntimeError as e:
                yield f"data: {json.dumps({'status': 'error', 'message': str(e)})}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'status': 'error', 'message': str(e)})}\n\n"
        except Exception as e:
            logger.error("SSE animate generator crashed: %s", e, exc_info=True)
            try:
                yield f"data: {json.dumps({'status': 'error', 'message': str(e)})}\n\n"
            except Exception:
                pass

    return StreamingResponse(sse_generator(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# HTTP endpoints
# ---------------------------------------------------------------------------
@router.post("/generate")
async def generate_image(request: Request):
    """Generate an image from a text prompt.

    Supports format param: 'auto' (default), 'svg', 'png', 'transparent_png'.
    Supports style param, enhance_prompt flag, and backend selection.
    """
    data = await request.json()
    prompt = data.get("prompt", "")
    if not prompt.strip():
        raise HTTPException(400, "Prompt is required")

    fmt = data.get("format", "png").lower()
    if fmt not in ("auto", "svg", "png", "transparent_png"):
        fmt = "png"

    style = data.get("style", "none").lower()
    enhance_prompt = data.get("enhance_prompt", False)
    backend = data.get("backend", "local").lower()
    if backend not in ("local", "api"):
        backend = "local"

    try:
        stream = data.get("stream", False)
        
        if stream:
            from fastapi.responses import StreamingResponse
            import queue
            import asyncio
            import json
            
            q = queue.Queue()
            
            async def generator():
                try:
                    task = asyncio.create_task(
                        generate_image_core(
                            prompt=prompt,
                            negative_prompt=data.get("negative_prompt", "blurry, low quality, distorted"),
                            width=min(data.get("width", 1024), 2048),
                            height=min(data.get("height", 1024), 2048),
                            steps=min(data.get("steps", 4), 50),
                            guidance=data.get("guidance_scale", 0.0),
                            format=fmt,
                            style=style,
                            enhance_prompt=enhance_prompt,
                            backend=backend,
                            reference_image=data.get("reference_image", None),
                            strength=data.get("strength", 0.5),
                            stream_queue=q,
                        )
                    )

                    import time as _time
                    _last_keepalive = _time.monotonic()

                    while not task.done() or not q.empty():
                        try:
                            item = await asyncio.to_thread(q.get, timeout=0.5)
                            yield f"data: {json.dumps(item)}\n\n"
                            _last_keepalive = _time.monotonic()
                        except queue.Empty:
                            # Send SSE keepalive comment every 2s to prevent
                            # browser / proxy from closing the connection
                            now = _time.monotonic()
                            if now - _last_keepalive > 2.0:
                                yield ": keepalive\n\n"
                                _last_keepalive = now
                            await asyncio.sleep(0.05)

                    try:
                        result = await task
                        yield f"data: {json.dumps({'status': 'done', 'result': result})}\n\n"
                    except RuntimeError as e:
                        error_msg = str(e)
                        if "403 Forbidden" in error_msg or "401 Unauthorized" in error_msg or "private repository" in error_msg:
                            error_msg = f"Hugging Face Token is invalid or does not have access to this model. Please check your token permissions: {error_msg}"
                        yield f"data: {json.dumps({'status': 'error', 'message': error_msg})}\n\n"
                    except Exception as e:
                        yield f"data: {json.dumps({'status': 'error', 'message': str(e)})}\n\n"
                except Exception as e:
                    # Top-level catch: ensure we ALWAYS send an error event
                    # instead of silently dropping the connection
                    logger.error("SSE generator crashed: %s", e, exc_info=True)
                    try:
                        yield f"data: {json.dumps({'status': 'error', 'message': str(e)})}\n\n"
                    except Exception:
                        pass

            return StreamingResponse(generator(), media_type="text/event-stream")
        else:
            result = await generate_image_core(
                prompt=prompt,
                negative_prompt=data.get("negative_prompt", "blurry, low quality, distorted"),
                width=min(data.get("width", 1024), 2048),
                height=min(data.get("height", 1024), 2048),
                steps=min(data.get("steps", 4), 50),
                guidance=data.get("guidance_scale", 0.0),
                format=fmt,
                style=style,
                enhance_prompt=enhance_prompt,
                backend=backend,
                reference_image=data.get("reference_image", None),
                strength=data.get("strength", 0.5),
            )
            return result
    except RuntimeError as e:
        error_msg = str(e)
        if "403 Forbidden" in error_msg or "401 Unauthorized" in error_msg or "private repository" in error_msg:
            raise HTTPException(403, f"Hugging Face Token is invalid or does not have access to this model. Please check your token permissions or accept the terms of use on Hugging Face: {error_msg}")
        raise HTTPException(500, error_msg)
    except Exception as e:
        raise HTTPException(500, f"Image generation failed: {e}")

@router.post("/remove-bg")
async def remove_bg(request: Request):
    """Remove background from one or more selected images."""
    data = await request.json()
    filenames = data.get("filenames", [])
    settings = data.get("settings", {})
    if not filenames:
        raise HTTPException(400, "No filenames provided")
        
    try:
        from rembg import new_session
    except ImportError:
        raise HTTPException(500, "rembg is not installed on the server.")

    processed = []
    
    for filename in filenames:
        filepath = os.path.join(IMAGES_DIR, filename)
        if not os.path.exists(filepath):
            continue
            
        try:
            with open(filepath, "rb") as f:
                input_bytes = f.read()
                
            output_bytes = _remove_bg_enhanced(input_bytes, **settings)
            
            new_filename = f"gen_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}_nobg.png"
            new_filepath = os.path.join(IMAGES_DIR, new_filename)
            
            with open(new_filepath, "wb") as f:
                f.write(output_bytes)
                
            # Copy prompt if exists
            txt_path = filepath + ".txt"
            if os.path.exists(txt_path):
                with open(txt_path, "r", encoding="utf-8") as f:
                    prompt = f.read()
                with open(new_filepath + ".txt", "w", encoding="utf-8") as f:
                    f.write(prompt + " (background removed)")
                    
            processed.append(new_filename)
        except Exception as e:
            logger.error("Failed to remove bg for %s: %s", filename, e)
            
    return {"status": "ok", "processed": processed}

@router.post("/remove-bg-preview")
async def remove_bg_preview(request: Request):
    """Generate a quick base64 preview of the background removal."""
    data = await request.json()
    filename = data.get("filename")
    settings = data.get("settings", {})
    if not filename:
        raise HTTPException(400, "No filename provided")
        
    filepath = os.path.join(IMAGES_DIR, filename)
    if not os.path.exists(filepath):
        raise HTTPException(404, "File not found")
        
    try:
        with open(filepath, "rb") as f:
            input_bytes = f.read()
            
        output_bytes = _remove_bg_enhanced(input_bytes, **settings)
        
        # Encode to base64
        b64_img = base64.b64encode(output_bytes).decode('utf-8')
        return {"status": "ok", "image_base64": b64_img}
    except Exception as e:
        logger.error("Failed to generate remove bg preview for %s: %s", filename, e)
        raise HTTPException(500, str(e))

@router.post("/upload")
async def upload_image(request: Request):
    """Upload an image to the media gallery."""
    try:
        from fastapi import UploadFile, File
        form = await request.form()
        file = form.get("file")
        if not file or not getattr(file, "filename", None):
            raise HTTPException(400, "No file provided")
            
        import uuid
        import shutil
        from datetime import datetime
        
        ext = file.filename.split('.')[-1] if '.' in file.filename else 'png'
        filename = f"upload_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.{ext}"
        filepath = os.path.join(IMAGES_DIR, filename)
        
        with open(filepath, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        return {"status": "ok", "url": f"/data/images/{filename}", "filename": filename}
    except Exception as e:
        logger.error(f"Image upload failed: {e}")
        raise HTTPException(500, str(e))

@router.get("/gallery")
async def list_images():
    """List all generated images."""
    images = []
    if os.path.exists(IMAGES_DIR):
        for f in sorted(os.listdir(IMAGES_DIR), reverse=True):
            if f.endswith((".png", ".jpg", ".svg", ".gif", ".mp4")):
                if f.endswith(".svg"):
                    fmt = "svg"
                elif f.endswith(".gif"):
                    fmt = "gif"
                elif f.endswith(".mp4"):
                    fmt = "mp4"
                else:
                    fmt = "png"
                prompt_text = ""
                txt_path = os.path.join(IMAGES_DIR, f + ".txt")
                if os.path.exists(txt_path):
                    with open(txt_path, "r", encoding="utf-8") as tf:
                        prompt_text = tf.read().strip()
                images.append({"filename": f, "path": os.path.join(IMAGES_DIR, f), "format": fmt, "prompt": prompt_text})
    return {"images": images[:200]}


# (Duplicate /remove-bg route removed — see remove_bg() above)

@router.post("/make-coloring")
async def make_coloring(request: Request):
    """Transform an image into a children's coloring page (line art)."""
    data = await request.json()
    filename = data.get("filename", "")
    input_b64 = data.get("base64", "")

    try:
        from PIL import Image, ImageFilter, ImageOps
        import numpy as np
        import io

        if filename:
            filepath = os.path.join(IMAGES_DIR, os.path.basename(filename))
            if not os.path.exists(filepath):
                raise HTTPException(404, f"Image not found: {filename}")
            with open(filepath, "rb") as f:
                input_data = f.read()
        elif input_b64:
            input_data = base64.b64decode(input_b64)
        else:
            raise HTTPException(400, "Provide 'filename' or 'base64'")

        logger.info("Making coloring page for %s (%d KB)...", filename or "base64", len(input_data) // 1024)

        img = Image.open(io.BytesIO(input_data)).convert("L")
        inverted_img = ImageOps.invert(img)
        blurred_img = inverted_img.filter(ImageFilter.GaussianBlur(radius=5))
        
        def dodge(front, back):
            result = np.zeros_like(back, dtype=np.float32)
            mask = front == 255
            with np.errstate(divide='ignore', invalid='ignore'):
                calc = back.astype(np.float32) * 256.0 / (256.0 - front.astype(np.float32))
            result[~mask] = calc[~mask]
            result[mask] = 255.0
            result = np.clip(result, 0, 255)
            return result.astype('uint8')
            
        img_np = np.array(img)
        blur_np = np.array(blurred_img)
        sketch_np = dodge(blur_np, img_np)
        sketch_img = Image.fromarray(sketch_np)
        
        out_io = io.BytesIO()
        sketch_img.save(out_io, format="PNG")
        output_data = out_io.getvalue()

        base_name = os.path.splitext(os.path.basename(filename))[0] if filename else f"img_{uuid.uuid4().hex[:6]}"
        out_filename = f"{base_name}_coloring.png"
        out_filepath = os.path.join(IMAGES_DIR, out_filename)
        with open(out_filepath, "wb") as f:
            f.write(output_data)

        out_b64 = base64.b64encode(output_data).decode()

        logger.info("Coloring page created → %s (%d KB)", out_filename, len(output_data) // 1024)

        return {
            "status": "ok",
            "filename": out_filename,
            "path": out_filepath,
            "url": f"/data/images/{out_filename}",
            "base64": out_b64,
            "original": filename,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Coloring page creation failed: %s", e)
        raise HTTPException(500, f"Coloring page creation failed: {e}")

@router.post("/convert-video")
async def convert_video(request: Request):
    """Convert a video to GIF or a GIF to MP4 using FFmpeg."""
    data = await request.json()
    filename = data.get("filename", "")
    target_format = data.get("target_format", "gif").lower()

    if not filename:
        raise HTTPException(400, "filename is required")
    if target_format not in ("gif", "mp4", "webm"):
        raise HTTPException(400, "target_format must be gif, mp4, or webm")

    input_path = os.path.join(IMAGES_DIR, os.path.basename(filename))
    if not os.path.exists(input_path):
        raise HTTPException(404, f"File not found: {filename}")

    base_name = os.path.splitext(os.path.basename(filename))[0]
    out_filename = f"{base_name}_conv.{target_format}"
    out_filepath = os.path.join(IMAGES_DIR, out_filename)

    import subprocess
    import asyncio

    try:
        if target_format == "gif":
            # Any to GIF
            cmd = [
                "ffmpeg", "-y", "-i", input_path,
                "-vf", "fps=10,scale=720:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse",
                "-loop", "0", out_filepath
            ]
        elif target_format == "webm":
            # Any to WEBM
            cmd = [
                "ffmpeg", "-y", "-i", input_path,
                "-c:v", "libvpx-vp9",
                "-crf", "30",
                "-b:v", "0",
                "-pix_fmt", "yuv420p",
                "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                out_filepath
            ]
        else:
            # Any to MP4
            cmd = [
                "ffmpeg", "-y", "-i", input_path,
                "-movflags", "faststart",
                "-pix_fmt", "yuv420p",
                "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                out_filepath
            ]

        logger.info(f"Running FFmpeg conversion: {' '.join(cmd)}")
        result = await asyncio.to_thread(
            subprocess.run, cmd, capture_output=True, text=True
        )

        if result.returncode != 0:
            logger.error(f"FFmpeg failed: {result.stderr}")
            raise RuntimeError(f"FFmpeg error: {result.stderr}")

        # Copy original text file if it exists
        txt_path = input_path + ".txt"
        if os.path.exists(txt_path):
            with open(txt_path, "r", encoding="utf-8") as f:
                prompt = f.read()
            with open(out_filepath + ".txt", "w", encoding="utf-8") as f:
                f.write(prompt)

        return {
            "status": "ok",
            "filename": out_filename,
            "url": f"/data/images/{out_filename}",
            "format": target_format
        }

    except Exception as e:
        logger.error(f"Video conversion failed: {e}")
        raise HTTPException(500, f"Video conversion failed: {e}")



@router.delete("/delete")
async def delete_image(request: Request):
    """Delete a single image/video from the gallery."""
    data = await request.json()
    filename = data.get("filename", "")
    if not filename:
        raise HTTPException(400, "filename is required")
    # Prevent directory traversal
    safe_name = os.path.basename(filename)
    filepath = os.path.join(IMAGES_DIR, safe_name)
    if not os.path.exists(filepath):
        raise HTTPException(404, f"File not found: {safe_name}")
    os.remove(filepath)
    if os.path.exists(filepath + ".txt"):
        os.remove(filepath + ".txt")
    logger.info("Deleted image: %s", safe_name)
    return {"status": "ok", "deleted": safe_name}


@router.post("/delete-batch")
async def delete_images_batch(request: Request):
    """Delete multiple images/videos from the gallery."""
    data = await request.json()
    filenames = data.get("filenames", [])
    if not filenames:
        raise HTTPException(400, "filenames list is required")
    deleted = []
    errors = []
    for fname in filenames:
        safe_name = os.path.basename(fname)
        filepath = os.path.join(IMAGES_DIR, safe_name)
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
                if os.path.exists(filepath + ".txt"):
                    os.remove(filepath + ".txt")
                deleted.append(safe_name)
            else:
                errors.append(f"Not found: {safe_name}")
        except Exception as e:
            errors.append(f"{safe_name}: {e}")
    logger.info("Batch deleted %d files, %d errors", len(deleted), len(errors))
    return {"status": "ok", "deleted": deleted, "errors": errors}


@router.get("/download-zip")
async def download_gallery_zip(request: Request):
    """Download gallery files as a ZIP archive.

    Query params:
        files: comma-separated filenames (optional, downloads all if empty)
    """
    import zipfile
    import io
    from fastapi.responses import StreamingResponse

    files_param = request.query_params.get("files", "")
    if files_param:
        requested = [os.path.basename(f.strip()) for f in files_param.split(",") if f.strip()]
    else:
        # All gallery files
        requested = []
        if os.path.exists(IMAGES_DIR):
            for f in sorted(os.listdir(IMAGES_DIR)):
                if f.endswith((".png", ".jpg", ".webp", ".svg", ".gif", ".mp4")):
                    requested.append(f)

    if not requested:
        raise HTTPException(404, "No files to download")

    # Build ZIP in memory
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname in requested:
            filepath = os.path.join(IMAGES_DIR, fname)
            if os.path.exists(filepath):
                zf.write(filepath, fname)
            if os.path.exists(filepath + ".txt"):
                zf.write(filepath + ".txt", fname + ".txt")

    buf.seek(0)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_name = f"clawzd_gallery_{timestamp}.zip"

    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_name}"'},
    )


def _gather_project_context(project: str = "") -> str:
    """Auto-gather project context from workspace files.

    Reads clawzd.md, README files, package.json, and directory listing
    to build a rich context string for AI prompt generation.
    """
    from config import WORKSPACE_DIR

    base = os.path.realpath(WORKSPACE_DIR)
    project_dir = os.path.join(base, project) if project and project != "." else base

    if not os.path.isdir(project_dir):
        project_dir = base

    parts = []

    # 1. Project name from directory
    project_name = os.path.basename(project_dir) if project_dir != base else os.path.basename(base)
    if project_name:
        parts.append(f"Project Name: {project_name}")

    # 2. clawzd.md (user-defined context)
    for ctx_name in ("clawzd.md",):
        ctx_path = os.path.join(project_dir, ctx_name)
        if not os.path.isfile(ctx_path):
            ctx_path = os.path.join(base, ctx_name)
        if os.path.isfile(ctx_path):
            try:
                with open(ctx_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read(4000).strip()
                if content:
                    parts.append(f"Project Context (clawzd.md):\n{content}")
            except Exception:
                pass

    # 3. README files
    for readme_name in ("README.md", "readme.md", "README.txt", "README"):
        readme_path = os.path.join(project_dir, readme_name)
        if os.path.isfile(readme_path):
            try:
                with open(readme_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read(3000).strip()
                if content:
                    parts.append(f"README:\n{content}")
                break
            except Exception:
                pass

    # 4. package.json (name + description)
    pkg_path = os.path.join(project_dir, "package.json")
    if os.path.isfile(pkg_path):
        try:
            import json
            with open(pkg_path, "r", encoding="utf-8") as f:
                pkg = json.load(f)
            pkg_info = []
            if pkg.get("name"):
                pkg_info.append(f"Name: {pkg['name']}")
            if pkg.get("description"):
                pkg_info.append(f"Description: {pkg['description']}")
            if pkg.get("keywords"):
                pkg_info.append(f"Keywords: {', '.join(pkg['keywords'][:10])}")
            if pkg_info:
                parts.append("package.json:\n" + "\n".join(pkg_info))
        except Exception:
            pass

    # 5. setup.py / pyproject.toml description
    for meta_name in ("pyproject.toml", "setup.cfg"):
        meta_path = os.path.join(project_dir, meta_name)
        if os.path.isfile(meta_path):
            try:
                with open(meta_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read(2000).strip()
                if content:
                    parts.append(f"{meta_name}:\n{content}")
                break
            except Exception:
                pass

    # 6. Directory listing (top-level only, for tech stack hints)
    try:
        entries = sorted(os.listdir(project_dir))
        # Filter hidden files and limit
        visible = [e for e in entries if not e.startswith(".")][:30]
        if visible:
            parts.append(f"Top-level files: {', '.join(visible)}")
    except Exception:
        pass

    result = "\n\n".join(parts)
    logger.info("Auto-gathered project context (%d chars) for project='%s'", len(result), project or ".")
    return result


@router.post("/suggest-prompt")
async def suggest_prompt(request: Request):
    """Generate an image/logo prompt based on project context.

    If no context is provided by the client, automatically gathers context
    from workspace files (clawzd.md, README, package.json, directory listing).
    """
    data = await request.json()
    context = data.get("context", "")
    target = data.get("target", "logo")
    project = data.get("project", "")

    # Auto-gather project context if none provided
    if not context.strip():
        context = _gather_project_context(project)

    if not context.strip():
        # Ultimate fallback if no context could be gathered at all
        return {"prompt": f"A professional {target} for the project, minimal design, flat vector graphic, clean background"}

    import httpx
    from config import OLLAMA_HOST, OLLAMA_MODEL

    if target == "presentation":
        system_prompt = (
            "You are an expert presentation designer. "
            "The user wants to generate a slide deck for their project. "
            "Read the provided project context to deduce the project's core subject, theme, and purpose. "
            "CRITICAL INSTRUCTIONS:\n"
            "1. You MUST explicitly state the core subject or theme of the project.\n"
            "2. Keep it under 20 words.\n"
            "3. The final output MUST be entirely in English (translate the context if needed).\n"
            "4. Output ONLY the English topic string. NO intro, NO explanation, NO markdown.\n"
            "5. Skip all brainstorming and output the final text immediately."
        )
    else:
        system_prompt = (
            "You are an expert prompt engineer for stable diffusion. "
            f"The user wants to generate a '{target}' for their project. "
            "Read the provided project context to deduce the project's core subject, theme, and purpose. "
            f"Create a highly detailed, descriptive, and visually rich stable diffusion prompt for this {target}. "
            "CRITICAL INSTRUCTIONS:\n"
            "1. You MUST explicitly include the core subject or theme of the project in the visual description.\n"
            "2. Keep it under 50 words, using dense, descriptive, comma-separated keywords.\n"
            "3. The final output MUST be entirely in English (translate any French or foreign context first).\n"
            "4. Output ONLY the final English prompt. NO intro, NO explanation, NO markdown.\n"
            "5. Skip all brainstorming and output the final prompt immediately."
        )

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": context,
        "system": system_prompt,
        "stream": False,
        "options": {
            "temperature": 0.7,
            "num_predict": 2048,
        },
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(f"{OLLAMA_HOST}/api/generate", json=payload)
            resp.raise_for_status()
            data = resp.json()
            enhanced = data.get("response", "").strip()
            
            # Remove <think>...</think> block if present
            import re
            enhanced = _clean_llm_output(enhanced)
            
            if enhanced:
                return {"prompt": enhanced}
    except Exception as e:
        logger.warning(f"Failed to generate prompt from context: {e}")

    # Fallback on failure
    return {"prompt": f"A professional {target} for the project, minimal design, flat vector graphic, clean background"}

