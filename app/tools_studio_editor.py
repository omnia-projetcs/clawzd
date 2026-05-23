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
from config import DATA_DIR

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
    "vintage": "eq=contrast=0.9:brightness=0.05:saturation=0.8,hue=h=-10"
}

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

                if is_image:
                    # Convert image to loop video slide
                    cmd = [
                        "ffmpeg", "-y", "-loop", "1", "-i", filepath,
                        "-t", str(duration),
                        "-vf", f"scale={width}:{height},format=yuv420p",
                        "-c:v", "libx264", "-r", str(fps),
                        temp_clip_path
                    ]
                else:
                    # Preprocess video with trimming, speed, scaling and filters
                    vf_filters = [f"scale={width}:{height}"]
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
                if res.returncode == 0 and os.path.exists(temp_clip_path):
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
