# External dependencies for internal database connections

The core ETL and dashboard run without third-party packages. Direct read-only extraction from internal databases requires the optional dependencies below.

## Python packages

Install from `requirements-db.txt` on deployment hosts that need live DB extraction:

```bash
python -m pip install -r requirements-db.txt
```

Equivalent optional-extra form:

```bash
python -m pip install '.[db]'
```

Packages:

| Internal source | Python dependency | Purpose |
| --- | --- | --- |
| ClientProfile SQL Server | `pyodbc>=5.1.0` | ODBC connection to SQL Server and `finrep.getReportFormInfo` extraction. |
| Oracle EWS / credit contracts | `oracledb>=2.4.0` | Oracle read-only queries in thin mode, or thick mode when Instant Client is configured. |
| Private env files | `python-dotenv>=1.0.1` | Optional `.env` loading helper for production wrappers. The repository also has a stdlib parser. |

## System / driver dependencies

These are not vendored in git and must be installed by the target environment owner:

### SQL Server / ClientProfile

- Microsoft ODBC Driver 17 or 18 for SQL Server.
- `unixODBC` on Linux hosts.
- Network route/firewall access to `CLIENTPROFILE_SQL_SERVER`.
- Read-only database principal or trusted Kerberos/AD identity.

Typical Linux packages, depending on base image and internal mirror naming:

```bash
msodbcsql18
unixodbc
unixodbc-dev
```

### Oracle EWS

- `oracledb` thin mode: no Oracle Instant Client required for many deployments.
- `oracledb` thick mode / legacy `cx_Oracle`: Oracle Instant Client and library path configured by platform team.
- Network route/firewall access to `ORACLE_DSN`.
- Read-only Oracle user.

## Configuration variables

Use a private env file based on `python/config.example.env`:

```text
CLIENTPROFILE_SQL_SERVER=
CLIENTPROFILE_SQL_DATABASE=ClientProfile
CLIENTPROFILE_SQL_DRIVER=ODBC Driver 18 for SQL Server
CLIENTPROFILE_SQL_TRUSTED_CONNECTION=yes
CLIENTPROFILE_SQL_USER=
CLIENTPROFILE_SQL_PASSWORD=
CLIENTPROFILE_SQL_ENCRYPT=yes
CLIENTPROFILE_SQL_TRUST_SERVER_CERTIFICATE=yes

ORACLE_DSN=
ORACLE_USER=
ORACLE_PASSWORD=
```

## Verification commands

Check dependency and connector readiness without opening a DB session:

```bash
python scripts/check_runtime_dependencies.py
./scripts/check_db_connections.sh
```

Generate a safe ClientProfile dry-run SQL command:

```bash
python python/db_connectors.py \
  --dry-run-finrep \
  --report-form 1 \
  --year 2025 \
  --quarter 4 \
  --edrpou 12345678
```

## Security constraints

- All source DB accounts must be read-only.
- The connector layer blocks obvious mutating SQL keywords.
- `CREATE_DOC`, `UPDATE_DOC`, and `DELETE_DOC` calls are explicitly blocked.
- Real credentials must be stored in an approved secret manager or private env file; never commit them.
