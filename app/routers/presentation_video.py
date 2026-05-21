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

async def generate_slide_narration_script(slide_elements: List[dict]) -> str:
    """Uses the default LLM provider to write an engaging script for a slide based on its content."""
    texts = []
    for el in slide_elements:
        if el.get("type") in ("text", "table"):
            content = el.get("content", "").strip()
            if content:
                texts.append(content)
                
    # Premium fallbacks in slide's language
    slide_summary = " | ".join(texts[:5]) if texts else ""
    is_english = any(any(c in "abcdefghijklmnopqrstuvwxyz" for c in word.lower()) and word.lower() in ("the", "welcome", "slide", "presentation", "business", "data", "results") for word in slide_summary.split())
    
    if not texts:
        if is_english:
            return "On this slide, we present the key visual highlights and overview of our current topics."
        else:
            return "Sur cette diapositive, nous vous présentons les informations clés et les éléments visuels de notre présentation."
        
    prompt = (
        "Write a short, engaging, and professional presentation narration script (2 to 3 sentences) for a virtual AI presenter presenting this slide. "
        "The tone must be natural and fluent. Do NOT write any stage directions, presenter notes, or introductory text. "
        "Write the narration in the same language as the slide content (e.g. if the slide is in French, write the narration in French; if in English, write in English). "
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
        if is_english:
            return "Here is the next slide summarizing our primary points and key deliverables."
        else:
            return "Voici la diapositive suivante de notre présentation, résumant les points et objectifs clés."

async def synthesize_speech(text: str, voice: str, output_path: str):
    """Synthesizes high-quality audio narration for a slide using edge-tts."""
    import edge_tts
    try:
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(output_path)
    except Exception as e:
        logger.error(f"edge-tts synthesis failed: {e}")
        raise RuntimeError(f"Faux pas lors de la synthèse vocale : {e}")

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
    """Loads a presenter portrait, resizes and masks it into a high-quality circle with alpha."""
    avatar_file = f"{avatar_name}.png"
    avatar_path = os.path.join(STATIC_DIR, "img", "avatars", avatar_file)
    if not os.path.exists(avatar_path):
        logger.warning(f"Avatar path not found: {avatar_path}")
        return None
        
    try:
        avatar_img = Image.open(avatar_path).convert("RGBA")
        avatar_img = avatar_img.resize((size, size), Image.Resampling.LANCZOS)
        
        # Build circular transparency mask
        mask = Image.new("L", (size, size), 0)
        draw_mask = ImageDraw.Draw(mask)
        draw_mask.ellipse((0, 0, size, size), fill=255)
        
        circular = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        circular.paste(avatar_img, (0, 0))
        circular.putalpha(mask)
        return circular
    except Exception as e:
        logger.error(f"Error creating circular avatar: {e}")
        return None

def overlay_animated_avatar(
    slide_image: Image.Image,
    avatar_img: Image.Image,
    position_mode: str,
    frame_idx: int,
    speech_active: bool
):
    """Draws the talking avatar circle and an organic pulsing sound visualizer HUD."""
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
        
    # Scale avatar proportionally to simulate head bobbing / breathing projection
    new_w = max(10, int(av_size * scale))
    new_h = max(10, int(av_size * scale))
    active_avatar = avatar_img.resize((new_w, new_h), Image.Resampling.LANCZOS)
    
    # Rotate slightly to simulate head tilting/swaying naturally
    if angle != 0.0:
        active_avatar = active_avatar.rotate(angle, resample=Image.Resampling.BICUBIC, expand=False)
        
    # Calculate offset to paste at centered zoom anchor
    offset_x = (av_size - new_w) // 2
    offset_y = (av_size - new_h) // 2 + int(dy)
    
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
    
    # Step 1: Pre-process narration scripts (AI synthesis if empty and auto_narrate enabled)
    logger.info("Step 1: Analyzing and synthesizing slide narration scripts...")
    for idx, page in enumerate(pages):
        narration = page.get("narration", "").strip()
        if not narration:
            if payload.auto_narrate:
                logger.info(f"Generating auto-narration for slide {idx+1} using LLM...")
                generated = await generate_slide_narration_script(page.get("elements", []))
                page["narration"] = generated
            else:
                page["narration"] = ""

    # Step 2: Render slides and synthesize voiceover audios in a temp directory
    logger.info("Step 2: Rendering slide PNGs and generating neural Edge-TTS voiceovers...")
    fps = 15
    frames = []
    temp_audios = []
    
    avatar_sprite = None
    if payload.avatar != "none":
        avatar_sprite = create_circular_avatar(payload.avatar, size=160)
        
    with tempfile.TemporaryDirectory() as temp_work_dir:
        # Generate slide PNG images
        try:
            slide_paths = _generate_pngs(pages, os.path.join(temp_work_dir, "slide.png"), payload.canvas_width, payload.canvas_height)
        except Exception as e:
            logger.error(f"Slide PNG rendering failed: {e}")
            raise HTTPException(500, f"Impossible de générer les images des diapositives : {e}")
            
        # Process each slide's assets
        for idx, page in enumerate(pages):
            slide_img_path = slide_paths[idx]
            narration_text = page.get("narration", "").strip()
            
            audio_path = os.path.join(temp_work_dir, f"audio_{idx}.mp3")
            duration = 4.0 # default duration if no narration
            has_speech = False
            
            if narration_text:
                try:
                    await synthesize_speech(narration_text, payload.voice, audio_path)
                    duration = get_audio_duration(audio_path)
                    temp_audios.append(audio_path)
                    has_speech = True
                except Exception as e:
                    logger.error(f"TTS synthesis failed for slide {idx}: {e}")
                    # fallback to silent slide
                    has_speech = False
            
            # If a slide has no speech, generate a silent MP3 file for alignment
            if not has_speech:
                silent_audio_path = os.path.join(temp_work_dir, f"silent_{idx}.mp3")
                cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:c=mono", "-t", str(duration), "-c:a", "libmp3lame", silent_audio_path]
                subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                temp_audios.append(silent_audio_path)
                
            # Compile frames for this slide's duration
            total_slide_frames = int(duration * fps)
            base_slide_img = Image.open(slide_img_path).convert("RGBA")
            
            for f in range(total_slide_frames):
                # Copy canvas to avoid dirty mutations
                frame_img = base_slide_img.copy()
                
                # Apply speaking avatar layers if active
                if avatar_sprite:
                    overlay_animated_avatar(
                        frame_img,
                        avatar_sprite,
                        payload.avatar_position,
                        frame_idx=len(frames),
                        speech_active=has_speech
                    )
                    
                # Convert back to standard RGB numpy array for imageio writer
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
    script = await generate_slide_narration_script(elements)
    return {"script": script}

