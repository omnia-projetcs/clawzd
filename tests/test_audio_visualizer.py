import os
import subprocess
import pytest
from fastapi.testclient import TestClient
from app.gateway import app
from config import DATA_DIR

client = TestClient(app)
IMAGES_DIR = os.path.join(DATA_DIR, "images")
AUDIO_DIR = os.path.join(DATA_DIR, "audio")

@pytest.mark.parametrize("style,theme", [
    ("waveform_centered", "matrix_green"),
    ("waveform_lines", "fire_ice"),
    ("frequency_bars", "gold_glow"),
    ("retro_oscilloscope", "classic_cyan"),
    ("spectrogram", "cyberpunk_purple")
])
def test_generate_visualizer_endpoint(style, theme):
    # Ensure directories exist
    os.makedirs(IMAGES_DIR, exist_ok=True)
    os.makedirs(AUDIO_DIR, exist_ok=True)
    
    # 1. Create a 1-second silent audio file for testing
    dummy_audio_name = f"visualizer_test_{style}_{theme}_1s.mp3"
    dummy_audio_path = os.path.join(AUDIO_DIR, dummy_audio_name)
    
    # FFmpeg command to generate 1 second of silence
    gen_cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", "anullsrc=r=44100:cl=mono",
        "-t", "1",
        "-c:a", "libmp3lame",
        dummy_audio_path
    ]
    
    proc = subprocess.run(gen_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.returncode == 0, f"Failed to generate dummy audio file: {proc.stderr.decode('utf-8')}"
    assert os.path.exists(dummy_audio_path), "Dummy audio file does not exist"
    
    # 2. Test visualizer generation endpoint
    payload = {
        "filename": dummy_audio_name,
        "style": style,
        "theme": theme,
        "resolution": "1280x720",
        "fps": 30
    }
    
    try:
        resp = client.post("/studio/generate_visualizer", json=payload)
        assert resp.status_code == 200, f"Endpoint failed: {resp.text}"
        
        data = resp.json()
        assert data.get("status") == "ok"
        assert "filename" in data
        assert data["filename"].startswith("viz_")
        assert data["filename"].endswith(".mp4")
        assert "url" in data
        assert data["url"] == f"/data/images/{data['filename']}"
        assert "duration" in data
        assert float(data["duration"]) > 0
        
        # Verify output video file actually exists
        out_video_path = os.path.join(IMAGES_DIR, data["filename"])
        assert os.path.exists(out_video_path), "Generated visualizer video file does not exist"
        
        # Clean up generated video
        if os.path.exists(out_video_path):
            os.remove(out_video_path)
            
    finally:
        # Clean up temporary audio file
        if os.path.exists(dummy_audio_path):
            os.remove(dummy_audio_path)
