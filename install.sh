#!/bin/bash
set -e

# ==============================================
#   Clawzd – Script d'installation automatisé
# ==============================================

echo "=============================================="
echo "       Clawzd - Installation complète"
echo "=============================================="

OS="$(uname -s)"
echo "Système d'exploitation détecté : $OS"

# ---------- Vérifications système ----------
if ! command -v python3 &> /dev/null; then
    echo "ERREUR : Python3 n'est pas installé."
    exit 1
fi

PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
if ! python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"; then
    echo "ERREUR : Python 3.11 ou supérieur requis. Version actuelle : $PYTHON_VERSION"
    exit 1
fi

if ! command -v curl &> /dev/null; then
    echo "ERREUR : curl n'est pas installé (requis pour les téléchargements)."
    exit 1
fi

# ---------- Vérification d'Ollama ----------
echo ""
echo "--- Vérification d'Ollama ---"
if command -v ollama &> /dev/null; then
    OLLAMA_VERSION=$(ollama --version 2>&1 | grep -oP '\d+\.\d+\.\d+' || echo "?")
    echo "Ollama détecté (v$OLLAMA_VERSION)."

    # Vérifier que le service tourne
    if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
        MODEL_COUNT=$(curl -s http://localhost:11434/api/tags | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('models',[])))" 2>/dev/null || echo "?")
        echo "Ollama est en marche — $MODEL_COUNT modèles installés."
    else
        echo "Ollama est installé mais le service n'est pas démarré."
        echo "Démarrage d'Ollama..."
        ollama serve &> /dev/null &
        sleep 3
        if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
            echo "Ollama démarré avec succès."
        else
            echo "ATTENTION : Impossible de démarrer Ollama automatiquement."
            echo "Lancez-le manuellement : ollama serve"
        fi
    fi
else
    echo "Ollama n'est pas installé."
    echo "Installation d'Ollama..."
    if [ "$OS" = "Darwin" ]; then
        if command -v brew &> /dev/null; then
            brew install --cask ollama
        else
            echo "ERREUR : Homebrew requis pour installer Ollama sur Mac. Installez Homebrew puis relancez."
            exit 1
        fi
    else
        curl -fsSL https://ollama.com/install.sh | sh
    fi
    
    if command -v ollama &> /dev/null; then
        echo "Ollama installé avec succès."
        echo "Démarrage d'Ollama..."
        ollama serve &> /dev/null &
        sleep 3
    else
        echo "ERREUR : L'installation d'Ollama a échoué."
        echo "Installez manuellement : https://ollama.com/download"
        exit 1
    fi
fi

# ---------- Environnement virtuel ----------
if [ ! -d ".venv" ]; then
    echo ""
    echo "Création de l'environnement virtuel Python..."
    python3 -m venv .venv
    source .venv/bin/activate
else
    source .venv/bin/activate
    echo "Environnement virtuel existant activé."
fi

# Toujours s'assurer que pip, setuptools et wheel sont à jour
pip install --upgrade pip setuptools wheel

# ---------- Installation des dépendances Python ----------
echo ""
echo "--- Installation des dépendances Python (requirements.txt) ---"
pip install -r requirements.txt 2>&1 | tail -10

# ---------- Installation des navigateurs Playwright ----------
echo ""
echo "--- Installation des navigateurs Playwright ---"
if python -c "import playwright" &>/dev/null; then
    echo "Installation de Chromium pour Playwright..."
    python -m playwright install chromium 2>&1 | tail -3
    # Installer les dépendances système de Playwright (si possible)
    if command -v sudo &> /dev/null; then
        echo "Installation des dépendances système Playwright..."
        python -m playwright install-deps chromium 2>&1 | tail -3 || echo "ATTENTION : install-deps a échoué. Exécutez : sudo python -m playwright install-deps chromium"
    else
        echo "ATTENTION : sudo non disponible. Exécutez manuellement : sudo python -m playwright install-deps chromium"
    fi
else
    echo "ATTENTION : playwright n'a pas pu être importé, saut de l'installation du navigateur."
fi

# ---------- Installation de Trivy (scanner de vulnérabilités) ----------
echo ""
echo "--- Installation de Trivy (code audit) ---"
if command -v trivy &> /dev/null; then
    TRIVY_VER=$(trivy --version 2>&1 | grep -oP 'Version: \K[0-9.]+' || echo "?")
    echo "Trivy déjà installé (v$TRIVY_VER)."
else
    echo "Installation de Trivy..."
    if [ "$OS" = "Darwin" ]; then
        if command -v brew &> /dev/null; then
            brew install trivy
        else
            echo "ATTENTION : Homebrew non trouvé. Installez Trivy manuellement."
        fi
    else
        if command -v sudo &> /dev/null; then
            # Méthode officielle : script d'installation Aqua Security
            curl -sfL https://raw.githubusercontent.com/aquasecurity/trivy/main/contrib/install.sh | sudo sh -s -- -b /usr/local/bin 2>&1 | tail -3
            if command -v trivy &> /dev/null; then
                echo "✓ Trivy installé avec succès."
            else
                echo "ATTENTION : L'installation automatique de Trivy a échoué."
                echo "  Installez manuellement : https://aquasecurity.github.io/trivy/latest/getting-started/installation/"
            fi
        else
            echo "ATTENTION : sudo non disponible. Installez Trivy manuellement :"
            echo "  curl -sfL https://raw.githubusercontent.com/aquasecurity/trivy/main/contrib/install.sh | sudo sh -s -- -b /usr/local/bin"
        fi
    fi
fi


# ---------- Vérification des dépendances critiques ----------
echo ""
echo "--- Vérification des dépendances installées ---"
MISSING=""

check_dep() {
    local pkg="$1"
    local import_name="$2"
    if ! python -c "import $import_name" &>/dev/null; then
        echo "  ✗ $pkg ($import_name) — MANQUANT"
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
    echo "  ✗ trivy — MANQUANT (installer via install.sh ou manuellement)"
fi

# Semantic code graph
if command -v graphify &> /dev/null; then
    echo "  ✓ graphify (semantic code graph)"
else
    echo "  ✗ graphify — MANQUANT (pip install graphifyy)"
fi

# Structural code graph (MCP)
if command -v code-review-graph &> /dev/null; then
    echo "  ✓ code-review-graph (MCP structural analysis)"
else
    echo "  ✗ code-review-graph — MANQUANT (pip install code-review-graph)"
fi

# Browser & Automation
check_dep "playwright" "playwright"
check_dep "apscheduler" "apscheduler"

# Image & Video generation (Local AI)
if python -c "import torch" &>/dev/null; then
    echo "  ✓ torch (Local AI Generation)"
else
    echo "  ✗ torch — MANQUANT (requis pour la génération d'images/vidéos locale)"
    MISSING="$MISSING torch diffusers accelerate"
fi

# Integrations
check_dep "discord.py" "discord"

# Document processing
check_dep "PyMuPDF" "fitz"
check_dep "pdfplumber" "pdfplumber"

if [ -n "$MISSING" ]; then
    echo ""
    echo "⚠ Dépendances manquantes :$MISSING"
    echo "  Tentative de réinstallation..."
    pip install $MISSING 2>&1 | tail -5
fi

# ---------- Téléchargement des assets statiques ----------
echo ""
echo "--- Téléchargement des assets statiques (mode offline) ---"
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

# ---------- Fichier .env et Tokens ----------
echo ""
echo "--- Configuration de l'environnement ---"

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
    echo "Fichier .env créé par défaut."
fi

if [ -t 0 ]; then
    read -p "Voulez-vous configurer les clés d'API (Tokens) maintenant ? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        for TOKEN in "OPENAI_API_KEY" "ANTHROPIC_API_KEY" "GOOGLE_API_KEY" "XAI_API_KEY" "GROQ_API_KEY" "GITHUB_TOKEN"; do
            read -p "Entrez $TOKEN (laissez vide pour ignorer) : " token_val
            if [ -n "$token_val" ]; then
                # Vérifier si la clé existe déjà dans .env
                if grep -q "^${TOKEN}=" .env; then
                    if [ "$OS" = "Darwin" ]; then
                        sed -i '' "s|^${TOKEN}=.*|${TOKEN}=${token_val}|" .env
                    else
                        sed -i "s|^${TOKEN}=.*|${TOKEN}=${token_val}|" .env
                    fi
                else
                    echo "${TOKEN}=${token_val}" >> .env
                fi
                echo "✓ $TOKEN configuré."
            fi
        done
    fi
fi

# ---------- Installation des modèles via Ollama ----------
echo ""
echo "--- Installation des modèles LLM locaux ---"

if [ -t 0 ] && [ -f "models_catalog.json" ]; then
    read -p "Voulez-vous choisir les modèles locaux à télécharger via Ollama ? (y/n) " -n 1 -r
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
    print(f"Erreur lors de la lecture de models_catalog.json : {e}")
    sys.exit(1)

print("\nModèles disponibles :")
for i, m in enumerate(models):
    rec = " [Recommandé]" if m.get("recommended") else ""
    print(f"{i+1}) {m['name']} ({m['params']}, {m['size_gb']}GB) - {m['description']}{rec}")

print("\nEntrez les numéros des modèles à télécharger, séparés par des virgules (ex: 1,3,4).")
print("Tapez 'all' pour télécharger tous les modèles recommandés.")
print("Laissez vide pour ignorer.")

choice = input("Votre choix : ").strip().lower()
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
                print(f"Numéro invalide ignoré : {p}")

for model_id in to_download:
    print(f"\n--- Téléchargement du modèle {model_id} ---")
    try:
        subprocess.run(["ollama", "pull", model_id], check=True)
    except subprocess.CalledProcessError:
        print(f"Erreur lors du téléchargement de {model_id}.")
EOF
        python3 .model_wizard.py
        rm -f .model_wizard.py
    else
        DEFAULT_MODEL=$( (grep -oP 'OLLAMA_MODEL=\K.*' .env 2>/dev/null || awk -F '=' '/^OLLAMA_MODEL=/ {print $2}' .env 2>/dev/null || echo "qwen3.5:9b") | tr -d "\"'" )
        if ollama list 2>/dev/null | grep -q "$(echo $DEFAULT_MODEL | cut -d: -f1)"; then
            echo "Modèle $DEFAULT_MODEL déjà installé."
        else
            echo "Téléchargement du modèle par défaut ($DEFAULT_MODEL) via Ollama..."
            ollama pull "$DEFAULT_MODEL"
        fi
    fi
else
    DEFAULT_MODEL=$( (grep -oP 'OLLAMA_MODEL=\K.*' .env 2>/dev/null || awk -F '=' '/^OLLAMA_MODEL=/ {print $2}' .env 2>/dev/null || echo "qwen3.5:9b") | tr -d "\"'" )
    if ollama list 2>/dev/null | grep -q "$(echo $DEFAULT_MODEL | cut -d: -f1)"; then
        echo "Modèle $DEFAULT_MODEL déjà installé."
    else
        echo "Téléchargement du modèle par défaut ($DEFAULT_MODEL) via Ollama..."
        ollama pull "$DEFAULT_MODEL"
    fi
fi

# ---------- Création des dossiers de travail ----------
mkdir -p data/sessions data/profiles data/skills data/images data/screenshots data/audit_reports data/snapshots data/playbooks data/playbook_state data/checkpoints workspace chroma_db

echo ""
# ---------- Service Système ----------
if [ -t 0 ]; then
    echo "=============================================="
    read -p "Voulez-vous installer Clawzd en tant que service système pour qu'il démarre automatiquement au démarrage ? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        CURRENT_DIR="$(pwd)"
        CURRENT_USER="$(whoami)"
        if [ "$OS" = "Linux" ]; then
            SERVICE_FILE="/etc/systemd/system/clawzd.service"
            echo "Création du service systemd..."
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
                echo "Service systemd activé. Vous pouvez le démarrer avec: sudo systemctl start clawzd"
            else
                echo "Erreur : sudo requis pour installer le service systemd."
            fi
        elif [ "$OS" = "Darwin" ]; then
            PLIST_FILE="$HOME/Library/LaunchAgents/com.clawzd.plist"
            echo "Création du service launchd (Mac)..."
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
            echo "Service launchd activé. Clawzd démarrera automatiquement à l'ouverture de session."
        fi
    fi
fi

echo ""
echo "=============================================="
echo "  Installation terminée avec succès !"
echo ""
echo "  Backend LLM : Ollama ($DEFAULT_MODEL)"
echo "  Lancez l'application : ./run.sh"
echo "=============================================="