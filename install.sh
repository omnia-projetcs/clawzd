#!/bin/bash
set -e

# ==============================================
#   Clawzd – Automated Installation Script
# ==============================================

echo "=============================================="
echo "       Clawzd - Full Installation"
echo "=============================================="

OS="$(uname -s)"
echo "Detected Operating System: $OS"

# ---------- Docker Installation Option ----------
echo ""
if [ -t 0 ]; then
    read -p "Would you like to install Clawzd using Docker (with NVIDIA GPU support)? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "--- Docker Installation ---"
        if ! command -v docker &> /dev/null; then
            echo "Docker is not installed. Automatically installing Docker and NVIDIA Container Toolkit..."
            if [ "$OS" = "Darwin" ]; then
                echo "Please install Docker Desktop for Mac manually from: https://docs.docker.com/desktop/install/mac-install/"
                exit 1
            fi
            if ! command -v curl &> /dev/null || ! command -v sudo &> /dev/null; then
                echo "ERROR: curl and sudo are required to automatically install Docker."
                exit 1
            fi
            
            # Installation de Docker
            echo "Downloading and installing Docker..."
            curl -fsSL https://get.docker.com -o get-docker.sh
            sudo sh get-docker.sh
            rm -f get-docker.sh
            
            # Installation du NVIDIA Container Toolkit (pour Debian/Ubuntu)
            echo "Installing NVIDIA Container Toolkit..."
            if command -v apt-get &> /dev/null; then
                curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
                curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
                    sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
                    sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
                sudo apt-get update
                sudo apt-get install -y nvidia-container-toolkit
                sudo nvidia-ctk runtime configure --runtime=docker
                sudo systemctl restart docker
                echo "NVIDIA Container Toolkit installed and Docker restarted."
            else
                echo "WARNING: Package manager not supported for automatic NVIDIA Toolkit installation."
                echo "Please install it manually if needed."
            fi
            
            # Ajout de l'utilisateur au groupe docker
            sudo usermod -aG docker $USER || true
            echo "WARNING: You might need to log out and log back in for Docker permissions to take effect."
            echo "If the next step fails, please relaunch this script."
        fi
        if ! docker compose version &> /dev/null && ! command -v docker-compose &> /dev/null; then
            echo "ERROR: Docker Compose is not installed. Please install it and try again."
            exit 1
        fi
        
        # Create default .env if it doesn't exist
        if [ ! -f ".env" ]; then
            if [ -f ".env.example" ]; then
                cp .env.example .env
            else
                cat > .env << 'EOF'
# === Clawzd Configuration ===
LLM_PROVIDER=local
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=qwen3.5:9b
APP_HOST=0.0.0.0
APP_PORT=8888
EOF
            fi
            echo "Default .env file created."
        fi

        # Make sure target directories exist
        mkdir -p data/sessions data/profiles data/skills data/images data/screenshots data/audit_reports data/snapshots data/playbooks data/playbook_state data/checkpoints workspace chroma_db models

        echo "Starting Docker Compose (building... this may take a while)..."
        if docker compose version &> /dev/null; then
            docker compose up -d --build
        else
            docker-compose up -d --build
        fi
        
        echo ""
        echo "=============================================="
        echo "  Docker Installation completed!"
        echo "  The application should be accessible at: http://localhost:8888"
        echo "  Local shared folders: ./data, ./models, ./workspace"
        echo "=============================================="
        exit 0
    fi
fi

# ---------- System Checks ----------
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python3 is not installed."
    exit 1
fi

PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
if ! python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"; then
    echo "ERROR: Python 3.11 or higher is required. Current version: $PYTHON_VERSION"
    exit 1
fi

if ! command -v curl &> /dev/null; then
    echo "ERROR: curl is not installed (required for downloads)."
    exit 1
fi

# ---------- Ollama Check ----------
echo ""
echo "--- Checking Ollama ---"
if command -v ollama &> /dev/null; then
    OLLAMA_VERSION=$(ollama --version 2>&1 | grep -oP '\d+\.\d+\.\d+' || echo "?")
    echo "Ollama detected (v$OLLAMA_VERSION)."

    # Verify that the service is running
    if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
        MODEL_COUNT=$(curl -s http://localhost:11434/api/tags | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('models',[])))" 2>/dev/null || echo "?")
        echo "Ollama is running — $MODEL_COUNT models installed."
    else
        echo "Ollama is installed but the service is not running."
        echo "Starting Ollama..."
        ollama serve &> /dev/null &
        sleep 3
        if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
            echo "Ollama started successfully."
        else
            echo "WARNING: Could not start Ollama automatically."
            echo "Please start it manually: ollama serve"
        fi
    fi
else
    echo "Ollama is not installed."
    echo "Installing Ollama..."
    if [ "$OS" = "Darwin" ]; then
        if command -v brew &> /dev/null; then
            brew install --cask ollama
        else
            echo "ERROR: Homebrew is required to install Ollama on Mac. Please install Homebrew and rerun."
            exit 1
        fi
    else
        curl -fsSL https://ollama.com/install.sh | sh
    fi
    
    if command -v ollama &> /dev/null; then
        echo "Ollama installed successfully."
        echo "Starting Ollama..."
        ollama serve &> /dev/null &
        sleep 3
    else
        echo "ERROR: Ollama installation failed."
        echo "Please install manually: https://ollama.com/download"
        exit 1
    fi
fi

# ---------- System Dependencies ----------
echo ""
echo "--- Installing System Dependencies ---"
if command -v apt-get &> /dev/null; then
    if command -v sudo &> /dev/null; then
        echo "Installing TTS, media and OCR dependencies (requires sudo)..."
        sudo apt-get update && sudo apt-get install -y espeak espeak-ng espeak-data libespeak-dev ffmpeg tesseract-ocr tesseract-ocr-eng tesseract-ocr-fra
    else
        echo "WARNING: sudo not available. Please install manually: apt-get install espeak espeak-ng espeak-data libespeak-dev ffmpeg tesseract-ocr tesseract-ocr-eng tesseract-ocr-fra"
    fi
fi

# ---------- Virtual Environment ----------
if [ ! -d ".venv" ]; then
    echo ""
    echo "Creating Python virtual environment..."
    python3 -m venv .venv
    source .venv/bin/activate
else
    source .venv/bin/activate
    echo "Existing virtual environment activated."
fi

# Always ensure pip, setuptools, and wheel are up to date
pip install --upgrade pip setuptools wheel

# ---------- Python Dependencies Installation ----------
echo ""
echo "--- Installing Python dependencies (requirements.txt) ---"
pip install -r requirements.txt 2>&1 | tail -10

# ---------- Playwright Browsers Installation ----------
echo ""
echo "--- Installing Playwright browsers ---"
if python -c "import playwright" &>/dev/null; then
    echo "Installing Chromium for Playwright..."
    python -m playwright install chromium 2>&1 | tail -3
    # Install system dependencies for Playwright (if possible)
    if command -v sudo &> /dev/null; then
        echo "Installing Playwright system dependencies..."
        python -m playwright install-deps chromium 2>&1 | tail -3 || echo "WARNING: install-deps failed. Run: sudo python -m playwright install-deps chromium"
    else
        echo "WARNING: sudo not available. Run manually: sudo python -m playwright install-deps chromium"
    fi
else
    echo "WARNING: playwright could not be imported, skipping browser installation."
fi

# ---------- Trivy Installation (vulnerability scanner) ----------
echo ""
echo "--- Installing Trivy (code audit) ---"
if command -v trivy &> /dev/null; then
    TRIVY_VER=$(trivy --version 2>&1 | grep -oP 'Version: \K[0-9.]+' || echo "?")
    echo "Trivy is already installed (v$TRIVY_VER)."
else
    echo "Installing Trivy..."
    if [ "$OS" = "Darwin" ]; then
        if command -v brew &> /dev/null; then
            brew install trivy
        else
            echo "WARNING: Homebrew not found. Install Trivy manually."
        fi
    else
        if command -v sudo &> /dev/null; then
            # Official method: Aqua Security install script
            curl -sfL https://raw.githubusercontent.com/aquasecurity/trivy/main/contrib/install.sh | sudo sh -s -- -b /usr/local/bin 2>&1 | tail -3
            if command -v trivy &> /dev/null; then
                echo "✓ Trivy installed successfully."
            else
                echo "WARNING: Automatic Trivy installation failed."
                echo "  Install manually: https://aquasecurity.github.io/trivy/latest/getting-started/installation/"
            fi
        else
            echo "WARNING: sudo not available. Install Trivy manually:"
            echo "  curl -sfL https://raw.githubusercontent.com/aquasecurity/trivy/main/contrib/install.sh | sudo sh -s -- -b /usr/local/bin"
        fi
    fi
fi


# ---------- Critical Dependencies Check ----------
echo ""
echo "--- Checking installed dependencies ---"
MISSING=""

check_dep() {
    local pkg="$1"
    local import_name="$2"
    if ! python -c "import $import_name" &>/dev/null; then
        echo "  ✗ $pkg ($import_name) — MISSING"
        MISSING="$MISSING $pkg"
    else
        echo "  ✓ $pkg"
    fi
}

# Core
check_dep "fastapi" "fastapi"
check_dep "uvicorn" "uvicorn"
check_dep "sse-starlette" "sse_starlette"
check_dep "jinja2" "jinja2"
check_dep "python-multipart" "multipart"
check_dep "python-dotenv" "dotenv"
check_dep "pydantic" "pydantic"
check_dep "httpx" "httpx"

# LLM
check_dep "openai" "openai"
check_dep "google-genai" "google.genai"

# RAG
check_dep "chromadb" "chromadb"
check_dep "sentence-transformers" "sentence_transformers"

# Search
check_dep "ddgs" "ddgs"

# Code quality (CLI tools)
check_dep "pylint" "pylint"
check_dep "bandit" "bandit"
check_dep "radon" "radon"
check_dep "semgrep" "semgrep"

# Security scanner (CLI tool)
if command -v trivy &> /dev/null; then
    echo "  ✓ trivy"
else
    echo "  ✗ trivy — MISSING (install via install.sh or manually)"
fi

# Semantic code graph
if command -v graphify &> /dev/null; then
    echo "  ✓ graphify (semantic code graph)"
else
    echo "  ✗ graphify — MISSING (pip install graphifyy)"
fi

# Structural code graph (MCP)
if command -v code-review-graph &> /dev/null; then
    echo "  ✓ code-review-graph (MCP structural analysis)"
else
    echo "  ✗ code-review-graph — MISSING (pip install code-review-graph)"
fi

# Browser & Automation
check_dep "playwright" "playwright"
check_dep "apscheduler" "apscheduler"

# Image & Video generation (Local AI)
if python -c "import torch" &>/dev/null; then
    echo "  ✓ torch (Local AI Generation)"
else
    echo "  ✗ torch — MISSING (required for local image/video generation)"
    MISSING="$MISSING torch diffusers accelerate"
fi

# Integrations
check_dep "discord.py" "discord"

# Document processing
check_dep "PyMuPDF" "fitz"
check_dep "pdfplumber" "pdfplumber"

if [ -n "$MISSING" ]; then
    echo ""
    echo "⚠ Missing dependencies :$MISSING"
    echo "  Attempting to reinstall..."
    pip install $MISSING 2>&1 | tail -5
fi

# ---------- Download Static Assets ----------
echo ""
echo "--- Downloading static assets (offline mode) ---"
mkdir -p static/css static/js static/fonts

download_file() {
    local url="$1"
    local dest="$2"
    if [ ! -f "$dest" ]; then
        echo "Downloading $(basename "$dest")..."
        if ! curl -L --fail --progress-bar -o "$dest" "$url"; then
            echo "ERROR: Failed to download $url"
            exit 1
        fi
        echo "OK: $(basename "$dest")"
    else
        echo "SKIP: $(basename "$dest") already exists."
    fi
}

download_file "https://unpkg.com/htmx.org@1.9.12/dist/htmx.min.js" "static/js/htmx.min.js"
download_file "https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.min.css" "static/css/pico.min.css"
download_file "https://github.com/rsms/inter/raw/master/docs/font-files/Inter-Regular.woff2" "static/fonts/inter.woff2"
download_file "https://raw.githubusercontent.com/paul-norman/codemirror6-prebuilt/main/dist/python.min.js" "static/js/cm6.bundle.js"

# Highlight.js for syntax highlighting (local bundle)
download_file "https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js" "static/js/highlight.min.js"
download_file "https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github-dark.min.css" "static/css/github-dark.min.css"

# Mermaid.js for diagrams (local bundle)
download_file "https://cdnjs.cloudflare.com/ajax/libs/mermaid/10.9.1/mermaid.min.js" "static/js/mermaid.min.js"

# ---------- .env File and Tokens ----------
echo ""
echo "--- Environment Configuration ---"

if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        cp .env.example .env
    else
        cat > .env << 'EOF'
# === Clawzd Configuration ===
LLM_PROVIDER=local
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=qwen3.5:9b
APP_HOST=0.0.0.0
APP_PORT=8888
EOF
    fi
    echo "Default .env file created."
fi

if [ -t 0 ]; then
    read -p "Would you like to configure API keys (Tokens) now? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        for TOKEN in "OPENAI_API_KEY" "ANTHROPIC_API_KEY" "GOOGLE_API_KEY" "XAI_API_KEY" "GROQ_API_KEY" "GITHUB_TOKEN"; do
            read -p "Enter $TOKEN (leave blank to skip): " token_val
            if [ -n "$token_val" ]; then
                # Check if the key already exists in .env
                if grep -q "^${TOKEN}=" .env; then
                    if [ "$OS" = "Darwin" ]; then
                        sed -i '' "s|^${TOKEN}=.*|${TOKEN}=${token_val}|" .env
                    else
                        sed -i "s|^${TOKEN}=.*|${TOKEN}=${token_val}|" .env
                    fi
                else
                    echo "${TOKEN}=${token_val}" >> .env
                fi
                echo "✓ $TOKEN configured."
            fi
        done
    fi
fi

# ---------- Installation of Models via Ollama ----------
echo ""
echo "--- Installing local LLM models ---"

if [ -t 0 ] && [ -f "models_catalog.json" ]; then
    read -p "Would you like to choose local models to download via Ollama? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        cat > .model_wizard.py << 'EOF'
import json
import subprocess
import sys

try:
    with open("models_catalog.json", "r") as f:
        models = json.load(f)
except Exception as e:
    print(f"Error reading models_catalog.json: {e}")
    sys.exit(1)

print("\nAvailable Models:")
for i, m in enumerate(models):
    rec = " [Recommended]" if m.get("recommended") else ""
    print(f"{i+1}) {m['name']} ({m['params']}, {m['size_gb']}GB) - {m['description']}{rec}")

print("\nEnter the numbers of the models to download, separated by commas (e.g., 1,3,4).")
print("Type 'all' to download all recommended models.")
print("Leave blank to skip.")

choice = input("Your choice: ").strip().lower()
if not choice:
    sys.exit(0)

to_download = []
if choice == 'all':
    to_download = [m['ollama_id'] for m in models if m.get('recommended')]
else:
    parts = [p.strip() for p in choice.split(',')]
    for p in parts:
        if p.isdigit():
            idx = int(p) - 1
            if 0 <= idx < len(models):
                to_download.append(models[idx]['ollama_id'])
            else:
                print(f"Invalid number ignored: {p}")

for model_id in to_download:
    print(f"\n--- Downloading model {model_id} ---")
    try:
        subprocess.run(["ollama", "pull", model_id], check=True)
    except subprocess.CalledProcessError:
        print(f"Error downloading {model_id}.")
EOF
        python3 .model_wizard.py
        rm -f .model_wizard.py
    else
        DEFAULT_MODEL=$( (grep -oP 'OLLAMA_MODEL=\K.*' .env 2>/dev/null || awk -F '=' '/^OLLAMA_MODEL=/ {print $2}' .env 2>/dev/null || echo "qwen3.5:9b") | tr -d "\"'" )
        if ollama list 2>/dev/null | grep -q "$(echo $DEFAULT_MODEL | cut -d: -f1)"; then
            echo "Model $DEFAULT_MODEL is already installed."
        else
            echo "Downloading the default model ($DEFAULT_MODEL) via Ollama..."
            ollama pull "$DEFAULT_MODEL"
        fi
    fi
else
    DEFAULT_MODEL=$( (grep -oP 'OLLAMA_MODEL=\K.*' .env 2>/dev/null || awk -F '=' '/^OLLAMA_MODEL=/ {print $2}' .env 2>/dev/null || echo "qwen3.5:9b") | tr -d "\"'" )
    if ollama list 2>/dev/null | grep -q "$(echo $DEFAULT_MODEL | cut -d: -f1)"; then
        echo "Model $DEFAULT_MODEL is already installed."
    else
        echo "Downloading the default model ($DEFAULT_MODEL) via Ollama..."
        ollama pull "$DEFAULT_MODEL"
    fi
fi

# --- Pull the enhance/enrichment model (fast, non-reasoning) ---
ENHANCE_MODEL_ID=$( (grep -oP 'ENHANCE_MODEL=\K.*' .env 2>/dev/null || awk -F '=' '/^ENHANCE_MODEL=/ {print $2}' .env 2>/dev/null || echo "gemma3:4b") | tr -d "\"'" )
if [ -n "$ENHANCE_MODEL_ID" ] && [ "$ENHANCE_MODEL_ID" != "$DEFAULT_MODEL" ]; then
    if ollama list 2>/dev/null | grep -q "$(echo $ENHANCE_MODEL_ID | cut -d: -f1)"; then
        echo "Enhance model $ENHANCE_MODEL_ID is already installed."
    else
        echo "Downloading enhance model ($ENHANCE_MODEL_ID) via Ollama..."
        ollama pull "$ENHANCE_MODEL_ID" || echo "WARNING: Could not download $ENHANCE_MODEL_ID — enrichment will fall back to default model."
    fi
fi

# ---------- Creating Working Directories ----------
mkdir -p data/sessions data/profiles data/skills data/images data/screenshots data/audit_reports data/snapshots data/playbooks data/playbook_state data/checkpoints workspace chroma_db

echo ""
# ---------- System Service ----------
if [ -t 0 ]; then
    echo "=============================================="
    read -p "Would you like to install Clawzd as a system service so it starts automatically on boot? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        CURRENT_DIR="$(pwd)"
        CURRENT_USER="$(whoami)"
        if [ "$OS" = "Linux" ]; then
            SERVICE_FILE="/etc/systemd/system/clawzd.service"
            echo "Creating systemd service..."
            if command -v sudo &> /dev/null; then
                sudo bash -c "cat > $SERVICE_FILE" << EOF
[Unit]
Description=Clawzd AI Assistant
After=network.target ollama.service

[Service]
Type=simple
User=$CURRENT_USER
WorkingDirectory=$CURRENT_DIR
ExecStart=$CURRENT_DIR/run.sh
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
                sudo systemctl daemon-reload
                sudo systemctl enable clawzd.service
                echo "systemd service enabled. You can start it with: sudo systemctl start clawzd"
            else
                echo "Error: sudo is required to install the systemd service."
            fi
        elif [ "$OS" = "Darwin" ]; then
            PLIST_FILE="$HOME/Library/LaunchAgents/com.clawzd.plist"
            echo "Creating launchd service (Mac)..."
            mkdir -p ~/Library/LaunchAgents
            cat > "$PLIST_FILE" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.clawzd</string>
    <key>ProgramArguments</key>
    <array>
        <string>$CURRENT_DIR/run.sh</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$CURRENT_DIR</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardErrorPath</key>
    <string>$CURRENT_DIR/clawzd.err</string>
    <key>StandardOutPath</key>
    <string>$CURRENT_DIR/clawzd.out</string>
</dict>
</plist>
EOF
            launchctl load -w "$PLIST_FILE"
            echo "launchd service enabled. Clawzd will start automatically on login."
        fi
    fi
fi

echo ""
echo "=============================================="
echo "  Installation completed successfully!"
echo ""
echo "  LLM Backend: Ollama ($DEFAULT_MODEL)"
echo "  Run the application: ./run.sh"
echo "=============================================="