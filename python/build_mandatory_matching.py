"""Build year-specific group matching from mandatory clients and group directory.

Input data is intentionally stored as text CSV because binary workbook artifacts
are not supported in this repository.
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path
from typing import Iterable, Mapping

MATCHING_HEADERS = [
    "group_id", "matching_year", "group_name", "edrpou", "client_code", "client_name",
    "mandatory_no", "segment", "inclusion_flag", "consolidation_method", "ownership_share_pct",
    "match_key", "is_main_company", "note",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def slug(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-zА-Яа-яІіЇїЄєҐґ]+", "_", value.strip()).strip("_")
    return cleaned.upper() or "UNMAPPED"


def normalize_edrpou(value: str) -> str:
    return str(value or "").strip().zfill(8)


def group_lookup(directory_rows: Iterable[Mapping[str, str]]) -> dict[str, dict[str, str]]:
    lookup: dict[str, dict[str, str]] = {}
    for row in directory_rows:
        edrpou = normalize_edrpou(row.get("edrpou", ""))
        if edrpou and edrpou != "00000000":
            lookup[edrpou] = dict(row)
    return lookup


def build_matching_rows(mandatory_rows: Iterable[Mapping[str, str]], directory_rows: Iterable[Mapping[str, str]], year: int) -> list[dict[str, str]]:
    directory_by_edrpou = group_lookup(directory_rows)
    rows: list[dict[str, str]] = []
    for src in mandatory_rows:
        edrpou = normalize_edrpou(src.get("edrpou", ""))
        directory_match = directory_by_edrpou.get(edrpou)
        group_name = directory_match.get("group_name", "") if directory_match else ""
        if group_name:
            group_id = f"GROUP_{slug(group_name)}"
            note = "mandatory_2025; group_directory_match=1"
        else:
            group_name = f"UNMAPPED_{edrpou}"
            group_id = f"GROUP_UNMAPPED_{edrpou}"
            note = "mandatory_2025; group_directory_match=0; уточнити групу в довіднику"
        rows.append({
            "group_id": group_id,
            "matching_year": str(year),
            "group_name": group_name,
            "edrpou": edrpou,
            "client_code": str(src.get("client_code", "")).strip(),
            "client_name": str(src.get("client_name", "")).strip(),
            "mandatory_no": str(src.get("mandatory_no", "")).strip(),
            "segment": str(src.get("segment", "")).strip(),
            "inclusion_flag": "1",
            "consolidation_method": "SUM",
            "ownership_share_pct": "100",
            "match_key": f"{year}|{edrpou}",
            "is_main_company": "1",
            "note": note,
        })
    return rows


def write_csv(path: Path, rows: Iterable[Mapping[str, str]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def validate_mandatory_rows(rows: list[Mapping[str, str]], expected_count: int | None = None) -> list[str]:
    issues: list[str] = []
    edrpous = [normalize_edrpou(row.get("edrpou", "")) for row in rows]
    if expected_count is not None and len(rows) != expected_count:
        issues.append(f"Expected {expected_count} mandatory clients, got {len(rows)}")
    duplicates = sorted({edrpou for edrpou in edrpous if edrpous.count(edrpou) > 1})
    if duplicates:
        issues.append(f"Duplicate mandatory EDRPOU: {duplicates}")
    invalid = [edrpou for edrpou in edrpous if not re.fullmatch(r"\d{8}", edrpou)]
    if invalid:
        issues.append(f"Invalid EDRPOU values: {invalid}")
    return issues


def main() -> None:
    parser = argparse.ArgumentParser(description="Build matching CSV from mandatory clients and group directory")
    parser.add_argument("--mandatory", default="data/mandatory_clients_2025.csv")
    parser.add_argument("--group-directory", default="data/group_directory.csv")
    parser.add_argument("--out", default="templates/01_Group_Matching.csv")
    parser.add_argument("--year", type=int, default=2025)
    parser.add_argument("--expected-count", type=int, default=96)
    parser.add_argument("--fail-on-unmapped", action="store_true")
    args = parser.parse_args()

    mandatory_rows = read_csv(Path(args.mandatory))
    directory_rows = read_csv(Path(args.group_directory))
    issues = validate_mandatory_rows(mandatory_rows, args.expected_count)
    matching_rows = build_matching_rows(mandatory_rows, directory_rows, args.year)
    unmapped_count = sum("group_directory_match=0" in row["note"] for row in matching_rows)
    if args.fail_on_unmapped and unmapped_count:
        issues.append(f"Unmapped mandatory clients: {unmapped_count}")
    if issues:
        raise SystemExit("; ".join(issues))
    write_csv(Path(args.out), matching_rows, MATCHING_HEADERS)
    print(f"Wrote {len(matching_rows)} matching rows to {args.out}; unmapped={unmapped_count}")


if __name__ == "__main__":
    main()
