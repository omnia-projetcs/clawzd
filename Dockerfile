FROM python:3.11-slim-bookworm

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    ffmpeg \
    libsm6 \
    libxext6 \
    build-essential \
    espeak \
    espeak-ng \
    espeak-data \
    tesseract-ocr \
    tesseract-ocr-eng \
    tesseract-ocr-fra \
    fonts-dejavu-core \
    fonts-dejavu-extra \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

# Install Trivy
RUN curl -sfL https://raw.githubusercontent.com/aquasecurity/trivy/main/contrib/install.sh | sh -s -- -b /usr/local/bin

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers and dependencies
RUN playwright install chromium \
    && playwright install-deps chromium

# Copy package files and install/build frontend when present
COPY package.json vite.config.js ./
COPY static ./static
RUN if [ -f package.json ]; then npm install && npm run build || echo "Frontend build skipped"; fi

# Download offline static assets (idempotent)
COPY scripts/common.sh ./scripts/common.sh
RUN bash -c 'source scripts/common.sh && clawzd_download_static_assets'

# Copy application source code
COPY . .

# Entrypoint handles migrations and directory bootstrap
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Expose the default FastAPI port
EXPOSE 8888

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["python", "main.py"]