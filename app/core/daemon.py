"""
Clawzd — Background Daemon Manager.
Manages long-running server processes (daemons) inside isolated environments.
"""
import logging
import os
import shlex
import subprocess
import threading
from typing import Dict, Any, Optional
from config import DATA_DIR

logger = logging.getLogger("clawzd.daemon")

DAEMON_LOGS_DIR = os.path.join(DATA_DIR, "logs", "daemons")

class DaemonInfo:
    def __init__(self, name: str, cmd: str, port: Optional[int] = None, cwd: Optional[str] = None):
        self.name = name
        self.cmd = cmd
        self.port = port
        self.cwd = cwd
        self.process: Optional[subprocess.Popen] = None
        self.status = "stopped"  # stopped, running, failed

class DaemonManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if not cls._instance:
                cls._instance = super(DaemonManager, cls).__new__(cls, *args, **kwargs)
                cls._instance._init_manager()
            return cls._instance

    def _init_manager(self):
        self.daemons: Dict[str, DaemonInfo] = {}
        os.makedirs(DAEMON_LOGS_DIR, exist_ok=True)

    def register_daemon(self, name: str, cmd: str, port: Optional[int] = None, cwd: Optional[str] = None):
        """Register a daemon with a specific command and optional port/working directory."""
        with self._lock:
            self.daemons[name] = DaemonInfo(name, cmd, port, cwd)
            logger.info("Registered daemon '%s' with command: %s", name, cmd)

    def start_daemon(self, name: str) -> bool:
        """Start a registered daemon in the background, logging its output to a file."""
        with self._lock:
            info = self.daemons.get(name)
            if not info:
                logger.error("Cannot start unregistered daemon: %s", name)
                return False

            if info.process and info.process.poll() is None:
                logger.info("Daemon '%s' is already running (PID: %d)", name, info.process.pid)
                return True

            log_file_path = os.path.join(DAEMON_LOGS_DIR, f"{name}.log")
            logger.info("Starting daemon '%s' -> logs at %s", name, log_file_path)

            try:
                log_file = open(log_file_path, "w", encoding="utf-8")
                # Spawn process in background — use shell=False for security (SEC-4)
                cmd_args = shlex.split(info.cmd) if isinstance(info.cmd, str) else info.cmd
                info.process = subprocess.Popen(
                    cmd_args,
                    shell=False,
                    cwd=info.cwd,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    start_new_session=True  # decouple from parent process group
                )
                info.status = "running"
                logger.info("Daemon '%s' started with PID: %d", name, info.process.pid)
                return True
            except Exception as e:
                logger.error("Failed to start daemon '%s': %s", name, e)
                info.status = "failed"
                return False

    def stop_daemon(self, name: str) -> bool:
        """Stop a running daemon process."""
        with self._lock:
            info = self.daemons.get(name)
            if not info or not info.process:
                logger.info("Daemon '%s' is not running", name)
                return True

            logger.info("Stopping daemon '%s' (PID: %d)", name, info.process.pid)
            try:
                # Terminate cleanly first
                info.process.terminate()
                info.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.warning("Daemon '%s' did not terminate in time. Killing it...", name)
                info.process.kill()
                info.process.wait()
            except Exception as e:
                logger.error("Error while terminating daemon '%s': %s", name, e)
                return False
            finally:
                info.status = "stopped"
                info.process = None

            logger.info("Daemon '%s' stopped successfully", name)
            return True

    def get_daemon_status(self, name: str) -> str:
        """Get the status of a daemon (running, stopped, failed)."""
        with self._lock:
            info = self.daemons.get(name)
            if not info:
                return "unknown"
            
            if info.process:
                poll = info.process.poll()
                if poll is not None:
                    info.status = "failed" if poll != 0 else "stopped"
                    info.process = None
            
            return info.status

def get_daemon_manager() -> DaemonManager:
    """Singleton getter for the DaemonManager."""
    return DaemonManager()
