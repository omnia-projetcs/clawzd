#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

KILL_EXISTING="${CLAWZD_KILL_EXISTING:-0}"
if [ "${1:-}" = "--kill-existing" ]; then
    KILL_EXISTING=1
    shift
fi

# Smart detection of Docker mode
USE_DOCKER=0
if [ "${1:-}" = "--docker" ]; then
    USE_DOCKER=1
    shift
elif [ ! -d ".venv" ] && command -v docker &>/dev/null && [ -f "docker-compose.yml" ]; then
    # If no virtual environment exists but Docker compose is available, default to Docker
    USE_DOCKER=1
fi

if [ "$USE_DOCKER" = "1" ]; then
    echo "Running Clawzd in Docker mode..."
    if [ -f "$SCRIPT_DIR/scripts/common.sh" ]; then
        # shellcheck source=scripts/common.sh
        source "$SCRIPT_DIR/scripts/common.sh"
        
        # Load APP_PORT from .env if present
        PORT=8888
        if [ -f ".env" ]; then
            ENV_PORT=$(grep -E "^APP_PORT=" .env | cut -d'=' -f2 | tr -d "'\" ")
            if [ -n "$ENV_PORT" ]; then
                PORT=$ENV_PORT
            fi
        fi

        # Check if the configured port is in use on the host
        PORT_PID=""
        if command -v lsof >/dev/null 2>&1; then
            PORT_PID=$(lsof -t -i :"$PORT" 2>/dev/null || true)
        elif command -v fuser >/dev/null 2>&1; then
            PORT_PID=$(fuser "$PORT"/tcp 2>/dev/null | awk '{print $NF}' || true)
        fi

        if [ -n "$PORT_PID" ]; then
            if [ "$KILL_EXISTING" = "1" ]; then
                echo "Port $PORT is already in use by process(es): $PORT_PID. CLAWZD_KILL_EXISTING=1, freeing the port..."
                # shellcheck disable=SC2086
                kill $PORT_PID 2>/dev/null || true
                sleep 1
            else
                echo "WARNING: Port $PORT is already in use on the host. Docker container might fail to start if port is bound."
            fi
        fi

        clawzd_docker_up "$@"
        echo "Clawzd started in Docker. Logs can be viewed with: $(clawzd_detect_docker_compose) $(clawzd_compose_files) logs -f"
        exit 0
    else
        echo "ERROR: scripts/common.sh not found."
        exit 1
    fi
fi

# Kill any existing instances to avoid "Address already in use"
mapfile -t PIDS < <(pgrep -f "python.*main\.py" 2>/dev/null || true)
if [ "${#PIDS[@]}" -gt 0 ]; then
    echo "Stopping existing Clawzd instance(s): ${PIDS[*]}"
    kill "${PIDS[@]}" 2>/dev/null || true
    sleep 1
    for PID in "${PIDS[@]}"; do
        if kill -0 "$PID" 2>/dev/null; then
            kill -9 "$PID" 2>/dev/null || true
        fi
    done
fi

# Ensure child uvicorn workers are also killed
for UVICORN_PATTERN in "uvicorn app.gateway:app" "uvicorn.*main:app"; do
    mapfile -t UVICORN_PIDS < <(pgrep -f "$UVICORN_PATTERN" 2>/dev/null || true)
    if [ "${#UVICORN_PIDS[@]}" -gt 0 ]; then
        kill "${UVICORN_PIDS[@]}" 2>/dev/null || true
        sleep 0.5
        for PID in "${UVICORN_PIDS[@]}"; do
            if kill -0 "$PID" 2>/dev/null; then
                kill -9 "$PID" 2>/dev/null || true
            fi
        done
    fi
done

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
    PORT_PID=$(lsof -t -i :"$PORT" 2>/dev/null || true)
elif command -v fuser >/dev/null 2>&1; then
    PORT_PID=$(fuser "$PORT"/tcp 2>/dev/null | awk '{print $NF}' || true)
fi

if [ -n "$PORT_PID" ]; then
    if [ "$KILL_EXISTING" = "1" ]; then
        echo "Port $PORT is already in use by process(es): $PORT_PID. CLAWZD_KILL_EXISTING=1, freeing the port..."
        # shellcheck disable=SC2086
        kill $PORT_PID 2>/dev/null || true
        sleep 1
    else
        echo "ERROR: Port $PORT is already in use by process(es): $PORT_PID."
        echo "Set CLAWZD_KILL_EXISTING=1 or run ./run.sh --kill-existing to free the port automatically."
        exit 1
    fi
fi


if [ -x ".venv/bin/python3" ]; then
    PYTHON_CMD=".venv/bin/python3"
elif [ -x ".venv/bin/python" ]; then
    PYTHON_CMD=".venv/bin/python"
else
    echo "Virtual environment not found. Run ./install.sh first."
    exit 127
fi

# Source virtual environment if available (for PATH and other env vars)
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
fi

export PYTHONUNBUFFERED=1
exec "$PYTHON_CMD" main.py "$@"
