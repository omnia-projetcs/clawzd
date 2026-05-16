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

# Disable the safetensors auto-conversion background thread.
# It tries to create a conversion PR on HuggingFace Hub and times out.
try:
    import transformers.safetensors_conversion
    transformers.safetensors_conversion.auto_conversion = lambda *a, **kw: None
except Exception:
    pass

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
# Bark v2 FR speakers — community-verified gender mapping:
#   0 = male (deep, mature)      3 = male (medium, standard)
#   1 = female (warm, soft)      2 = female (young, bright)
#   4 = male (slightly higher)   5 = female (confident, pro)
#   6 = male  7 = female  8 = male  9 = female
# "gender_tag" is prepended to Bark input to bias the model's voice.
VOICE_PRESETS = {
    "male_deep":   {"description": "Man (deep)",   "bark_speaker": "v2/fr_speaker_0", "speecht5_speaker": 1, "gender_tag": "[MAN] ",
                    "edge_fr": "fr-FR-HenriNeural", "edge_en": "en-US-GuyNeural", "espeak_variant": "+m1"},
    "male_medium": {"description": "Man (medium)", "bark_speaker": "v2/fr_speaker_3", "speecht5_speaker": 5, "gender_tag": "[MAN] ",
                    "edge_fr": "fr-FR-RemyMultilingualNeural", "edge_en": "en-US-AndrewNeural", "espeak_variant": "+m3"},
    "female_soft":  {"description": "Woman (soft)",  "bark_speaker": "v2/fr_speaker_1", "speecht5_speaker": 2, "gender_tag": "[WOMAN] ",
                    "edge_fr": "fr-FR-DeniseNeural", "edge_en": "en-US-JennyNeural", "espeak_variant": "+f2"},
    "female_pro":   {"description": "Woman (pro)",   "bark_speaker": "v2/fr_speaker_5", "speecht5_speaker": 6, "gender_tag": "[WOMAN] ",
                    "edge_fr": "fr-FR-VivienneMultilingualNeural", "edge_en": "en-US-AvaNeural", "espeak_variant": "+f4"},
    "child":        {"description": "Child",         "bark_speaker": "v2/fr_speaker_2", "speecht5_speaker": 2, "gender_tag": "",
                    "edge_fr": "fr-FR-EloiseNeural", "edge_en": "en-US-AnaNeural", "espeak_variant": "+f5"},
    "robot":        {"description": "Robot",         "bark_speaker": "v2/en_speaker_9", "speecht5_speaker": 4, "gender_tag": "",
                    "edge_fr": "fr-FR-HenriNeural", "edge_en": "en-US-EricNeural", "espeak_variant": "+m7"},
    "narrator":     {"description": "Narrator",      "bark_speaker": "v2/en_speaker_6", "speecht5_speaker": 0, "gender_tag": "[MAN] ",
                    "edge_fr": "fr-FR-RemyMultilingualNeural", "edge_en": "en-US-BrianNeural", "espeak_variant": "+m1"},
}

# Edge TTS language → locale mapping
_EDGE_LANG_MAP = {
    "fr": "fr-FR", "en": "en-US", "es": "es-ES", "de": "de-DE",
    "it": "it-IT", "pt": "pt-BR", "ja": "ja-JP", "zh": "zh-CN",
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

# Cancel flag for audio generation
_audio_cancel_requested = False
_audio_current_task_id = ""


def _cancel_audio_generation(task_id: str = ""):
    """Request cancellation of a running audio generation."""
    global _audio_cancel_requested
    _audio_cancel_requested = True
    _audio_generation_progress["active"] = False


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
                torch_dtype=torch.float32,
                use_safetensors=False,
            )
            # ── Sanitise generation_config to suppress transformers warnings ──
            gc = model.generation_config
            # 1. pad_token_id must be set explicitly
            if gc.pad_token_id is None:
                gc.pad_token_id = gc.eos_token_id
            # 2. Remove deprecated `min_eos_p` — it triggers a
            #    "generation_config + generation-related args" warning
            if hasattr(gc, "min_eos_p"):
                delattr(gc, "min_eos_p")
            # 3. Clear the default max_length=20 that conflicts with
            #    max_new_tokens=768 set by Bark internally
            if getattr(gc, "max_length", None) is not None:
                gc.max_length = None
            if _gpu_ok:
                model = model.to("cuda")
            _tts_pipeline = {"type": "bark", "processor": processor, "model": model}

        else:  # speecht5
            from transformers import SpeechT5Processor, SpeechT5ForTextToSpeech, SpeechT5HifiGan
            logger.info("Loading SpeechT5 TTS model...")
            processor = SpeechT5Processor.from_pretrained("microsoft/speecht5_tts", local_files_only=_should_use_local_files("microsoft/speecht5_tts"))
            model = SpeechT5ForTextToSpeech.from_pretrained("microsoft/speecht5_tts", local_files_only=_should_use_local_files("microsoft/speecht5_tts"),
                use_safetensors=False,
            )
            vocoder = SpeechT5HifiGan.from_pretrained("microsoft/speecht5_hifigan", local_files_only=_should_use_local_files("microsoft/speecht5_hifigan"),
                use_safetensors=False,
            )
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
                resp = urllib.request.urlopen(url, timeout=60)
                embeddings = []
                with zipfile.ZipFile(io.BytesIO(resp.read())) as z:
                    npy_files = sorted([n for n in z.namelist() if n.endswith(".npy")])
                    for f in npy_files[:7]:
                        with z.open(f) as npy_file:
                            x = np.load(io.BytesIO(npy_file.read()))
                            embeddings.append(torch.tensor(x))
                torch.save(embeddings, embeddings_path)
                logger.info("Saved SpeechT5 speaker embeddings.")
            
            embeddings_dataset = torch.load(embeddings_path, weights_only=True)
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
            torch_dtype=torch.float32,
            use_safetensors=False,
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
        max_val = np.max(np.abs(audio_array))
        if max_val > 0.95:
            # Only normalize if it's clipping or too loud
            audio_array = audio_array / max_val * 0.95
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
    total_chunks = len(chunks)

    logger.info("SpeechT5 TTS: %d chunk(s) to generate from %d chars", total_chunks, len(text))

    for i, chunk in enumerate(chunks):
        # Update progress: 20% → 80% spread over chunks
        pct = 20.0 + (i / max(total_chunks, 1)) * 60.0
        _audio_generation_progress.update({"active": True, "progress": pct,
            "stage": f"chunk {i+1}/{total_chunks}"})

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
        all_audio.append(np.zeros(int(16000 * 0.25), dtype=np.float32))

    if all_audio:
        all_audio.pop() # remove trailing silence

    audio = np.concatenate(all_audio) if len(all_audio) > 1 else all_audio[0]

    # Trim to max duration
    sample_rate = 16000
    max_samples = int(duration_max * sample_rate)
    if len(audio) > max_samples:
        audio = audio[:max_samples]

    return audio, sample_rate


def _generate_tts_espeak_sync(text, voice_style="female_soft", language="auto", duration_max=300):
    """Generate TTS using espeak-ng directly via subprocess.

    Bypasses pyttsx3 entirely to avoid the SetVoiceByName bug on
    modern espeak-ng where voice IDs use the family/lang format.
    """
    import tempfile
    import os
    import numpy as np
    import scipy.io.wavfile as wav

    lang_code = "fr" if language == "auto" else language
    preset = VOICE_PRESETS.get(voice_style, VOICE_PRESETS["female_soft"])
    variant = preset.get("espeak_variant", "")

    # Build espeak-ng voice string: language + optional variant
    voice = lang_code + variant  # e.g. "fr+f2", "en+m1"

    # Speed: slightly slower for deep voices, default 150 wpm
    speed = "130" if "deep" in voice_style else "150"

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        import subprocess
        result = subprocess.run(
            ["espeak-ng", "-v", voice, "-s", speed, "-a", "80",
             "-w", tmp_path, text],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode != 0:
            logger.warning("espeak-ng failed (rc=%d): %s", result.returncode, result.stderr)
            # Fallback: try without variant
            subprocess.run(
                ["espeak-ng", "-v", lang_code, "-s", speed, "-a", "80",
                 "-w", tmp_path, text],
                capture_output=True, text=True, timeout=120, check=True
            )

        if not os.path.exists(tmp_path) or os.path.getsize(tmp_path) == 0:
            raise RuntimeError("espeak-ng failed to generate audio file.")

        sample_rate, audio = wav.read(tmp_path)

        if len(audio.shape) > 1:
            audio = audio.mean(axis=1)

        if audio.dtype == np.int16:
            audio = audio.astype(np.float32) / 32767.0
        elif audio.dtype == np.int32:
            audio = audio.astype(np.float32) / 2147483648.0

        max_samples = int(duration_max * sample_rate)
        if len(audio) > max_samples:
            audio = audio[:max_samples]

        return audio, sample_rate

    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


async def _generate_tts_espeak(text, voice_style="female_soft", language="auto", duration_max=300):
    """Async wrapper for espeak-ng TTS."""
    import asyncio
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _generate_tts_espeak_sync, text, voice_style, language, duration_max)


async def _generate_tts_edge(text, voice_style="female_soft", language="auto", duration_max=300):
    """Generate TTS using Microsoft Edge neural voices (edge-tts).

    Produces crystal-clear, natural-sounding speech with no crackling
    or background noise. Requires internet access.
    """
    import edge_tts
    import tempfile
    import os
    import numpy as np
    import scipy.io.wavfile as wav

    preset = VOICE_PRESETS.get(voice_style, VOICE_PRESETS["female_soft"])
    lang_code = "fr" if language == "auto" else language

    # Pick the right Edge voice for the language
    if lang_code in ("fr", "fr-fr", "fr-be", "fr-ch"):
        voice_name = preset.get("edge_fr", "fr-FR-DeniseNeural")
    elif lang_code in ("en", "en-us", "en-gb"):
        voice_name = preset.get("edge_en", "en-US-JennyNeural")
    else:
        # For other languages, try to find a matching locale
        locale = _EDGE_LANG_MAP.get(lang_code, f"{lang_code}-{lang_code.upper()}")
        # Use Multilingual voices for best coverage
        if "female" in voice_style or "child" in voice_style:
            voice_name = preset.get("edge_fr", "fr-FR-VivienneMultilingualNeural")
        else:
            voice_name = preset.get("edge_en", "en-US-AndrewMultilingualNeural")
        # Override with locale-specific if possible
        try:
            voices = await edge_tts.list_voices()
            for v in voices:
                if v["Locale"].startswith(lang_code):
                    wanted_gender = "Female" if ("female" in voice_style or "child" in voice_style) else "Male"
                    if v["Gender"] == wanted_gender:
                        voice_name = v["ShortName"]
                        break
        except Exception:
            pass  # Keep default voice

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        tmp_mp3 = tmp.name
    tmp_wav = tmp_mp3.replace(".mp3", ".wav")

    try:
        communicate = edge_tts.Communicate(text, voice_name)
        await communicate.save(tmp_mp3)

        if not os.path.exists(tmp_mp3) or os.path.getsize(tmp_mp3) == 0:
            raise RuntimeError(f"Edge TTS failed to generate audio for voice {voice_name}.")

        # Convert MP3 → WAV for consistent pipeline handling
        import subprocess
        subprocess.run(
            ["ffmpeg", "-y", "-i", tmp_mp3, "-ar", "24000", "-ac", "1", tmp_wav],
            capture_output=True, timeout=60, check=True
        )

        sample_rate, audio = wav.read(tmp_wav)

        if len(audio.shape) > 1:
            audio = audio.mean(axis=1)

        if audio.dtype == np.int16:
            audio = audio.astype(np.float32) / 32767.0
        elif audio.dtype == np.int32:
            audio = audio.astype(np.float32) / 2147483648.0

        max_samples = int(duration_max * sample_rate)
        if len(audio) > max_samples:
            audio = audio[:max_samples]

        logger.info("Edge TTS: generated %d samples @ %dHz with voice %s", len(audio), sample_rate, voice_name)
        return audio, sample_rate

    finally:
        for p in (tmp_mp3, tmp_wav):
            if os.path.exists(p):
                os.remove(p)



def _denoise_audio(audio, sample_rate, strength=0.03):
    """Multi-stage cleanup to remove crackling, hiss, and saturation.

    1. High-pass at 80 Hz — removes DC offset and low rumble.
    2. Low-pass at min(sr/2-100, 8000) Hz — cuts harsh high-frequency artefacts.
    3. Soft noise-gate — zeros out samples below `strength` amplitude.
    4. Peak normalization to -3 dBFS — prevents saturation.
    """
    import numpy as np
    try:
        from scipy.signal import butter, sosfilt
        # High-pass at 80 Hz (2nd-order Butterworth)
        sos_hp = butter(2, 80, btype="high", fs=sample_rate, output="sos")
        audio = sosfilt(sos_hp, audio).astype(np.float32)

        # Low-pass to cut harsh artefacts (clamp below Nyquist)
        lp_freq = min(8000, sample_rate / 2 - 100)
        if lp_freq > 100:
            sos_lp = butter(3, lp_freq, btype="low", fs=sample_rate, output="sos")
            audio = sosfilt(sos_lp, audio).astype(np.float32)
    except Exception:
        pass  # scipy unavailable — skip filters

    # Soft noise-gate: zero out very quiet samples (hiss in pauses)
    gate = np.abs(audio) > strength
    audio = audio * gate

    # Peak-normalize to -3 dBFS (≈ 0.707) to avoid saturation
    peak = np.max(np.abs(audio))
    if peak > 0.01:
        audio = audio / peak * 0.707

    return audio


async def _generate_tts_bark(text, voice_style="female_soft", language="auto"):
    """Generate speech using Bark (more natural, multi-language).

    Bark generates ~13 s of audio per chunk.  French speech averages
    ~5 chars/word and ~150 words/min → one chunk ≈ 100 chars to stay
    safely within 13 s.  We split aggressively so that the model
    reproduces the *entire* input text without truncation.
    """
    import torch
    import numpy as np

    pipeline = _get_tts_pipeline("bark")
    preset = VOICE_PRESETS.get(voice_style, VOICE_PRESETS["female_soft"])

    processor = pipeline["processor"]
    model = pipeline["model"]

    # Bark uses voice presets (e.g. "v2/fr_speaker_0")
    voice_preset = preset["bark_speaker"]
    gender_tag = preset.get("gender_tag", "")

    # Override language if explicitly selected
    if language and language != "auto":
        parts = voice_preset.split("/")
        if len(parts) == 2 and "_" in parts[1]:
            lang_part, rest = parts[1].split("_", 1)
            voice_preset = f"{parts[0]}/{language}_{rest}"

    # ── Split text into SHORT chunks (≤100 chars) ──────────────────────
    # Bark can only reliably produce ~13 s of audio per generation.
    # 100 chars ≈ 20 words ≈ 8-10 s of speech → safe margin.
    chunks = _split_text(text, max_len=100)
    all_audio = []
    total_chunks = len(chunks)

    sample_rate = model.generation_config.sample_rate
    silence = np.zeros(int(sample_rate * 0.25), dtype=np.float32)

    logger.info("Bark TTS: %d chunk(s) to generate from %d chars", total_chunks, len(text))

    for i, chunk in enumerate(chunks):
        # Update progress: 20% → 80% spread over chunks
        pct = 20.0 + (i / max(total_chunks, 1)) * 60.0
        _audio_generation_progress.update({"active": True, "progress": pct,
            "stage": f"chunk {i+1}/{total_chunks}"})

        # Prepend gender bias tag for more consistent voice output
        tagged_chunk = gender_tag + chunk if gender_tag else chunk

        inputs = processor(tagged_chunk, voice_preset=voice_preset, return_tensors="pt")
        if _gpu_ok:
            inputs = {k: v.to("cuda") for k, v in inputs.items()}

        # Build explicit attention_mask for every tensor that looks like
        # token ids — this suppresses the "attention_mask not set" warning.
        for key in list(inputs.keys()):
            mask_key = key.replace("input_ids", "attention_mask")
            if key.endswith("input_ids") and mask_key not in inputs:
                inputs[mask_key] = torch.ones_like(inputs[key])

        with torch.no_grad():
            # Lower temperatures → more conservative, fewer artifacts/crackling
            #   semantic_temperature:  controls text-to-semantic tokens (default 0.7)
            #   coarse_temperature:    controls coarse acoustic tokens (default 0.7)
            #   fine_temperature:      controls fine acoustic tokens   (default 0.5)
            output = model.generate(
                **inputs,
                semantic_temperature=0.6,
                coarse_temperature=0.5,
                fine_temperature=0.4,
            )
        all_audio.append(output.cpu().numpy().squeeze())
        all_audio.append(silence)

    if all_audio:
        all_audio.pop()  # remove trailing silence

    audio = np.concatenate(all_audio) if len(all_audio) > 1 else all_audio[0]

    # Post-processing: remove crackling / hiss
    audio = _denoise_audio(audio, sample_rate)

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

    # Estimate generation time and start a progress thread
    import threading, time as _time
    _est_seconds = duration * (0.5 if _gpu_ok else 3.0)
    _music_start = _time.monotonic()
    _music_done = threading.Event()

    def _music_progress_updater():
        while not _music_done.is_set():
            elapsed = _time.monotonic() - _music_start
            # Estimate progress: 15% → 85% based on estimated time
            pct = 15.0 + min(70.0, (elapsed / max(_est_seconds, 1.0)) * 70.0)
            _audio_generation_progress.update({"active": True, "progress": pct,
                "stage": f"generating ({int(elapsed)}s)"})
            _music_done.wait(timeout=1.0)

    progress_thread = threading.Thread(target=_music_progress_updater, daemon=True)
    progress_thread.start()

    try:
        with torch.no_grad():
            audio_values = model.generate(**inputs, max_new_tokens=max_new_tokens)
    finally:
        _music_done.set()
        progress_thread.join(timeout=2.0)

    audio = audio_values[0, 0].cpu().numpy()
    sample_rate = model.config.audio_encoder.sampling_rate
    return audio, sample_rate


def _split_text(text, max_len=500):
    """Split text into chunks that the TTS model can handle faithfully.

    Priority order:
      1. Split on sentence boundaries  ( .  !  ?  …  )
      2. Split on clause boundaries     ( ,  ;  :  –  — )
      3. Split on word boundaries       (spaces)

    Every returned chunk is guaranteed ≤ max_len characters.
    """
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_len:
        return [text]

    # ── Pass 1: split on sentence boundaries ────────────────────
    sentence_re = re.compile(r'(?<=[.!?…])\s+')
    raw_sentences = sentence_re.split(text)

    # ── Pass 2: break any sentence still > max_len on clause marks
    clause_re = re.compile(r'(?<=[,;:–—])\s+')
    fragments = []
    for s in raw_sentences:
        if len(s) <= max_len:
            fragments.append(s)
        else:
            for part in clause_re.split(s):
                fragments.append(part)

    # ── Pass 3: break any fragment still > max_len on word boundaries
    fine = []
    for frag in fragments:
        if len(frag) <= max_len:
            fine.append(frag)
        else:
            words = frag.split()
            buf = ""
            for w in words:
                if buf and len(buf) + 1 + len(w) > max_len:
                    fine.append(buf)
                    buf = w
                else:
                    buf = (buf + " " + w).strip()
            if buf:
                fine.append(buf)

    # ── Pass 4: merge tiny fragments back together (≥ 30 chars pref.)
    chunks = []
    current = ""
    for f in fine:
        if current and len(current) + 1 + len(f) > max_len:
            chunks.append(current.strip())
            current = f
        else:
            current = (current + " " + f).strip()
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
    tts_engine = data.get("tts_engine", "bark")

    enhance_prompt = data.get("enhance_prompt", False)

    if format_type not in ("wav", "mp3", "ogg"):
        format_type = "wav"

    generated_prompt = None

    global _audio_generation_progress, _audio_cancel_requested, _audio_current_task_id
    _audio_cancel_requested = False

    # Generate task ID for tracking
    import uuid as _uuid
    _audio_current_task_id = f"audio_{_uuid.uuid4().hex[:8]}"

    from app.tools.task_manager import register_task, unregister_task
    register_task(_audio_current_task_id, "audio", (text or prompt)[:60], {"mode": mode})

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
            if tts_engine == "edge":
                audio, sr = await _generate_tts_edge(text, voice_style, language, duration)
                _audio_generation_progress["progress"] = 80.0
            elif tts_engine == "bark":
                audio, sr = await _generate_tts_bark(text, voice_style, language)
                _audio_generation_progress["progress"] = 80.0
            elif tts_engine == "pyttsx3":
                audio, sr = await _generate_tts_espeak(text, voice_style, language, duration)
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

        elif mode == "song":
            _audio_generation_progress = {
                "active": True, "progress": 15.0, "stage": "generating",
            }
            if not text:
                raise HTTPException(400, "Lyrics (text) are required for song generation")
                
            if enhance_prompt:
                text = await _enhance_lyrics_with_llm(text)
                generated_prompt = text
                
            # Format text for Bark singing
            # Using music notes helps Bark realize it should sing, but can bias it towards English.
            # We wrap the text in notes and add a language hint if not auto.
            lang_hint = f"[{language.upper()}] " if language and language != "auto" else ""
            song_text = "♪ " + lang_hint + text.replace("\n", " ♪\n♪ ") + " ♪"
            song_text = song_text.replace("♪ ♪", "♪")
            
            audio, sr = await _generate_tts_bark(song_text, voice_style=voice_style, language=language)
            
            _audio_generation_progress = {
                "active": True, "progress": 90.0, "stage": "saving",
            }
            meta_prompt = f"[Song/{voice_style}] {text[:200]}"
            filename = _save_audio(audio, sr, format_type, meta_prompt, mode=mode)

        elif mode == "music":
            _audio_generation_progress = {
                "active": True, "progress": 15.0, "stage": "generating",
            }
            desc = prompt or text or "upbeat electronic music"
            audio, sr = await _generate_music(desc, genre, tempo_bpm, duration)
            _audio_generation_progress = {
                "active": True, "progress": 90.0, "stage": "saving",
            }
            meta_prompt = f"[Music/{genre or 'auto'}] {desc[:200]}"
            filename = _save_audio(audio, sr, format_type, meta_prompt, mode=mode)

        else:
            raise HTTPException(400, f"Unknown mode: {mode}")

        _audio_generation_progress["active"] = False
        unregister_task(_audio_current_task_id)
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
        unregister_task(_audio_current_task_id)
        raise
    except Exception as e:
        _audio_generation_progress["active"] = False
        unregister_task(_audio_current_task_id)
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
    from config import MODELS_DIR

    cache_dir = Path(MODELS_DIR) / "hub"

    model_map = {
        "tts": {
            "speecht5": "microsoft/speecht5_tts",
            "bark": "suno/bark",
        },
        "music": {"default": "facebook/musicgen-small"},
        "song": {"default": "suno/bark"},
        "voice_clone": {"default": "coqui/XTTS-v2"},
    }

    models = model_map.get(mode, {})
    target = models.get(tts_engine, models.get("default", ""))

    if not target:
        return {"downloaded": True}

    # Check if model folder exists in HF cache
    safe_name = "models--" + target.replace("/", "--")
    model_path = cache_dir / safe_name
    downloaded = model_path.exists() and (any(model_path.rglob("*.safetensors")) or any(model_path.rglob("*.bin")))

    return {"downloaded": bool(downloaded), "model": target}


@router.get("/download-status")
async def download_status():
    """Return current model download progress."""
    return _audio_download_state

@router.get("/generation-progress")
async def audio_generation_progress():
    """Return the current audio generation progress."""
    return _audio_generation_progress


@router.post("/estimate")
async def estimate_audio(request: Request):
    """Estimate generation time and output audio duration for a given text.

    Returns:
        chunks:          number of TTS chunks that will be generated
        audio_duration:  estimated output audio length in seconds
        gen_time:        estimated wall-clock generation time in seconds
        gen_time_label:  human-readable generation time string
    """
    data = await request.json()
    text = data.get("text", "").strip()
    mode = data.get("mode", "tts")
    tts_engine = data.get("tts_engine", "speecht5")
    duration = float(data.get("duration", 30))  # for music mode

    if mode == "music":
        # MusicGen: ~50 tokens/s, generation speed ≈ 0.3-1× realtime on GPU
        gen_time = duration * (0.5 if _gpu_ok else 3.0)
        return {
            "chunks": 1,
            "audio_duration": round(duration, 1),
            "gen_time": round(gen_time, 1),
            "gen_time_label": _format_duration(gen_time),
        }

    if not text:
        return {"chunks": 0, "audio_duration": 0, "gen_time": 0, "gen_time_label": "0s"}

    if mode == "song" or tts_engine == "bark":
        # Bark: 100-char chunks, ~13s audio each, ~8s/chunk GPU, ~30s/chunk CPU
        chunks = _split_text(text, max_len=100)
        n = len(chunks)
        audio_dur = n * 10  # ~10s of speech per chunk (conservative)
        per_chunk = 8.0 if _gpu_ok else 30.0
        gen_time = n * per_chunk
    elif tts_engine == "edge":
        # Edge TTS: API based, single chunk, very fast
        n = 1
        word_count = len(text.split())
        audio_dur = word_count / 2.5  # ~150 wpm
        gen_time = max(1.0, len(text) / 200.0)  # fast network call
    elif tts_engine == "pyttsx3":
        # Espeak: local binary, single chunk, instant
        n = 1
        word_count = len(text.split())
        audio_dur = word_count / 2.5  # ~150 wpm
        gen_time = max(0.5, len(text) / 500.0)
    else:
        # SpeechT5: 500-char chunks, ~150 words/min, very fast
        chunks = _split_text(text, max_len=500)
        n = len(chunks)
        word_count = len(text.split())
        audio_dur = word_count / 2.5  # ~150 wpm = 2.5 words/s
        per_chunk = 2.0 if _gpu_ok else 8.0
        gen_time = n * per_chunk

    return {
        "chunks": n,
        "audio_duration": round(audio_dur, 1),
        "gen_time": round(gen_time, 1),
        "gen_time_label": _format_duration(gen_time),
    }


def _format_duration(seconds: float) -> str:
    """Convert seconds to a human-readable string like '1m 30s'."""
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    m = s // 60
    r = s % 60
    return f"{m}m {r}s" if r else f"{m}m"
