"""
Build EWS group financials from ClientProfile-style wide financial statements.

The module implements the rules from docs/TZ_Group_Financials_EWS.md:
- EDRPOU is always treated as text.
- group matching is year-specific: matching_year + edrpou.
- only rows with inclusion_flag=1 are consolidated.
- financial line codes 1000...2650 and staff count are aggregated with SUM.
- KVED metadata is selected from the main company, or from the highest-revenue
  company when the main-company flag is not available.
- source databases are read-only: this script reads CSV/XLSX exports and writes
  generated files only.

CSV mode is dependency-free. Excel mode uses openpyxl when available and falls back to a stdlib XLSX reader/writer.
"""

from __future__ import annotations

import argparse
import csv
import importlib
import importlib.util
import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

FINANCIAL_CODES = [
    "1000", "1001", "1002", "1005", "1010", "1011", "1012", "1015", "1020", "1030", "1035", "1040", "1045", "1050", "1060", "1065",
    "1090", "1095", "1100", "1101", "1102", "1103", "1104", "1110", "1115", "1120", "1125", "1130", "1135", "1136", "1140", "1145",
    "1155", "1160", "1165", "1166", "1167", "1170", "1180", "1190", "1195", "1200", "1300", "1400", "1405", "1410", "1415", "1420",
    "1425", "1430", "1435", "1495", "1500", "1505", "1510", "1515", "1520", "1525", "1530", "1535", "1540", "1545", "1595м", "1595",
    "1600", "1605", "1610", "1615", "1620", "1621", "1625", "1630", "1635", "1640", "1645", "1650", "1660", "1665", "1670", "1690",
    "1695", "1700", "1800", "1900", "2000", "2010", "2011", "2012", "2013", "2014", "2050", "2070", "2090", "2095", "2105", "2110",
    "2111", "2112", "2120", "2121", "2122", "2130", "2150", "2160", "2165", "2180", "2190", "2195", "2200", "2220", "2240", "2250",
    "2255", "2270", "2275", "2280", "2285", "2290", "2295", "2300", "2305", "2310", "2350", "2355", "2400", "2405", "2410", "2415",
    "2445", "2450", "2455", "2460", "2465", "2500", "2505", "2510", "2515", "2520", "2550", "2600", "2605", "2610", "2615", "2650",
]

RAW_META_HEADERS = [
    "Ідентифікатор",
    "Звітна дата",
    "Код ЄДРПОУ",
    "Форма звітності",
]
TAIL_META_HEADERS = [
    "Середня чисельність працівників",
    "Клас КВЕД2010",
    "Секція КВЕД2010",
    "Користувач",
    "Версія 0.10.005",
    "Дата та час збереження інформації",
]
CANONICAL_WIDE_HEADERS = RAW_META_HEADERS + FINANCIAL_CODES + TAIL_META_HEADERS
TRUE_VALUES = {"1", "true", "так", "yes", "y", "included", "include"}


@dataclass(frozen=True)
class MatchRow:
    group_id: str
    matching_year: int
    group_name: str
    edrpou: str
    client_name: str = ""
    inclusion_flag: bool = True
    consolidation_method: str = "SUM"
    ownership_share_pct: Optional[float] = None
    is_main_company: bool = False
    note: str = ""


@dataclass
class WideFinancialRow:
    identifier: str
    report_date: str
    report_year: int
    edrpou: str
    report_form: str
    client_name: str = ""
    group_id: str = "UNMATCHED"
    group_name: str = ""
    values: Dict[str, float] = field(default_factory=dict)
    staff_count: float = 0.0
    kved_class: str = ""
    kved_section: str = ""
    source_user: str = ""
    source_version: str = ""
    source_saved_at: str = ""
    is_main_company: bool = False


@dataclass
class ValidationIssue:
    check_name: str
    status: str
    details: str


def parse_number(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if s in {"", "-", "#DIV/0!", "#VALUE!", "#ДІЛЕННЯ/0!", "#ЗНАЧЕННЯ!"}:
        return None
    s = s.replace(" ", "").replace("\u00a0", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def truthy(value: Any) -> bool:
    return stringify(value).lower() in TRUE_VALUES


def report_year_from_date(report_date: Any) -> int:
    if isinstance(report_date, datetime):
        dt = report_date.date()
    elif isinstance(report_date, date):
        dt = report_date
    else:
        raw = stringify(report_date)
        if not raw:
            raise ValueError("report_date is required")
        if raw.replace(".", "", 1).isdigit():
            base = date(1899, 12, 30)
            from datetime import timedelta
            dt = base + timedelta(days=int(float(raw)))
        elif "." in raw:
            dt = datetime.strptime(raw[:10], "%d.%m.%Y").date()
        else:
            dt = datetime.strptime(raw[:10], "%Y-%m-%d").date()
    return dt.year - 1 if dt.month == 1 and dt.day == 1 else dt.year


def normalize_report_date(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    raw = stringify(value)
    if raw.replace(".", "", 1).isdigit():
        base = date(1899, 12, 30)
        from datetime import timedelta
        return (base + timedelta(days=int(float(raw)))).isoformat()
    if "." in raw:
        return datetime.strptime(raw[:10], "%d.%m.%Y").date().isoformat()
    return raw[:10]


def safe_number(value: Any) -> float:
    parsed = parse_number(value)
    return 0.0 if parsed is None else parsed


def safe_div(numerator: float, denominator: float) -> Optional[float]:
    if abs(denominator) < 1e-9:
        return None
    return numerator / denominator


def load_matching(path: Path) -> Dict[Tuple[int, str], MatchRow]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return matching_from_dicts(csv.DictReader(f))


def matching_from_dicts(rows: Iterable[Mapping[str, Any]]) -> Dict[Tuple[int, str], MatchRow]:
    out: Dict[Tuple[int, str], MatchRow] = {}
    for row in rows:
        edrpou = stringify(row.get("edrpou") or row.get("Код ЄДРПОУ"))
        if not edrpou:
            continue
        year = int(safe_number(row.get("matching_year") or row.get("year")))
        include_value = row.get("inclusion_flag", 1)
        include = truthy(include_value) if stringify(include_value) else True
        match = MatchRow(
            group_id=stringify(row.get("group_id")),
            matching_year=year,
            group_name=stringify(row.get("group_name")),
            edrpou=edrpou,
            client_name=stringify(row.get("client_name")),
            inclusion_flag=include,
            consolidation_method=stringify(row.get("consolidation_method") or "SUM"),
            ownership_share_pct=parse_number(row.get("ownership_share_pct")),
            is_main_company=truthy(row.get("is_main_company")),
            note=stringify(row.get("note") or row.get("comment")),
        )
        out[(year, edrpou)] = match
    return out


def wide_rows_from_dicts(rows: Iterable[Mapping[str, Any]], matching: Mapping[Tuple[int, str], MatchRow]) -> List[WideFinancialRow]:
    out: List[WideFinancialRow] = []
    for src in rows:
        edrpou = stringify(src.get("Код ЄДРПОУ") or src.get("edrpou"))
        report_date_raw = src.get("Звітна дата") or src.get("report_date")
        if not edrpou or not stringify(report_date_raw):
            continue
        report_date = normalize_report_date(report_date_raw)
        report_year = report_year_from_date(report_date)
        match = matching.get((report_year, edrpou))
        group_id = match.group_id if match and match.inclusion_flag else "UNMATCHED"
        row = WideFinancialRow(
            identifier=stringify(src.get("Ідентифікатор") or src.get("identifier") or group_id),
            report_date=report_date,
            report_year=report_year,
            edrpou=edrpou,
            report_form=stringify(src.get("Форма звітності") or src.get("report_form") or "Ф1/Ф2"),
            client_name=stringify(src.get("Назва клієнта") or src.get("client_name") or (match.client_name if match else "")),
            group_id=group_id,
            group_name=match.group_name if match else "",
            values={code: safe_number(src.get(code)) for code in FINANCIAL_CODES},
            staff_count=safe_number(src.get("Середня чисельність працівників") or src.get("staff_count")),
            kved_class=stringify(src.get("Клас КВЕД2010") or src.get("kved_class")),
            kved_section=stringify(src.get("Секція КВЕД2010") or src.get("kved_section")),
            source_user=stringify(src.get("Користувач") or src.get("source_user")),
            source_version=stringify(src.get("Версія 0.10.005") or src.get("source_version")),
            source_saved_at=stringify(src.get("Дата та час збереження інформації") or src.get("source_saved_at")),
            is_main_company=bool(match and match.is_main_company),
        )
        out.append(row)
    return out


def load_raw_wide(path: Path, matching: Mapping[Tuple[int, str], MatchRow]) -> List[WideFinancialRow]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return wide_rows_from_dicts(csv.DictReader(f), matching)


def normalize_to_long(rows: Sequence[WideFinancialRow]) -> List[dict]:
    long_rows: List[dict] = []
    for src in rows:
        for code in FINANCIAL_CODES:
            long_rows.append({
                "group_id": src.group_id,
                "group_name": src.group_name,
                "report_date": src.report_date,
                "report_year": src.report_year,
                "edrpou": src.edrpou,
                "client_name": src.client_name,
                "report_form": src.report_form,
                "line_code": code,
                "line_value": src.values.get(code, 0.0),
            })
    return long_rows


def choose_group_metadata(rows: Sequence[WideFinancialRow]) -> Tuple[str, str]:
    main_rows = [row for row in rows if row.is_main_company]
    candidate = main_rows[0] if main_rows else max(rows, key=lambda row: row.values.get("2000", 0.0))
    return candidate.kved_class, candidate.kved_section


def aggregate_group_wide(rows: Sequence[WideFinancialRow]) -> List[WideFinancialRow]:
    buckets: Dict[Tuple[str, str, int, str], List[WideFinancialRow]] = defaultdict(list)
    for row in rows:
        if row.group_id != "UNMATCHED":
            buckets[(row.group_id, row.report_date, row.report_year, row.report_form)].append(row)

    group_rows: List[WideFinancialRow] = []
    loaded_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    for (group_id, report_date, year, report_form), members in sorted(buckets.items()):
        values = {code: sum(member.values.get(code, 0.0) for member in members) for code in FINANCIAL_CODES}
        kved_class, kved_section = choose_group_metadata(members)
        group_rows.append(WideFinancialRow(
            identifier=group_id,
            report_date=report_date,
            report_year=year,
            edrpou=group_id,
            report_form=report_form,
            client_name=members[0].group_name or group_id,
            group_id=group_id,
            group_name=members[0].group_name or group_id,
            values=values,
            staff_count=sum(member.staff_count for member in members),
            kved_class=kved_class,
            kved_section=kved_section,
            source_user="EWS_ETL",
            source_version="group-financials-1.0",
            source_saved_at=loaded_at,
        ))
    return group_rows


def aggregate_group_long(rows: Sequence[WideFinancialRow]) -> List[dict]:
    out: List[dict] = []
    buckets: Dict[Tuple[str, str, int, str], List[WideFinancialRow]] = defaultdict(list)
    for row in rows:
        if row.group_id != "UNMATCHED":
            buckets[(row.group_id, row.report_date, row.report_year, row.report_form)].append(row)
    for (group_id, report_date, year, report_form), members in sorted(buckets.items()):
        members_edrpou = ";".join(sorted({member.edrpou for member in members}))
        for code in FINANCIAL_CODES:
            out.append({
                "group_id": group_id,
                "group_name": members[0].group_name or group_id,
                "report_date": report_date,
                "report_year": year,
                "report_form": report_form,
                "line_code": code,
                "line_value": sum(member.values.get(code, 0.0) for member in members),
                "members_count": len({member.edrpou for member in members}),
                "members_edrpou": members_edrpou,
                "aggregation_rule": "SUM",
            })
    return out


def get_line(lines: Mapping[str, float], code: str) -> float:
    return float(lines.get(code, 0.0) or 0.0)


def calculate_indicators_for_lines(lines: Mapping[str, float], days: int = 365) -> dict:
    revenue = get_line(lines, "2000")
    cogs = get_line(lines, "2050")
    gross_profit = get_line(lines, "2090") - get_line(lines, "2095")
    ebit = get_line(lines, "2190") - get_line(lines, "2195")
    depreciation = get_line(lines, "2515")
    ebitda = ebit + depreciation
    nie = get_line(lines, "2250") - get_line(lines, "2220")
    net_income = get_line(lines, "2350") - get_line(lines, "2355")
    cash = get_line(lines, "1165")
    ar = get_line(lines, "1120") + get_line(lines, "1125")
    inventory = get_line(lines, "1100") + get_line(lines, "1110")
    ap = get_line(lines, "1605") + get_line(lines, "1615")
    total_assets = get_line(lines, "1300")
    equity = get_line(lines, "1495")
    current_assets = get_line(lines, "1195")
    current_liabilities = get_line(lines, "1695")
    debt = get_line(lines, "1510") + get_line(lines, "1515") + get_line(lines, "1600") + get_line(lines, "1610")
    dso = safe_div(ar * days, revenue)
    operating_cost_base = abs(cogs - depreciation)
    dio = safe_div(inventory * days, operating_cost_base)
    dpo = safe_div(ap * days, operating_cost_base)
    financial_cycle = None if dso is None or dio is None or dpo is None else dso + dio - dpo
    return {
        "revenue": revenue,
        "gross_profit": gross_profit,
        "ebit": ebit,
        "depreciation": depreciation,
        "ebitda": ebitda,
        "ebitda_margin": safe_div(ebitda, revenue),
        "nie": nie,
        "net_income": net_income,
        "cash": cash,
        "accounts_receivable": ar,
        "inventory": inventory,
        "accounts_payable": ap,
        "total_assets": total_assets,
        "equity": equity,
        "current_assets": current_assets,
        "current_liabilities": current_liabilities,
        "total_interest_bearing_debt": debt,
        "net_debt": debt - cash,
        "equity_ratio": safe_div(equity, total_assets),
        "current_ratio": safe_div(current_assets, current_liabilities),
        "net_debt_to_ebitda": safe_div(debt - cash, ebitda) if ebitda > 0 else None,
        "icrm": safe_div(ebitda, abs(nie)) if abs(nie) >= 1 else None,
        "dso_days": dso,
        "dio_days": dio,
        "dpo_days": dpo,
        "financial_cycle_days": financial_cycle,
        "average_capital_need": safe_div(abs(cogs) * financial_cycle, days) if financial_cycle is not None else None,
    }


def build_indicator_rows(company_rows: Sequence[WideFinancialRow], group_rows: Sequence[WideFinancialRow]) -> List[dict]:
    out: List[dict] = []
    for entity_type, rows in (("COMPANY", company_rows), ("GROUP", group_rows)):
        for row in rows:
            metrics = calculate_indicators_for_lines(row.values)
            entity_id = row.edrpou if entity_type == "COMPANY" else row.group_id
            out.append({
                "entity_type": entity_type,
                "entity_id": entity_id,
                "entity_name": row.client_name or row.group_name or entity_id,
                "report_date": row.report_date,
                "year": row.report_year,
                "source_sheet": "02_Raw_Wide" if entity_type == "COMPANY" else "03_Group_Aggregated",
                **metrics,
            })
    out.sort(key=lambda item: (item["entity_type"], item["entity_id"], item["year"], item["report_date"]))
    previous_revenue: Dict[Tuple[str, str], float] = {}
    for item in out:
        key = (item["entity_type"], item["entity_id"])
        item["revenue_growth_pct"] = safe_div(item["revenue"], previous_revenue[key]) - 1 if key in previous_revenue and abs(previous_revenue[key]) > 1e-9 else None
        previous_revenue[key] = item["revenue"]
    return out


def validation_report(company_rows: Sequence[WideFinancialRow], group_rows: Sequence[WideFinancialRow], indicator_rows: Sequence[Mapping[str, Any]]) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    unmatched = sorted({(row.report_year, row.edrpou) for row in company_rows if row.group_id == "UNMATCHED"})
    issues.append(ValidationIssue("Raw rows have matched group_id", "OK" if not unmatched else "CHECK", f"Unmatched: {unmatched}" if unmatched else "All included raw rows matched by matching_year+edrpou"))

    seen: Dict[Tuple[int, str, str, str], int] = defaultdict(int)
    for row in company_rows:
        seen[(row.report_year, row.report_date, row.edrpou, row.report_form)] += 1
    duplicates = [key for key, count in seen.items() if count > 1]
    issues.append(ValidationIssue("No duplicate company report keys", "OK" if not duplicates else "CHECK", f"Duplicates: {duplicates}" if duplicates else "No duplicate report keys"))

    balance_breaks = []
    for row in group_rows:
        diff = row.values.get("1300", 0.0) - row.values.get("1900", 0.0)
        if abs(diff) > 1:
            balance_breaks.append((row.group_id, row.report_year, row.report_date, diff))
    issues.append(ValidationIssue("Assets balance equation", "OK" if not balance_breaks else "CHECK", f"Diffs over tolerance: {balance_breaks}" if balance_breaks else "Line 1300 equals line 1900 within +/-1"))

    issues.append(ValidationIssue("Group rows created", "OK" if group_rows else "CHECK", f"Group rows: {len(group_rows)}"))

    missing_metrics = []
    for item in indicator_rows:
        if item["entity_type"] == "GROUP" and any(item.get(metric) in (None, "") for metric in ("revenue", "ebitda", "total_assets", "equity")):
            missing_metrics.append((item["entity_id"], item["year"]))
    issues.append(ValidationIssue("Dashboard metrics not blank", "OK" if not missing_metrics else "CHECK", f"Missing group metrics: {missing_metrics}" if missing_metrics else "Revenue, EBITDA, assets and equity available"))
    return issues


def wide_row_to_dict(row: WideFinancialRow, group_mode: bool = False) -> dict:
    data = {
        "Ідентифікатор": row.identifier,
        "Звітна дата": row.report_date,
        "Код ЄДРПОУ": row.group_id if group_mode else row.edrpou,
        "Форма звітності": row.report_form,
    }
    data.update({code: row.values.get(code, 0.0) for code in FINANCIAL_CODES})
    data.update({
        "Середня чисельність працівників": row.staff_count,
        "Клас КВЕД2010": row.kved_class,
        "Секція КВЕД2010": row.kved_section,
        "Користувач": row.source_user,
        "Версія 0.10.005": row.source_version,
        "Дата та час збереження інформації": row.source_saved_at,
    })
    return data


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]], fieldnames: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def read_excel_table(workbook_path: Path, sheet_name: str) -> List[dict]:
    openpyxl = importlib.import_module("openpyxl")
    wb = openpyxl.load_workbook(workbook_path, data_only=True)
    ws = wb[sheet_name]
    headers = [stringify(cell.value) for cell in ws[1]]
    rows = []
    for values in ws.iter_rows(min_row=2, values_only=True):
        row = {headers[idx]: values[idx] for idx in range(min(len(headers), len(values))) if headers[idx]}
        if any(stringify(value) for value in row.values()):
            rows.append(row)
    return rows


def clear_and_write_sheet(ws: Any, headers: Sequence[str], rows: Sequence[Mapping[str, Any]]) -> None:
    ws.delete_rows(1, ws.max_row)
    ws.append(list(headers))
    for row in rows:
        ws.append([row.get(header, "") for header in headers])
    ws.freeze_panes = "A2"
    for col_cells in ws.columns:
        letter = col_cells[0].column_letter
        max_len = max(len(stringify(cell.value)) for cell in col_cells[:100])
        ws.column_dimensions[letter].width = min(max(max_len + 2, 10), 28)


def export_excel(template_path: Path, output_path: Path, matching_rows: Sequence[Mapping[str, Any]], company_rows: Sequence[WideFinancialRow], group_rows: Sequence[WideFinancialRow], indicator_rows: Sequence[Mapping[str, Any]], checks: Sequence[ValidationIssue]) -> None:
    openpyxl = importlib.import_module("openpyxl")
    wb = openpyxl.load_workbook(template_path)
    clear_and_write_sheet(wb["01_Group_Matching"], ["group_id", "matching_year", "group_name", "edrpou", "client_name", "inclusion_flag", "consolidation_method", "ownership_share_pct", "match_key", "is_main_company", "note"], matching_rows)
    clear_and_write_sheet(wb["02_Raw_Wide"], CANONICAL_WIDE_HEADERS, [wide_row_to_dict(row) for row in company_rows])
    clear_and_write_sheet(wb["03_Group_Aggregated"], CANONICAL_WIDE_HEADERS, [wide_row_to_dict(row, group_mode=True) for row in group_rows])
    indicator_headers = ["entity_type", "entity_id", "entity_name", "report_date", "year", "source_sheet", "revenue", "revenue_growth_pct", "gross_profit", "ebit", "depreciation", "ebitda", "ebitda_margin", "nie", "net_income", "cash", "accounts_receivable", "inventory", "accounts_payable", "total_assets", "equity", "current_assets", "current_liabilities", "total_interest_bearing_debt", "net_debt", "equity_ratio", "current_ratio", "net_debt_to_ebitda", "icrm", "dso_days", "dio_days", "dpo_days", "financial_cycle_days", "average_capital_need"]
    clear_and_write_sheet(wb["04_Financials_Model"], indicator_headers, indicator_rows)
    clear_and_write_sheet(wb["07_Data_Checks"], ["check_name", "status", "details"], [issue.__dict__ for issue in checks])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)


def make_demo_rows(raw_rows: List[dict]) -> List[dict]:
    demo_profiles = {
        "EDRPOU_1": {"1000": 1500, "1100": 800, "1110": 120, "1120": 900, "1125": 120, "1165": 350, "1195": 2600, "1300": 6100, "1495": 2800, "1510": 900, "1515": 300, "1600": 450, "1605": 700, "1610": 250, "1615": 150, "1695": 2100, "1900": 6100, "2000": 7200, "2050": 4700, "2090": 2500, "2190": 1200, "2220": 80, "2250": 260, "2300": 120, "2350": 820, "2515": 420},
        "EDRPOU_2": {"1000": 900, "1100": 650, "1110": 90, "1120": 700, "1125": 80, "1165": 220, "1195": 1900, "1300": 4200, "1495": 1700, "1510": 650, "1515": 180, "1600": 320, "1605": 560, "1610": 190, "1615": 110, "1695": 1600, "1900": 4200, "2000": 5300, "2050": 3600, "2090": 1700, "2190": 820, "2220": 50, "2250": 190, "2300": 80, "2350": 560, "2515": 310},
    }
    out = []
    for row in raw_rows:
        edrpou = stringify(row.get("Код ЄДРПОУ") or row.get("edrpou"))
        new_row = dict(row)
        if edrpou in demo_profiles and all(not stringify(row.get(code)) for code in FINANCIAL_CODES):
            new_row.update(demo_profiles[edrpou])
            new_row["Середня чисельність працівників"] = 145 if edrpou == "EDRPOU_1" else 96
            new_row["Клас КВЕД2010"] = "46.90" if edrpou == "EDRPOU_1" else "52.29"
            new_row["Секція КВЕД2010"] = "G" if edrpou == "EDRPOU_1" else "H"
            new_row["Користувач"] = "ClientProfile export"
            new_row["Версія 0.10.005"] = "0.10.005"
            new_row["Дата та час збереження інформації"] = "2026-05-18T08:09:02Z"
        out.append(new_row)
    return out



def _column_letter(index: int) -> str:
    letters = ""
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def _minimal_read_excel_table(workbook_path: Path, sheet_name: str) -> List[dict]:
    import xml.etree.ElementTree as ET
    import zipfile

    ns = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main", "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
    rel_ns = "{http://schemas.openxmlformats.org/package/2006/relationships}"
    with zipfile.ZipFile(workbook_path) as z:
        shared: List[str] = []
        if "xl/sharedStrings.xml" in z.namelist():
            root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in root.findall("a:si", ns):
                shared.append("".join(t.text or "" for t in si.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t")))
        wb_root = ET.fromstring(z.read("xl/workbook.xml"))
        rel_root = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        rels = {rel.attrib["Id"]: rel.attrib["Target"].lstrip("/") for rel in rel_root.findall(f"{rel_ns}Relationship")}
        target = None
        for sheet in wb_root.find("a:sheets", ns):
            if sheet.attrib["name"] == sheet_name:
                target = rels[sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]]
                break
        if target is None:
            raise KeyError(f"Sheet not found: {sheet_name}")
        if not target.startswith("xl/"):
            target = "xl/" + target
        sheet_root = ET.fromstring(z.read(target))

    rows_by_num: Dict[int, Dict[int, Any]] = defaultdict(dict)
    for row in sheet_root.findall(".//a:row", ns):
        row_num = int(row.attrib["r"])
        for cell in row.findall("a:c", ns):
            ref = cell.attrib.get("r", "A1")
            col_letters = "".join(ch for ch in ref if ch.isalpha())
            col_num = 0
            for ch in col_letters:
                col_num = col_num * 26 + ord(ch.upper()) - 64
            cell_type = cell.attrib.get("t")
            value_node = cell.find("a:v", ns)
            inline_node = cell.find("a:is/a:t", ns)
            value: Any = ""
            if cell_type == "s" and value_node is not None:
                value = shared[int(value_node.text or 0)]
            elif cell_type == "inlineStr" and inline_node is not None:
                value = inline_node.text or ""
            elif value_node is not None:
                value = value_node.text or ""
            rows_by_num[row_num][col_num] = value
    if not rows_by_num:
        return []
    headers = [stringify(rows_by_num[min(rows_by_num)].get(col, "")) for col in range(1, max(rows_by_num[min(rows_by_num)]) + 1)]
    out: List[dict] = []
    for row_num in sorted(r for r in rows_by_num if r != min(rows_by_num)):
        row = {headers[col - 1]: rows_by_num[row_num].get(col, "") for col in range(1, len(headers) + 1) if headers[col - 1]}
        if any(stringify(value) for value in row.values()):
            out.append(row)
    return out


def _xml_escape(value: Any) -> str:
    import html
    return html.escape(stringify(value), quote=True)


def _sheet_xml(headers: Sequence[str], rows: Sequence[Mapping[str, Any]]) -> str:
    all_rows: List[Sequence[Any]] = [headers] + [[row.get(header, "") for header in headers] for row in rows]
    xml_rows = []
    for r_idx, values in enumerate(all_rows, start=1):
        cells = []
        for c_idx, value in enumerate(values, start=1):
            ref = f"{_column_letter(c_idx)}{r_idx}"
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                cells.append(f'<c r="{ref}"><v>{value}</v></c>')
            else:
                cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{_xml_escape(value)}</t></is></c>')
        xml_rows.append(f'<row r="{r_idx}">' + ''.join(cells) + '</row>')
    return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' + \
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheetData>' + \
        ''.join(xml_rows) + '</sheetData></worksheet>'


def _minimal_export_excel(output_path: Path, sheets: Sequence[Tuple[str, Sequence[str], Sequence[Mapping[str, Any]]]]) -> None:
    import zipfile
    output_path.parent.mkdir(parents=True, exist_ok=True)
    content_overrides = ''.join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i, _ in enumerate(sheets, start=1))
    workbook_sheets = ''.join(f'<sheet name="{_xml_escape(name)}" sheetId="{i}" r:id="rId{i}"/>' for i, (name, _, _) in enumerate(sheets, start=1))
    workbook_rels = ''.join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>' for i, _ in enumerate(sheets, start=1))
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>' + content_overrides + '</Types>')
        z.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr("xl/workbook.xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>' + workbook_sheets + '</sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + workbook_rels + '</Relationships>')
        for i, (_, headers, rows) in enumerate(sheets, start=1):
            z.writestr(f"xl/worksheets/sheet{i}.xml", _sheet_xml(headers, rows))


def read_excel_table(workbook_path: Path, sheet_name: str) -> List[dict]:
    if importlib.util.find_spec("openpyxl") is not None:
        openpyxl = importlib.import_module("openpyxl")
        wb = openpyxl.load_workbook(workbook_path, data_only=True)
        ws = wb[sheet_name]
        headers = [stringify(cell.value) for cell in ws[1]]
        rows = []
        for values in ws.iter_rows(min_row=2, values_only=True):
            row = {headers[idx]: values[idx] for idx in range(min(len(headers), len(values))) if headers[idx]}
            if any(stringify(value) for value in row.values()):
                rows.append(row)
        return rows
    return _minimal_read_excel_table(workbook_path, sheet_name)


def export_excel(template_path: Path, output_path: Path, matching_rows: Sequence[Mapping[str, Any]], company_rows: Sequence[WideFinancialRow], group_rows: Sequence[WideFinancialRow], indicator_rows: Sequence[Mapping[str, Any]], checks: Sequence[ValidationIssue]) -> None:
    matching_headers = ["group_id", "matching_year", "group_name", "edrpou", "client_name", "inclusion_flag", "consolidation_method", "ownership_share_pct", "match_key", "is_main_company", "note"]
    indicator_headers = ["entity_type", "entity_id", "entity_name", "report_date", "year", "source_sheet", "revenue", "revenue_growth_pct", "gross_profit", "ebit", "depreciation", "ebitda", "ebitda_margin", "nie", "net_income", "cash", "accounts_receivable", "inventory", "accounts_payable", "total_assets", "equity", "current_assets", "current_liabilities", "total_interest_bearing_debt", "net_debt", "equity_ratio", "current_ratio", "net_debt_to_ebitda", "icrm", "dso_days", "dio_days", "dpo_days", "financial_cycle_days", "average_capital_need"]
    check_rows = [issue.__dict__ for issue in checks]
    if importlib.util.find_spec("openpyxl") is not None:
        openpyxl = importlib.import_module("openpyxl")
        wb = openpyxl.load_workbook(template_path)
        clear_and_write_sheet(wb["01_Group_Matching"], matching_headers, matching_rows)
        clear_and_write_sheet(wb["02_Raw_Wide"], CANONICAL_WIDE_HEADERS, [wide_row_to_dict(row) for row in company_rows])
        clear_and_write_sheet(wb["03_Group_Aggregated"], CANONICAL_WIDE_HEADERS, [wide_row_to_dict(row, group_mode=True) for row in group_rows])
        clear_and_write_sheet(wb["04_Financials_Model"], indicator_headers, indicator_rows)
        clear_and_write_sheet(wb["07_Data_Checks"], ["check_name", "status", "details"], check_rows)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        wb.save(output_path)
        return
    _minimal_export_excel(output_path, [
        ("01_Group_Matching", matching_headers, matching_rows),
        ("02_Raw_Wide", CANONICAL_WIDE_HEADERS, [wide_row_to_dict(row) for row in company_rows]),
        ("03_Group_Aggregated", CANONICAL_WIDE_HEADERS, [wide_row_to_dict(row, group_mode=True) for row in group_rows]),
        ("04_Financials_Model", indicator_headers, indicator_rows),
        ("07_Data_Checks", ["check_name", "status", "details"], check_rows),
    ])


def write_run_manifest(
    output_dir: Path,
    input_excel: Optional[Path],
    output_excel: Optional[Path],
    company_rows: Sequence[WideFinancialRow],
    group_rows: Sequence[WideFinancialRow],
    long_rows: Sequence[Mapping[str, Any]],
    group_long_rows: Sequence[Mapping[str, Any]],
    indicator_rows: Sequence[Mapping[str, Any]],
    checks: Sequence[ValidationIssue],
    demo_values: bool,
) -> None:
    """Write a machine-readable run manifest for auditability and handover."""
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "generated_at_utc": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "input_excel": str(input_excel) if input_excel else None,
        "output_excel": str(output_excel) if output_excel else None,
        "demo_values": demo_values,
        "rules": {
            "edrpou_type": "string",
            "matching_key": ["matching_year", "edrpou"],
            "inclusion_filter": "inclusion_flag=1",
            "financial_line_aggregation": "SUM",
            "staff_aggregation": "SUM",
            "kved_rule": "is_main_company=1 else highest revenue",
            "metadata_rule": "ETL metadata",
        },
        "counts": {
            "company_wide_rows": len(company_rows),
            "company_long_rows": len(long_rows),
            "group_wide_rows": len(group_rows),
            "group_long_rows": len(group_long_rows),
            "indicator_rows": len(indicator_rows),
            "validation_checks": len(checks),
        },
        "validation": [issue.__dict__ for issue in checks],
        "outputs": {
            "company_financials_long": str(output_dir / "company_financials_long.csv"),
            "group_financials_long": str(output_dir / "group_financials_long.csv"),
            "group_financials_wide": str(output_dir / "group_financials_wide.csv"),
            "financial_indicators": str(output_dir / "financial_indicators.csv"),
            "validation_report": str(output_dir / "validation_report.csv"),
        },
    }
    (output_dir / "run_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def assert_no_blocking_validation(checks: Sequence[ValidationIssue]) -> None:
    failed = [issue for issue in checks if issue.status.upper() not in {"OK", "WARN", "WARNING"}]
    if failed:
        details = "; ".join(f"{issue.check_name}: {issue.details}" for issue in failed)
        raise SystemExit(f"Validation failed: {details}")


def build_from_excel(input_excel: Path, output_dir: Path, output_excel: Path, demo_values: bool = False, fail_on_check: bool = False) -> None:
    matching_dicts = read_excel_table(input_excel, "01_Group_Matching")
    raw_dicts = read_excel_table(input_excel, "02_Raw_Wide")
    if demo_values:
        raw_dicts = make_demo_rows(raw_dicts)
    matching = matching_from_dicts(matching_dicts)
    company_rows = wide_rows_from_dicts(raw_dicts, matching)
    group_rows = aggregate_group_wide(company_rows)
    long_rows = normalize_to_long(company_rows)
    group_long_rows = aggregate_group_long(company_rows)
    indicator_rows = build_indicator_rows(company_rows, group_rows)
    checks = validation_report(company_rows, group_rows, indicator_rows)

    write_csv(output_dir / "company_financials_long.csv", long_rows, ["group_id", "group_name", "report_date", "report_year", "edrpou", "client_name", "report_form", "line_code", "line_value"])
    write_csv(output_dir / "group_financials_long.csv", group_long_rows, ["group_id", "group_name", "report_date", "report_year", "report_form", "line_code", "line_value", "members_count", "members_edrpou", "aggregation_rule"])
    write_csv(output_dir / "group_financials_wide.csv", [wide_row_to_dict(row, group_mode=True) for row in group_rows], CANONICAL_WIDE_HEADERS)
    indicator_headers = ["entity_type", "entity_id", "entity_name", "report_date", "year", "source_sheet", "revenue", "revenue_growth_pct", "gross_profit", "ebit", "depreciation", "ebitda", "ebitda_margin", "nie", "net_income", "cash", "accounts_receivable", "inventory", "accounts_payable", "total_assets", "equity", "current_assets", "current_liabilities", "total_interest_bearing_debt", "net_debt", "equity_ratio", "current_ratio", "net_debt_to_ebitda", "icrm", "dso_days", "dio_days", "dpo_days", "financial_cycle_days", "average_capital_need"]
    write_csv(output_dir / "financial_indicators.csv", indicator_rows, indicator_headers)
    write_csv(output_dir / "validation_report.csv", [issue.__dict__ for issue in checks], ["check_name", "status", "details"])
    export_excel(input_excel, output_excel, matching_dicts, company_rows, group_rows, indicator_rows, checks)
    write_run_manifest(output_dir, input_excel, output_excel, company_rows, group_rows, long_rows, group_long_rows, indicator_rows, checks, demo_values)
    if fail_on_check:
        assert_no_blocking_validation(checks)


def build_from_csv_args(args: argparse.Namespace) -> None:
    matching = load_matching(Path(args.matching))
    company_rows = load_raw_wide(Path(args.raw_wide), matching)
    group_rows = aggregate_group_wide(company_rows)
    group_long = aggregate_group_long(company_rows)
    long_rows = normalize_to_long(company_rows)
    indicators = build_indicator_rows(company_rows, group_rows)
    checks = validation_report(company_rows, group_rows, indicators)
    write_csv(Path(args.out_long), long_rows, ["group_id", "group_name", "report_date", "report_year", "edrpou", "client_name", "report_form", "line_code", "line_value"])
    write_csv(Path(args.out_group), group_long, ["group_id", "group_name", "report_date", "report_year", "report_form", "line_code", "line_value", "members_count", "members_edrpou", "aggregation_rule"])
    output_dir = Path(args.output_dir)
    write_csv(output_dir / "group_financials_wide.csv", [wide_row_to_dict(row, group_mode=True) for row in group_rows], CANONICAL_WIDE_HEADERS)
    indicator_headers = ["entity_type", "entity_id", "entity_name", "report_date", "year", "source_sheet", "revenue", "revenue_growth_pct", "gross_profit", "ebit", "depreciation", "ebitda", "ebitda_margin", "nie", "net_income", "cash", "accounts_receivable", "inventory", "accounts_payable", "total_assets", "equity", "current_assets", "current_liabilities", "total_interest_bearing_debt", "net_debt", "equity_ratio", "current_ratio", "net_debt_to_ebitda", "icrm", "dso_days", "dio_days", "dpo_days", "financial_cycle_days", "average_capital_need"]
    write_csv(output_dir / "financial_indicators.csv", indicators, indicator_headers)
    write_csv(output_dir / "validation_report.csv", [issue.__dict__ for issue in checks], ["check_name", "status", "details"])
    write_run_manifest(output_dir, None, None, company_rows, group_rows, long_rows, group_long, indicators, checks, False)
    if args.fail_on_check:
        assert_no_blocking_validation(checks)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build EWS company and group financial outputs")
    parser.add_argument("--input-excel", help="Template/input Excel with 01_Group_Matching and 02_Raw_Wide sheets")
    parser.add_argument("--output-dir", default="output", help="Directory for generated CSV reports")
    parser.add_argument("--output-excel", default="output/Group_Financials_EWS_Filled.xlsx", help="Filled Excel workbook")
    parser.add_argument("--demo-values", action="store_true", help="Populate empty placeholder raw rows with clearly synthetic demonstration values")
    parser.add_argument("--fail-on-check", action="store_true", help="Exit non-zero when validation_report contains CHECK statuses")
    parser.add_argument("--matching", help="CSV group matching file")
    parser.add_argument("--raw-wide", help="CSV raw wide financials")
    parser.add_argument("--out-long", help="Output normalized long CSV")
    parser.add_argument("--out-group", help="Output aggregated group long CSV")
    args = parser.parse_args()

    if args.input_excel:
        build_from_excel(Path(args.input_excel), Path(args.output_dir), Path(args.output_excel), args.demo_values, args.fail_on_check)
    elif args.matching and args.raw_wide and args.out_long and args.out_group:
        build_from_csv_args(args)
    else:
        parser.error("Use either --input-excel or the CSV arguments: --matching --raw-wide --out-long --out-group")


if __name__ == "__main__":
    main()
