#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

python python/dashboard_app.py \
  --output-dir output \
  --env-file "${EWS_ENV_FILE:-python/config.example.env}" \
  --host "${EWS_DASHBOARD_HOST:-127.0.0.1}" \
  --port "${EWS_DASHBOARD_PORT:-8765}"
