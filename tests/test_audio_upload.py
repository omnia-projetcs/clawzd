"""
Clawzd Audio Upload — Integration and API verification test suite.
"""
import sys
import os
import io
import shutil
import pytest
from fastapi.testclient import TestClient

# Add workspace directory to python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.gateway import app
from app.tools_audio import AUDIO_DIR

def test_audio_upload_flow():
    client = TestClient(app)
    
    # 1. Create a dummy audio file content (e.g., mock MP3 bytes)
    mock_audio_content = b"ID3\x03\x00\x00\x00\x00\x00\x00Dummy MP3 Audio Content bytes for testing 12345"
    filename = "test_upload_audio.mp3"
    
    # 2. Upload the file
    response = client.post(
        "/audio/upload",
        files={"file": (filename, io.BytesIO(mock_audio_content), "audio/mpeg")}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "filename" in data
    assert "url" in data
    
    uploaded_filename = data["filename"]
    uploaded_filepath = os.path.join(AUDIO_DIR, uploaded_filename)
    meta_filepath = uploaded_filepath + ".meta"
    
    try:
        # Verify file exists on disk
        assert os.path.exists(uploaded_filepath)
        
        # Verify metadata exists on disk and has correct format
        assert os.path.exists(meta_filepath)
        import json
        with open(meta_filepath, "r") as f:
            meta = json.load(f)
        assert meta["mode"] == "upload"
        assert filename in meta["prompt"]
        
        # 3. Test duplicate upload check
        response_dup = client.post(
            "/audio/upload",
            files={"file": (filename, io.BytesIO(mock_audio_content), "audio/mpeg")}
        )
        assert response_dup.status_code == 409
        dup_data = response_dup.json()
        assert "detail" in dup_data
        assert "already exists" in dup_data["detail"]
        
    finally:
        # Clean up files created during testing
        if os.path.exists(uploaded_filepath):
            os.remove(uploaded_filepath)
        if os.path.exists(meta_filepath):
            os.remove(meta_filepath)

if __name__ == "__main__":
    test_audio_upload_flow()
    print("🎉 Audio upload flow tests completed successfully!")
