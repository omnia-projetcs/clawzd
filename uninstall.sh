#!/bin/bash
# ==============================================
#   Clawzd — Uninstall Script
# ==============================================

echo "=============================================="
echo "       Clawzd - Uninstall"
echo "=============================================="

# --- Stop running service ---
PIDS=$(pgrep -f "uvicorn app.gateway:app" 2>/dev/null || true)
if [ -n "$PIDS" ]; then
    echo "Stopping running Clawzd instance..."
    kill $PIDS 2>/dev/null || true
    sleep 1
    kill -9 $PIDS 2>/dev/null || true
fi

# --- Virtual environment removal ---
echo ""
echo "Remove virtual environment (.venv)? (y/n)"
read -r rep
if [ "$rep" = "y" ] || [ "$rep" = "o" ]; then
    rm -rf .venv
    echo "✓ Virtual environment removed."
fi

# --- Data removal ---
echo ""
echo "Remove application data (chroma_db/, data/, workspace/)? (y/n)"
echo "  WARNING: This deletes all sessions, profiles, feedback, and skills."
read -r rep
if [ "$rep" = "y" ] || [ "$rep" = "o" ]; then
    rm -rf chroma_db data workspace
    echo "✓ Application data removed."
fi

# --- Ollama model deletion ---
echo ""
echo "Remove Ollama models? (y/n)"
echo "  This will delete ALL models from Ollama (not just Clawzd ones)."
read -r rep
if [ "$rep" = "y" ] || [ "$rep" = "o" ]; then
    if command -v ollama &> /dev/null; then
        echo ""
        echo "Installed Ollama models:"
        ollama list 2>/dev/null || echo "  (none)"
        echo ""
        echo "Delete ALL listed models? (y/n)"
        read -r confirm
        if [ "$confirm" = "y" ] || [ "$confirm" = "o" ]; then
            MODELS=$(ollama list 2>/dev/null | tail -n +2 | awk '{print $1}')
            for model in $MODELS; do
                echo "  Deleting $model..."
                ollama rm "$model" 2>/dev/null || true
            done
            echo "✓ Ollama models removed."
        else
            echo "Skipped model deletion."
        fi
    else
        echo "Ollama not installed — skipping."
    fi
fi

# --- Models directory ---
echo ""
echo "Remove local models directory (models/)? (y/n)"
read -r rep
if [ "$rep" = "y" ] || [ "$rep" = "o" ]; then
    rm -rf models
    echo "✓ Models directory removed."
fi

echo ""
echo "=============================================="
echo "  Uninstall complete."
echo "  Project source code is preserved."
echo "=============================================="