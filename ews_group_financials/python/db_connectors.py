"""Read-only database connector layer for EWS Group Financials.

The project can run fully from CSV files, but production deployments normally need
read-only extraction from ClientProfile SQL Server and optional Oracle EWS sources.
This module centralizes connection configuration, driver checks, read-only SQL
safety guards, and dry-run command generation so credentials and network-specific
settings stay outside source control.
"""

from __future__ import annotations

import argparse
import csv
import importlib
import importlib.util
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence

MUTATING_SQL_KEYWORDS = {
    "ALTER", "CREATE", "DELETE", "DROP", "EXECUTE", "GRANT", "INSERT", "MERGE",
    "REVOKE", "TRUNCATE", "UPDATE", "UPSERT", "CREATE_DOC", "UPDATE_DOC", "DELETE_DOC",
}
READONLY_EXEC_PREFIXES = (
    "EXEC [finrep].[getReportFormInfo]",
    "EXEC finrep.getReportFormInfo",
    "EXEC [finrep].[getReportFormInfoSQL]",
    "EXEC finrep.getReportFormInfoSQL",
)


@dataclass(frozen=True)
class ConnectorStatus:
    name: str
    configured: bool
    driver_available: bool
    ready: bool
    message: str


@dataclass(frozen=True)
class SqlServerConfig:
    server: str = ""
    database: str = ""
    driver: str = "ODBC Driver 17 for SQL Server"
    trusted_connection: str = "yes"
    user: str = ""
    password: str = ""
    encrypt: str = "yes"
    trust_server_certificate: str = "yes"


@dataclass(frozen=True)
class OracleConfig:
    dsn: str = ""
    user: str = ""
    password: str = ""


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def merged_env(env_file: Optional[Path] = None) -> dict[str, str]:
    merged = dict(os.environ)
    if env_file:
        merged.update(load_env_file(env_file))
    return merged


def sqlserver_config_from_env(env: Mapping[str, str]) -> SqlServerConfig:
    return SqlServerConfig(
        server=env.get("CLIENTPROFILE_SQL_SERVER", ""),
        database=env.get("CLIENTPROFILE_SQL_DATABASE", ""),
        driver=env.get("CLIENTPROFILE_SQL_DRIVER", "ODBC Driver 17 for SQL Server"),
        trusted_connection=env.get("CLIENTPROFILE_SQL_TRUSTED_CONNECTION", "yes"),
        user=env.get("CLIENTPROFILE_SQL_USER", ""),
        password=env.get("CLIENTPROFILE_SQL_PASSWORD", ""),
        encrypt=env.get("CLIENTPROFILE_SQL_ENCRYPT", "yes"),
        trust_server_certificate=env.get("CLIENTPROFILE_SQL_TRUST_SERVER_CERTIFICATE", "yes"),
    )


def oracle_config_from_env(env: Mapping[str, str]) -> OracleConfig:
    return OracleConfig(
        dsn=env.get("ORACLE_DSN", ""),
        user=env.get("ORACLE_USER", ""),
        password=env.get("ORACLE_PASSWORD", ""),
    )


def mask_secret(value: str) -> str:
    if not value:
        return ""
    return "***"


def is_sql_readonly(sql: str, allow_finrep_exec: bool = True) -> bool:
    normalized = " ".join(sql.replace(";", " ").replace("\n", " ").split())
    upper = normalized.upper()
    if any(blocked in upper for blocked in ("CREATE_DOC", "UPDATE_DOC", "DELETE_DOC")):
        return False
    if allow_finrep_exec and any(upper.startswith(prefix.upper()) for prefix in READONLY_EXEC_PREFIXES):
        return True
    tokens = {token.strip("[]().,;").upper() for token in normalized.replace(".", " ").split()}
    return not bool(tokens & MUTATING_SQL_KEYWORDS)


def build_sqlserver_connection_string(config: SqlServerConfig) -> str:
    parts = [
        f"DRIVER={{{config.driver}}}",
        f"SERVER={config.server}",
        f"DATABASE={config.database}",
        f"Encrypt={config.encrypt}",
        f"TrustServerCertificate={config.trust_server_certificate}",
    ]
    if config.trusted_connection.lower() in {"yes", "true", "1"}:
        parts.append("Trusted_Connection=yes")
    else:
        parts.extend([f"UID={config.user}", f"PWD={config.password}"])
    return ";".join(parts)


def clientprofile_finrep_sql(report_form: int, year: int, quarter: int, edrpous: Sequence[str]) -> str:
    edrpou_csv = ",".join(str(edrpou).strip() for edrpou in edrpous if str(edrpou).strip())
    return (
        "EXEC [finrep].[getReportFormInfo] "
        f"@reportForm = {int(report_form)}, @year = {int(year)}, "
        f"@qr = {int(quarter)}, @edrpou = N'{edrpou_csv}'"
    )


class ClientProfileSqlServerConnector:
    def __init__(self, config: SqlServerConfig):
        self.config = config

    def status(self) -> ConnectorStatus:
        configured = bool(self.config.server and self.config.database)
        driver_available = importlib.util.find_spec("pyodbc") is not None
        if not configured:
            message = "CLIENTPROFILE_SQL_SERVER and CLIENTPROFILE_SQL_DATABASE are required"
        elif not driver_available:
            message = "pyodbc is not installed in this environment"
        else:
            message = "ready"
        return ConnectorStatus("clientprofile_sql_server", configured, driver_available, configured and driver_available, message)

    def connect(self) -> Any:
        status = self.status()
        if not status.ready:
            raise RuntimeError(status.message)
        pyodbc = importlib.import_module("pyodbc")
        return pyodbc.connect(build_sqlserver_connection_string(self.config), autocommit=True)

    def query_readonly(self, sql: str, parameters: Sequence[Any] = ()) -> list[dict[str, Any]]:
        if not is_sql_readonly(sql):
            raise ValueError("Refusing to execute non-read-only SQL")
        with self.connect() as connection:
            cursor = connection.cursor()
            cursor.execute(sql, parameters)
            columns = [column[0] for column in cursor.description] if cursor.description else []
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def fetch_finrep(self, report_form: int, year: int, quarter: int, edrpous: Sequence[str]) -> list[dict[str, Any]]:
        sql = clientprofile_finrep_sql(report_form, year, quarter, edrpous)
        return self.query_readonly(sql)


class OracleReadOnlyConnector:
    def __init__(self, config: OracleConfig):
        self.config = config

    def status(self) -> ConnectorStatus:
        configured = bool(self.config.dsn and self.config.user)
        driver_available = importlib.util.find_spec("oracledb") is not None or importlib.util.find_spec("cx_Oracle") is not None
        if not configured:
            message = "ORACLE_DSN and ORACLE_USER are required"
        elif not driver_available:
            message = "oracledb/cx_Oracle is not installed in this environment"
        else:
            message = "ready"
        return ConnectorStatus("oracle_ews", configured, driver_available, configured and driver_available, message)

    def connect(self) -> Any:
        status = self.status()
        if not status.ready:
            raise RuntimeError(status.message)
        module_name = "oracledb" if importlib.util.find_spec("oracledb") is not None else "cx_Oracle"
        oracle_driver = importlib.import_module(module_name)
        return oracle_driver.connect(user=self.config.user, password=self.config.password, dsn=self.config.dsn)

    def query_readonly(self, sql: str, parameters: Optional[Mapping[str, Any]] = None) -> list[dict[str, Any]]:
        if not is_sql_readonly(sql, allow_finrep_exec=False):
            raise ValueError("Refusing to execute non-read-only SQL")
        with self.connect() as connection:
            cursor = connection.cursor()
            cursor.execute(sql, parameters or {})
            columns = [column[0].lower() for column in cursor.description] if cursor.description else []
            return [dict(zip(columns, row)) for row in cursor.fetchall()]


def write_rows_csv(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    rows = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row.keys()}) if rows else []
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def connector_statuses(env_file: Optional[Path] = None) -> list[ConnectorStatus]:
    env = merged_env(env_file)
    return [
        ClientProfileSqlServerConnector(sqlserver_config_from_env(env)).status(),
        OracleReadOnlyConnector(oracle_config_from_env(env)).status(),
    ]


def sanitized_config(env_file: Optional[Path] = None) -> dict[str, Any]:
    env = merged_env(env_file)
    sql_config = sqlserver_config_from_env(env)
    oracle_config = oracle_config_from_env(env)
    return {
        "clientprofile_sql_server": {**asdict(sql_config), "password": mask_secret(sql_config.password)},
        "oracle_ews": {**asdict(oracle_config), "password": mask_secret(oracle_config.password)},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Check and use read-only EWS database connectors")
    parser.add_argument("--env-file", default="python/config.example.env")
    parser.add_argument("--check", action="store_true", help="Print connector readiness as JSON")
    parser.add_argument("--dry-run-finrep", action="store_true", help="Print read-only ClientProfile finrep SQL without connecting")
    parser.add_argument("--report-form", type=int, default=1)
    parser.add_argument("--year", type=int, default=2025)
    parser.add_argument("--quarter", type=int, default=4)
    parser.add_argument("--edrpou", action="append", default=[])
    parser.add_argument("--extract-finrep-csv", help="Run ClientProfile extraction and write raw rows to CSV")
    args = parser.parse_args()

    env_file = Path(args.env_file) if args.env_file else None
    if args.check:
        payload = {
            "statuses": [asdict(status) for status in connector_statuses(env_file)],
            "config": sanitized_config(env_file),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    if args.dry_run_finrep:
        print(clientprofile_finrep_sql(args.report_form, args.year, args.quarter, args.edrpou))
    if args.extract_finrep_csv:
        env = merged_env(env_file)
        connector = ClientProfileSqlServerConnector(sqlserver_config_from_env(env))
        rows = connector.fetch_finrep(args.report_form, args.year, args.quarter, args.edrpou)
        write_rows_csv(Path(args.extract_finrep_csv), rows)


if __name__ == "__main__":
    main()
