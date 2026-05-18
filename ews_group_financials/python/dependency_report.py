"""Report optional external dependencies for internal EWS database integrations."""

from __future__ import annotations

import argparse
import importlib.metadata
import importlib.util
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "python") not in sys.path:
    sys.path.insert(0, str(ROOT / "python"))

from db_connectors import connector_statuses, sanitized_config  # noqa: E402


def load_dependency_manifest(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def package_status(name: str, minimum_version: str = "") -> dict[str, Any]:
    available = importlib.util.find_spec(name) is not None
    version = None
    if available:
        try:
            version = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            version = "unknown"
    return {
        "name": name,
        "minimum_version": minimum_version,
        "available": available,
        "installed_version": version,
    }


def build_dependency_report(manifest_path: Path, env_file: Path | None = None) -> dict[str, Any]:
    manifest = load_dependency_manifest(manifest_path)
    packages = [
        {
            **package_status(pkg["name"], pkg.get("minimum_version", "")),
            "used_for": pkg.get("used_for", ""),
            "required_when": pkg.get("required_when", ""),
        }
        for pkg in manifest.get("python_optional_packages", [])
    ]
    return {
        "manifest_version": manifest.get("version"),
        "purpose": manifest.get("purpose"),
        "python_optional_packages": packages,
        "native_drivers": manifest.get("native_drivers", []),
        "internal_databases": manifest.get("internal_databases", []),
        "network_dependencies": manifest.get("network_dependencies", []),
        "connector_statuses": [asdict(status) for status in connector_statuses(env_file)],
        "sanitized_config": sanitized_config(env_file),
    }


def assert_required_dependency_metadata(report: dict[str, Any]) -> None:
    if not report.get("internal_databases"):
        raise SystemExit("No internal database dependencies are declared")
    if not report.get("python_optional_packages"):
        raise SystemExit("No optional Python database packages are declared")
    for db in report["internal_databases"]:
        if db.get("access") != "read-only":
            raise SystemExit(f"Database dependency is not read-only: {db.get('logical_name')}")
        forbidden = set(db.get("forbidden_operations", []))
        if not {"CREATE_DOC", "UPDATE_DOC", "DELETE_DOC"}.issubset(forbidden):
            raise SystemExit(f"SR_BANK document operations are not blocked for {db.get('logical_name')}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Report dependencies for internal database integrations")
    parser.add_argument("--manifest", default="config/internal_db_dependencies.json")
    parser.add_argument("--env-file", default="python/config.example.env")
    parser.add_argument("--check", action="store_true", help="Validate dependency metadata in addition to printing it")
    args = parser.parse_args()

    env_file = Path(args.env_file) if args.env_file else None
    report = build_dependency_report(Path(args.manifest), env_file)
    if args.check:
        assert_required_dependency_metadata(report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
