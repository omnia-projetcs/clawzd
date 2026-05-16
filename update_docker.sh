#!/bin/bash
# ==============================================
#   Clawzd — Docker Update Script
# ==============================================
set -e

echo "=============================================="
echo "       Clawzd - Update (Docker)"
echo "=============================================="

# --- Git pull ---
echo ""
echo "--- Pulling latest changes ---"
git pull origin main 2>&1 || echo "WARNING: git pull failed (not a git repo or no remote)"

# --- Docker Compose checks ---
if command -v docker-compose &> /dev/null; then
    DOCKER_CMD="docker-compose"
elif docker compose version &> /dev/null; then
    DOCKER_CMD="docker compose"
else
    echo "ERROR: Neither 'docker-compose' nor 'docker compose' found."
    exit 1
fi

echo ""
echo "--- Rebuilding Docker Images ---"
$DOCKER_CMD build

echo ""
echo "--- Restarting Containers ---"
$DOCKER_CMD down
$DOCKER_CMD up -d

echo ""
echo "=============================================="
echo " Update complete! Clawzd is restarting in Docker."
echo " Check logs with: $DOCKER_CMD logs -f"
echo "=============================================="
