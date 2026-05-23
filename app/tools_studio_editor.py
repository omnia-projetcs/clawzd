"""
Clawzd — Premiere-style Studio Editor Backend compilation engine.
Compiles multi-track JSON timelines into finished audio/video assets via FFmpeg.
"""
import os
import re
import uuid
import logging
import subprocess
import shutil
import asyncio
import tempfile
from datetime import datetime
from fastapi import APIRouter, Request, HTTPException
from PIL import Image, ImageDraw, ImageFont
import numpy as np
import imageio
from config import DATA_DIR, PEXELS_API_KEY, PIXABAY_API_KEY

logger = logging.getLogger("clawzd.studio_editor")
router = APIRouter()

IMAGES_DIR = os.path.join(DATA_DIR, "images")
AUDIO_DIR = os.path.join(DATA_DIR, "audio")

os.makedirs(IMAGES_DIR, exist_ok=True)
os.makedirs(AUDIO_DIR, exist_ok=True)

# Visual filters mapping to FFmpeg video filters
COLOR_FILTERS = {
    "none": "",
    "grayscale": "hue=s=0",
    "sepia": "colorchannelmixer=.393:.769:.189:0:.349:.686:.168:0:.272:.534:.131",
    "cinematic": "eq=contrast=1.1:brightness=-0.05:saturation=1.2",
    "cyberpunk": "eq=contrast=1.2:saturation=1.5,hue=h=180",
    "vignette": "vignette=angle=0.5",
    "vintage": "eq=contrast=0.9:brightness=0.05:saturation=0.8,hue=h=-10",
    "ascii_art": "ascii_art"
}

def get_scale_crop_filter(src_w: int, src_h: int, target_w: int, target_h: int) -> str:
    """Calculate scale and crop filter to fill target resolution without stretching."""
    if src_w <= 0 or src_h <= 0:
        return f"scale={target_w}:{target_h}"
    src_ar = src_w / src_h
    target_ar = target_w / target_h
    
    if abs(src_ar - target_ar) < 0.01:
        return f"scale={target_w}:{target_h}"
    elif src_ar > target_ar:
        scaled_w = int(target_h * src_ar)
        if scaled_w % 2 != 0:
            scaled_w += 1
        return f"scale={scaled_w}:{target_h},crop={target_w}:{target_h}"
    else:
        scaled_h = int(target_w / src_ar)
        if scaled_h % 2 != 0:
            scaled_h += 1
        return f"scale={target_w}:{scaled_h},crop={target_w}:{target_h}"

def get_media_info(filepath: str) -> dict:
    """Read media details (duration, width, height, has_audio) using ffprobe/ffmpeg."""
    info = {"duration": 5.0, "width": 1280, "height": 720, "has_audio": False}
    try:
        cmd = ["ffmpeg", "-i", filepath]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5)
        output = res.stderr

        # Parse duration (e.g. Duration: 00:01:23.45)
        dur_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", output)
        if dur_match:
            h, m, s = float(dur_match.group(1)), float(dur_match.group(2)), float(dur_match.group(3))
            info["duration"] = h * 3600 + m * 60 + s

        # Parse resolution (e.g. Video: ..., 1920x1080)
        res_match = re.search(r"Video:.*?\b(\d{3,5})x(\d{3,5})\b", output)
        if res_match:
            info["width"] = int(res_match.group(1))
            info["height"] = int(res_match.group(2))

        # Check audio stream presence
        if "Audio:" in output:
            info["has_audio"] = True
    except Exception as e:
        logger.error(f"Error parsing media details for {filepath}: {e}")
    return info

def convert_frame_to_ascii_image(
    frame_img, 
    target_width: int, 
    target_height: int, 
    ascii_width: int = 160, 
    ascii_height: int = 80, 
    text_color: str = "green", 
    chars_set: str = "standard"
) -> Image.Image:
    # 1. Convert frame to grayscale
    gray_img = frame_img.convert("L")
    
    small_img = gray_img.resize((ascii_width, ascii_height), Image.Resampling.BILINEAR)
    pixels = small_img.load()
    
    # Color small image to read original colors if color theme is source
    color_pixels = None
    if text_color == "source":
        try:
            color_small = frame_img.resize((ascii_width, ascii_height), Image.Resampling.BILINEAR).convert("RGB")
            color_pixels = color_small.load()
        except Exception:
            pass

    # 3. Create black background image
    out_img = Image.new("RGB", (target_width, target_height), color="black")
    draw = ImageDraw.Draw(out_img)
    
    # Locate a monospace font
    font = None
    try:
        font_paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
            "/usr/share/fonts/truetype/freefont/FreeMonoBold.ttf",
            "/usr/share/fonts/truetype/freefont/FreeMono.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf"
        ]
        for path in font_paths:
            if os.path.exists(path):
                font = ImageFont.truetype(path, int(target_height / ascii_height) + 1)
                break
    except Exception:
        pass
        
    if font is None:
        font = ImageFont.load_default()
        
    # Char sets mapping
    chars_map = {
        "standard": " .:-=+*#%@",
        "binary": " 01",
        "blocks": " ░▒▓█",
        "matrix": " ｦｧｨｩｪｫｬｭｮｯｰｱｲｳｴｵｶｷｸｹｺｻｼｽｾｿﾀﾁﾂﾃﾄﾅﾆﾇﾈﾉﾊﾋﾌﾍﾎﾏﾐﾑﾒﾓﾔﾕﾖﾗﾘﾙﾚﾛﾜﾝ10"
    }
    CHARS = chars_map.get(chars_set, " .:-=+*#@")
    num_chars = len(CHARS)
    
    char_w = target_width / ascii_width
    char_h = target_height / ascii_height
    
    # Color themes mapping
    color_map = {
        "green": (57, 255, 20),
        "amber": (255, 176, 0),
        "cyan": (0, 255, 255),
        "white": (255, 255, 255)
    }
    
    for y in range(ascii_height):
        for x in range(ascii_width):
            val = pixels[x, y]
            char_idx = int(val / 256 * num_chars)
            char_idx = min(char_idx, num_chars - 1)
            char = CHARS[char_idx]
            
            if text_color == "source" and color_pixels:
                color = color_pixels[x, y]
            else:
                color = color_map.get(text_color, (57, 255, 20))
            
            pos_x = x * char_w
            pos_y = y * char_h
            draw.text((pos_x, pos_y), char, font=font, fill=color)
            
    return out_img

def convert_video_to_ascii(
    input_path: str, 
    output_path: str, 
    target_width: int, 
    target_height: int, 
    duration: float, 
    fps: int = 30,
    ascii_width: int = 160,
    ascii_height: int = 80,
    text_color: str = "green",
    chars_set: str = "standard"
):
    
    reader = None
    writer = None
    try:
        reader = imageio.get_reader(input_path)
        meta = reader.get_meta_data()
        orig_fps = meta.get("fps", fps)
        if not orig_fps or orig_fps <= 0:
            orig_fps = fps
            
        writer = imageio.get_writer(output_path, fps=orig_fps, codec="libx264")
        
        for frame in reader:
            pil_img = Image.fromarray(frame)
            ascii_img = convert_frame_to_ascii_image(
                pil_img, target_width, target_height,
                ascii_width=ascii_width, ascii_height=ascii_height,
                text_color=text_color, chars_set=chars_set
            )
            out_frame = np.array(ascii_img)
            writer.append_data(out_frame)
    except Exception as e:
        logger.error(f"Error in video ascii conversion: {e}", exc_info=True)
    finally:
        if reader:
            try:
                reader.close()
            except Exception:
                pass
        if writer:
            try:
                writer.close()
            except Exception:
                pass

def convert_image_to_ascii_video(input_path: str, output_path: str, target_width: int, target_height: int, duration: float, fps: int = 30):
    
    writer = None
    try:
        writer = imageio.get_writer(output_path, fps=fps, codec="libx264")
        pil_img = Image.open(input_path)
        ascii_img = convert_frame_to_ascii_image(pil_img, target_width, target_height)
        out_frame = np.array(ascii_img)
        
        num_frames = int(duration * fps)
        for _ in range(num_frames):
            writer.append_data(out_frame)
    except Exception as e:
        logger.error(f"Error in image ascii video conversion: {e}", exc_info=True)
    finally:
        if writer:
            try:
                writer.close()
            except Exception:
                pass

@router.post("/export")
async def export_timeline(request: Request):
    """Compile audio, video, and text timeline tracks into finished media using FFmpeg."""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    export_format = data.get("export_format", "mp4").lower()
    resolution = data.get("resolution", "1280x720")
    fps = int(data.get("fps", 30))
    tracks = data.get("tracks", {})

    video_clips = tracks.get("video", [])
    audio_clips = tracks.get("audio", [])
    text_clips = tracks.get("text", [])

    if export_format not in ("mp4", "webm", "mp3", "wav"):
        export_format = "mp4"

    # Match resolution pattern
    res_match = re.match(r"^(\d+)x(\d+)$", resolution)
    width, height = (1280, 720) if not res_match else (int(res_match.group(1)), int(res_match.group(2)))

    # Calculate composition total duration
    total_duration = 5.0
    for clip in video_clips + audio_clips + text_clips:
        clip_end = float(clip.get("start", 0)) + float(clip.get("duration", 5))
        if clip_end > total_duration:
            total_duration = clip_end

    # Cap max duration to 5 minutes to prevent infinite loops / resource exhaustion
    total_duration = min(total_duration, 300.0)

    # 1. Create a safe temporary directory to hold intermediate assets
    temp_dir = tempfile.mkdtemp()
    logger.info("Created temporary compilation workspace: %s", temp_dir)

    try:
        # Check if we are doing an audio-only export
        is_audio_only = export_format in ("mp3", "wav")

        preprocessed_video_clips = []
        preprocessed_audio_clips = []

        # PREPROCESS VIDEO/IMAGE CLIPS (if not audio-only)
        if not is_audio_only:
            for idx, clip in enumerate(video_clips):
                filename = os.path.basename(clip.get("filename", ""))
                start = float(clip.get("start", 0))
                duration = float(clip.get("duration", 5))
                trim_start = float(clip.get("trim_start", 0))
                speed = float(clip.get("speed", 1.0))
                speed = max(0.5, min(speed, 2.0)) # Clamp speed to standard FFmpeg limits
                color_filter = clip.get("filter", "none").lower()

                filepath = os.path.join(IMAGES_DIR, filename)
                if not os.path.exists(filepath):
                    continue

                # Temp preprocessed clip path
                temp_clip_path = os.path.join(temp_dir, f"video_clip_{idx}.mp4")
                is_image = filename.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".svg"))

                # Determine original source dimensions
                src_w, src_h = width, height
                if is_image:
                    try:
                        with Image.open(filepath) as img:
                            src_w, src_h = img.size
                    except Exception:
                        pass
                else:
                    info = get_media_info(filepath)
                    src_w, src_h = info.get("width", width), info.get("height", height)

                # Generate professional crop/scale filter
                scale_filter = get_scale_crop_filter(src_w, src_h, width, height)

                if is_image:
                    if color_filter == "ascii_art":
                        logger.info(f"Rendering static image to ASCII Art: {filepath} -> {temp_clip_path}")
                        convert_image_to_ascii_video(filepath, temp_clip_path, width, height, duration, fps)
                        res_code = 0
                    else:
                        cmd = [
                            "ffmpeg", "-y", "-loop", "1", "-i", filepath,
                            "-t", str(duration),
                            "-vf", f"{scale_filter},format=yuv420p",
                            "-c:v", "libx264", "-r", str(fps),
                            temp_clip_path
                        ]
                        logger.info("Preprocessing video clip %d: %s", idx, " ".join(cmd))
                        res = subprocess.run(cmd, capture_output=True, text=True)
                        res_code = res.returncode
                else:
                    if color_filter == "ascii_art":
                        temp_trimmed = os.path.join(temp_dir, f"trimmed_{idx}.mp4")
                        vf_filters = [scale_filter]
                        if speed != 1.0:
                            vf_filters.append(f"setpts=(1/{speed})*PTS")
                        
                        cmd = [
                            "ffmpeg", "-y",
                            "-ss", str(trim_start),
                            "-t", str(duration),
                            "-i", filepath,
                            "-vf", ",".join(vf_filters),
                            "-c:v", "libx264", "-an", "-r", str(fps), "-pix_fmt", "yuv420p",
                            temp_trimmed
                        ]
                        logger.info("Preprocessing video clip for ASCII %d: %s", idx, " ".join(cmd))
                        res = subprocess.run(cmd, capture_output=True)
                        if res.returncode == 0 and os.path.exists(temp_trimmed):
                            logger.info(f"Converting video clip {idx} to ASCII Art: {temp_trimmed} -> {temp_clip_path}")
                            convert_video_to_ascii(temp_trimmed, temp_clip_path, width, height, duration, fps)
                            res_code = 0
                        else:
                            res_code = res.returncode
                    else:
                        vf_filters = [scale_filter]
                        if speed != 1.0:
                            vf_filters.append(f"setpts=(1/{speed})*PTS")
                        
                        filter_fx = COLOR_FILTERS.get(color_filter, "")
                        if filter_fx:
                            vf_filters.append(filter_fx)

                        cmd = [
                            "ffmpeg", "-y",
                            "-ss", str(trim_start),
                            "-t", str(duration),
                            "-i", filepath,
                            "-vf", ",".join(vf_filters),
                            "-c:v", "libx264", "-an", "-r", str(fps), "-pix_fmt", "yuv420p",
                            temp_clip_path
                        ]
                        logger.info("Preprocessing video clip %d: %s", idx, " ".join(cmd))
                        res = subprocess.run(cmd, capture_output=True, text=True)
                        res_code = res.returncode

                if res_code == 0 and os.path.exists(temp_clip_path):
                    preprocessed_video_clips.append({
                        "path": temp_clip_path,
                        "start": start,
                        "end": start + duration
                    })
                    # Extract original video audio if it has any
                    info = get_media_info(filepath)
                    if info["has_audio"]:
                        temp_aud_path = os.path.join(temp_dir, f"extracted_aud_{idx}.wav")
                        aud_cmd = [
                            "ffmpeg", "-y",
                            "-ss", str(trim_start),
                            "-t", str(duration),
                            "-i", filepath,
                            "-vn", "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2",
                            temp_aud_path
                        ]
                        logger.info("Extracting audio from video clip %d: %s", idx, " ".join(aud_cmd))
                        res_aud = subprocess.run(aud_cmd, capture_output=True)
                        if res_aud.returncode == 0 and os.path.exists(temp_aud_path):
                            # Append as audio clip item
                            preprocessed_audio_clips.append({
                                "path": temp_aud_path,
                                "start": start,
                                "duration": duration,
                                "volume": 1.0,
                                "speed": speed
                            })

        # PREPROCESS AUDIO CLIPS
        for idx, clip in enumerate(audio_clips):
            filename = os.path.basename(clip.get("filename", ""))
            start = float(clip.get("start", 0))
            duration = float(clip.get("duration", 5))
            trim_start = float(clip.get("trim_start", 0))
            volume = float(clip.get("volume", 1.0))
            speed = float(clip.get("speed", 1.0))
            speed = max(0.5, min(speed, 2.0))

            # Try locating in audio gallery, fallback to image gallery
            filepath = os.path.join(AUDIO_DIR, filename)
            if not os.path.exists(filepath):
                filepath = os.path.join(IMAGES_DIR, filename)
                if not os.path.exists(filepath):
                    continue

            temp_aud_path = os.path.join(temp_dir, f"audio_clip_{idx}.wav")
            
            # Trim and apply volume and speed
            af_filters = [f"volume={volume}"]
            if speed != 1.0:
                af_filters.append(f"atempo={speed}")

            cmd = [
                "ffmpeg", "-y",
                "-ss", str(trim_start),
                "-t", str(duration),
                "-i", filepath,
                "-af", ",".join(af_filters),
                "-ac", "2", "-ar", "44100",
                temp_aud_path
            ]
            logger.info("Preprocessing audio clip %d: %s", idx, " ".join(cmd))
            res = subprocess.run(cmd, capture_output=True)
            if res.returncode == 0 and os.path.exists(temp_aud_path):
                preprocessed_audio_clips.append({
                    "path": temp_aud_path,
                    "start": start,
                    "duration": duration,
                    "volume": volume,
                    "speed": speed
                })

        # 2. SEQUENCE THE VIDEO TIMELINE ONTO CANVAS
        final_video_track = os.path.join(temp_dir, "timeline_video_only.mp4")
        if not is_audio_only:
            # Create standard solid black canvas video
            black_canvas = os.path.join(temp_dir, "canvas_0.mp4")
            canvas_cmd = [
                "ffmpeg", "-y", "-f", "lavfi",
                "-i", f"color=c=black:s={width}x{height}:d={total_duration}:r={fps}",
                "-pix_fmt", "yuv420p", "-c:v", "libx264",
                black_canvas
            ]
            logger.info("Generating background canvas video: %s", " ".join(canvas_cmd))
            subprocess.run(canvas_cmd, capture_output=True, check=True)

            current_canvas = black_canvas
            # Overlay each preprocessed video sequence onto canvas
            for idx, clip in enumerate(preprocessed_video_clips):
                next_canvas = os.path.join(temp_dir, f"canvas_{idx+1}.mp4")
                overlay_cmd = [
                    "ffmpeg", "-y", "-i", current_canvas, "-i", clip["path"],
                    "-filter_complex", f"[0:v][1:v]overlay=x=0:y=0:enable='between(t,{clip['start']},{clip['end']})'[out]",
                    "-map", "[out]", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    next_canvas
                ]
                logger.info("Overlaying video clip %d: %s", idx, " ".join(overlay_cmd))
                res = subprocess.run(overlay_cmd, capture_output=True)
                if res.returncode == 0 and os.path.exists(next_canvas):
                    current_canvas = next_canvas
                else:
                    logger.error(f"Failed to overlay clip {idx}: {res.stderr}")

            shutil.copy(current_canvas, final_video_track)

            # 3. BURN TEXT OVERLAYS
            if text_clips:
                current_video = final_video_track
                for idx, clip in enumerate(text_clips):
                    text = clip.get("text", "").replace("'", "'\\\\''")
                    start = float(clip.get("start", 0))
                    duration = float(clip.get("duration", 5))
                    color = clip.get("color", "white").lower()
                    font_size = int(clip.get("font_size", 32))
                    position = clip.get("position", "bottom").lower()

                    # Set text position layout
                    if position == "top":
                        pos_y = "40"
                    elif position == "middle":
                        pos_y = "(h-text_h)/2"
                    else: # bottom
                        pos_y = f"h-{font_size}-60"

                    next_video = os.path.join(temp_dir, f"video_text_{idx+1}.mp4")
                    drawtext_cmd = [
                        "ffmpeg", "-y", "-i", current_video,
                        "-vf", f"drawtext=text='{text}':fontcolor={color}:fontsize={font_size}:x=(w-text_w)/2:y={pos_y}:enable='between(t,{start},{start+duration})'",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        next_video
                    ]
                    logger.info("Burning text overlay %d: %s", idx, " ".join(drawtext_cmd))
                    res = subprocess.run(drawtext_cmd, capture_output=True)
                    if res.returncode == 0 and os.path.exists(next_video):
                        current_video = next_video
                    else:
                        logger.error(f"Failed to burn text overlay {idx}: {res.stderr}")

                shutil.copy(current_video, final_video_track)

        # 4. MIX AUDIO TIMELINE
        final_audio_track = os.path.join(temp_dir, "timeline_audio_mixed.wav")
        if preprocessed_audio_clips:
            delayed_audio_files = []
            for idx, clip in enumerate(preprocessed_audio_clips):
                delayed_path = os.path.join(temp_dir, f"delayed_aud_{idx}.wav")
                delay_ms = int(clip["start"] * 1000)

                # Delay audio stream start using adelay filter
                delay_cmd = [
                    "ffmpeg", "-y", "-i", clip["path"],
                    "-filter_complex", f"adelay={delay_ms}|{delay_ms}",
                    "-ac", "2", "-ar", "44100",
                    delayed_path
                ]
                logger.info("Applying timeline delay to audio clip %d: %s", idx, " ".join(delay_cmd))
                res = subprocess.run(delay_cmd, capture_output=True)
                if res.returncode == 0 and os.path.exists(delayed_path):
                    delayed_audio_files.append(delayed_path)

            if delayed_audio_files:
                mix_inputs = []
                for p in delayed_audio_files:
                    mix_inputs.extend(["-i", p])
                
                mix_cmd = [
                    "ffmpeg", "-y"
                ] + mix_inputs + [
                    "-filter_complex", f"amix=inputs={len(delayed_audio_files)}:duration=longest:dropout_transition=0",
                    "-ac", "2", "-ar", "44100",
                    final_audio_track
                ]
                logger.info("Mixing audio timeline track: %s", " ".join(mix_cmd))
                subprocess.run(mix_cmd, capture_output=True, check=True)
            else:
                # Fallback to silent track
                silent_cmd = [
                    "ffmpeg", "-y", "-f", "lavfi",
                    "-i", f"anullsrc=cl=stereo:r=44100:d={total_duration}",
                    "-acodec", "pcm_s16le",
                    final_audio_track
                ]
                subprocess.run(silent_cmd, capture_output=True, check=True)
        else:
            # Fallback silent track
            silent_cmd = [
                "ffmpeg", "-y", "-f", "lavfi",
                "-i", f"anullsrc=cl=stereo:r=44100:d={total_duration}",
                "-acodec", "pcm_s16le",
                final_audio_track
            ]
            subprocess.run(silent_cmd, capture_output=True, check=True)

        # 5. FINAL EXPORT COMPILE
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        uid = uuid.uuid4().hex[:6]
        out_filename = f"editor_{timestamp}_{uid}.{export_format}"

        if is_audio_only:
            # Export mixed audio directly to audio gallery
            out_filepath = os.path.join(AUDIO_DIR, out_filename)
            if export_format == "wav":
                shutil.copy(final_audio_track, out_filepath)
            else: # mp3
                mp3_cmd = [
                    "ffmpeg", "-y", "-i", final_audio_track,
                    "-b:a", "192k",
                    out_filepath
                ]
                logger.info("Compressing mixed audio to MP3: %s", " ".join(mp3_cmd))
                subprocess.run(mp3_cmd, capture_output=True, check=True)

            # Write meta
            import json
            meta_path = out_filepath + ".meta"
            with open(meta_path, "w") as f:
                json.dump({
                    "prompt": f"Editor Studio Mixdown ({len(audio_clips)} clips)",
                    "created": datetime.now().isoformat(),
                    "mode": "music",
                    "duration": total_duration
                }, f)

            gallery_url = f"/data/audio/{out_filename}"
        else:
            # Merge overlaid video track and mixed audio track
            out_filepath = os.path.join(IMAGES_DIR, out_filename)
            
            # Select proper encoder for format
            vcodec = "libx264" if export_format == "mp4" else "libvpx-vp9"
            acodec = "aac" if export_format == "mp4" else "libopus"
            
            merge_cmd = [
                "ffmpeg", "-y",
                "-i", final_video_track,
                "-i", final_audio_track,
                "-c:v", vcodec, "-pix_fmt", "yuv420p",
                "-c:a", acodec,
                "-shortest",
                out_filepath
            ]
            logger.info("Compiling final video output: %s", " ".join(merge_cmd))
            subprocess.run(merge_cmd, capture_output=True, check=True)

            # Write prompt meta text file
            with open(out_filepath + ".txt", "w", encoding="utf-8") as f:
                f.write(f"Studio Editor Render ({len(video_clips)} video clips, {len(audio_clips)} audio clips)")

            gallery_url = f"/data/images/{out_filename}"

        logger.info("Render successful! Final asset stored at: %s", out_filepath)
        return {
            "status": "ok",
            "filename": out_filename,
            "url": gallery_url,
            "format": export_format,
            "duration": total_duration
        }

    except Exception as e:
        logger.error("Studio Editor timeline compilation failed: %s", e, exc_info=True)
        raise HTTPException(500, f"Compilation failed: {e}")

    finally:
        # Cleanup temporary files
        try:
            shutil.rmtree(temp_dir)
            logger.info("Cleaned temporary workspace: %s", temp_dir)
        except Exception:
            pass

@router.post("/ai_plan")
async def ai_plan(request: Request):
    """Generate a multi-track timeline plan from a natural language prompt using gallery assets."""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    prompt = data.get("prompt", "").strip()
    if not prompt:
        raise HTTPException(400, "Prompt is required")

    # Gather all assets from images/audio directories
    images = []
    if os.path.exists(IMAGES_DIR):
        for f in os.listdir(IMAGES_DIR):
            if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".svg", ".mp4", ".webm")):
                images.append(f)

    audios = []
    if os.path.exists(AUDIO_DIR):
        for f in os.listdir(AUDIO_DIR):
            if f.lower().endswith((".mp3", ".wav", ".m4a", ".ogg")):
                audios.append(f)

    if not images:
        raise HTTPException(400, "Your gallery is empty. Please upload or generate some images/videos first!")

    # Query LLM to organize these assets
    from app.llm_provider import get_llm_provider
    from config import LLM_PROVIDER
    import json

    system_prompt = (
        "You are an AI Video Editor. Your task is to plan a professional video timeline by sequencing available media files.\n"
        "You must respond with ONLY a raw JSON block matching this exact structure:\n"
        "{\n"
        "  \"duration\": 30.0,\n"
        "  \"clips\": [\n"
        "    {\n"
        "      \"filename\": \"image_or_video_file.png\",\n"
        "      \"track\": \"video\",\n"
        "      \"start\": 0.0,\n"
        "      \"duration\": 5.0,\n"
        "      \"trim_start\": 0.0,\n"
        "      \"speed\": 1.0,\n"
        "      \"filter\": \"none\"\n"
        "    },\n"
        "    {\n"
        "      \"filename\": \"ambient_music.mp3\",\n"
        "      \"track\": \"audio\",\n"
        "      \"start\": 0.0,\n"
        "      \"duration\": 15.0,\n"
        "      \"trim_start\": 0.0,\n"
        "      \"volume\": 0.8,\n"
        "      \"speed\": 1.0\n"
        "    },\n"
        "    {\n"
        "      \"text\": \"Subtitle Overlay Text\",\n"
        "      \"track\": \"text\",\n"
        "      \"start\": 1.0,\n"
        "      \"duration\": 4.0,\n"
        "      \"color\": \"white\",\n"
        "      \"font_size\": 28,\n"
        "      \"position\": \"bottom\"\n"
        "    }\n"
        "  ]\n"
        "}\n\n"
        "Constraints:\n"
        "- The 'track' field must be 'video', 'audio', or 'text'.\n"
        "- For 'video' clips, 'filename' MUST be chosen strictly from the Available Video/Image Files listed below.\n"
        "- For 'audio' clips, 'filename' MUST be chosen strictly from the Available Audio Files listed below.\n"
        "- For 'text' clips, 'text' is the subtitle overlay, and 'filename' is NOT required.\n"
        "- Available filters for 'video' clips are: 'none', 'grayscale', 'sepia', 'cinematic', 'cyberpunk', 'vignette', 'vintage', 'ascii_art'.\n"
        "- Ensure clips do not overlap on the same track unless intended. Sequence them nicely.\n"
        "- Respond with ONLY the valid JSON block, starting with '{' and ending with '}'. No chat, no markdown fences."
    )

    user_content = (
        f"Available Video/Image Files:\n{json.dumps(images, indent=2)}\n\n"
        f"Available Audio Files:\n{json.dumps(audios, indent=2)}\n\n"
        f"User Prompt / Creative Concept: \"{prompt}\"\n\n"
        "Please plan a stunning, coherent video using these assets."
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content}
    ]

    try:
        # Resolve LLM provider
        provider = get_llm_provider(LLM_PROVIDER)
        raw_resp = await provider.chat(messages)
        raw_resp = raw_resp.strip()

        # Clean markdown fences if any
        if raw_resp.startswith("```"):
            lines = raw_resp.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            raw_resp = "\n".join(lines).strip()

        start_idx = raw_resp.find("{")
        end_idx = raw_resp.rfind("}")
        if start_idx != -1 and end_idx != -1:
            raw_resp = raw_resp[start_idx:end_idx + 1]

        plan_data = json.loads(raw_resp)
        return plan_data

    except Exception as e:
        logger.error(f"Failed to generate AI montage plan: {e}", exc_info=True)
        # Fallback dynamic mock plan using actual assets
        fallback_clips = []
        curr_time = 0.0
        for img in images[:5]:
            fallback_clips.append({
                "id": f"clip_{uuid.uuid4().hex[:6]}",
                "filename": img,
                "track": "video",
                "start": curr_time,
                "duration": 4.0,
                "trim_start": 0.0,
                "speed": 1.0,
                "filter": "cinematic"
            })
            fallback_clips.append({
                "text": "Creative AI Edit",
                "track": "text",
                "start": curr_time + 0.5,
                "duration": 3.0,
                "color": "yellow",
                "font_size": 28,
                "position": "bottom"
            })
            curr_time += 4.0

        if audios:
            fallback_clips.append({
                "id": f"clip_{uuid.uuid4().hex[:6]}",
                "filename": audios[0],
                "track": "audio",
                "start": 0.0,
                "duration": curr_time,
                "trim_start": 0.0,
                "volume": 0.8,
                "speed": 1.0
            })

        return {
            "duration": curr_time,
            "clips": fallback_clips,
            "error_fallback": str(e)
        }

# ==========================================
# OPENMONTAGE ADVANCED CREATIVE CAPABILITIES
# ==========================================

CURATED_MOCK_VIDEOS = [
    {
        "id": "mock_vid_1",
        "title": "Cyberpunk City Loop",
        "url": "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ElephantsDream.mp4",
        "type": "video",
        "duration": 653.0,
        "thumbnail": "https://images.pexels.com/photos/1612351/pexels-photo-1612351.jpeg?auto=compress&cs=tinysrgb&h=150"
    },
    {
        "id": "mock_vid_2",
        "title": "Calm Nature Sunrise",
        "url": "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4",
        "type": "video",
        "duration": 596.0,
        "thumbnail": "https://images.pexels.com/photos/3244513/pexels-photo-3244513.jpeg?auto=compress&cs=tinysrgb&h=150"
    },
    {
        "id": "mock_vid_3",
        "title": "Minimal Code Editor Setup",
        "url": "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerBlazes.mp4",
        "type": "video",
        "duration": 15.0,
        "thumbnail": "https://images.pexels.com/photos/577585/pexels-photo-577585.jpeg?auto=compress&cs=tinysrgb&h=150"
    },
    {
        "id": "mock_vid_4",
        "title": "Sci-Fi Robot Lab",
        "url": "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/TearsOfSteel.mp4",
        "type": "video",
        "duration": 734.0,
        "thumbnail": "https://images.pexels.com/photos/2599244/pexels-photo-2599244.jpeg?auto=compress&cs=tinysrgb&h=150"
    }
]

CURATED_MOCK_AUDIOS = [
    {
        "id": "mock_aud_1",
        "title": "Synthwave Cyberpunk Anthem",
        "url": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-1.mp3",
        "type": "audio",
        "duration": 372.0,
        "thumbnail": ""
    },
    {
        "id": "mock_aud_2",
        "title": "Chill Lo-Fi Coffee Shop Beat",
        "url": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-2.mp3",
        "type": "audio",
        "duration": 425.0,
        "thumbnail": ""
    },
    {
        "id": "mock_aud_3",
        "title": "Ambient Deep Space Probe",
        "url": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-3.mp3",
        "type": "audio",
        "duration": 344.0,
        "thumbnail": ""
    },
    {
        "id": "mock_aud_4",
        "title": "Epic Orchestral Adventure Theme",
        "url": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-4.mp3",
        "type": "audio",
        "duration": 302.0,
        "thumbnail": ""
    },
    {
        "id": "mock_aud_5",
        "title": "Upbeat Funk & Groove Loop",
        "url": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-5.mp3",
        "type": "audio",
        "duration": 362.0,
        "thumbnail": ""
    },
    {
        "id": "mock_aud_6",
        "title": "Electro Lounge Afterhours",
        "url": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-6.mp3",
        "type": "audio",
        "duration": 502.0,
        "thumbnail": ""
    },
    {
        "id": "mock_aud_7",
        "title": "Retro 8-Bit Arcade Run",
        "url": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-8.mp3",
        "type": "audio",
        "duration": 318.0,
        "thumbnail": ""
    },
    {
        "id": "mock_aud_8",
        "title": "Smooth Jazz Coffee Break",
        "url": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-10.mp3",
        "type": "audio",
        "duration": 512.0,
        "thumbnail": ""
    },
    {
        "id": "mock_aud_9",
        "title": "Digital Watch Beep Sound Effect",
        "url": "https://actions.google.com/sounds/v1/alarms/digital_watch_alarm_long.ogg",
        "type": "audio",
        "duration": 4.0,
        "thumbnail": ""
    }
]

@router.post("/silence_detect")
async def silence_detect(request: Request):
    """Detect silent segments and speech intervals in a media clip using FFmpeg silencedetect."""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    filename = os.path.basename(data.get("filename", ""))
    threshold_db = float(data.get("threshold_db", -35.0))
    min_duration = float(data.get("min_duration", 0.5))
    padding = float(data.get("padding", 0.1))

    if not filename:
        raise HTTPException(400, "Filename is required")

    filepath = os.path.join(AUDIO_DIR, filename)
    if not os.path.exists(filepath):
        filepath = os.path.join(IMAGES_DIR, filename)
        if not os.path.exists(filepath):
            raise HTTPException(404, f"File {filename} not found in audio or video directories.")

    try:
        # Get total media duration
        info = get_media_info(filepath)
        total_duration = info.get("duration", 0.0)

        if total_duration <= 0.0:
            raise HTTPException(400, "Invalid file duration")

        # Run silence detection via FFmpeg silencedetect
        cmd = [
            "ffmpeg",
            "-i", filepath,
            "-af", f"silencedetect=noise={threshold_db}dB:d={min_duration}",
            "-f", "null", "-"
        ]

        logger.info(f"Running silence detection on: {filepath} ({total_duration}s)")
        
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        output = stderr.decode("utf-8", errors="ignore")

        # Parse output
        starts = re.findall(r"silence_start:\s*([\d.]+)", output)
        ends = re.findall(r"silence_end:\s*([\d.]+)", output)
        durations = re.findall(r"silence_duration:\s*([\d.]+)", output)

        silences = []
        for i in range(min(len(starts), len(ends))):
            silences.append({
                "start": float(starts[i]),
                "end": float(ends[i]),
                "duration": float(durations[i]) if i < len(durations) else float(ends[i]) - float(starts[i])
            })

        # Compute speech segments
        speech_segments = []
        cursor = 0.0
        for silence in silences:
            speech_end = silence["start"] + padding
            if speech_end > cursor:
                speech_segments.append({
                    "start": cursor,
                    "end": min(speech_end, total_duration)
                })
            cursor = max(cursor, silence["end"] - padding)

        if cursor < total_duration:
            speech_segments.append({
                "start": cursor,
                "end": total_duration
            })

        # Clean speech segments
        cleaned_speech = []
        for seg in speech_segments:
            if seg["end"] - seg["start"] < 0.01:
                continue
            if cleaned_speech and seg["start"] - cleaned_speech[-1]["end"] < 0.05:
                cleaned_speech[-1]["end"] = seg["end"]
            else:
                cleaned_speech.append(seg)

        return {
            "status": "ok",
            "total_duration": total_duration,
            "silences": silences,
            "speech_segments": cleaned_speech
        }

    except Exception as e:
        logger.error(f"Silence detection failed: {e}", exc_info=True)
        raise HTTPException(500, f"Silence detection failed: {str(e)}")

@router.post("/search_stock")
async def search_stock(request: Request):
    """Search for stock B-rolls or audio. Fallbacks gracefully to curated mock lists."""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")
        
    query = data.get("query", "").strip().lower()
    media_type = data.get("type", "video").strip().lower() # "video", "image", "audio"

    # Curated elegant fallback search (works 100% offline/out-of-the-box!)
    results = []
    if media_type == "audio":
        source_list = CURATED_MOCK_AUDIOS
    else:
        source_list = CURATED_MOCK_VIDEOS

    if not query:
        results = source_list
    else:
        for item in source_list:
            if query in item["title"].lower():
                results.append(item)
    return {"status": "ok", "results": results}

@router.post("/download_stock")
async def download_stock(request: Request):
    """Download a stock asset locally into Clawzd directories and register it in editor."""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    url = data.get("url", "").strip()
    media_type = data.get("type", "video").strip().lower() # "video", "image", "audio"
    title = data.get("title", "downloaded_asset").strip()

    if not url:
        raise HTTPException(400, "URL is required")

    # Clean filename from title
    clean_title = re.sub(r"[^a-zA-Z0-9_\-]", "_", title).lower()
    
    # Determine ext from url
    import urllib.parse
    parsed_url = urllib.parse.urlparse(url)
    ext = os.path.splitext(parsed_url.path)[1].lower()
    if not ext:
        ext = ".mp3" if media_type == "audio" else ".mp4"

    # Limit filename length
    clean_title = clean_title[:30]
    filename = f"stock_{clean_title}_{uuid.uuid4().hex[:4]}{ext}"
    
    if media_type == "audio":
        dest_dir = AUDIO_DIR
    else:
        dest_dir = IMAGES_DIR

    dest_path = os.path.join(dest_dir, filename)

    try:
        logger.info(f"Downloading stock asset from: {url} -> {dest_path}")
        
        import urllib.request
        def _download():
            req = urllib.request.Request(
                url, 
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept': '*/*',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Referer': 'https://www.pexels.com/'
                }
            )
            with urllib.request.urlopen(req, timeout=30) as response, open(dest_path, 'wb') as out_file:
                shutil.copyfileobj(response, out_file)
        
        await asyncio.to_thread(_download)
        
        # Resolve duration if possible
        duration = 5.0
        try:
            info = get_media_info(dest_path)
            duration = info.get("duration", 5.0)
        except Exception:
            pass

        return {
            "status": "ok",
            "filename": filename,
            "url": f"/data/audio/{filename}" if media_type == "audio" else f"/data/images/{filename}",
            "type": media_type,
            "duration": duration
        }

    except Exception as e:
        logger.error(f"Failed to download stock asset: {e}", exc_info=True)
        raise HTTPException(500, f"Download failed: {str(e)}")

# ==========================================
# LOSSLESS-CUT OPTIMIZED API ROUTES
# ==========================================

@router.post("/lossless_trim")
async def lossless_trim(request: Request):
    """
    Découpe ultra-rapide d'un clip sans réencodage (Direct Stream Copy).
    Utile pour le nettoyage instantané de fichiers volumineux.
    """
    try:
        data = await request.json()
        filename = os.path.basename(data.get("filename", ""))
        start = float(data.get("start", 0.0))
        duration = float(data.get("duration", 5.0))
        
        if not filename:
            raise HTTPException(400, "Le nom du fichier est requis")
            
        src_path = os.path.join(IMAGES_DIR, filename)
        if not os.path.exists(src_path):
            src_path = os.path.join(AUDIO_DIR, filename)
            
        if not os.path.exists(src_path):
            raise HTTPException(404, "Fichier source introuvable")
            
        # Génération du nom de sortie
        ext = os.path.splitext(filename)[1]
        out_filename = f"trimmed_{uuid.uuid4().hex[:6]}{ext}"
        dest_path = os.path.join(IMAGES_DIR, out_filename) if ext.lower() in [".mp4", ".webm"] else os.path.join(AUDIO_DIR, out_filename)
        
        # Commande FFmpeg de copie directe de flux (lossless)
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start),
            "-t", str(duration),
            "-i", src_path,
            "-c", "copy",  # Direct Stream Copy (sans réencodage)
            "-map_metadata", "0",
            dest_path
        ]
        
        logger.info(f"Execution Lossless Trim: {' '.join(cmd)}")
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        
        if proc.returncode != 0:
            err_msg = stderr.decode("utf-8")
            logger.error(f"FFmpeg trim error: {err_msg}")
            raise HTTPException(500, f"Erreur FFmpeg : {err_msg}")
            
        return {
            "status": "ok",
            "filename": out_filename,
            "url": f"/data/images/{out_filename}" if ext.lower() in [".mp4", ".webm"] else f"/data/audio/{out_filename}",
            "duration": duration
        }
    except Exception as e:
        logger.error(f"Lossless trim failed: {e}")
        raise HTTPException(500, str(e))


@router.post("/lossless_merge")
async def lossless_merge(request: Request):
    """
    Fusionne instantanément plusieurs fichiers audio/vidéo ayant les mêmes codecs.
    """
    try:
        data = await request.json()
        filenames = data.get("filenames", [])
        
        if len(filenames) < 2:
            raise HTTPException(400, "Au moins deux fichiers sont requis pour la fusion.")
            
        temp_list_path = os.path.join(tempfile.gettempdir(), f"merge_list_{uuid.uuid4().hex[:6]}.txt")
        
        # Vérification et écriture de la liste des fichiers
        first_ext = os.path.splitext(filenames[0])[1].lower()
        with open(temp_list_path, "w", encoding="utf-8") as f:
            for fname in filenames:
                path = os.path.join(IMAGES_DIR, fname) if first_ext in [".mp4", ".webm"] else os.path.join(AUDIO_DIR, fname)
                if os.path.exists(path):
                    f.write(f"file '{path}'\n")
                    
        out_filename = f"merged_{uuid.uuid4().hex[:6]}{first_ext}"
        dest_path = os.path.join(IMAGES_DIR, out_filename) if first_ext in [".mp4", ".webm"] else os.path.join(AUDIO_DIR, out_filename)
        
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", temp_list_path,
            "-c", "copy",  # Fusion directe sans réencoder
            dest_path
        ]
        
        proc = await asyncio.create_subprocess_exec(*cmd)
        await proc.wait()
        
        # Nettoyage fichier temporaire
        if os.path.exists(temp_list_path):
            os.remove(temp_list_path)
            
        return {"status": "ok", "filename": out_filename, "url": f"/data/images/{out_filename}" if first_ext in [".mp4", ".webm"] else f"/data/audio/{out_filename}"}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/stream_info")
async def stream_info(request: Request):
    """
    Analyse les flux internes d'un fichier multimédia (Audio, Vidéo, Sous-titres).
    """
    try:
        data = await request.json()
        filename = os.path.basename(data.get("filename", ""))
        
        filepath = os.path.join(IMAGES_DIR, filename)
        if not os.path.exists(filepath):
            filepath = os.path.join(AUDIO_DIR, filename)
            
        if not os.path.exists(filepath):
            raise HTTPException(404, "Fichier introuvable")
            
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "stream=index,codec_type,codec_name,channels,r_frame_rate",
            "-of", "json", filepath
        ]
        
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        
        import json
        return json.loads(stdout.decode("utf-8"))
    except Exception as e:
        logger.error(f"Stream info probe failed: {e}")
        raise HTTPException(500, str(e))


@router.post("/snapshot")
async def take_snapshot(request: Request):
    """
    Extrait une image clé haute définition instantanée d'une vidéo à un timestamp précis.
    """
    try:
        data = await request.json()
        filename = os.path.basename(data.get("filename", ""))
        timestamp = float(data.get("time", 0.0))
        
        filepath = os.path.join(IMAGES_DIR, filename)
        if not os.path.exists(filepath):
            raise HTTPException(404, "Vidéo introuvable")
            
        snap_name = f"snap_{os.path.splitext(filename)[0]}_{int(timestamp*1000)}.png"
        dest_path = os.path.join(IMAGES_DIR, snap_name)
        
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(timestamp),
            "-i", filepath,
            "-vframes", "1",
            "-q:v", "2",  # Qualité maximale pour le snapshot
            dest_path
        ]
        
        logger.info(f"Taking snapshot: {' '.join(cmd)}")
        proc = await asyncio.create_subprocess_exec(*cmd)
        await proc.wait()
        
        return {"status": "ok", "filename": snap_name, "url": f"/data/images/{snap_name}"}
    except Exception as e:
        logger.error(f"Snapshot extraction failed: {e}")
        raise HTTPException(500, str(e))


