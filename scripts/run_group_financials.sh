#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

python python/build_group_financials.py \
  --matching templates/01_Group_Matching.csv \
  --raw-wide templates/02_Raw_Wide.csv \
  --out-long output/company_financials_long.csv \
  --out-group output/group_financials_long.csv \
  --output-dir output \
  --fail-on-check

python scripts/check_runtime_dependencies.py | tee output/runtime_dependencies.json
python python/db_connectors.py --env-file python/config.example.env --check | tee output/db_connection_status.json
python python/dashboard_app.py --output-dir output --env-file python/config.example.env --check
python python/dashboard_app.py --output-dir output --env-file python/config.example.env --export-html output/dashboard_snapshot.html
python -m unittest discover -s tests -v
python - <<'PY'
from pathlib import Path
import csv
import json

required = [
    Path('output/company_financials_long.csv'),
    Path('output/group_financials_long.csv'),
    Path('output/group_financials_wide.csv'),
    Path('output/financial_indicators.csv'),
    Path('output/validation_report.csv'),
    Path('output/run_manifest.json'),
]
for path in required:
    assert path.exists() and path.stat().st_size > 0, f'Missing or empty output: {path}'
with Path('output/run_manifest.json').open(encoding='utf-8') as f:
    manifest = json.load(f)
assert manifest['counts']['group_wide_rows'] >= 1
with Path('output/validation_report.csv').open(encoding='utf-8-sig', newline='') as f:
    statuses = {row['status'] for row in csv.DictReader(f)}
assert statuses == {'OK'}, statuses
print('text outputs ok')
PY
