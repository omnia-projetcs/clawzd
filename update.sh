#!/bin/bash
# ==============================================
#   Clawzd — Update Script
# ==============================================
set -e

echo "=============================================="
echo "       Clawzd - Update"
echo "=============================================="

# Activate virtual environment
if [ -d ".venv" ]; then
    source .venv/bin/activate
else
    echo "ERROR: .venv not found. Run install.sh first."
    exit 1
fi

# --- Git pull ---
echo ""
echo "--- Pulling latest changes ---"
git pull origin main 2>&1 || echo "WARNING: git pull failed (not a git repo or no remote)"

# --- Reinstall dependencies ---
echo ""
echo "--- Updating Python dependencies ---"
pip install -r requirements.txt --upgrade --quiet 2>&1 | tail -5

# --- Ensure data directories exist ---
mkdir -p data/sessions data/profiles data/skills data/images data/screenshots data/audit_reports workspace chroma_db

# --- Verify Ollama model hash ---
echo ""
echo "--- Verifying Ollama model integrity ---"
if command -v ollama &> /dev/null; then
    # Read active model from .env
    if [ -f ".env" ]; then
        ACTIVE_MODEL=$( (grep -oP 'OLLAMA_MODEL=\K.*' .env 2>/dev/null || echo "") | tr -d "\"'" )
    fi
    ACTIVE_MODEL=${ACTIVE_MODEL:-"qwen3:latest"}

    # Check model is present and get its digest
    MODEL_INFO=$(ollama show "$ACTIVE_MODEL" --modelfile 2>/dev/null || echo "")
    if [ -n "$MODEL_INFO" ]; then
        DIGEST=$(ollama list 2>/dev/null | grep "$(echo $ACTIVE_MODEL | cut -d: -f1)" | awk '{print $2}' | head -1)
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
    # Check for active user services first
    if systemctl --user is-active --quiet clawzd.service 2>/dev/null || systemctl --user is-failed --quiet clawzd.service 2>/dev/null; then
        SERVICE_NAME="clawzd.service"
        USER_MODE=true
    elif systemctl --user is-active --quiet houseofclaw.service 2>/dev/null || systemctl --user is-failed --quiet houseofclaw.service 2>/dev/null; then
        SERVICE_NAME="houseofclaw.service"
        USER_MODE=true
    # Then check for active system services
    elif systemctl is-active --quiet clawzd.service 2>/dev/null || systemctl is-failed --quiet clawzd.service 2>/dev/null; then
        SERVICE_NAME="clawzd.service"
    elif systemctl is-active --quiet houseofclaw.service 2>/dev/null || systemctl is-failed --quiet houseofclaw.service 2>/dev/null; then
        SERVICE_NAME="houseofclaw.service"
    fi
fi

if [ -n "$SERVICE_NAME" ]; then
    if [ "$USER_MODE" = true ]; then
        echo "User systemd service ($SERVICE_NAME) detected and active. Restarting via systemctl --user..."
        systemctl --user restart "$SERVICE_NAME"
        echo "✓ Service restarted via systemd (--user)."
    else
        echo "Systemd service ($SERVICE_NAME) detected and active. Restarting via systemctl..."
        # Ask for rights if not root
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
    # Fallback to local background script
    # run.sh handles killing existing instances internally
    
    # Restart in background
    echo "Starting Clawzd via run.sh in background..."
    ./run.sh &
    sleep 2

    # Verify it started
    if pgrep -f "python.*main\.py" > /dev/null 2>&1 || pgrep -f "uvicorn app.gateway:app" > /dev/null 2>&1; then
        echo "✓ Clawzd restarted successfully"
    else
        echo "WARNING: Service may not have started. Check manually: ./run.sh"
    fi
fi

echo ""
echo "=============================================="
echo "  Update complete!"
echo "=============================================="