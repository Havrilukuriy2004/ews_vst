"""Report optional runtime dependencies for DB and Excel integrations."""

from __future__ import annotations

import importlib.util
import json
import platform
import shutil
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class RuntimeDependency:
    name: str
    kind: str
    required_for: str
    available: bool
    install_hint: str


def module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def command_available(name: str) -> bool:
    return shutil.which(name) is not None


def dependency_report() -> dict[str, object]:
    dependencies = [
        RuntimeDependency("pyodbc", "python", "ClientProfile SQL Server live extraction", module_available("pyodbc"), "python -m pip install -r requirements-db.txt"),
        RuntimeDependency("oracledb", "python", "Oracle EWS live queries", module_available("oracledb"), "python -m pip install -r requirements-db.txt"),
        RuntimeDependency("python-dotenv", "python", "optional private .env loading", module_available("dotenv"), "python -m pip install -r requirements-db.txt"),
        RuntimeDependency("openpyxl", "python", "optional XLSX import/export", module_available("openpyxl"), "python -m pip install -r requirements-excel.txt"),
        RuntimeDependency("sqlcmd", "system", "manual SQL Server diagnostics", command_available("sqlcmd"), "install sqlcmd from the approved internal package mirror"),
        RuntimeDependency("tnsping", "system", "manual Oracle connectivity diagnostics", command_available("tnsping"), "install Oracle Instant Client tools if thick-mode diagnostics are required"),
    ]
    return {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "dependencies": [asdict(dep) for dep in dependencies],
        "db_ready": module_available("pyodbc") and module_available("oracledb"),
        "excel_ready": module_available("openpyxl"),
    }


if __name__ == "__main__":
    print(json.dumps(dependency_report(), ensure_ascii=False, indent=2))
