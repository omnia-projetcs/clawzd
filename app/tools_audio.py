"""
Clawzd — Audio generation tool.

Modes:
1. TTS (Text-to-Speech) — SpeechT5 or Bark
2. Voice Cloning — Coqui XTTS-v2
3. Music Generation — MusicGen (instrumental)
4. Song Generation — MusicGen + melody reference
"""
import os
import re
import uuid
import logging

def _should_use_local_files(repo_id: str) -> bool:
    import os
    from config import MODELS_DIR
    if repo_id.startswith("http") or repo_id.endswith(".gguf"):
        return False
    safe_name = "models--" + repo_id.replace("/", "--")
    model_path = os.path.join(MODELS_DIR, "hub", safe_name)
    if os.path.exists(model_path):
        for root, dirs, files in os.walk(model_path):
            for file in files:
                if file.endswith(".safetensors") or file.endswith(".bin"):
                    return True
    return False

import subprocess
from datetime import datetime
from fastapi import APIRouter, Request, HTTPException, UploadFile, File, Form
from fastapi.responses import JSONResponse
from config import DATA_DIR

logger = logging.getLogger("clawzd.audio")
router = APIRouter()

AUDIO_DIR = os.path.join(DATA_DIR, "audio")
os.makedirs(AUDIO_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# GPU capability check
# ---------------------------------------------------------------------------
_gpu_ok = False
try:
    import torch
    if torch.cuda.is_available():
        _gpu_ok = True
        logger.info("GPU OK for audio generation: %s", torch.cuda.get_device_name())
    else:
        logger.info("CUDA not available — audio generation will use CPU (slower)")
except Exception as e:
    logger.info("PyTorch not available (%s) — audio on CPU", e)

# ---------------------------------------------------------------------------
# Voice presets for TTS
# ---------------------------------------------------------------------------
VOICE_PRESETS = {
    "male_deep": {"description": "Homme (grave)", "bark_speaker": "v2/fr_speaker_1", "speecht5_speaker": 0},
    "male_medium": {"description": "Homme (medium)", "bark_speaker": "v2/fr_speaker_3", "speecht5_speaker": 1},
    "female_soft": {"description": "Femme (douce)", "bark_speaker": "v2/fr_speaker_0", "speecht5_speaker": 2},
    "female_pro": {"description": "Femme (professionnelle)", "bark_speaker": "v2/fr_speaker_2", "speecht5_speaker": 3},
    "child": {"description": "Enfant", "bark_speaker": "v2/fr_speaker_4", "speecht5_speaker": 4},
    "robot": {"description": "Robot", "bark_speaker": "v2/en_speaker_9", "speecht5_speaker": 5},
    "narrator": {"description": "Narrateur", "bark_speaker": "v2/en_speaker_6", "speecht5_speaker": 6},
}

MUSIC_GENRES = [
    "pop", "rock", "jazz", "classical", "edm", "hiphop",
    "lofi", "ambient", "cinematic", "rnb", "reggae", "metal",
    "folk", "country", "blues", "electronic", "trap", "chillhop",
]

# ---------------------------------------------------------------------------
# Pipeline management (lazy-load, single instance)
# ---------------------------------------------------------------------------
_tts_pipeline = None
_tts_model_name = None
_music_pipeline = None
_music_model_name = None

_audio_download_state = {
    "active": False,
    "progress": 0.0,
    "model": "",
}

_audio_generation_progress = {
    "active": False,
    "progress": 0.0,  # 0-100
    "stage": "",      # 'loading_model', 'generating', 'saving'
}


def _release_all_audio():
    """Release all audio pipelines and free VRAM."""
    global _tts_pipeline, _tts_model_name, _music_pipeline, _music_model_name
    import gc
    if _tts_pipeline is not None:
        del _tts_pipeline
        _tts_pipeline = None
        _tts_model_name = None
    if _music_pipeline is not None:
        del _music_pipeline
        _music_pipeline = None
        _music_model_name = None
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


def _release_image_pipelines():
    """Release image/video pipelines to free VRAM for audio."""
    try:
        from app.tools_image import _release_pipeline, _release_i2i_pipeline, _release_video_pipeline, _release_i2v_pipeline
        _release_pipeline()
        _release_i2i_pipeline()
        _release_video_pipeline()
        _release_i2v_pipeline()
        logger.info("Released image/video pipelines to free VRAM for audio")
    except Exception:
        pass


def _get_tts_pipeline(model_name="speecht5"):
    """Load TTS pipeline (SpeechT5 or Bark)."""
    global _tts_pipeline, _tts_model_name, _audio_download_state

    if _tts_pipeline is not None and _tts_model_name == model_name:
        return _tts_pipeline

    _release_all_audio()
    _release_image_pipelines()

    _audio_download_state = {"active": True, "progress": 0.0, "model": model_name}

    try:
        import torch

        if model_name == "bark":
            from transformers import AutoProcessor, BarkModel
            logger.info("Loading Bark TTS model...")
            processor = AutoProcessor.from_pretrained("suno/bark", local_files_only=_should_use_local_files("suno/bark"))
            model = BarkModel.from_pretrained("suno/bark", local_files_only=_should_use_local_files("suno/bark"),
                torch_dtype=torch.float16 if _gpu_ok else torch.float32,
            )
            if _gpu_ok:
                model = model.to("cuda")
            _tts_pipeline = {"type": "bark", "processor": processor, "model": model}

        else:  # speecht5
            from transformers import SpeechT5Processor, SpeechT5ForTextToSpeech, SpeechT5HifiGan
            logger.info("Loading SpeechT5 TTS model...")
            processor = SpeechT5Processor.from_pretrained("microsoft/speecht5_tts", local_files_only=_should_use_local_files("microsoft/speecht5_tts"))
            model = SpeechT5ForTextToSpeech.from_pretrained("microsoft/speecht5_tts", local_files_only=_should_use_local_files("microsoft/speecht5_tts"))
            vocoder = SpeechT5HifiGan.from_pretrained("microsoft/speecht5_hifigan", local_files_only=_should_use_local_files("microsoft/speecht5_hifigan"))
            # Load pre-downloaded speaker embeddings
            import os
            embeddings_path = os.path.join(DATA_DIR, "audio_speakers", "speecht5_speaker_embeddings.pt")
            if not os.path.exists(embeddings_path):
                logger.info("Downloading SpeechT5 speaker embeddings...")
                os.makedirs(os.path.dirname(embeddings_path), exist_ok=True)
                import urllib.request
                import zipfile
                import io
                import numpy as np
                url = "https://huggingface.co/datasets/Matthijs/cmu-arctic-xvectors/resolve/main/spkrec-xvect.zip"
                resp = urllib.request.urlopen(url)
                embeddings = []
                with zipfile.ZipFile(io.BytesIO(resp.read())) as z:
                    npy_files = sorted([n for n in z.namelist() if n.endswith(".npy")])
                    for f in npy_files[:7]:
                        with z.open(f) as npy_file:
                            x = np.load(io.BytesIO(npy_file.read()))
                            embeddings.append(torch.tensor(x))
                torch.save(embeddings, embeddings_path)
                logger.info("Saved SpeechT5 speaker embeddings.")
            
            embeddings_dataset = torch.load(embeddings_path)
            if _gpu_ok:
                model = model.to("cuda")
                vocoder = vocoder.to("cuda")
            _tts_pipeline = {
                "type": "speecht5",
                "processor": processor,
                "model": model,
                "vocoder": vocoder,
                "embeddings": embeddings_dataset,
            }

        _tts_model_name = model_name
        _audio_download_state["active"] = False
        return _tts_pipeline

    except Exception as e:
        _audio_download_state["active"] = False
        logger.error("Failed to load TTS pipeline: %s", e)
        raise RuntimeError(f"TTS pipeline failed: {e}")


def _get_music_pipeline(model_name="musicgen-small"):
    """Load MusicGen pipeline."""
    global _music_pipeline, _music_model_name, _audio_download_state

    if _music_pipeline is not None and _music_model_name == model_name:
        return _music_pipeline

    _release_all_audio()
    _release_image_pipelines()

    _audio_download_state = {"active": True, "progress": 0.0, "model": model_name}

    try:
        import torch
        from transformers import AutoProcessor, MusicgenForConditionalGeneration

        repo = f"facebook/{model_name}"
        logger.info("Loading MusicGen model: %s", repo)

        processor = AutoProcessor.from_pretrained(repo, local_files_only=_should_use_local_files(repo))
        model = MusicgenForConditionalGeneration.from_pretrained(repo, local_files_only=_should_use_local_files(repo),
            torch_dtype=torch.float16 if _gpu_ok else torch.float32,
        )
        if _gpu_ok:
            model = model.to("cuda")

        _music_pipeline = {"processor": processor, "model": model}
        _music_model_name = model_name
        _audio_download_state["active"] = False
        return _music_pipeline

    except Exception as e:
        _audio_download_state["active"] = False
        logger.error("Failed to load MusicGen pipeline: %s", e)
        raise RuntimeError(f"MusicGen pipeline failed: {e}")


# ---------------------------------------------------------------------------
# Audio generation functions
# ---------------------------------------------------------------------------

def _save_audio(audio_array, sample_rate, format_type="wav", prompt="", mode="tts"):
    """Save audio array to file. Returns filename."""
    import numpy as np

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    uid = uuid.uuid4().hex[:6]
    filename = f"audio_{timestamp}_{uid}.{format_type}"
    filepath = os.path.join(AUDIO_DIR, filename)

    # Normalize audio
    if isinstance(audio_array, list):
        audio_array = np.array(audio_array)
    if audio_array.dtype == np.float32 or audio_array.dtype == np.float16:
        audio_array = np.clip(audio_array, -1.0, 1.0)
        
    duration_sec = len(audio_array) / sample_rate if sample_rate > 0 else 0.0

    import scipy.io.wavfile as wav
    wav_path = filepath if format_type == "wav" else filepath.replace(f".{format_type}", ".wav")

    # Ensure mono and correct shape
    if len(audio_array.shape) > 1:
        audio_array = audio_array.squeeze()
    
    # Convert to int16 for wav
    audio_int16 = (audio_array * 32767).astype(np.int16)
    wav.write(wav_path, sample_rate, audio_int16)

    if format_type == "mp3":
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-i", wav_path, "-b:a", "192k", filepath],
                capture_output=True, timeout=60
            )
            os.remove(wav_path)
        except Exception as e:
            logger.warning("ffmpeg MP3 conversion failed, keeping WAV: %s", e)
            filename = filename.replace(".mp3", ".wav")
    elif format_type == "ogg":
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-i", wav_path, "-c:a", "libvorbis", "-q:a", "6", filepath],
                capture_output=True, timeout=60
            )
            os.remove(wav_path)
        except Exception as e:
            logger.warning("ffmpeg OGG conversion failed, keeping WAV: %s", e)
            filename = filename.replace(".ogg", ".wav")

    # Save metadata
    meta_path = os.path.join(AUDIO_DIR, filename + ".meta")
    try:
        import json
        with open(meta_path, "w") as f:
            json.dump({
                "prompt": prompt, 
                "created": datetime.now().isoformat(),
                "mode": mode,
                "duration": duration_sec
            }, f)
    except Exception:
        pass

    logger.info("Audio saved: %s (%d samples @ %dHz)", filename, len(audio_array), sample_rate)
    return filename

async def _enhance_lyrics_with_llm(prompt: str) -> str:
    """Generate song lyrics from a short prompt using the local LLM."""
    import httpx
    from config import OLLAMA_HOST, OLLAMA_MODEL
    
    system_prompt = (
        "You are an expert lyricist. The user will give you a short theme or idea. "
        "Your mission is to write A SINGLE short VERSE and a very catchy CHORUS on this theme. "
        "IMPORTANT: Keep the text very short (maximum 40 words). Do not include any introduction, title, or explanation. "
        "Write only the lyrics of the song."
    )
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{OLLAMA_HOST}/api/chat",
                json={
                    "model": OLLAMA_MODEL,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        # /no_think disables Qwen 3 reasoning chain for fast output
                        {"role": "user", "content": f"/no_think\n{prompt}"}
                    ],
                    "stream": False,
                    "options": {"temperature": 0.7, "num_predict": 256}
                }
            )
            if resp.status_code == 200:
                data = resp.json()
                lyrics = data.get("message", {}).get("content", "").strip()
                # Clean AI reasoning leakage (<think> blocks, self-commentary)
                if lyrics:
                    from app.tools_image import _clean_llm_output
                    lyrics = _clean_llm_output(lyrics)
                if lyrics:
                    return lyrics
    except Exception as e:
        logger.warning("LLM lyrics enhancement failed: %s", e)
        
    return prompt



async def _generate_tts(text, voice_style="female_soft", language="auto", duration_max=300):
    """Generate speech from text using SpeechT5."""
    import torch
    import numpy as np

    pipeline = _get_tts_pipeline("speecht5")

    preset = VOICE_PRESETS.get(voice_style, VOICE_PRESETS["female_soft"])
    speaker_idx = preset["speecht5_speaker"] % len(pipeline["embeddings"])
    speaker_embedding = pipeline["embeddings"][speaker_idx].unsqueeze(0)

    if _gpu_ok:
        speaker_embedding = speaker_embedding.to("cuda")

    processor = pipeline["processor"]
    model = pipeline["model"]
    vocoder = pipeline["vocoder"]

    # Split text into chunks (SpeechT5 has ~600 char limit)
    chunks = _split_text(text, max_len=500)
    all_audio = []

    for chunk in chunks:
        inputs = processor(text=chunk, return_tensors="pt")
        if _gpu_ok:
            inputs = {k: v.to("cuda") for k, v in inputs.items()}

        with torch.no_grad():
            speech = model.generate_speech(
                inputs["input_ids"],
                speaker_embedding,
                vocoder=vocoder,
            )
        all_audio.append(speech.cpu().numpy())

    audio = np.concatenate(all_audio) if len(all_audio) > 1 else all_audio[0]

    # Trim to max duration
    sample_rate = 16000
    max_samples = int(duration_max * sample_rate)
    if len(audio) > max_samples:
        audio = audio[:max_samples]

    return audio, sample_rate


async def _generate_tts_bark(text, voice_style="female_soft", language="auto"):
    """Generate speech using Bark (more natural, multi-language)."""
    import torch
    import numpy as np

    pipeline = _get_tts_pipeline("bark")
    preset = VOICE_PRESETS.get(voice_style, VOICE_PRESETS["female_soft"])

    processor = pipeline["processor"]
    model = pipeline["model"]

    # Bark uses voice presets (e.g. "v2/fr_speaker_0")
    voice_preset = preset["bark_speaker"]
    
    # Override language if explicitly selected
    if language and language != "auto":
        parts = voice_preset.split("/")
        if len(parts) == 2 and "_" in parts[1]:
            # Replace 'fr_speaker_0' with '{language}_speaker_0'
            lang_part, rest = parts[1].split("_", 1)
            voice_preset = f"{parts[0]}/{language}_{rest}"

    # Split long text
    chunks = _split_text(text, max_len=200)  # Bark works best with shorter chunks
    all_audio = []

    for chunk in chunks:
        inputs = processor(chunk, voice_preset=voice_preset, return_tensors="pt")
        if _gpu_ok:
            inputs = {k: v.to("cuda") for k, v in inputs.items()}

        with torch.no_grad():
            output = model.generate(**inputs)
        all_audio.append(output.cpu().numpy().squeeze())

    audio = np.concatenate(all_audio) if len(all_audio) > 1 else all_audio[0]
    sample_rate = model.generation_config.sample_rate
    return audio, sample_rate


async def _generate_music(prompt, genre="", tempo_bpm=120, duration=30):
    """Generate instrumental music using MusicGen."""
    import torch
    import numpy as np

    pipeline = _get_music_pipeline("musicgen-small")
    processor = pipeline["processor"]
    model = pipeline["model"]

    # Build enriched prompt
    full_prompt = prompt
    if genre:
        full_prompt = f"{genre} style, {full_prompt}"
    if tempo_bpm:
        full_prompt += f", {tempo_bpm} BPM"

    inputs = processor(text=[full_prompt], padding=True, return_tensors="pt")
    if _gpu_ok:
        inputs = {k: v.to("cuda") for k, v in inputs.items()}

    # Calculate max tokens for duration (MusicGen generates at 50 tokens/sec by default)
    max_new_tokens = int(duration * 50)
    max_new_tokens = min(max_new_tokens, 6000)  # Cap at ~120s

    with torch.no_grad():
        audio_values = model.generate(**inputs, max_new_tokens=max_new_tokens)

    audio = audio_values[0, 0].cpu().numpy()
    sample_rate = model.config.audio_encoder.sampling_rate
    return audio, sample_rate


def _split_text(text, max_len=500):
    """Split text into chunks at sentence boundaries."""
    if len(text) <= max_len:
        return [text]

    sentences = re.split(r'(?<=[.!?])\s+', text)
    chunks = []
    current = ""

    for s in sentences:
        if len(current) + len(s) + 1 > max_len:
            if current:
                chunks.append(current.strip())
            current = s
        else:
            current = (current + " " + s).strip()

    if current:
        chunks.append(current.strip())

    return chunks if chunks else [text[:max_len]]


# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------

@router.post("/generate")
async def generate_audio(request: Request):
    """Generate audio (TTS, music, voice clone, or song)."""
    data = await request.json()
    mode = data.get("mode", "tts")
    text = data.get("text", "").strip()
    prompt = data.get("prompt", "").strip()
    voice_style = data.get("voice_style", "female_soft")
    genre = data.get("genre", "")
    tempo_bpm = int(data.get("tempo_bpm", 120))
    duration = min(float(data.get("duration", 30)), 300)
    format_type = data.get("format", "wav")
    language = data.get("language", "auto")
    tts_engine = data.get("tts_engine", "speecht5")

    enhance_prompt = data.get("enhance_prompt", False)

    if format_type not in ("wav", "mp3", "ogg"):
        format_type = "wav"

    generated_prompt = None

    global _audio_generation_progress
    _audio_generation_progress = {
        "active": True, "progress": 5.0, "stage": "loading_model",
    }

    try:
        if mode == "tts":
            if not text:
                raise HTTPException(400, "Text is required for TTS")
            
            _audio_generation_progress = {
                "active": True, "progress": 20.0, "stage": "generating",
            }
            if tts_engine == "bark":
                audio, sr = await _generate_tts_bark(text, voice_style, language)
                _audio_generation_progress["progress"] = 80.0
            else:
                audio, sr = await _generate_tts(text, voice_style, language, duration)
                _audio_generation_progress["progress"] = 80.0

            _audio_generation_progress = {
                "active": True, "progress": 90.0, "stage": "saving",
            }
            meta_prompt = f"[TTS/{voice_style}] {text[:200]}"
            filename = _save_audio(audio, sr, format_type, meta_prompt, mode=mode)

        elif mode == "voice_clone":
            _audio_generation_progress = {
                "active": True, "progress": 20.0, "stage": "generating",
            }
            ref_audio = data.get("reference_audio", "")
            if not ref_audio or not text:
                raise HTTPException(400, "Text and reference audio required for voice cloning")

            # Voice cloning via TTS library (Coqui XTTS-v2)
            ref_path = os.path.join(AUDIO_DIR, ref_audio)
            if not os.path.exists(ref_path):
                raise HTTPException(404, "Reference audio not found")

            try:
                from TTS.api import TTS as CoquiTTS
                _release_all_audio()
                _release_image_pipelines()

                tts = CoquiTTS("tts_models/multilingual/multi-dataset/xtts_v2")
                if _gpu_ok:
                    tts = tts.to("cuda")

                import tempfile
                with tempfile.NamedTemporaryFile(suffix=f".{format_type}", delete=False) as tmp:
                    tmp_path = tmp.name

                tts.tts_to_file(
                    text=text,
                    speaker_wav=ref_path,
                    language=language if language != "auto" else "fr",
                    file_path=tmp_path,
                )

                # Move to audio dir
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                uid = uuid.uuid4().hex[:6]
                filename = f"clone_{timestamp}_{uid}.{format_type}"
                filepath = os.path.join(AUDIO_DIR, filename)

                import shutil
                shutil.move(tmp_path, filepath)

                # Save metadata
                import json
                meta_path = os.path.join(AUDIO_DIR, filename + ".meta")
                with open(meta_path, "w") as f:
                    # Coqui XTTS generates 24kHz audio usually
                    duration_sec = os.path.getsize(filepath) / (24000 * 2)  # rough estimation
                    json.dump({
                        "prompt": f"[Clone] {text[:200]}", 
                        "created": datetime.now().isoformat(),
                        "mode": mode,
                        "duration": duration_sec
                    }, f)

                del tts
                import gc
                gc.collect()
                if _gpu_ok:
                    import torch
                    torch.cuda.empty_cache()

            except ImportError:
                raise HTTPException(500, "TTS library (Coqui) not installed. Run: pip install TTS")

        elif mode in ("music", "song"):
            _audio_generation_progress = {
                "active": True, "progress": 15.0, "stage": "generating",
            }
            desc = prompt or text or "upbeat electronic music"
            
            if mode == "song" and text:
                if enhance_prompt:
                    text = await _enhance_lyrics_with_llm(text)
                    generated_prompt = text
                desc = f"song with lyrics theme: {text[:100]}, {desc}"

            audio, sr = await _generate_music(desc, genre, tempo_bpm, duration)
            _audio_generation_progress = {
                "active": True, "progress": 90.0, "stage": "saving",
            }
            meta_prompt = f"[{'Song' if mode == 'song' else 'Music'}/{genre or 'auto'}] {desc[:200]}"
            filename = _save_audio(audio, sr, format_type, meta_prompt, mode=mode)

        else:
            raise HTTPException(400, f"Unknown mode: {mode}")

        _audio_generation_progress["active"] = False
        result = {
            "status": "ok",
            "filename": filename,
            "url": f"/data/audio/{filename}",
            "mode": mode,
        }
        if generated_prompt:
            result["prompt"] = generated_prompt
        return result

    except HTTPException:
        _audio_generation_progress["active"] = False
        raise
    except Exception as e:
        _audio_generation_progress["active"] = False
        logger.error("Audio generation failed: %s", e, exc_info=True)
        return {"error": str(e)}


@router.get("/gallery")
async def audio_gallery():
    """List all generated audio files."""
    files = []
    for f in sorted(os.listdir(AUDIO_DIR), reverse=True):
        if f.endswith((".wav", ".mp3", ".ogg")):
            meta_path = os.path.join(AUDIO_DIR, f + ".meta")
            prompt = ""
            mode = "unknown"
            duration = 0.0
            try:
                import json
                with open(meta_path) as mf:
                    meta = json.load(mf)
                    prompt = meta.get("prompt", "")
                    mode = meta.get("mode", "unknown")
                    duration = meta.get("duration", 0.0)
            except Exception:
                pass

            files.append({
                "filename": f,
                "format": f.rsplit(".", 1)[-1],
                "prompt": prompt,
                "mode": mode,
                "duration": duration,
                "size": os.path.getsize(os.path.join(AUDIO_DIR, f)),
            })

    return {"audio_files": files}


@router.post("/upload-reference")
async def upload_reference(file: UploadFile = File(...)):
    """Upload reference audio for voice cloning."""
    if not file.filename:
        raise HTTPException(400, "No file provided")

    ext = file.filename.rsplit(".", 1)[-1].lower()
    if ext not in ("wav", "mp3", "ogg", "flac", "m4a"):
        raise HTTPException(400, "Unsupported audio format")

    uid = uuid.uuid4().hex[:8]
    filename = f"ref_{uid}.{ext}"
    filepath = os.path.join(AUDIO_DIR, filename)

    content = await file.read()
    with open(filepath, "wb") as f:
        f.write(content)

    return {"filename": filename, "url": f"/data/audio/{filename}"}


@router.delete("/delete")
async def delete_audio(request: Request):
    """Delete an audio file."""
    data = await request.json()
    filename = data.get("filename", "")
    if not filename:
        raise HTTPException(400, "filename required")

    filepath = os.path.join(AUDIO_DIR, filename)
    meta_path = filepath + ".meta"

    if os.path.exists(filepath):
        os.remove(filepath)
    if os.path.exists(meta_path):
        os.remove(meta_path)

    return {"status": "ok", "deleted": filename}


@router.get("/check-model")
async def check_audio_model(mode: str = "tts", tts_engine: str = "speecht5"):
    """Check if the audio model is already downloaded."""
    from pathlib import Path

    cache_dir = Path.home() / ".cache" / "huggingface" / "hub"

    model_map = {
        "tts": {
            "speecht5": "microsoft/speecht5_tts",
            "bark": "suno/bark",
        },
        "music": {"default": "facebook/musicgen-small"},
        "song": {"default": "facebook/musicgen-small"},
        "voice_clone": {"default": "coqui/XTTS-v2"},
    }

    models = model_map.get(mode, {})
    target = models.get(tts_engine, models.get("default", ""))

    if not target:
        return {"downloaded": True}

    # Check if model folder exists in HF cache
    safe_name = "models--" + target.replace("/", "--")
    model_path = cache_dir / safe_name
    downloaded = model_path.exists() and any(model_path.rglob("*.safetensors")) or any(model_path.rglob("*.bin"))

    return {"downloaded": bool(downloaded), "model": target}


@router.get("/download-status")
async def download_status():
    """Return current model download progress."""
    return _audio_download_state

@router.get("/generation-progress")
async def audio_generation_progress():
    """Return the current audio generation progress."""
    return _audio_generation_progress
