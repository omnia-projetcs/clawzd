#!/bin/bash
# ==============================================
#   Clawzd — Docker Update Script
# ==============================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/common.sh
source "$SCRIPT_DIR/scripts/common.sh"

echo "=============================================="
echo "       Clawzd - Update (Docker)"
echo "=============================================="

# --- Git pull ---
echo ""
echo "--- Pulling latest changes ---"
git pull origin main 2>&1 || echo "WARNING: git pull failed (not a git repo or no remote)"

clawzd_ensure_env_file
clawzd_ensure_data_dirs

DOCKER_CMD=$(clawzd_detect_docker_compose) || {
    echo "ERROR: Neither 'docker-compose' nor 'docker compose' found."
    exit 1
}
COMPOSE_FILES=$(clawzd_compose_files)
clawzd_print_docker_gpu_status

echo ""
echo "--- Rebuilding Docker Images ---"
# shellcheck disable=SC2086
$DOCKER_CMD $COMPOSE_FILES build

echo ""
echo "--- Restarting Containers ---"
# shellcheck disable=SC2086
$DOCKER_CMD $COMPOSE_FILES down
# shellcheck disable=SC2086
$DOCKER_CMD $COMPOSE_FILES up -d

echo ""
echo "--- Pulling default Ollama models (inside container) ---"
DEFAULT_MODEL=$(clawzd_read_env_value "OLLAMA_MODEL" "qwen3.5:9b")
ENHANCE_MODEL=$(clawzd_read_env_value "ENHANCE_MODEL" "gemma3:4b")
docker exec ollama ollama pull "$DEFAULT_MODEL" 2>&1 || echo "WARNING: Could not pull $DEFAULT_MODEL in ollama container."
if [ -n "$ENHANCE_MODEL" ] && [ "$ENHANCE_MODEL" != "$DEFAULT_MODEL" ]; then
    docker exec ollama ollama pull "$ENHANCE_MODEL" 2>&1 || echo "WARNING: Could not pull $ENHANCE_MODEL in ollama container."
fi

echo ""
echo "=============================================="
echo " Update complete! Clawzd is restarting in Docker."
echo " Check logs with: $DOCKER_CMD $COMPOSE_FILES logs -f"
echo "=============================================="
