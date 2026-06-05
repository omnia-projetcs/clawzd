"""
Clawzd — Virtual Environment Orchestrator.
Manages creation and package installation for isolated Python virtual environments.
"""
import logging
import os
import sys
import subprocess
from pathlib import Path
from config import DATA_DIR

logger = logging.getLogger("clawzd.venv_orchestrator")

VENVS_DIR = os.path.join(DATA_DIR, "venvs")

class VenvOrchestrator:
    @staticmethod
    def get_venv_path(app_name: str) -> str:
        """Get the base path of the virtual environment for a given application."""
        return os.path.join(VENVS_DIR, app_name)

    @classmethod
    def get_python_executable(cls, app_name: str) -> str:
        """Get the path to the isolated Python interpreter."""
        venv_path = cls.get_venv_path(app_name)
        if sys.platform == "win32":
            return os.path.join(venv_path, "Scripts", "python.exe")
        return os.path.join(venv_path, "bin", "python")

    @classmethod
    def get_pip_executable(cls, app_name: str) -> str:
        """Get the path to the isolated pip installer."""
        venv_path = cls.get_venv_path(app_name)
        if sys.platform == "win32":
            return os.path.join(venv_path, "Scripts", "pip.exe")
        return os.path.join(venv_path, "bin", "pip")

    @classmethod
    def create_venv(cls, app_name: str) -> str:
        """Create a new virtual environment if it does not already exist."""
        venv_path = cls.get_venv_path(app_name)
        python_bin = cls.get_python_executable(app_name)

        if os.path.exists(python_bin):
            logger.info("Virtual environment for '%s' already exists at %s", app_name, venv_path)
            return venv_path

        logger.info("Creating virtual environment for '%s' at %s", app_name, venv_path)
        os.makedirs(VENVS_DIR, exist_ok=True)
        
        try:
            subprocess.run([sys.executable, "-m", "venv", venv_path], check=True)
            # Upgrade pip in the new venv
            pip_bin = cls.get_pip_executable(app_name)
            subprocess.run([pip_bin, "install", "--upgrade", "pip"], check=True, stdout=subprocess.DEVNULL)
            logger.info("Successfully created venv for '%s'", app_name)
        except Exception as e:
            logger.error("Failed to create virtual environment for '%s': %s", app_name, e)
            raise RuntimeError(f"Venv creation failed: {e}")

        return venv_path

    @classmethod
    def install_requirements(cls, app_name: str, req_path: str) -> bool:
        """Install packages from a requirements file into the application's venv."""
        cls.create_venv(app_name)
        pip_bin = cls.get_pip_executable(app_name)

        logger.info("Installing requirements into '%s' venv from %s", app_name, req_path)
        try:
            subprocess.run([pip_bin, "install", "-r", req_path], check=True)
            logger.info("Successfully installed requirements for '%s'", app_name)
            return True
        except Exception as e:
            logger.error("Failed to install requirements for '%s': %s", app_name, e)
            return False
