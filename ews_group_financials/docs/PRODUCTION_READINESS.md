# Production readiness: GUI and database connections

This package now contains three execution layers:

1. **CSV ETL layer** — deterministic, dependency-free transformation and validation.
2. **Read-only database connector layer** — configurable SQL Server / Oracle access wrappers with mutation guards.
3. **Graphical web dashboard** — dependency-free browser UI for KPIs, drill-down tables, validation and DB readiness.

## Graphical dashboard

Run locally:

```bash
./scripts/run_dashboard.sh
```

Default URL:

```text
http://127.0.0.1:8765/dashboard
```

Available JSON APIs:

- `/api/summary`
- `/api/indicators`
- `/api/validation`
- `/api/group-wide`
- `/api/db-status`
- `/health`

The UI is intentionally implemented with Python standard library HTML/CSS/HTTP primitives so it can run in restricted bank environments without a frontend build chain or binary assets.



## External dependencies for internal databases

The machine-readable dependency inventory is stored in `config/internal_db_dependencies.json` and is intentionally separate from the dependency-free CSV ETL path. It declares:

- optional Python packages (`pyodbc`, `oracledb`, `openpyxl`);
- native drivers (Microsoft ODBC Driver for SQL Server, Oracle Instant Client);
- internal DB endpoints and environment variables;
- required ClientProfile `finrep` procedures/views;
- read-only allowed operations and forbidden mutating operations.

Install optional DB dependencies only on the approved deployment host:

```bash
python -m pip install -r requirements-db.txt
```

Validate the dependency inventory and local driver readiness:

```bash
./scripts/check_internal_db_dependencies.sh
```

## Database connector layer

Check configured connectors:

```bash
./scripts/check_db_connections.sh
```

Dry-run ClientProfile extraction SQL:

```bash
python python/db_connectors.py \
  --env-file path/to/private.env \
  --dry-run-finrep \
  --report-form 1 \
  --year 2025 \
  --quarter 4 \
  --edrpou 12345678 \
  --edrpou 87654321
```

Live ClientProfile extraction to CSV, when `pyodbc` and real read-only credentials are available:

```bash
python python/db_connectors.py \
  --env-file path/to/private.env \
  --extract-finrep-csv output/clientprofile_raw_extract.csv \
  --report-form 1 \
  --year 2025 \
  --quarter 4 \
  --edrpou 12345678 \
  --edrpou 87654321
```

## Safety rules

- Source database credentials must be read-only.
- Real credentials are never committed to git.
- SQL mutation keywords are blocked by `python/db_connectors.py`.
- ClientProfile extraction is limited to the documented `finrep.getReportFormInfo` / `finrep.getReportFormInfoSQL` read-only procedures.
- No `SR_BANK CREATE_DOC`, `UPDATE_DOC` or `DELETE_DOC` calls are implemented.

## Deployment checklist

- Create a private `.env` from `python/config.example.env`.
- Install only the drivers required by the deployment target (`pyodbc`, `oracledb`, ODBC driver packages).
- Confirm `/api/db-status` reports the connector as `ready=true`.
- Run `./scripts/run_group_financials.sh` and confirm validation is clean.
- Start `./scripts/run_dashboard.sh` behind the approved internal reverse proxy if a shared UI is required.
