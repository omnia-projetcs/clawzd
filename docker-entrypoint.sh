#!/bin/bash
set -e

cd /app

# Ensure runtime directories exist (mounted volumes may be empty on first run)
mkdir -p \
    data/sessions data/profiles data/skills data/images data/screenshots \
    data/audit_reports data/snapshots data/playbooks data/playbook_state \
    data/checkpoints data/audio data/rag data/research data/memories \
    workspace chroma_db models

echo "--- Running database migrations ---"
python migrate.py 2>&1 || echo "WARNING: migration failed — app will init on startup."

exec "$@"