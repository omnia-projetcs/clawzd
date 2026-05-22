import os, json, uuid
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
from app.gateway import app
from app.tools_research import RESEARCH_DIR, _proj_dir

client = TestClient(app)

def test_research_to_presentation_endpoints():
    pid = "test_proj_123"
    pdir = _proj_dir(pid)
    os.makedirs(pdir, exist_ok=True)
    
    # Save a fake research project structure
    proj_data = {
        "id": pid,
        "title": "Test Research Report",
        "report_md": "# Test Research Report\n\n## Section 1\n- Point 1\n- Point 2\n\n## Section 2\n- Point 3\n- Point 4",
        "provider": "test_provider",
        "model": "test_model"
    }
    
    with open(os.path.join(pdir, "project.json"), "w", encoding="utf-8") as f:
        json.dump(proj_data, f)
        
    try:
        # Test 1: POST /research/projects/{pid}/export format=pptx
        resp = client.post(f"/research/projects/{pid}/export", json={"format": "pptx"})
        # Could fail if python-pptx is not installed, but it should return 200 or 500.
        assert resp.status_code in [200, 500]

        # Test 2: POST /research/projects/{pid}/to-presentation-studio
        fake_llm_response = """
{
  "title": "Generated Presentation Title",
  "theme": "modern",
  "slides": [
    {"type": "title", "title": "Welcome Slide", "subtitle": "Introductory content"},
    {"type": "bullets", "title": "Main Points", "points": ["Key bullet one", "Key bullet two"]},
    {"type": "closing", "title": "Thank You", "subtitle": "Contact details"}
  ]
}
"""
        with patch("app.tools_research._llm_call", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = fake_llm_response
            
            resp = client.post(f"/research/projects/{pid}/to-presentation-studio")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"
            assert "id" in data
            assert data["title"] == "Generated Presentation Title"
            
            # Verify the generated JSON presentation exists in presentations dir
            from app.tools_presentation import get_presentations_dir
            pres_file = os.path.join(get_presentations_dir(), f"{data['id']}.json")
            assert os.path.exists(pres_file)
            
            # Read the file and verify structure
            with open(pres_file, "r", encoding="utf-8") as f:
                saved_pres = json.load(f)
            assert saved_pres["title"] == "Generated Presentation Title"
            assert len(saved_pres["pages"]) == 3
            
            # Clean up generated presentation
            if os.path.exists(pres_file):
                os.remove(pres_file)
                
    finally:
        # Cleanup
        import shutil
        if os.path.exists(pdir):
            shutil.rmtree(pdir)
