"""
Clawzd — WebDev Studio Workspace Sync Router.
WebSocket router that synchronizes files between the local host workspace/
and the in-browser WebContainer virtual filesystem.
"""
import asyncio
import base64
import logging
import os
from pathlib import Path
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from config import WORKSPACE_DIR

router = APIRouter()
logger = logging.getLogger("clawzd.webdev_sync")

# Excluded folders to prevent syncing huge dependencies or git tracking files
EXCLUDED_FOLDERS = {
    ".git",
    "node_modules",
    "venv",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".vscode",
    "bolt_diy",
}


def _is_excluded(path: Path, base_dir: Path) -> bool:
    """Check if the path falls under any excluded folder."""
    try:
        rel = path.relative_to(base_dir)
        for part in rel.parts:
            if part in EXCLUDED_FOLDERS:
                return True
    except Exception:
        pass
    return False


def _get_workspace_files(base_dir: Path) -> dict[str, dict]:
    """Recursively scans WORKSPACE_DIR and reads files (handles binary as base64)."""
    files = {}
    if not base_dir.exists():
        base_dir.mkdir(parents=True, exist_ok=True)

    for root, _, filenames in os.walk(base_dir):
        root_path = Path(root)
        if _is_excluded(root_path, base_dir):
            continue

        for filename in filenames:
            file_path = root_path / filename
            if _is_excluded(file_path, base_dir):
                continue

            # Calculate relative path as flat key
            try:
                rel_path = str(file_path.relative_to(base_dir))
            except ValueError:
                continue

            # Skip symlinks to avoid circular loops or broken target warnings
            if file_path.is_symlink():
                continue

            try:
                stat = file_path.stat()
                mtime = stat.st_mtime
                size = stat.st_size

                # Avoid reading extremely large files (limit to 5MB)
                if size > 5 * 1024 * 1024:
                    continue

                # Read content: try text first, fallback to base64 for binary
                try:
                    with open(file_path, "r", encoding="utf-8", errors="strict") as f:
                        content = f.read()
                        if "\x00" in content:
                            raise UnicodeDecodeError("utf-8", b"", 0, 1, "null byte")
                        is_binary = False
                except (UnicodeDecodeError, ValueError):
                    with open(file_path, "rb") as f:
                        binary_data = f.read()
                        content = base64.b64encode(binary_data).decode("utf-8")
                        is_binary = True

                files[rel_path] = {
                    "content": content,
                    "is_binary": is_binary,
                    "mtime": mtime,
                }
            except Exception as e:
                logger.warning("Failed to read workspace file %s: %s", rel_path, e)

    return files


@router.websocket("/sync")
async def websocket_sync_endpoint(websocket: WebSocket):
    """FastAPI WebSocket endpoint for real-time bidirectionnal workspace sync."""
    await websocket.accept()
    logger.info("WebDev sync WebSocket connection accepted.")

    base_dir = Path(WORKSPACE_DIR).resolve()
    # Track the state of the workspace (rel_path -> mtime) to detect host changes
    tracked_state = {}

    async def client_listener():
        """Listens for file writes, deletions, and creations from the client."""
        nonlocal tracked_state
        try:
            while True:
                data = await websocket.receive_json()
                msg_type = data.get("type")
                rel_path = data.get("path")

                if not msg_type or not rel_path:
                    continue

                # Clean and sanitize the path to prevent directory traversal
                safe_path = (base_dir / rel_path).resolve()
                if not safe_path.is_relative_to(base_dir):
                    logger.warning("Blocked traversal attempt to path: %s", rel_path)
                    continue

                if msg_type == "write":
                    content = data.get("content", "")
                    is_binary = data.get("is_binary", False)

                    # Ensure parent directories exist
                    safe_path.parent.mkdir(parents=True, exist_ok=True)

                    try:
                        if is_binary:
                            binary_data = base64.b64decode(content)
                            with open(safe_path, "wb") as f:
                                f.write(binary_data)
                        else:
                            with open(safe_path, "w", encoding="utf-8") as f:
                                f.write(content)

                        # Update local tracking so we don't reflect this write back to client
                        stat = safe_path.stat()
                        tracked_state[rel_path] = stat.st_mtime
                        logger.debug("Successfully synchronized write for: %s", rel_path)
                    except Exception as e:
                        logger.error("Failed to write synced file %s: %s", rel_path, e)

                elif msg_type == "delete":
                    try:
                        if safe_path.exists():
                            if safe_path.is_file():
                                safe_path.unlink()
                            elif safe_path.is_dir():
                                import shutil
                                shutil.rmtree(safe_path)

                            # Remove from local tracked state
                            tracked_state.pop(rel_path, None)
                            logger.debug("Successfully synchronized delete for: %s", rel_path)
                    except Exception as e:
                        logger.error("Failed to delete synced file %s: %s", rel_path, e)

        except WebSocketDisconnect:
            logger.info("Client listener disconnected.")
        except Exception as e:
            logger.error("Error in client listener: %s", e)

    async def host_watcher():
        """Periodically scans host filesystem for edits and pushes them to client."""
        nonlocal tracked_state
        try:
            while True:
                await asyncio.sleep(1.5)
                current_files = _get_workspace_files(base_dir)

                # 1. Detect added and modified files
                for rel_path, info in current_files.items():
                    last_mtime = tracked_state.get(rel_path)
                    # If file is new or modified on host
                    if last_mtime is None or info["mtime"] > last_mtime:
                        tracked_state[rel_path] = info["mtime"]
                        # Push to client
                        await websocket.send_json({
                            "type": "write",
                            "path": rel_path,
                            "content": info["content"],
                            "is_binary": info["is_binary"],
                        })
                        logger.debug("Pushed host edit to client: %s", rel_path)

                # 2. Detect deleted files
                deleted_paths = []
                for rel_path in list(tracked_state.keys()):
                    if rel_path not in current_files:
                        deleted_paths.append(rel_path)
                        tracked_state.pop(rel_path)

                for rel_path in deleted_paths:
                    await websocket.send_json({
                        "type": "delete",
                        "path": rel_path,
                    })
                    logger.debug("Pushed host delete to client: %s", rel_path)

        except WebSocketDisconnect:
            logger.info("Host watcher disconnected.")
        except Exception as e:
            logger.error("Error in host watcher: %s", e)

    # Perform initial full scan and send files to WebContainer to populate it
    try:
        initial_files = _get_workspace_files(base_dir)
        # Send everything in one initialization packet or multiple packets
        # In a real environment, sending them all in a single init message is perfect
        init_payload = {
            "type": "init",
            "files": {
                rel_path: {"content": info["content"], "is_binary": info["is_binary"]}
                for rel_path, info in initial_files.items()
            }
        }
        await websocket.send_json(init_payload)

        # Initialize tracking times
        tracked_state = {rel_path: info["mtime"] for rel_path, info in initial_files.items()}
        logger.info("Sent %d files to client WebContainer for initial sync.", len(initial_files))

        # Launch concurrent background listener and watcher
        await asyncio.gather(client_listener(), host_watcher())

    except WebSocketDisconnect:
        logger.info("WebDev sync WebSocket disconnected.")
    except Exception as e:
        logger.error("WebDev sync WebSocket crashed: %s", e)
