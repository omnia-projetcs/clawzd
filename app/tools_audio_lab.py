"""
Clawzd — Audio Lab and Voice Restoration Tool.

Integrates Alibaba's ClearerVoice-Studio (via the clearvoice package)
to provide AI-powered Speech Enhancement, Speech Separation,
Speech Super-Resolution, and Target Speaker Extraction.
"""
import os
import re
import uuid
import logging
import asyncio
import threading
import time
from datetime import datetime
from fastapi import APIRouter, Request, HTTPException, UploadFile, File, Form
from fastapi.responses import JSONResponse
from config import DATA_DIR, MODELS_DIR

logger = logging.getLogger("clawzd.audio_lab")
router = APIRouter()

# Target directory for lab results
AUDIO_LAB_DIR = os.path.join(DATA_DIR, "audio_lab")
os.makedirs(AUDIO_LAB_DIR, exist_ok=True)

# Also expose a route for standard Clawzd audio directory since processed files can be used by the Studio Editor
AUDIO_DIR = os.path.join(DATA_DIR, "audio")
os.makedirs(AUDIO_DIR, exist_ok=True)

# Global progress tracking dictionary
_audio_lab_progress = {
    "active": False,
    "progress": 0.0,
    "stage": "",       # 'loading_model', 'processing', 'saving'
    "task_id": "",
    "result_url": None,
    "error": None,
}

def _release_other_pipelines():
    """Release VRAM and CPU pipelines from core audio tools to prevent memory thrashing."""
    try:
        from app.tools_audio import _release_all_audio
        _release_all_audio()
    except Exception as e:
        logger.warning("Failed to release core audio resources: %s", e)


def _process_effects_with_pedalboard(input_path: str, output_path: str, model_name: str):
    import subprocess
    import tempfile
    import os
    import shutil
    from pedalboard import Pedalboard, Compressor, HighpassFilter, LowpassFilter, Reverb, Delay, PitchShift, Chorus, Limiter
    from pedalboard.io import AudioFile
    
    temp_wav_in = None
    temp_wav_out = None
    
    # 1. Convert input to WAV if not already WAV
    if not input_path.lower().endswith(".wav"):
        fd, temp_wav_in = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        logger.info("Converting non-WAV input %s to temp WAV %s for Pedalboard...", input_path, temp_wav_in)
        subprocess.run(["ffmpeg", "-y", "-i", input_path, "-ac", "2", "-ar", "44100", temp_wav_in], capture_output=True, check=True)
        read_path = temp_wav_in
    else:
        read_path = input_path

    # 2. Determine target output format
    is_mp3_out = output_path.lower().endswith(".mp3")
    is_ogg_out = output_path.lower().endswith(".ogg")
    
    if is_mp3_out or is_ogg_out:
        fd, temp_wav_out = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        write_path = temp_wav_out
    else:
        write_path = output_path
        
    try:
        # 3. Read input audio
        with AudioFile(read_path) as f:
            audio = f.read(f.frames)
            sr = f.samplerate
            
        # 4. Define effects chain based on the chosen preset
        if model_name == "warm_vocal":
            board = Pedalboard([
                HighpassFilter(cutoff_frequency_hz=80),
                Compressor(threshold_db=-18.0, ratio=2.5, attack_ms=10.0, release_ms=100.0),
                Reverb(room_size=0.15, wet_level=0.1, dry_level=0.9, width=0.5)
            ])
        elif model_name == "studio_master":
            board = Pedalboard([
                Compressor(threshold_db=-14.0, ratio=3.0, attack_ms=15.0, release_ms=150.0),
                Delay(delay_seconds=0.2, feedback=0.15, mix=0.08),
                Limiter(threshold_db=-1.0, release_ms=50.0)
            ])
        elif model_name == "telephone_voice":
            board = Pedalboard([
                HighpassFilter(cutoff_frequency_hz=400),
                LowpassFilter(cutoff_frequency_hz=3000),
                Compressor(threshold_db=-20.0, ratio=4.0),
                Chorus(rate_hz=1.0, depth=0.25, centre_delay_ms=7.0, feedback=0.0, mix=0.1)
            ])
        elif model_name == "radio_broadcast":
            board = Pedalboard([
                HighpassFilter(cutoff_frequency_hz=60),
                Compressor(threshold_db=-24.0, ratio=4.5, attack_ms=5.0, release_ms=80.0),
                Limiter(threshold_db=-0.5, release_ms=40.0)
            ])
        elif model_name == "spaced_reverb":
            board = Pedalboard([
                Reverb(room_size=0.75, wet_level=0.45, dry_level=0.55, width=1.0, damping=0.3)
            ])
        elif model_name == "pitch_shift_up":
            board = Pedalboard([
                PitchShift(semitones=2.0)
            ])
        elif model_name == "pitch_shift_down":
            board = Pedalboard([
                PitchShift(semitones=-2.0)
            ])
        else:
            board = Pedalboard([
                HighpassFilter(cutoff_frequency_hz=40),
                Compressor(threshold_db=-12.0, ratio=2.0)
            ])
            
        # 5. Process
        effected = board(audio, sr)
        
        # 6. Write
        with AudioFile(write_path, 'w', sr, effected.shape[0]) as f:
            f.write(effected)
            
        # 7. Convert temp WAV output back to target format if needed
        if is_mp3_out:
            logger.info("Converting Pedalboard WAV output to MP3: %s", output_path)
            subprocess.run(["ffmpeg", "-y", "-i", write_path, "-b:a", "192k", output_path], capture_output=True, check=True)
        elif is_ogg_out:
            logger.info("Converting Pedalboard WAV output to OGG: %s", output_path)
            subprocess.run(["ffmpeg", "-y", "-i", write_path, "-c:a", "libvorbis", "-q:a", "6", output_path], capture_output=True, check=True)
            
        # Calculate duration
        duration = effected.shape[1] / sr if len(effected.shape) > 1 else effected.shape[0] / sr
        return duration
        
    finally:
        # Cleanup
        for path in (temp_wav_in, temp_wav_out):
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass


def _process_in_thread(task_id: str, task_type: str, model_name: str, input_path: str, output_path: str, reference_path: str = None):
    """Worker thread running ClearVoice, Pedalboard or HeartTranscriptor inference."""
    global _audio_lab_progress
    from app.tools.task_manager import update_task, unregister_task
    
    _audio_lab_progress.update({
        "active": True,
        "progress": 10.0,
        "stage": "loading_model",
        "task_id": task_id,
        "result_url": None,
        "error": None,
    })
    update_task(task_id, progress=10.0, stage="loading_model")
    
    try:
        # 1. Release competing pipelines
        _release_other_pipelines()
        
        import torch
        import json
        import shutil
        
        # Check if doing Pro Audio Effects & VST processing
        if task_type == "audio_effects":
            logger.info("Applying Pedalboard audio effects (preset: %s)...", model_name)
            _audio_lab_progress.update({
                "progress": 30.0,
                "stage": "loading_pedalboard",
            })
            
            _audio_lab_progress.update({
                "progress": 50.0,
                "stage": "applying_effects",
            })
            
            duration_sec = _process_effects_with_pedalboard(input_path, output_path, model_name)
            
            _audio_lab_progress.update({
                "progress": 80.0,
                "stage": "saving_output",
            })
            
            # Copy to static audio dir and save metadata
            dest_filename = f"lab_{task_id}_{os.path.basename(output_path)}"
            dest_path = os.path.join(AUDIO_DIR, dest_filename)
            shutil.copy2(output_path, dest_path)
            
            meta_path = dest_path + ".meta"
            with open(meta_path, "w") as f:
                json.dump({
                    "prompt": f"[Pro Audio Effects] Preset '{model_name}' applied to {os.path.basename(input_path)}",
                    "created": datetime.now().isoformat(),
                    "mode": "audio_lab",
                    "duration": duration_sec,
                    "task_type": task_type,
                    "model_name": model_name,
                }, f)
                
            _audio_lab_progress.update({
                "active": False,
                "progress": 100.0,
                "stage": "completed",
                "result_url": f"/data/audio/{dest_filename}",
            })
            
            logger.info("Pedalboard effects successfully processed: %s", dest_path)
            return
            
        # Check if doing Lyrics Transcription
        if task_type == "lyrics_transcription":
            logger.info("Initializing HeartTranscriptor pipeline...")
            ht_dir = os.path.join(MODELS_DIR, "HeartTranscriptor-oss")
            if not os.path.exists(ht_dir):
                _audio_lab_progress.update({
                    "progress": 20.0,
                    "stage": "downloading_weights",
                })
                logger.info("Downloading HeartTranscriptor-oss checkpoint from HuggingFace...")
                from huggingface_hub import snapshot_download
                snapshot_download(repo_id="HeartMuLa/HeartTranscriptor-oss", local_dir=ht_dir, local_dir_use_symlinks=False)
                
            _audio_lab_progress.update({
                "progress": 40.0,
                "stage": "loading_model",
            })
            
            from app.heartmula.hearttranscriptor import HeartTranscriptorPipeline
            device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
            dtype = torch.float16 if torch.cuda.is_available() else torch.float32
            
            pipeline = HeartTranscriptorPipeline.from_pretrained(
                pretrained_path=MODELS_DIR,
                device=device,
                dtype=dtype
            )
            
            _audio_lab_progress.update({
                "progress": 60.0,
                "stage": "processing",
            })
            
            logger.info("Running lyrics transcription on %s", input_path)
            result = pipeline(input_path)
            transcribed_text = result.get("text", "").strip()
            
            logger.info("Transcription completed: %s", transcribed_text)
            
            txt_output_path = os.path.splitext(output_path)[0] + ".txt"
            with open(txt_output_path, "w", encoding="utf-8") as f:
                f.write(transcribed_text)
                
            shutil.copy2(input_path, output_path)
            
            dest_filename = f"lab_{task_id}_{os.path.basename(output_path)}"
            dest_path = os.path.join(AUDIO_DIR, dest_filename)
            shutil.copy2(output_path, dest_path)
            
            dest_txt_path = os.path.splitext(dest_path)[0] + ".txt"
            shutil.copy2(txt_output_path, dest_txt_path)
            
            meta_path = dest_path + ".meta"
            with open(meta_path, "w") as f:
                duration_sec = 0.0
                try:
                    import soundfile as sf
                    info = sf.info(dest_path)
                    duration_sec = info.duration
                except Exception:
                    pass
                    
                json.dump({
                    "prompt": f"[Lyrics Transcription] Processed: {os.path.basename(input_path)}",
                    "created": datetime.now().isoformat(),
                    "mode": "lyrics_transcription",
                    "duration": duration_sec,
                    "task_type": task_type,
                    "model_name": model_name,
                    "transcription": transcribed_text,
                }, f)
                
            _audio_lab_progress.update({
                "active": False,
                "progress": 100.0,
                "stage": "completed",
                "result_url": f"/data/audio/{dest_filename}",
                "transcription": transcribed_text,
            })
            return

        elif task_type == "lyrics_transcription_separated":
            logger.info("Step 1: Running MossFormer2 speech separation...")
            _audio_lab_progress.update({
                "progress": 15.0,
                "stage": "separating_vocals",
            })
            
            from clearvoice import ClearVoice
            sep_engine = ClearVoice(task="speech_separation", model_names=["MossFormer2_SS_16K"])
            
            temp_sep_dir = os.path.join(AUDIO_LAB_DIR, f"sep_{task_id}")
            os.makedirs(temp_sep_dir, exist_ok=True)
            
            temp_sep_out = os.path.join(temp_sep_dir, "vocals.wav")
            sep_engine(input_path=input_path, online_write=True, output_path=temp_sep_out)
            
            separated_files = [os.path.join(temp_sep_dir, f) for f in os.listdir(temp_sep_dir) if f.endswith(".wav")]
            if not separated_files:
                logger.warning("Vocal separation didn't produce files in expected directory, trying fallback to raw input.")
                vocal_track_path = input_path
            else:
                vocal_track_path = separated_files[0]
                logger.info("Vocal track isolated at: %s", vocal_track_path)
                
            _audio_lab_progress.update({
                "progress": 50.0,
                "stage": "loading_model",
            })
            
            ht_dir = os.path.join(MODELS_DIR, "HeartTranscriptor-oss")
            if not os.path.exists(ht_dir):
                logger.info("Downloading HeartTranscriptor-oss checkpoint from HuggingFace...")
                from huggingface_hub import snapshot_download
                snapshot_download(repo_id="HeartMuLa/HeartTranscriptor-oss", local_dir=ht_dir, local_dir_use_symlinks=False)
                
            from app.heartmula.hearttranscriptor import HeartTranscriptorPipeline
            device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
            dtype = torch.float16 if torch.cuda.is_available() else torch.float32
            
            pipeline = HeartTranscriptorPipeline.from_pretrained(
                pretrained_path=MODELS_DIR,
                device=device,
                dtype=dtype
            )
            
            _audio_lab_progress.update({
                "progress": 70.0,
                "stage": "transcribing",
            })
            
            result = pipeline(vocal_track_path)
            transcribed_text = result.get("text", "").strip()
            
            logger.info("Separated Vocal Transcription completed: %s", transcribed_text)
            
            try:
                shutil.rmtree(temp_sep_dir)
            except Exception:
                pass
                
            txt_output_path = os.path.splitext(output_path)[0] + ".txt"
            with open(txt_output_path, "w", encoding="utf-8") as f:
                f.write(transcribed_text)
                
            shutil.copy2(input_path, output_path)
            
            dest_filename = f"lab_{task_id}_{os.path.basename(output_path)}"
            dest_path = os.path.join(AUDIO_DIR, dest_filename)
            shutil.copy2(output_path, dest_path)
            
            dest_txt_path = os.path.splitext(dest_path)[0] + ".txt"
            shutil.copy2(txt_output_path, dest_txt_path)
            
            meta_path = dest_path + ".meta"
            with open(meta_path, "w") as f:
                duration_sec = 0.0
                try:
                    import soundfile as sf
                    info = sf.info(dest_path)
                    duration_sec = info.duration
                except Exception:
                    pass
                    
                json.dump({
                    "prompt": f"[Lyrics Transcription (Vocal Separated)] Processed: {os.path.basename(input_path)}",
                    "created": datetime.now().isoformat(),
                    "mode": "lyrics_transcription_separated",
                    "duration": duration_sec,
                    "task_type": task_type,
                    "model_name": model_name,
                    "transcription": transcribed_text,
                }, f)
                
            _audio_lab_progress.update({
                "active": False,
                "progress": 100.0,
                "stage": "completed",
                "result_url": f"/data/audio/{dest_filename}",
                "transcription": transcribed_text,
            })
            return

        # 2. Lazy import clearvoice
        from clearvoice import ClearVoice
        
        _audio_lab_progress.update({
            "progress": 30.0,
            "stage": "processing",
        })
        
        # 3. Initialize ClearVoice instance
        # ClearVoice uses (self, task, model_names)
        logger.info("Initializing ClearVoice task=%s model=%s", task_type, model_name)
        
        # The package handles target_speaker_extraction, speech_separation, speech_enhancement, speech_super_resolution
        engine = ClearVoice(task=task_type, model_names=[model_name])
        
        _audio_lab_progress.update({
            "progress": 50.0,
        })
        
        # 4. Invoke model processing
        # call_io_mode will be invoked by __call__ when input_path is a string
        # For target speaker extraction, some models may require target voice anchors.
        # ClearVoice handles general wav files. Let's process.
        logger.info("Processing audio input_path=%s output_path=%s", input_path, output_path)
        
        # MossFormer/FRCRN processes input.
        # ClearVoice __call__ accepts (input_path, online_write=False, output_path=None)
        # If online_write=True, it will write the output automatically using model.write()
        # We can also call it with online_write=True and output_path
        engine(input_path=input_path, online_write=True, output_path=output_path)
        
        _audio_lab_progress.update({
            "progress": 85.0,
            "stage": "saving",
        })
        
        # Check if the output file actually exists and contains data
        # Sometimes model.write writes to subfolders or specific patterns if multi-model/multi-input.
        # If output_path was written directly, verify it.
        # Let's inspect if clearvoice wrote to the exact output_path or created a subfolder.
        # By default, ClearVoice writes to output_path. Let's make sure it's valid.
        if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
            # Fallback search if clearvoice saved to a subfolder
            logger.warning("Target output_path %s not found immediately. Checking subfolders.", output_path)
            parent_dir = os.path.dirname(output_path)
            filename = os.path.basename(output_path)
            found = False
            for root, dirs, files in os.walk(parent_dir):
                for f in files:
                    if f == filename and os.path.getsize(os.path.join(root, f)) > 0:
                        import shutil
                        shutil.move(os.path.join(root, f), output_path)
                        found = True
                        break
                if found:
                    break
            
            if not found:
                raise RuntimeError("ClearVoice did not produce a valid output file.")
        
        # Also copy the output file to the primary Clawzd static audio dir so it can be loaded
        # in the general media gallery or timeline editor
        dest_filename = f"lab_{task_id}_{os.path.basename(output_path)}"
        dest_path = os.path.join(AUDIO_DIR, dest_filename)
        import shutil
        shutil.copy2(output_path, dest_path)
        
        # Save metadata for gallery compatibility
        meta_path = dest_path + ".meta"
        import json
        with open(meta_path, "w") as f:
            # Calculate rough duration
            duration_sec = 0.0
            try:
                import soundfile as sf
                info = sf.info(dest_path)
                duration_sec = info.duration
            except Exception:
                pass
            
            json.dump({
                "prompt": f"[AudioLab / {model_name}] Processed: {os.path.basename(input_path)}",
                "created": datetime.now().isoformat(),
                "mode": "audio_lab",
                "duration": duration_sec,
                "task_type": task_type,
                "model_name": model_name,
            }, f)
        
        logger.info("Audio Lab processing completed successfully: %s", dest_path)
        
        _audio_lab_progress.update({
            "active": False,
            "progress": 100.0,
            "stage": "completed",
            "result_url": f"/data/audio/{dest_filename}",
        })
        
    except Exception as e:
        logger.error("Audio Lab processing failed: %s", e, exc_info=True)
        _audio_lab_progress.update({
            "active": False,
            "progress": 0.0,
            "stage": "failed",
            "error": str(e),
        })
        update_task(task_id, status="failed", stage="failed", error=str(e))
    finally:
        if _audio_lab_progress.get("task_id") == task_id:
            stage = _audio_lab_progress.get("stage", "")
            result_url = _audio_lab_progress.get("result_url")
            if stage == "completed":
                unregister_task(
                    task_id,
                    status="completed",
                    result={"url": result_url} if result_url else None,
                )
            elif stage == "failed":
                unregister_task(
                    task_id,
                    status="failed",
                    error=_audio_lab_progress.get("error") or "Audio Lab processing failed.",
                )


@router.post("/process")
async def process_audio(request: Request):
    """
    Launch ClearVoice speech processing.
    
    Payload parameters:
    - mode: 'enhance', 'separate', 'upscale', 'extract_target'
    - input_file: filename of the source file (stored in data/audio/ or data/audio_lab/)
    - model: optional specific model name override
    """
    global _audio_lab_progress
    
    if _audio_lab_progress["active"]:
        raise HTTPException(status_code=400, detail="An Audio Lab process is already running.")
        
    data = await request.json()
    mode = data.get("mode", "enhance")
    input_file = data.get("input_file", "").strip()
    model_override = data.get("model", "").strip()
    
    if not input_file:
        raise HTTPException(status_code=400, detail="input_file parameter is required.")
        
    # Resolve the absolute path of the input file
    input_path = os.path.join(AUDIO_DIR, input_file)
    if not os.path.exists(input_path):
        input_path = os.path.join(AUDIO_LAB_DIR, input_file)
        if not os.path.exists(input_path):
            raise HTTPException(status_code=404, detail=f"Source file {input_file} not found.")
            
    # Determine the task and model
    task_type = "speech_enhancement"
    model_name = "MossFormer2_SE_48K"
    
    if mode == "enhance":
        task_type = "speech_enhancement"
        model_name = model_override or "MossFormer2_SE_48K"
    elif mode == "separate":
        task_type = "speech_separation"
        model_name = model_override or "MossFormer2_SS_16K"
    elif mode == "upscale":
        task_type = "speech_super_resolution"
        model_name = model_override or "MossFormer2_SR_48K"
    elif mode == "extract_target":
        task_type = "target_speaker_extraction"
        model_name = model_override or "AV_MossFormer2_TSE_16K"
    elif mode == "effects":
        task_type = "audio_effects"
        model_name = model_override or "warm_vocal"
    elif mode == "transcribe":
        task_type = "lyrics_transcription"
        model_name = "HeartTranscriptor-oss"
    elif mode == "transcribe_separated":
        task_type = "lyrics_transcription_separated"
        model_name = "MossFormer2_SS_16K + HeartTranscriptor-oss"
    else:
        raise HTTPException(status_code=400, detail=f"Unknown audio processing mode: {mode}")
        
    # Set up output path
    task_id = uuid.uuid4().hex[:8]
    ext = os.path.splitext(input_file)[1] or ".wav"
    output_filename = f"processed_{task_id}{ext}"
    output_path = os.path.join(AUDIO_LAB_DIR, output_filename)
    
    # Register background task
    from app.tools.task_manager import register_task, unregister_task
    register_task(task_id, "audio_lab", f"[{mode}] {input_file}", {"mode": mode, "model": model_name})
    
    # Launch worker thread
    thread = threading.Thread(
        target=_process_in_thread,
        args=(task_id, task_type, model_name, input_path, output_path),
        daemon=True
    )
    thread.start()
    
    # We clean the task in task_manager afterwards once checked
    return {
        "status": "ok",
        "task_id": task_id,
        "message": f"Processing started via model {model_name} in background thread.",
    }


@router.get("/progress")
async def get_progress():
    """Get the current Audio Lab processing progress."""
    return _audio_lab_progress


@router.post("/upload")
async def upload_audio(file: UploadFile = File(...)):
    """Upload a raw audio file to process in the Audio Lab."""
    # Validate extension
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in (".wav", ".mp3", ".ogg", ".flac", ".m4a", ".aac"):
        raise HTTPException(status_code=400, detail=f"Unsupported audio format: {ext}")
        
    # Save directly to Clawzd audio folder so it can be managed and previewed
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    uid = uuid.uuid4().hex[:6]
    clean_name = re.sub(r'[^a-zA-Z0-9_.-]', '_', file.filename)
    filename = f"upload_{timestamp}_{uid}_{clean_name}"
    filepath = os.path.join(AUDIO_DIR, filename)
    
    with open(filepath, "wb") as buffer:
        buffer.write(await file.read())
        
    # Save simple metadata
    meta_path = filepath + ".meta"
    import json
    with open(meta_path, "w") as f:
        duration_sec = 0.0
        try:
            import soundfile as sf
            info = sf.info(filepath)
            duration_sec = info.duration
        except Exception:
            pass
        
        json.dump({
            "prompt": f"[Upload] Raw user recording: {file.filename}",
            "created": datetime.now().isoformat(),
            "mode": "upload",
            "duration": duration_sec,
        }, f)
        
    return {
        "status": "ok",
        "filename": filename,
        "url": f"/data/audio/{filename}",
    }


# Hardware low-latency playback monitoring bridge context
from scripts.desktop_audio_monitor import DesktopAudioMonitor
_hardware_monitor = DesktopAudioMonitor()


@router.post("/monitor/play")
async def monitor_play(data: dict):
    """Play a generated or uploaded audio track direct to physical low-latency DACs."""
    filename = data.get("filename", "").strip()
    if not filename:
        raise HTTPException(status_code=400, detail="filename parameter is required.")
        
    filepath = os.path.join(AUDIO_DIR, filename)
    if not os.path.exists(filepath):
        filepath = os.path.join(AUDIO_LAB_DIR, filename)
        if not os.path.exists(filepath):
            raise HTTPException(status_code=404, detail=f"Audio file {filename} not found.")
            
    success = _hardware_monitor.play_file(filepath)
    return {
        "status": "ok" if success else "error",
        "message": f"Playback started direct to hardware DAC for {filename}." if success else "Failed to start hardware playback.",
    }


@router.post("/monitor/stop")
async def monitor_stop():
    """Stop any currently active low-latency DAC hardware playback."""
    _hardware_monitor.stop()
    return {
        "status": "ok",
        "message": "Hardware playback stopped.",
    }
