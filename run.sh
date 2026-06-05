#!/bin/bash

# Kill any existing instances to avoid "Address already in use"
PIDS=$(pgrep -f "python.*main\.py" 2>/dev/null || true)
if [ -n "$PIDS" ]; then
    echo "Killing existing Clawzd instance(s) (PID: $PIDS)..."
    kill $PIDS 2>/dev/null || true
    sleep 0.5
    kill -9 $PIDS 2>/dev/null || true
fi

# Ensure child uvicorn workers are also killed
UVICORN_PIDS=$(pgrep -f "uvicorn app.gateway:app" 2>/dev/null || true)
if [ -n "$UVICORN_PIDS" ]; then
    kill -9 $UVICORN_PIDS 2>/dev/null || true
fi

# Load APP_PORT from .env if present
PORT=8888
if [ -f ".env" ]; then
    ENV_PORT=$(grep -E "^APP_PORT=" .env | cut -d'=' -f2 | tr -d "'\" ")
    if [ -n "$ENV_PORT" ]; then
        PORT=$ENV_PORT
    fi
fi

# Kill any process occupying the target port to guarantee it is free
PORT_PID=""
if command -v lsof >/dev/null 2>&1; then
    PORT_PID=$(lsof -t -i :$PORT 2>/dev/null || true)
elif command -v fuser >/dev/null 2>&1; then
    PORT_PID=$(fuser $PORT/tcp 2>/dev/null | awk '{print $NF}' || true)
fi

if [ -n "$PORT_PID" ]; then
    echo "Port $PORT is already in use by process(es): $PORT_PID. Killing to free the port..."
    kill -9 $PORT_PID 2>/dev/null || true
    sleep 1
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