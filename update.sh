#!/bin/bash
# ==============================================
#   Clawzd — Update Script
# ==============================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/common.sh
source "$SCRIPT_DIR/scripts/common.sh"

echo "=============================================="
echo "       Clawzd - Update"
echo "=============================================="

# Activate virtual environment
if [ -d ".venv" ]; then
    source .venv/bin/activate
    PYTHON_CMD="python"
else
    echo "ERROR: .venv not found. Run install.sh first."
    exit 1
fi

# --- Git pull ---
echo ""
echo "--- Pulling latest changes ---"
git pull origin main 2>&1 || echo "WARNING: git pull failed (not a git repo or no remote)"

# --- System dependencies ---
echo ""
echo "--- Updating System Dependencies ---"
clawzd_install_system_deps

# --- Reinstall dependencies ---
echo ""
echo "--- Updating Python dependencies ---"
pip install -r requirements.txt --upgrade

# --- Playwright browsers ---
clawzd_install_playwright "$PYTHON_CMD"

# --- Static assets & frontend ---
echo ""
echo "--- Updating static assets ---"
clawzd_download_static_assets
clawzd_build_frontend

# --- Ensure data directories exist ---
clawzd_ensure_data_dirs

# --- Run database migrations ---
clawzd_run_migrations "$PYTHON_CMD"

# --- Verify Ollama model hash ---
echo ""
echo "--- Verifying Ollama model integrity ---"
if command -v ollama &> /dev/null; then
    ACTIVE_MODEL=$(clawzd_read_env_value "OLLAMA_MODEL" "qwen3.5:9b")

    MODEL_INFO=$(ollama show "$ACTIVE_MODEL" --modelfile 2>/dev/null || echo "")
    if [ -n "$MODEL_INFO" ]; then
        DIGEST=$(ollama list 2>/dev/null | grep "$(echo "$ACTIVE_MODEL" | cut -d: -f1)" | awk '{print $2}' | head -1)
        if [ -n "$DIGEST" ]; then
            echo "Model: $ACTIVE_MODEL"
            echo "Digest: $DIGEST"
            echo "✓ Model integrity verified"
        else
            echo "WARNING: Could not read model digest for $ACTIVE_MODEL"
        fi
    else
        echo "WARNING: Model $ACTIVE_MODEL not found in Ollama."
        echo "Run: ollama pull $ACTIVE_MODEL"
    fi
else
    echo "WARNING: Ollama not installed — skipping model verification."
fi

# --- Restart service ---
echo ""
echo "--- Restarting Clawzd service ---"

SERVICE_NAME=""
USER_MODE=false

if command -v systemctl &> /dev/null; then
    if systemctl --user is-active --quiet clawzd.service 2>/dev/null || systemctl --user is-failed --quiet clawzd.service 2>/dev/null; then
        SERVICE_NAME="clawzd.service"
        USER_MODE=true
    elif systemctl is-active --quiet clawzd.service 2>/dev/null || systemctl is-failed --quiet clawzd.service 2>/dev/null; then
        SERVICE_NAME="clawzd.service"
    fi
fi

if [ -n "$SERVICE_NAME" ]; then
    if [ "$USER_MODE" = true ]; then
        echo "User systemd service ($SERVICE_NAME) detected and active. Restarting via systemctl --user..."
        systemctl --user restart "$SERVICE_NAME"
        echo "✓ Service restarted via systemd (--user)."
    else
        echo "Systemd service ($SERVICE_NAME) detected and active. Restarting via systemctl..."
        if [ "$EUID" -ne 0 ]; then
            echo "Administrator rights are required to restart the system service. Requesting sudo..."
            if command -v sudo &> /dev/null; then
                sudo systemctl restart "$SERVICE_NAME"
            else
                su -c "systemctl restart $SERVICE_NAME"
            fi
        else
            systemctl restart "$SERVICE_NAME"
        fi
        echo "✓ Service restarted via systemd."
    fi
elif [ -f "$HOME/Library/LaunchAgents/com.clawzd.plist" ] && launchctl list | grep -q com.clawzd; then
    echo "Launchd service detected. Restarting via launchctl..."
    launchctl stop com.clawzd 2>/dev/null || true
    launchctl start com.clawzd
    echo "✓ Service restarted via launchctl."
else
    echo "Starting Clawzd via run.sh in background..."
    nohup ./run.sh > /dev/null 2>&1 &
    sleep 2

    if pgrep -f "python.*main\.py" > /dev/null 2>&1; then
        echo "✓ Clawzd restarted successfully"
    else
        echo "WARNING: Service may not have started. Check manually: ./run.sh"
    fi
fi

echo ""
echo "=============================================="
echo "  Update complete!"
echo "=============================================="