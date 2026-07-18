#!/bin/bash
# ==============================================
#   Clawzd — Shared install/update helpers
# ==============================================

CLAWZD_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

clawzd_detect_os() {
    uname -s
}

clawzd_detect_docker_compose() {
    if docker compose version &> /dev/null; then
        echo "docker compose"
    elif command -v docker-compose &> /dev/null; then
        echo "docker-compose"
    else
        return 1
    fi
}

clawzd_has_nvidia_gpu() {
    command -v nvidia-smi &> /dev/null && nvidia-smi &> /dev/null
}

clawzd_docker_supports_nvidia() {
    command -v docker &> /dev/null || return 1

    # Docker can list an NVIDIA runtime even when GPU device requests still fail.
    # Trust the runtime only after a real local --gpus smoke test succeeds.
    local image
    for image in clawzd-clawzd:latest ollama/ollama:latest python:3.11-slim-bookworm busybox:latest alpine:latest; do
        if docker image inspect "$image" &>/dev/null; then
            docker run --rm --pull=never --gpus all --entrypoint sh "$image" -c 'true' &>/dev/null
            return $?
        fi
    done

    return 1
}

clawzd_should_use_gpu_compose() {
    local mode
    mode=$(printf '%s' "${CLAWZD_DOCKER_GPU:-auto}" | tr '[:upper:]' '[:lower:]')

    case "$mode" in
        1|true|yes|on|gpu|nvidia|force)
            return 0
            ;;
        0|false|no|off|cpu|none)
            return 1
            ;;
        auto|"")
            ;;
        *)
            echo "WARNING: Unknown CLAWZD_DOCKER_GPU='$CLAWZD_DOCKER_GPU' — using auto detection." >&2
            ;;
    esac

    clawzd_has_nvidia_gpu && clawzd_docker_supports_nvidia
}

clawzd_print_docker_gpu_status() {
    local mode
    mode=$(printf '%s' "${CLAWZD_DOCKER_GPU:-auto}" | tr '[:upper:]' '[:lower:]')

    case "$mode" in
        1|true|yes|on|gpu|nvidia|force)
            echo "CLAWZD_DOCKER_GPU=$CLAWZD_DOCKER_GPU — forcing GPU compose overlay."
            return 0
            ;;
        0|false|no|off|cpu|none)
            echo "CLAWZD_DOCKER_GPU=$CLAWZD_DOCKER_GPU — running CPU-only Docker mode."
            return 0
            ;;
    esac

    if clawzd_should_use_gpu_compose; then
        echo "NVIDIA Docker GPU smoke test passed — enabling GPU compose overlay."
    elif clawzd_has_nvidia_gpu; then
        echo "NVIDIA GPU detected, but Docker GPU smoke test failed — running CPU-only Docker mode."
        echo "To force the GPU overlay after installing NVIDIA Container Toolkit, run with CLAWZD_DOCKER_GPU=1."
    else
        echo "No NVIDIA GPU detected — running CPU-only Docker mode."
    fi
}

clawzd_compose_files() {
    local files="-f docker-compose.yml"
    if clawzd_should_use_gpu_compose; then
        files="$files -f docker-compose.gpu.yml"
    fi
    echo "$files"
}

clawzd_ensure_data_dirs() {
    mkdir -p \
        data/sessions data/profiles data/skills data/images data/screenshots \
        data/audit_reports data/snapshots data/playbooks data/playbook_state \
        data/checkpoints data/audio data/rag data/research data/memories \
        workspace chroma_db models static/css static/js static/fonts
}

clawzd_ensure_env_file() {
    if [ -f "$CLAWZD_ROOT/.env" ]; then
        return 0
    fi
    if [ -f "$CLAWZD_ROOT/.env.example" ]; then
        cp "$CLAWZD_ROOT/.env.example" "$CLAWZD_ROOT/.env"
    else
        cat > "$CLAWZD_ROOT/.env" << 'EOF'
# === Clawzd Configuration ===
LLM_PROVIDER=ollama
OLLAMA_HOST=http://localhost:11434
OLLAMA_HOST_PORT=11435
OLLAMA_MODEL=qwen3.5:9b
ENHANCE_MODEL=gemma3:4b
APP_HOST=0.0.0.0
APP_PORT=8888
HF_HUB_DISABLE_PROGRESS_BARS=1
EOF
    fi
    echo "Default .env file created."
}

clawzd_download_static_assets() {
    cd "$CLAWZD_ROOT" || exit 1
    clawzd_ensure_data_dirs

    download_file() {
        local url="$1"
        local dest="$2"
        if [ ! -f "$dest" ]; then
            echo "Downloading $(basename "$dest")..."
            if ! curl -L --fail --progress-bar -o "$dest" "$url"; then
                echo "ERROR: Failed to download $url"
                return 1
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
    download_file "https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js" "static/js/highlight.min.js"
    download_file "https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github-dark.min.css" "static/css/github-dark.min.css"
    download_file "https://cdnjs.cloudflare.com/ajax/libs/mermaid/10.9.1/mermaid.min.js" "static/js/mermaid.min.js"
    download_file "https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js" "static/js/chart.min.js"
}

clawzd_build_frontend() {
    cd "$CLAWZD_ROOT" || exit 1
    if ! command -v npm &> /dev/null; then
        echo "WARNING: npm not found — skipping frontend build (raw static assets will be used)."
        return 0
    fi
    echo "--- Building frontend assets (Vite) ---"
    if [ -f package-lock.json ]; then
        npm ci
    else
        npm install
    fi
    npm run build
}

clawzd_run_migrations() {
    cd "$CLAWZD_ROOT" || exit 1
    local python_cmd="${1:-python3}"
    echo "--- Running database migrations ---"
    "$python_cmd" migrate.py 2>&1 || {
        echo "WARNING: Database migration failed. The app will attempt to initialize on startup."
    }
}

clawzd_install_system_deps() {
    if command -v apt-get &> /dev/null && command -v sudo &> /dev/null; then
        echo "Installing system dependencies (TTS, media, OCR)..."
        sudo apt-get update && sudo apt-get install -y \
            espeak espeak-ng espeak-data libespeak-dev \
            ffmpeg tesseract-ocr tesseract-ocr-eng tesseract-ocr-fra \
            fonts-dejavu-core fonts-dejavu-extra \
            || echo "WARNING: Some system packages could not be installed."
    fi
}

clawzd_install_playwright() {
    local python_cmd="${1:-python3}"
    echo "--- Installing Playwright browsers ---"
    if "$python_cmd" -c "import playwright" &>/dev/null; then
        "$python_cmd" -m playwright install chromium 2>&1 | tail -3
        if command -v sudo &> /dev/null; then
            "$python_cmd" -m playwright install-deps chromium 2>&1 | tail -3 \
                || echo "WARNING: playwright install-deps failed."
        fi
    else
        echo "WARNING: playwright not importable — skipping browser install."
    fi
}

clawzd_read_env_value() {
    local key="$1"
    local default="${2:-}"
    if [ -f "$CLAWZD_ROOT/.env" ]; then
        local value
        value=$(grep -E "^${key}=" "$CLAWZD_ROOT/.env" | tail -1 | cut -d'=' -f2- | tr -d "\"' " )
        if [ -n "$value" ]; then
            echo "$value"
            return 0
        fi
    fi
    echo "$default"
}

clawzd_pull_ollama_model() {
    local model_id="$1"
    if [ -z "$model_id" ]; then
        return 0
    fi
    if ! command -v ollama &> /dev/null; then
        echo "WARNING: Ollama not installed — cannot pull $model_id"
        return 0
    fi
    local base
    base=$(echo "$model_id" | cut -d: -f1)
    if ollama list 2>/dev/null | grep -q "$base"; then
        echo "Model $model_id is already installed."
        return 0
    fi
    echo "Downloading model ($model_id) via Ollama..."
    ollama pull "$model_id" || echo "WARNING: Could not download $model_id"
}

clawzd_pull_default_models() {
    local default_model enhance_model
    default_model=$(clawzd_read_env_value "OLLAMA_MODEL" "qwen3.5:9b")
    enhance_model=$(clawzd_read_env_value "ENHANCE_MODEL" "gemma3:4b")
    clawzd_pull_ollama_model "$default_model"
    if [ -n "$enhance_model" ] && [ "$enhance_model" != "$default_model" ]; then
        clawzd_pull_ollama_model "$enhance_model"
    fi
}

clawzd_docker_up() {
    cd "$CLAWZD_ROOT" || exit 1
    local compose_cmd
    compose_cmd=$(clawzd_detect_docker_compose) || {
        echo "ERROR: Docker Compose not found."
        exit 1
    }

    # Check if the configured APP_PORT is already in use on the host
    local port
    port=$(clawzd_read_env_value "APP_PORT" "8888")
    local port_pid=""
    if command -v lsof >/dev/null 2>&1; then
        port_pid=$(lsof -t -i :"$port" 2>/dev/null || true)
    elif command -v fuser >/dev/null 2>&1; then
        port_pid=$(fuser "$port"/tcp 2>/dev/null | awk '{print $NF}' || true)
    fi

    if [ -n "$port_pid" ]; then
        echo "WARNING: Port $port is already in use on the host by process(es): $port_pid."
        echo "If this is an existing Clawzd Docker container, docker compose will recreate it."
        echo "Otherwise, the container startup might fail because the port is already bound."
    fi

    local compose_files
    compose_files=$(clawzd_compose_files)
    clawzd_ensure_env_file
    clawzd_ensure_data_dirs
    # shellcheck disable=SC2086
    $compose_cmd $compose_files up -d --build --force-recreate "$@"
}

clawzd_docker_down() {
    cd "$CLAWZD_ROOT" || exit 1
    local compose_cmd
    compose_cmd=$(clawzd_detect_docker_compose) || return 1
    local compose_files
    compose_files=$(clawzd_compose_files)
    # shellcheck disable=SC2086
    $compose_cmd $compose_files down "$@"
}
