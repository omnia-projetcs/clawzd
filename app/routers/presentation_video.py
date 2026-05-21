"""
Clawzd — Presentation Video Export Router.

Handles exporting presentation slides into high-quality .mp4 videos
with AI narrator voices (edge-tts) and speaking circular AI avatars.
"""
import os
import re
import uuid
import math
import asyncio
import logging
import tempfile
import subprocess
from typing import List, Optional
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

import numpy as np
import imageio
from PIL import Image, ImageDraw, ImageOps, ImageFilter

from app.core.llm_provider import get_llm_provider
from app.tools_presentation import _generate_pngs
from config import DATA_DIR, STATIC_DIR

logger = logging.getLogger("clawzd.routers.presentation_video")
router = APIRouter()

class VideoExportRequest(BaseModel):
    pages: List[dict]
    canvas_width: int = 960
    canvas_height: int = 540
    voice: str = "fr-FR-DeniseNeural"
    avatar: str = "sophie"  # thomas, sophie, lucas, none
    avatar_position: str = "bottom-right"  # bottom-right, bottom-left, top-right, top-left
    auto_narrate: bool = False
    subtitles: bool = False
    subtitles_language: str = "none"
def clean_narration_text(text: str) -> str:
    """Cleans up narration text to ensure high-fidelity spoken quality without punctuation or formatting artifacts being spoken."""
    if not text:
        return ""
    # 0. Strip stage directions, placeholders, and bracketed notes (e.g. [Start], [End], [Finish], (laughing))
    text = re.sub(r'\[[^\]]*\]', ' ', text)
    text = re.sub(r'\([^)]*\)', ' ', text)
    
    # 1. Replace common bullet characters, stars, and underscores
    text = text.replace("_", " ")
    text = text.replace("*", " ")
    text = text.replace("•", " ")
    
    # 2. Replace hyphens used for bullet points or lists (e.g. at the start of a sentence or surrounded by spaces)
    text = re.sub(r'(?:^|\s)-\s+', ' ', text) # removes "- " at start or after space
    text = re.sub(r'\s+-\s+', ' ', text)       # removes " - " between words
    
    # 3. Clean up double/multiple spaces
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def format_ass_timestamp(seconds: float) -> str:
    """Format seconds into ASS subtitle format: h:mm:ss.cs (where cs is centiseconds)."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int(round((seconds % 1) * 100))
    if cs == 100:
        s += 1
        cs = 0
        if s == 60:
            m += 1
            s = 0
            if m == 60:
                h += 1
                m = 0
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

async def translate_narration_text(text: str, target_lang: str) -> str:
    """Translates narration text into the requested subtitle language using the default LLM provider."""
    if not text or not target_lang or target_lang == "none":
        return text
    
    lang_names = {
        "fr": "French (Français)",
        "en": "English (Anglais)",
        "es": "Spanish (Español)",
        "de": "German (Deutsch)",
        "it": "Italian (Italiano)"
    }
    target_lang_name = lang_names.get(target_lang.lower(), target_lang)
    
    prompt = (
        f"Translate the following text into fluent, natural {target_lang_name}. "
        "Do NOT add any notes, introductory text, explanations, or quotes. "
        "Return ONLY the clean translation text itself.\n\n"
        f"Text to translate:\n{text}"
    )
    
    try:
        from config import LLM_PROVIDER, OLLAMA_MODEL, VLLM_MODEL, GOOGLE_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY
        from app.core.llm_provider import get_llm_provider, _get_local_models, _get_vllm_models
        
        provider_key = LLM_PROVIDER
        model_key = None
        
        # Self-healing local model scanning
        if provider_key == "ollama":
            try:
                local_models = await _get_local_models()
            except Exception:
                local_models = []
            downloaded_ids = [m["id"] for m in local_models if m.get("id")]
            if downloaded_ids:
                if OLLAMA_MODEL in downloaded_ids:
                    model_key = OLLAMA_MODEL
                elif OLLAMA_MODEL + ":latest" in downloaded_ids:
                    model_key = OLLAMA_MODEL + ":latest"
                else:
                    model_key = downloaded_ids[0]
            else:
                if GOOGLE_API_KEY: provider_key = "google"
                elif OPENAI_API_KEY: provider_key = "openai"
                elif ANTHROPIC_API_KEY: provider_key = "anthropic"
        elif provider_key == "vllm":
            try:
                vllm_models = await _get_vllm_models()
            except Exception:
                vllm_models = []
            active_ids = [m["id"] for m in vllm_models if m.get("id")]
            if active_ids:
                if VLLM_MODEL in active_ids:
                    model_key = VLLM_MODEL
                else:
                    model_key = active_ids[0]
            else:
                if GOOGLE_API_KEY: provider_key = "google"
                elif OPENAI_API_KEY: provider_key = "openai"
                elif ANTHROPIC_API_KEY: provider_key = "anthropic"

        if provider_key in ("google", "openai", "anthropic"):
            if provider_key == "google" and not GOOGLE_API_KEY:
                provider_key = "openai" if OPENAI_API_KEY else ("anthropic" if ANTHROPIC_API_KEY else "ollama")
            elif provider_key == "openai" and not OPENAI_API_KEY:
                provider_key = "google" if GOOGLE_API_KEY else ("anthropic" if ANTHROPIC_API_KEY else "ollama")
            elif provider_key == "anthropic" and not ANTHROPIC_API_KEY:
                provider_key = "google" if GOOGLE_API_KEY else ("openai" if OPENAI_API_KEY else "ollama")

        provider = get_llm_provider(provider_key)
        kwargs = {}
        if model_key:
            kwargs["model"] = model_key
            
        messages = [{"role": "user", "content": prompt}]
        translated = await provider.chat(messages, **kwargs)
        return clean_narration_text(translated.strip())
    except Exception as e:
        logger.error(f"Failed to translate narration script: {e}")
        return text

async def generate_slide_narration_script(slide_elements: List[dict], target_lang: str = "fr") -> str:
    """Uses the default LLM provider to write an engaging script for a slide based on its content."""
    texts = []
    for el in slide_elements:
        if el.get("type") in ("text", "table"):
            content = el.get("content", "").strip()
            if content:
                # Clean up punctuation artifacts from the raw slide texts
                cleaned = clean_narration_text(content)
                if cleaned:
                    texts.append(cleaned)
                
    # Premium fallbacks in target language
    slide_summary = " | ".join(texts[:5]) if texts else ""
    
    if not texts:
        if target_lang == "en":
            return "On this slide, we present the key visual highlights and overview of our current topics."
        else:
            return "Sur cette diapositive, nous vous présentons les informations clés et les éléments visuels de notre présentation."
        
    if target_lang == "fr":
        prompt = (
            "Rédige un script de narration court, engageant et professionnel (2 à 3 phrases maximum) pour un présentateur virtuel présentant cette diapositive. "
            "Le ton doit être naturel et fluide. Ne mets AUCUNE note de présentation, direction scénique ou texte d'introduction. "
            "Rédige impérativement le script en français. "
            "Renvoie uniquement le texte parlé lui-même.\n\n"
            f"Contenu de la diapositive:\n{slide_summary}"
        )
    else:
        prompt = (
            "Write a short, engaging, and professional presentation narration script (2 to 3 sentences maximum) for a virtual presenter presenting this slide. "
            "The tone must be natural and fluent. Do NOT write any stage directions, presenter notes, or introductory text. "
            "You must write the script in English. "
            "Return ONLY the spoken text itself.\n\n"
            f"Slide Content:\n{slide_summary}"
        )
    
    try:
        from config import LLM_PROVIDER, OLLAMA_MODEL, VLLM_MODEL, GOOGLE_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY
        from app.core.llm_provider import get_llm_provider, _get_local_models, _get_vllm_models
        
        provider_key = LLM_PROVIDER
        model_key = None
        
        # Self-healing local model scanning
        if provider_key == "ollama":
            try:
                local_models = await _get_local_models()
            except Exception:
                local_models = []
            downloaded_ids = [m["id"] for m in local_models if m.get("id")]
            if downloaded_ids:
                if OLLAMA_MODEL in downloaded_ids:
                    model_key = OLLAMA_MODEL
                elif OLLAMA_MODEL + ":latest" in downloaded_ids:
                    model_key = OLLAMA_MODEL + ":latest"
                else:
                    model_key = downloaded_ids[0]
                    logger.info(f"Ollama model '{OLLAMA_MODEL}' not found. Falling back to downloaded model '{model_key}'")
            else:
                # No local model found in Ollama, try cloud fallbacks
                if GOOGLE_API_KEY:
                    provider_key = "google"
                elif OPENAI_API_KEY:
                    provider_key = "openai"
                elif ANTHROPIC_API_KEY:
                    provider_key = "anthropic"
                    
        elif provider_key == "vllm":
            try:
                vllm_models = await _get_vllm_models()
            except Exception:
                vllm_models = []
            active_ids = [m["id"] for m in vllm_models if m.get("id")]
            if active_ids:
                if VLLM_MODEL in active_ids:
                    model_key = VLLM_MODEL
                else:
                    model_key = active_ids[0]
                    logger.info(f"vLLM model '{VLLM_MODEL}' not found. Falling back to active model '{model_key}'")
            else:
                # No active vLLM model found, try cloud fallbacks
                if GOOGLE_API_KEY:
                    provider_key = "google"
                elif OPENAI_API_KEY:
                    provider_key = "openai"
                elif ANTHROPIC_API_KEY:
                    provider_key = "anthropic"

        # Check cloud keys and fallbacks
        if provider_key in ("google", "openai", "anthropic"):
            if provider_key == "google" and not GOOGLE_API_KEY:
                provider_key = "openai" if OPENAI_API_KEY else ("anthropic" if ANTHROPIC_API_KEY else "ollama")
            elif provider_key == "openai" and not OPENAI_API_KEY:
                provider_key = "google" if GOOGLE_API_KEY else ("anthropic" if ANTHROPIC_API_KEY else "ollama")
            elif provider_key == "anthropic" and not ANTHROPIC_API_KEY:
                provider_key = "google" if GOOGLE_API_KEY else ("openai" if OPENAI_API_KEY else "ollama")

        # Instantiate resolved provider
        provider = get_llm_provider(provider_key)
        kwargs = {}
        if model_key:
            kwargs["model"] = model_key
            
        messages = [{"role": "user", "content": prompt}]
        script = await provider.chat(messages, **kwargs)
        script = script.strip()
        
        # Robust semantic safety check: prevent speaking raw LLM error messages
        lower_s = script.lower()
        if "ollama" in lower_s or "error" in lower_s or "failed" in lower_s or "connection" in lower_s or len(script) < 5:
            raise ValueError("LLM returned model connection or error message: " + script)
        return script
    except Exception as e:
        logger.error(f"Failed to auto-generate narration script: {e}")
        if target_lang == "en":
            return "Here is the next slide summarizing our primary points and key deliverables."
        else:
            return "Voici la diapositive suivante de notre présentation, résumant les points et objectifs clés."

async def synthesize_speech(text: str, voice: str, output_path: str):
    """Synthesizes high-quality audio narration for a slide using edge-tts with premium denoising and high-fidelity 192k MP3 re-encoding."""
    import edge_tts
    import numpy as np
    import scipy.io.wavfile as wav
    import tempfile
    
    try:
        # Create temp files for intermediate high-quality processing
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp_mp3 = tmp.name
        tmp_wav = tmp_mp3.replace(".mp3", ".wav")
        
        try:
            # 1. Direct Edge-TTS synthesis
            communicate = edge_tts.Communicate(text, voice)
            await communicate.save(tmp_mp3)
            
            if not os.path.exists(tmp_mp3) or os.path.getsize(tmp_mp3) == 0:
                raise RuntimeError("Edge-TTS generated empty audio stream.")
                
            # 2. Convert to pristine 24kHz mono WAV
            subprocess.run(
                ["ffmpeg", "-y", "-i", tmp_mp3, "-ar", "24000", "-ac", "1", tmp_wav],
                capture_output=True, timeout=30, check=True
            )
            
            sample_rate, audio = wav.read(tmp_wav)
            if len(audio.shape) > 1:
                audio = audio.mean(axis=1)
                
            # Convert audio amplitude array to float32 [0.0, 1.0]
            if audio.dtype == np.int16:
                audio = audio.astype(np.float32) / 32767.0
            elif audio.dtype == np.int32:
                audio = audio.astype(np.float32) / 2147483648.0
                
            # 3. Premium Denoising & Multi-Stage Cleanup Filter
            # (High-pass 80Hz, Low-pass 8000Hz, noise-gate 0.03, peak normalize -3dBFS)
            from scipy.signal import butter, sosfilt
            try:
                # High-pass at 80 Hz
                sos_hp = butter(2, 80, btype="high", fs=sample_rate, output="sos")
                audio = sosfilt(sos_hp, audio).astype(np.float32)
                
                # Low-pass at 8000 Hz
                sos_lp = butter(3, 8000, btype="low", fs=sample_rate, output="sos")
                audio = sosfilt(sos_lp, audio).astype(np.float32)
            except Exception as fe:
                logger.warning(f"Denoise Butterworth filter failed: {fe}")
                
            # Soft Noise-Gate: zero out hiss in pauses
            gate = np.abs(audio) > 0.03
            audio = audio * gate
            
            # Peak-Normalize to -3 dBFS (~0.707) to avoid clipping/saturation
            peak = np.max(np.abs(audio))
            if peak > 0.01:
                audio = audio / peak * 0.707
                
            # 4. Save clean wav
            audio_int16 = (audio * 32767).astype(np.int16)
            wav.write(tmp_wav, sample_rate, audio_int16)
            
            # 5. Compress wav back to MP3 with high-fidelity 192k bitrate
            subprocess.run(
                ["ffmpeg", "-y", "-i", tmp_wav, "-b:a", "192k", output_path],
                capture_output=True, timeout=30, check=True
            )
            
        finally:
            # Cleanup temp files
            for p in (tmp_mp3, tmp_wav):
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except Exception:
                        pass
                        
    except Exception as e:
        logger.error(f"High-quality speech synthesis failed: {e}")
        # Fallback to direct edge-tts communicating if denoising chain fails
        try:
            communicate = edge_tts.Communicate(text, voice)
            await communicate.save(output_path)
        except Exception as e2:
            logger.error(f"Fallback edge-tts synthesis failed: {e2}")
            raise RuntimeError(f"La synthèse vocale a échoué : {e2}")

def get_audio_duration(file_path: str) -> float:
    """Extracts MP3 file duration using ffmpeg/ffprobe via subprocess."""
    try:
        cmd = ["ffmpeg", "-i", file_path]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5)
        output = result.stderr
        match = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", output)
        if match:
            hours = int(match.group(1))
            minutes = int(match.group(2))
            seconds = float(match.group(3))
            return hours * 3600 + minutes * 60 + seconds
    except Exception as e:
        logger.error(f"Error parsing audio duration: {e}")
    return 4.0 # fallback

def create_circular_avatar(avatar_name: str, size: int = 160) -> Optional[Image.Image]:
    """Loads a presenter portrait, resizes it to square with alpha (dynamic masking is done per frame)."""
    avatar_file = f"{avatar_name}.png"
    avatar_path = os.path.join(STATIC_DIR, "img", "avatars", avatar_file)
    if not os.path.exists(avatar_path):
        logger.warning(f"Avatar path not found: {avatar_path}")
        return None
        
    try:
        avatar_img = Image.open(avatar_path).convert("RGBA")
        return avatar_img.resize((size, size), Image.Resampling.LANCZOS)
    except Exception as e:
        logger.error(f"Error loading avatar: {e}")
        return None

def overlay_animated_avatar(
    slide_image: Image.Image,
    avatar_img: Image.Image,
    position_mode: str,
    frame_idx: int,
    speech_active: bool
):
    """Draws the talking avatar circle with dynamic Synthesia-style mouth lipsync and an organic HUD."""
    w, h = slide_image.size
    av_size = avatar_img.size[0]
    
    # Position mapping
    margin = 30
    if position_mode == "bottom-left":
        x, y = margin, h - av_size - margin
    elif position_mode == "top-right":
        x, y = w - av_size - margin, margin
    elif position_mode == "top-left":
        x, y = margin, margin
    else: # bottom-right
        x, y = w - av_size - margin, h - av_size - margin
        
    # Dynamic organic human presentation movement (swaying, bobbing, and scaling)
    angle = 0.0
    dy = 0.0
    scale = 1.0
    
    if speech_active:
        # Human swaying / head tilt (sine wave)
        angle = 3.5 * math.sin(frame_idx * 0.15) 
        # Conversational bobbing (up and down)
        dy = 4.0 * math.sin(frame_idx * 0.3)
        # Breathing / talking projection zoom
        scale = 1.0 + 0.03 * math.sin(frame_idx * 0.4)
    else:
        # Subtle breathing sway when not speaking
        angle = 1.0 * math.sin(frame_idx * 0.08)
        dy = 1.5 * math.sin(frame_idx * 0.1)
        scale = 1.0 + 0.01 * math.sin(frame_idx * 0.1)
        
    # 1. Slice avatar to animate jaw dropping (talking mouth cavity)
    split_y = int(av_size * 0.73)
    top_half = avatar_img.crop((0, 0, av_size, split_y))
    bottom_half = avatar_img.crop((0, split_y, av_size, av_size))
    
    jaw_drop = 0
    if speech_active:
        jaw_drop = int(4 * abs(math.sin(frame_idx * 0.75)))
        
    animated = Image.new("RGBA", (av_size, av_size + jaw_drop), (0, 0, 0, 0))
    
    # Draw open mouth oral cavity behind the lips
    if jaw_drop > 0:
        draw_cavity = ImageDraw.Draw(animated)
        cavity_x1 = int(av_size * 0.44)
        cavity_x2 = int(av_size * 0.56)
        cavity_y1 = split_y - 2
        cavity_y2 = split_y + jaw_drop + 2
        # Deep burgundy mouth interior
        draw_cavity.ellipse((cavity_x1, cavity_y1, cavity_x2, cavity_y2), fill=(90, 15, 25, 255))
        # Shiny white teeth line
        draw_cavity.rectangle((cavity_x1 + 3, cavity_y1, cavity_x2 - 3, cavity_y1 + 2), fill=(255, 255, 255, 255))
        
    # Paste face parts
    animated.paste(top_half, (0, 0))
    animated.paste(bottom_half, (0, split_y + jaw_drop))
    
    # 2. Build circular transparency mask for the animated frame
    mask = Image.new("L", animated.size, 0)
    draw_mask = ImageDraw.Draw(mask)
    draw_mask.ellipse((0, 0, animated.size[0], animated.size[1]), fill=255)
    
    active_avatar = Image.new("RGBA", animated.size, (0, 0, 0, 0))
    active_avatar.paste(animated, (0, 0))
    active_avatar.putalpha(mask)
        
    # Scale avatar proportionally to simulate head bobbing / breathing projection
    new_w = max(10, int(av_size * scale))
    new_h = max(10, int(active_avatar.size[1] * scale))
    active_avatar = active_avatar.resize((new_w, new_h), Image.Resampling.LANCZOS)
    
    # Rotate slightly to simulate head tilting/swaying naturally
    if angle != 0.0:
        active_avatar = active_avatar.rotate(angle, resample=Image.Resampling.BICUBIC, expand=False)
        
    # Calculate offset to paste at centered zoom anchor (anchor top face stable, chin drops)
    offset_x = (av_size - new_w) // 2
    offset_y = (av_size - int(av_size * scale)) // 2 + int(dy)
    
    paste_x = x + offset_x
    paste_y = y + offset_y
        
    # Create overlay drawing context for visualizer HUD
    hud_layer = Image.new("RGBA", slide_image.size, (0, 0, 0, 0))
    draw_hud = ImageDraw.Draw(hud_layer)
    
    center_x = x + av_size // 2
    center_y = y + av_size // 2
    radius = av_size // 2
    
    # Dynamic glowing audio waveform rings
    wave_pulse = 0.0
    if speech_active:
        wave_pulse = abs(math.sin(frame_idx * 0.4))
        
    # Presenter color theme (purple accent / blue cyan)
    primary_color = (124, 77, 255, 180)  # Violet
    secondary_color = (0, 229, 255, 120)  # Cyan
    
    # Draw pulsating back-glow
    glow_r = radius + int(8 + 12 * wave_pulse)
    draw_hud.ellipse(
        (center_x - glow_r, center_y - glow_r, center_x + glow_r, center_y + glow_r),
        outline=secondary_color,
        width=2
    )
    
    # Draw active voice visualizer wave arcs
    if speech_active:
        for angle_offset in (0, 120, 240):
            rot = (frame_idx * 5 + angle_offset) % 360
            span = 40 + 30 * wave_pulse
            draw_hud.arc(
                (center_x - radius - 5, center_y - radius - 5, center_x + radius + 5, center_y + radius + 5),
                start=rot,
                end=rot + span,
                fill=primary_color,
                width=3
            )
            
    # Paste circular avatar frame
    slide_image.paste(active_avatar, (paste_x, paste_y), active_avatar)
    
    # Composite HUD glow on top of slides
    slide_image.alpha_composite(hud_layer)

@router.post("/export-video")
async def export_presentation_video(payload: VideoExportRequest):
    """Compiles a complete video file from slides, neural edge-tts voiceover, and talking avatars."""
    pages = payload.pages
    if not pages:
        raise HTTPException(400, "La présentation doit contenir au moins une page.")
        
    video_dir = os.path.join(DATA_DIR, "media", "video")
    os.makedirs(video_dir, exist_ok=True)
    
    # Step 1: Pre-process narration scripts in parallel
    logger.info("Step 1: Analyzing and synthesizing slide narration scripts in parallel...")
    narration_tasks = []
    page_indices = []
    
    # Resolve target language strictly from the selected neural voice prefix
    target_lang = "en" if payload.voice.lower().startswith("en") else "fr"
    
    for idx, page in enumerate(pages):
        narration = page.get("narration", "").strip()
        if not narration and payload.auto_narrate:
            page_indices.append(idx)
            narration_tasks.append(generate_slide_narration_script(page.get("elements", []), target_lang=target_lang))
            
    if narration_tasks:
        logger.info(f"Generating auto-narrations for {len(narration_tasks)} slides in parallel...")
        generated_scripts = await asyncio.gather(*narration_tasks, return_exceptions=True)
        for i, script in enumerate(generated_scripts):
            idx = page_indices[i]
            if isinstance(script, Exception):
                logger.error(f"Narration generation failed for slide {idx+1}: {script}")
                pages[idx]["narration"] = ""
            else:
                pages[idx]["narration"] = clean_narration_text(script)
                
    # Step 2: Render slides and synthesize voiceover audios in a temp directory
    logger.info("Step 2: Rendering slide PNGs and generating neural Edge-TTS voiceovers...")
    fps = 15
    frames = []
    temp_audios = []
    
    avatar_sprite = None
    if payload.avatar != "none":
        avatar_sprite = create_circular_avatar(payload.avatar, size=160)
        
    # Pre-process subtitle translations in parallel if subtitles and translation are enabled
    if payload.subtitles and payload.subtitles_language != "none":
        voice_lang = "en" if payload.voice.lower().startswith("en") else "fr"
        sub_lang = payload.subtitles_language.lower()
        if voice_lang != sub_lang:
            logger.info("Pre-translating subtitles in parallel...")
            translation_tasks = []
            translation_indices = []
            for idx, page in enumerate(pages):
                n_text = clean_narration_text(page.get("narration", "").strip())
                if n_text:
                    translation_indices.append(idx)
                    translation_tasks.append(translate_narration_text(n_text, sub_lang))
            if translation_tasks:
                translated_texts = await asyncio.gather(*translation_tasks, return_exceptions=True)
                for i, trans_res in enumerate(translated_texts):
                    idx = translation_indices[i]
                    if isinstance(trans_res, Exception):
                        logger.error(f"Subtitle translation failed for slide {idx+1}: {trans_res}")
                    else:
                        pages[idx]["translated_subtitle"] = trans_res
                        
    with tempfile.TemporaryDirectory() as temp_work_dir:
        # Generate slide PNG images
        try:
            slide_paths = _generate_pngs(pages, os.path.join(temp_work_dir, "slide.png"), payload.canvas_width, payload.canvas_height)
        except Exception as e:
            logger.error(f"Slide PNG rendering failed: {e}")
            raise HTTPException(500, f"Impossible de générer les images des diapositives : {e}")
            

                
        # Parallel synthesis of neural speech tracks
        tts_tasks = []
        tts_indices = []
        for idx, page in enumerate(pages):
            narration_text = clean_narration_text(page.get("narration", "").strip())
            if narration_text:
                audio_path = os.path.join(temp_work_dir, f"audio_{idx}.mp3")
                tts_indices.append((idx, audio_path))
                tts_tasks.append(synthesize_speech(narration_text, payload.voice, audio_path))
                
        synthesized_audios = {}
        if tts_tasks:
            logger.info(f"Synthesizing speech for {len(tts_tasks)} narration tracks in parallel...")
            tts_results = await asyncio.gather(*tts_tasks, return_exceptions=True)
            for i, res in enumerate(tts_results):
                idx, audio_path = tts_indices[i]
                if isinstance(res, Exception):
                    logger.error(f"TTS synthesis failed for slide {idx+1}: {res}")
                else:
                    synthesized_audios[idx] = audio_path
                    
        # Process each slide's assets and build frame buffers
        dialogue_lines = []
        current_time = 0.0
        for idx, page in enumerate(pages):
            slide_img_path = slide_paths[idx]
            audio_path = os.path.join(temp_work_dir, f"audio_{idx}.mp3")
            duration = 4.0
            has_speech = False
            
            if idx in synthesized_audios:
                try:
                    duration = get_audio_duration(audio_path)
                    temp_audios.append(audio_path)
                    has_speech = True
                except Exception as e:
                    logger.error(f"Failed to load audio metadata for slide {idx+1}: {e}")
                    has_speech = False
                    
            if not has_speech:
                silent_audio_path = os.path.join(temp_work_dir, f"silent_{idx}.mp3")
                cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:c=mono", "-t", str(duration), "-c:a", "libmp3lame", silent_audio_path]
                subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                temp_audios.append(silent_audio_path)
                
            # Segment and timing subtitle text for this slide if requested
            if payload.subtitles:
                narration_text = clean_narration_text(page.get("narration", "").strip())
                if narration_text:
                    subtitle_text = page.get("translated_subtitle", narration_text) if payload.subtitles_language != "none" else narration_text
                    sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', subtitle_text) if s.strip()]
                    if sentences:
                        chunk_duration = duration / len(sentences)
                        for s_idx, sentence in enumerate(sentences):
                            c_start = current_time + s_idx * chunk_duration
                            c_end = c_start + chunk_duration
                            start_str = format_ass_timestamp(c_start)
                            end_str = format_ass_timestamp(c_end)
                            sentence_escaped = sentence.replace("{", "").replace("}", "")
                            dialogue_lines.append(f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{sentence_escaped}")
            
            # Increment timing tracking
            current_time += duration
            
            total_slide_frames = int(duration * fps)
            base_slide_img = Image.open(slide_img_path).convert("RGBA")
            
            # Performance optimization: static array expansion when no PIP presenter overlay is used
            if not avatar_sprite:
                rgb_frame = base_slide_img.convert("RGB")
                frame_arr = np.array(rgb_frame)
                frames.extend([frame_arr] * total_slide_frames)
            else:
                for f in range(total_slide_frames):
                    frame_img = base_slide_img.copy()
                    overlay_animated_avatar(
                        frame_img,
                        avatar_sprite,
                        payload.avatar_position,
                        frame_idx=len(frames),
                        speech_active=has_speech
                    )
                    rgb_frame = frame_img.convert("RGB")
                    frames.append(np.array(rgb_frame))
                    
        # Step 3: Lossless Audio Concatenation using ffmpeg
        logger.info("Step 3: Losslessly concatenating voice tracks...")
        concat_list_path = os.path.join(temp_work_dir, "concat.txt")
        with open(concat_list_path, "w", encoding="utf-8") as f:
            for audio in temp_audios:
                f.write(f"file '{audio}'\n")
                
        combined_audio_path = os.path.join(temp_work_dir, "combined.mp3")
        concat_cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list_path, "-c", "copy", combined_audio_path]
        subprocess.run(concat_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        # Step 4: Write silent MP4 video container
        logger.info("Step 4: Compiling high-DPI silent MP4 container...")
        silent_video_path = os.path.join(temp_work_dir, "silent_video.mp4")
        try:
            imageio.mimwrite(
                silent_video_path,
                frames,
                fps=fps,
                codec='libx264',
                pixelformat='yuv420p',
                quality=8,
                macro_block_size=1
            )
        except Exception as e:
            logger.error(f"Imageio silent video encoding failed: {e}")
            raise HTTPException(500, f"Erreur lors de l'encodage vidéo : {e}")
            
        # Step 5: Merge concatenated audio and silent video with optimal AAC compression
        logger.info("Step 5: Multiplexing audio and video tracks...")
        video_filename = f"presentation_{uuid.uuid4().hex[:8]}.mp4"
        final_video_path = os.path.join(video_dir, video_filename)
        
        # Write ASS subtitles file if requested
        temp_ass_path = None
        if payload.subtitles and dialogue_lines:
            temp_ass_path = os.path.join(temp_work_dir, "subtitles.ass")
            font_size = 20
            styles_definition = f"Style: Default,Arial,{font_size},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,3,1,1,2,10,10,20,1"
            
            ass_header = f"""[Script Info]
Title: Subtitles
ScriptType: v4.00+
WrapStyle: 0
PlayResX: {payload.canvas_width}
PlayResY: {payload.canvas_height}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
{styles_definition}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
            ass_content = ass_header + "\n".join(dialogue_lines) + "\n"
            with open(temp_ass_path, "w", encoding="utf-8") as f:
                f.write(ass_content)
            logger.info(f"Subtitles written to {temp_ass_path}")

        if temp_ass_path and os.path.exists(temp_ass_path):
            logger.info("Subtitles enabled. Burning subtitles into the video container...")
            escaped_ass = temp_ass_path.replace("'", "'\\\\''").replace(":", "\\:")
            mux_cmd = [
                "ffmpeg", "-y",
                "-i", silent_video_path,
                "-i", combined_audio_path,
                "-vf", f"subtitles='{escaped_ass}'",
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac",
                "-shortest",
                final_video_path
            ]
        else:
            mux_cmd = [
                "ffmpeg", "-y",
                "-i", silent_video_path,
                "-i", combined_audio_path,
                "-c:v", "copy",
                "-c:a", "aac",
                "-shortest",
                final_video_path
            ]
        
        result = subprocess.run(mux_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode != 0:
            logger.error(f"Ffmpeg multiplexing crashed: {result.stderr}")
            raise HTTPException(500, "La fusion de la vidéo et de l'audio a échoué.")
            
        logger.info(f"Success! AI Presenter presentation video generated: {final_video_path}")
        return {
            "status": "ok",
            "filename": video_filename,
            "url": f"/data/media/video/{video_filename}"
        }

@router.post("/auto-narrate")
async def auto_narrate_slide(payload: dict):
    """Generates an engaging spoken script for a slide based on its components."""
    elements = payload.get("elements", [])
    voice = payload.get("voice", "fr-FR-DeniseNeural")
    
    # Resolve target language strictly from the selected voice prefix
    target_lang = "en" if voice.lower().startswith("en") else "fr"
    
    script = await generate_slide_narration_script(elements, target_lang=target_lang)
    cleaned_script = clean_narration_text(script)
    return {"script": cleaned_script}



