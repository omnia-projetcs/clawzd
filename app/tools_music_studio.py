import os
import gc
import time
import uuid
import torch
import logging
from datetime import datetime
from typing import Dict, Any, Optional

from config import MODELS_DIR
from app.core.llm_provider import get_llm_provider

# Ensure HeartMuLa model dir matches Clawzd's models dir
os.environ["HEARTMULA_MODEL_DIR"] = MODELS_DIR

logger = logging.getLogger(__name__)

# HuggingFace model IDs
HF_HEARTCODEC_REPO = "HeartMuLa/HeartCodec-oss-20260123"
HF_HEARTMULA_GEN_REPO = "HeartMuLa/HeartMuLaGen"
DEFAULT_VERSION = "3B-happy-new-year"

MODEL_VERSIONS = {
    "3B": ("HeartMuLa/HeartMuLa-oss-3B", "HeartMuLa-oss-3B"),
    "RL-3B-20260123": ("HeartMuLa/HeartMuLa-RL-oss-3B-20260123", "HeartMuLa-oss-RL-3B-20260123"),
    "3B-happy-new-year": ("HeartMuLa/HeartMuLa-oss-3B-happy-new-year", "HeartMuLa-oss-3B-happy-new-year"),
}

def ensure_models_downloaded(model_dir: str, version: str = DEFAULT_VERSION) -> str:
    """Ensure HeartMuLa and HeartCodec models are downloaded locally with ModelScope fallback."""
    from huggingface_hub import hf_hub_download, snapshot_download
    
    os.makedirs(model_dir, exist_ok=True)
    hf_repo, folder_name = MODEL_VERSIONS.get(version, MODEL_VERSIONS[DEFAULT_VERSION])
    
    heartmula_path = os.path.join(model_dir, folder_name)
    heartcodec_path = os.path.join(model_dir, "HeartCodec-oss")
    tokenizer_path = os.path.join(model_dir, "tokenizer.json")
    gen_config_path = os.path.join(model_dir, "gen_config.json")
    
    # Check if all files already exist
    all_present = (
        os.path.exists(heartmula_path) and
        os.path.exists(heartcodec_path) and
        os.path.isfile(tokenizer_path) and
        os.path.isfile(gen_config_path)
    )
    
    if all_present:
        return model_dir
        
    logger.info("Downloading HeartMuLa models to %s...", model_dir)
    
    try:
        if not os.path.exists(heartmula_path):
            snapshot_download(repo_id=hf_repo, local_dir=heartmula_path, local_dir_use_symlinks=False)
            
        if not os.path.exists(heartcodec_path):
            snapshot_download(repo_id=HF_HEARTCODEC_REPO, local_dir=heartcodec_path, local_dir_use_symlinks=False)
            
        if not os.path.isfile(tokenizer_path):
            hf_hub_download(repo_id=HF_HEARTMULA_GEN_REPO, filename="tokenizer.json", local_dir=model_dir, local_dir_use_symlinks=False)
            
        if not os.path.isfile(gen_config_path):
            hf_hub_download(repo_id=HF_HEARTMULA_GEN_REPO, filename="gen_config.json", local_dir=model_dir, local_dir_use_symlinks=False)
    except Exception as hf_err:
        logger.warning("HuggingFace download failed: %s. Trying ModelScope as a fallback...", hf_err)
        try:
            from modelscope.hub.snapshot_download import snapshot_download as ms_snapshot_download
            
            ms_mula_repo = hf_repo
            ms_codec_repo = HF_HEARTCODEC_REPO
            ms_gen_repo = HF_HEARTMULA_GEN_REPO
            
            if not os.path.exists(heartmula_path):
                logger.info("Downloading HeartMuLa via ModelScope: %s", ms_mula_repo)
                ms_snapshot_download(model_id=ms_mula_repo, local_dir=heartmula_path)
                
            if not os.path.exists(heartcodec_path):
                logger.info("Downloading HeartCodec via ModelScope: %s", ms_codec_repo)
                ms_snapshot_download(model_id=ms_codec_repo, local_dir=heartcodec_path)
                
            if not os.path.isfile(tokenizer_path) or not os.path.isfile(gen_config_path):
                logger.info("Downloading config files via ModelScope: %s", ms_gen_repo)
                temp_config_dir = os.path.join(model_dir, "temp_ms_config")
                ms_snapshot_download(model_id=ms_gen_repo, local_dir=temp_config_dir)
                
                import shutil
                if os.path.exists(os.path.join(temp_config_dir, "tokenizer.json")):
                    shutil.copy2(os.path.join(temp_config_dir, "tokenizer.json"), tokenizer_path)
                if os.path.exists(os.path.join(temp_config_dir, "gen_config.json")):
                    shutil.copy2(os.path.join(temp_config_dir, "gen_config.json"), gen_config_path)
                    
                try:
                    shutil.rmtree(temp_config_dir)
                except Exception:
                    pass
        except Exception as ms_err:
            logger.error("ModelScope download fallback also failed: %s", ms_err)
            raise RuntimeError(f"Failed to download models from HuggingFace and ModelScope: {hf_err} | {ms_err}")
        
    logger.info("Models downloaded successfully!")
    return model_dir

async def generate_lyrics(prompt: str, genre: str) -> str:
    """Generate professional song lyrics using local or cloud LLM."""
    try:
        provider = get_llm_provider()
        system_prompt = (
            "You are a brilliant, Grammy-winning songwriter and lyricist.\n"
            "Generate structured song lyrics based on the user's prompt and genre.\n"
            "Format the output clearly with tags like [Verse 1], [Chorus], [Verse 2], [Bridge], [Outro].\n"
            "Include emotional cues, rhythm markers, and vocal directions where appropriate.\n"
            "Generate ONLY the raw lyrics, no introduction, greeting, or explanations."
        )
        user_prompt = f"Write lyrics for a {genre or 'pop'} song about: {prompt}"
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        lyrics = await provider.chat(messages)
        return lyrics.strip()
    except Exception as e:
        logger.error("Failed to generate lyrics: %s", e)
        return "[Verse 1]\nGenerated by HeartMuLa Studio\nMusic is the key to life\nAnd harmony is the guide."

async def generate_heartmula_song(
    data: Dict[str, Any],
    progress_dict: Dict[str, Any],
    audio_dir: str,
    format_type: str = "mp3"
) -> str:
    """Generate high-fidelity vocal + instrumental song using local HeartLib & mmgp."""
    # 1. Release VRAM locks to prevent crashes with other active pipelines
    from app.tools_audio import _release_all_audio, _release_image_pipelines
    _release_all_audio()
    _release_image_pipelines()
    
    # 2. Extract inputs
    text = data.get("text", "").strip()
    prompt = data.get("prompt", "").strip()
    lyrics = data.get("lyrics", "").strip()
    genre = data.get("genre", "pop").strip()
    tempo = int(data.get("tempo", 120))
    duration_sec = min(float(data.get("duration", 60)), 300)
    seed = int(data.get("seed", -1))
    version = data.get("version", "").strip() or DEFAULT_VERSION
    
    # Visual Reference Audio inputs
    ref_audio_file = data.get("reference_audio", "")
    ref_start = float(data.get("ref_audio_start_sec", 0.0))
    ref_duration = float(data.get("ref_audio_duration", 10.0))
    
    # Performance/Compilation Settings
    use_compile = data.get("torch_compile", False)
    use_int8 = data.get("int8_quantization", False)
    
    # Generate lyrics if not provided
    if not lyrics:
        if text:
            progress_dict.update({"active": True, "progress": 5.0, "stage": "generating_lyrics"})
            lyrics = await generate_lyrics(text, genre)
        else:
            lyrics = "[Verse 1]\nSinging along with Clawzd Media Studio!"
 
    # 3. Ensure models are downloaded
    progress_dict.update({"active": True, "progress": 10.0, "stage": "downloading_weights"})
    ensure_models_downloaded(MODELS_DIR, version)
    
    # 4. Initialize HeartMuLa mmgp Pipeline
    progress_dict.update({"active": True, "progress": 20.0, "stage": "initializing_pipeline"})
    
    from app.heartmula.pipeline import HeartMuLaPipeline
    from mmgp import offload as mmgp_offload
    
    # Auto VRAM profiling
    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    vram_gb = 12
    if torch.cuda.is_available():
        vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
        
    opt_level = "balanced"
    if vram_gb < 10:
        opt_level = "conservative"
    elif vram_gb > 18:
        opt_level = "aggressive"
        
    # Create the mmgp optimized pipeline
    pipeline = HeartMuLaPipeline(
        ckpt_root=MODELS_DIR,
        device=device,
        version=version,
    )
    
    # Configure mmgp offloading
    pipe_config = pipeline.get_mmgp_pipe_config(opt_level)
    profile_no = {"conservative": 1, "balanced": 3, "aggressive": 5}.get(opt_level, 3)
    
    offload_obj = mmgp_offload.profile(
        pipe_config["pipe"],
        profile_no=profile_no,
        coTenantsMap=pipe_config.get("coTenantsMap"),
        budgets=pipe_config.get("budgets"),
        verboseLevel=0,
        quantizeTransformer=use_int8,
    )
    pipeline.set_offload_obj(offload_obj)
    
    # 5. Handle Reference Audio (Style Transfer)
    ref_audio_path = None
    if ref_audio_file:
        full_ref_path = os.path.join(audio_dir, ref_audio_file)
        if os.path.exists(full_ref_path):
            ref_audio_path = full_ref_path
            
    # 6. Execute Generation
    progress_dict.update({"active": True, "progress": 30.0, "stage": "generating"})
    
    # Set seed
    if seed < 0:
        seed = int(time.time()) % 100000
    
    # Prepare style tags
    style_tags = f"{genre}, {tempo} bpm"
    if ref_audio_path:
        style_tags += ", style transfer"
        
    # Callback to update progress in Clawzd
    def generation_callback(step_idx=-1, override_num_inference_steps=None, force_refresh=False, **kwargs):
        # Allow abortion/cancellation from main audio thread
        import app.tools_audio
        if getattr(app.tools_audio, "_audio_cancel_requested", False):
            pipeline.request_interrupt()
            
        if override_num_inference_steps and override_num_inference_steps > 0:
            if step_idx >= 0:
                progress = 30.0 + (step_idx + 1) / override_num_inference_steps * 55.0
                progress_dict.update({
                    "active": True,
                    "progress": min(85.0, progress),
                    "stage": f"generating ({step_idx + 1}s / {override_num_inference_steps}s)"
                })
            else:
                progress_dict.update({"active": True, "progress": 30.0, "stage": "starting_generation"})
        elif force_refresh:
            progress_dict.update({"active": True, "progress": 85.0, "stage": "decoding"})
        else:
            progress_dict.update({"active": True, "progress": 85.0, "stage": "processing"})
            
    # Assemble input parameters
    pipeline_inputs = {
        "lyrics": lyrics,
        "tags": style_tags,
    }
    if ref_audio_path:
        pipeline_inputs["ref_audio"] = ref_audio_path
        pipeline_inputs["muq_segment_sec"] = ref_duration
        pipeline_inputs["ref_audio_start_sec"] = ref_start

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    uid = uuid.uuid4().hex[:6]
    filename = f"song_{timestamp}_{uid}.{format_type}"
    save_path = os.path.join(audio_dir, filename)
    
    try:
        # Run generation via heartlib/mmgp
        with torch.no_grad():
            pipeline.generate_with_callback(
                pipeline_inputs,
                max_audio_length_ms=int(duration_sec * 1000),
                save_path=save_path,
                temperature=1.0,
                callback=generation_callback
            )
            
        # Update progress to completed
        progress_dict.update({"active": True, "progress": 95.0, "stage": "saving"})
        
        # Write metadata
        import json
        meta_path = save_path + ".meta"
        with open(meta_path, "w") as f:
            json.dump({
                "prompt": text or prompt,
                "lyrics": lyrics,
                "genre": genre,
                "tempo": tempo,
                "duration": duration_sec,
                "seed": seed,
                "created": datetime.now().isoformat(),
                "mode": "song"
            }, f)
            
        progress_dict.update({"active": False, "progress": 100.0, "stage": "completed"})
        return filename
        
    finally:
        # Cleanup pipeline memory
        try:
            del pipeline
            if offload_obj:
                del offload_obj
        except Exception:
            pass
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
