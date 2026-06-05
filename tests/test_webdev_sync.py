"""
Clawzd — WebDev Studio Sync WebSocket Test Suite.
Verifies the handshake, initial sync loading, and client-to-host file writing.
"""
import os
import time
from fastapi.testclient import TestClient
from app.gateway import app
from config import WORKSPACE_DIR

client = TestClient(app)


def test_webdev_sync_websocket():
    """Verify WebSocket sync lifecycle, handshake, and client-to-host file syncing."""
    # Ensure WORKSPACE_DIR exists
    os.makedirs(WORKSPACE_DIR, exist_ok=True)

    # 1. Create a dummy test file on the host
    dummy_name = "test_sync_dummy_file.txt"
    dummy_path = os.path.join(WORKSPACE_DIR, dummy_name)
    if os.path.exists(dummy_path):
        os.remove(dummy_path)

    with open(dummy_path, "w", encoding="utf-8") as f:
        f.write("Hello from host system!")

    # 2. Write a binary dummy file on the host
    dummy_bin_name = "test_sync_dummy_binary.bin"
    dummy_bin_path = os.path.join(WORKSPACE_DIR, dummy_bin_name)
    if os.path.exists(dummy_bin_path):
        os.remove(dummy_bin_path)

    with open(dummy_bin_path, "wb") as f:
        f.write(b"\x00\x01\x02\x03\x04\x05")

    try:
        # Connect to FastAPI WebSocket endpoint
        with client.websocket_connect("/api/webdev/sync") as ws:
            # Receive initial files map (handshake init)
            init_msg = ws.receive_json()
            assert init_msg["type"] == "init"
            assert "files" in init_msg
            
            files = init_msg["files"]
            assert dummy_name in files
            assert files[dummy_name]["content"] == "Hello from host system!"
            assert files[dummy_name]["is_binary"] is False

            assert dummy_bin_name in files
            # Binary file content must be base64 encoded string
            assert isinstance(files[dummy_bin_name]["content"], str)
            assert files[dummy_bin_name]["is_binary"] is True

            # 3. Simulate client writing a new file inside the WebContainer
            client_file_name = "test_sync_client_write.txt"
            client_file_path = os.path.join(WORKSPACE_DIR, client_file_name)
            if os.path.exists(client_file_path):
                os.remove(client_file_path)

            ws.send_json({
                "type": "write",
                "path": client_file_name,
                "content": "Hello from virtual WebContainer sandbox!",
                "is_binary": False
            })

            # Give the async handler half a second to write the file physically
            time.sleep(0.5)

            # Assert file was created on host disk
            assert os.path.exists(client_file_path), "Client-written file was not created on host disk"
            with open(client_file_path, "r", encoding="utf-8") as f:
                assert f.read() == "Hello from virtual WebContainer sandbox!"

            # Clean up client file
            if os.path.exists(client_file_path):
                os.remove(client_file_path)

            # 4. Simulate client deleting a file
            ws.send_json({
                "type": "delete",
                "path": dummy_name
            })
            time.sleep(0.5)

            # Assert file was deleted from host disk
            assert not os.path.exists(dummy_path), "File was not deleted from host disk"

    finally:
        # Clean up all created files
        if os.path.exists(dummy_path):
            os.remove(dummy_path)
        if os.path.exists(dummy_bin_path):
            os.remove(dummy_bin_path)
