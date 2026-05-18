#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

python python/dependency_report.py \
  --manifest config/internal_db_dependencies.json \
  --env-file "${EWS_ENV_FILE:-python/config.example.env}" \
  --check
