import os
import io
import shutil
from fastapi.testclient import TestClient
from app.gateway import app
from app.tools_image import IMAGES_DIR

client = TestClient(app)

def test_image_upload_and_gallery():
    # Setup fresh IMAGES_DIR
    if os.path.exists(IMAGES_DIR):
        shutil.rmtree(IMAGES_DIR)
    os.makedirs(IMAGES_DIR, exist_ok=True)

    # 1. Upload a .JPEG file (uppercase)
    img_content = b"fake jpeg image data content here"
    file_name = "test_photo.JPEG"
    
    response = client.post(
        "/image/upload",
        files={"file": (file_name, io.BytesIO(img_content), "image/jpeg")}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    uploaded_filename = data["filename"]
    assert uploaded_filename.endswith(".JPEG")

    # 2. Check that it is retrieved in the gallery endpoint
    gallery_resp = client.get("/image/gallery")
    assert gallery_resp.status_code == 200
    gallery_data = gallery_resp.json()
    assert "images" in gallery_data
    
    # Verify the uploaded image is listed and has correct format field
    matching = [img for img in gallery_data["images"] if img["filename"] == uploaded_filename]
    assert len(matching) == 1
    assert matching[0]["format"] == "jpeg"

    # 3. Test duplicate prevention
    dup_resp = client.post(
        "/image/upload",
        files={"file": ("another_name.jpeg", io.BytesIO(img_content), "image/jpeg")}
    )
    assert dup_resp.status_code == 409
    assert "already exists" in dup_resp.json()["detail"]

    # Cleanup
    if os.path.exists(IMAGES_DIR):
        shutil.rmtree(IMAGES_DIR)
