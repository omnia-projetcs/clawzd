#!/bin/bash

# Kill any existing instances to avoid "Address already in use"
PIDS=$(pgrep -f "python.*main\.py" 2>/dev/null || true)
if [ -n "$PIDS" ]; then
    echo "Killing existing Clawzd instance(s) (PID: $PIDS)..."
    kill $PIDS 2>/dev/null || true
    sleep 1
    kill -9 $PIDS 2>/dev/null || true
fi

# Ensure child uvicorn workers are also killed
UVICORN_PIDS=$(pgrep -f "uvicorn app.gateway:app" 2>/dev/null || true)
if [ -n "$UVICORN_PIDS" ]; then
    kill -9 $UVICORN_PIDS 2>/dev/null || true
fi

if [ -x ".venv/bin/python3" ]; then
    PYTHON_CMD=".venv/bin/python3"
elif [ -x ".venv/bin/python" ]; then
    PYTHON_CMD=".venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_CMD="python3"
elif command -v python >/dev/null 2>&1; then
    PYTHON_CMD="python"
else
    echo "Python executable not found. Please ensure Python is installed and the virtual environment is valid."
    exit 127
fi

# Source virtual environment if available (for PATH and other env vars)
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
fi

export PYTHONUNBUFFERED=1
exec $PYTHON_CMD main.py "$@"