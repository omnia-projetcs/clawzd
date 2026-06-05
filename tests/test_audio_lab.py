"""
Clawzd Audio Lab — Integration and API verification test suite.
"""
import sys
import os
import pytest
from fastapi.testclient import TestClient

# Add workspace directory to python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

def test_imports():
    """Verify core audio lab library dependencies and imports."""
    try:
        import scipy
        import soundfile
        from clearvoice import ClearVoice
        print("✅ Core imports succeeded.")
        assert True
    except ImportError as e:
        print(f"❌ Core imports failed: {e}")
        assert False

def test_api_routes():
    """Verify that Audio Lab routes are successfully integrated into the main gateway."""
    from app.gateway import app
    client = TestClient(app)
    
    # Check that progress endpoint exists and is reachable
    response = client.get("/audio-lab/progress")
    assert response.status_code == 200
    data = response.json()
    assert "active" in data
    assert "progress" in data
    assert "stage" in data
    print("✅ Gateway /audio-lab/progress endpoint verified.")

def test_invalid_parameters():
    """Verify that bad inputs to the processing endpoint are caught gracefully."""
    from app.gateway import app
    client = TestClient(app)
    
    # Request processing without input file
    response = client.post("/audio-lab/process", json={
        "mode": "enhance",
        "input_file": "",
        "model": "MossFormer2_SE_48K"
    })
    assert response.status_code == 400
    assert "detail" in response.json()
    print("✅ Graceful validation error handling verified.")

if __name__ == "__main__":
    test_imports()
    test_api_routes()
    test_invalid_parameters()
    print("🎉 All Audio Lab integration tests completed successfully!")
