"""Dependency-free web dashboard for EWS Group Financials outputs.

Run locally:
    python python/dashboard_app.py --output-dir output --host 127.0.0.1 --port 8765

The dashboard is intentionally implemented with the Python standard library so it
works in locked-down bank environments and does not require binary assets.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import sys
from dataclasses import asdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "python") not in sys.path:
    sys.path.insert(0, str(ROOT / "python"))

from db_connectors import connector_statuses  # noqa: E402

NUMERIC_FIELDS = {
    "revenue", "revenue_growth_pct", "gross_profit", "ebit", "depreciation", "ebitda", "ebitda_margin",
    "nie", "net_income", "cash", "accounts_receivable", "inventory", "accounts_payable", "total_assets",
    "equity", "current_assets", "current_liabilities", "total_interest_bearing_debt", "net_debt",
    "equity_ratio", "current_ratio", "net_debt_to_ebitda", "icrm", "dso_days", "dio_days", "dpo_days",
    "financial_cycle_days", "average_capital_need", "line_value",
}


def parse_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(" ", "").replace(",", "."))
    except ValueError:
        return None


def read_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = []
        for row in csv.DictReader(f):
            converted = {}
            for key, value in row.items():
                converted[key] = parse_float(value) if key in NUMERIC_FIELDS else value
            rows.append(converted)
        return rows


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


class DashboardData:
    def __init__(self, output_dir: Path, env_file: Path | None = None):
        self.output_dir = output_dir
        self.env_file = env_file

    def indicators(self) -> list[dict[str, Any]]:
        return read_csv(self.output_dir / "financial_indicators.csv")

    def group_wide(self) -> list[dict[str, Any]]:
        return read_csv(self.output_dir / "group_financials_wide.csv")

    def validation(self) -> list[dict[str, Any]]:
        return read_csv(self.output_dir / "validation_report.csv")

    def manifest(self) -> dict[str, Any]:
        return read_json(self.output_dir / "run_manifest.json")

    def db_status(self) -> list[dict[str, Any]]:
        return [asdict(status) for status in connector_statuses(self.env_file)]

    def summary(self) -> dict[str, Any]:
        indicators = self.indicators()
        groups = [row for row in indicators if row.get("entity_type") == "GROUP"]
        latest_group = groups[-1] if groups else {}
        validation = self.validation()
        statuses = {str(row.get("status", "")) for row in validation}
        manifest = self.manifest()
        return {
            "kpi": {
                "revenue": latest_group.get("revenue"),
                "ebitda": latest_group.get("ebitda"),
                "ebitda_margin": latest_group.get("ebitda_margin"),
                "net_debt_to_ebitda": latest_group.get("net_debt_to_ebitda"),
                "icrm": latest_group.get("icrm"),
                "financial_cycle_days": latest_group.get("financial_cycle_days"),
            },
            "counts": manifest.get("counts", {}),
            "validation_statuses": sorted(status for status in statuses if status),
            "latest_group": latest_group,
            "db_status": self.db_status(),
        }


def format_value(value: Any) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, float):
        return f"{value:,.2f}".replace(",", " ")
    return html.escape(str(value))


def kpi_card(title: str, value: Any, suffix: str = "") -> str:
    return f'<div class="card"><div class="label">{html.escape(title)}</div><div class="value">{format_value(value)}{suffix}</div></div>'


def rows_table(rows: list[Mapping[str, Any]], columns: list[str]) -> str:
    head = "".join(f"<th>{html.escape(col)}</th>" for col in columns)
    body = []
    for row in rows:
        body.append("<tr>" + "".join(f"<td>{format_value(row.get(col))}</td>" for col in columns) + "</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def bar_svg(groups: list[Mapping[str, Any]]) -> str:
    values = [(str(row.get("entity_id", "")), parse_float(row.get("revenue")) or 0.0) for row in groups]
    if not values:
        return "<p>No group data.</p>"
    max_value = max(value for _, value in values) or 1.0
    bars = []
    for idx, (label, value) in enumerate(values):
        y = 24 + idx * 42
        width = int((value / max_value) * 520)
        bars.append(f'<text x="0" y="{y + 16}" class="svg-label">{html.escape(label)}</text>')
        bars.append(f'<rect x="110" y="{y}" width="{width}" height="24" rx="4"></rect>')
        bars.append(f'<text x="{120 + width}" y="{y + 17}" class="svg-value">{format_value(value)}</text>')
    height = 54 + len(values) * 42
    return f'<svg viewBox="0 0 720 {height}" role="img" aria-label="Revenue chart">{''.join(bars)}</svg>'


def render_dashboard(data: DashboardData) -> str:
    summary = data.summary()
    kpi = summary["kpi"]
    indicators = data.indicators()
    groups = [row for row in indicators if row.get("entity_type") == "GROUP"]
    companies = [row for row in indicators if row.get("entity_type") == "COMPANY"]
    validation = data.validation()
    db_status = summary["db_status"]
    html_doc = f"""<!doctype html>
<html lang="uk">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>EWS Group Financials Dashboard</title>
  <style>
    :root {{ --bg:#0f172a; --panel:#111827; --muted:#94a3b8; --text:#e5e7eb; --accent:#38bdf8; --ok:#22c55e; --warn:#f59e0b; }}
    * {{ box-sizing: border-box; }}
    body {{ margin:0; font-family: Inter, Segoe UI, Arial, sans-serif; background:linear-gradient(135deg,#0f172a,#172554); color:var(--text); }}
    header {{ padding:28px 32px; border-bottom:1px solid rgba(255,255,255,.1); }}
    h1 {{ margin:0; font-size:30px; }}
    h2 {{ margin-top:32px; }}
    main {{ padding:24px 32px 48px; }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:16px; }}
    .card, .panel {{ background:rgba(17,24,39,.88); border:1px solid rgba(255,255,255,.08); border-radius:16px; padding:18px; box-shadow:0 12px 28px rgba(0,0,0,.25); }}
    .label {{ color:var(--muted); font-size:13px; text-transform:uppercase; letter-spacing:.08em; }}
    .value {{ font-size:26px; font-weight:700; margin-top:8px; }}
    table {{ width:100%; border-collapse:collapse; overflow:hidden; border-radius:12px; }}
    th, td {{ padding:10px 12px; border-bottom:1px solid rgba(255,255,255,.08); text-align:left; }}
    th {{ color:#bae6fd; font-size:12px; text-transform:uppercase; letter-spacing:.06em; }}
    tr:hover {{ background:rgba(56,189,248,.08); }}
    .status-ok {{ color:var(--ok); font-weight:700; }}
    .status-bad {{ color:#fb7185; font-weight:700; }}
    svg {{ width:100%; max-height:300px; }} rect {{ fill:var(--accent); }} .svg-label,.svg-value {{ fill:var(--text); font-size:13px; }}
    .muted {{ color:var(--muted); }} code {{ color:#bae6fd; }}
  </style>
</head>
<body>
  <header>
    <h1>EWS Group Financials Dashboard</h1>
    <p class="muted">Групова фінансова звітність, EWS indicators, validation і DB connection readiness.</p>
  </header>
  <main>
    <section class="grid">
      {kpi_card('Revenue', kpi.get('revenue'))}
      {kpi_card('EBITDA', kpi.get('ebitda'))}
      {kpi_card('EBITDA margin', (kpi.get('ebitda_margin') or 0) * 100 if kpi.get('ebitda_margin') is not None else None, '%')}
      {kpi_card('Net Debt / EBITDA', kpi.get('net_debt_to_ebitda'))}
      {kpi_card('ICRm', kpi.get('icrm'))}
      {kpi_card('Financial Cycle', kpi.get('financial_cycle_days'), ' days')}
    </section>

    <section class="panel"><h2>Revenue by group</h2>{bar_svg(groups)}</section>
    <section class="panel"><h2>Group indicators</h2>{rows_table(groups, ['entity_id','entity_name','year','revenue','ebitda','ebitda_margin','net_debt_to_ebitda','icrm','financial_cycle_days'])}</section>
    <section class="panel"><h2>Company drill-down</h2>{rows_table(companies, ['entity_id','entity_name','year','revenue','ebitda','net_income','total_assets','equity'])}</section>
    <section class="panel"><h2>Validation</h2>{rows_table(validation, ['check_name','status','details'])}</section>
    <section class="panel"><h2>Database connections</h2>{rows_table(db_status, ['name','configured','driver_available','ready','message'])}</section>
    <section class="panel"><h2>API</h2><p class="muted">JSON endpoints: <code>/api/summary</code>, <code>/api/indicators</code>, <code>/api/validation</code>, <code>/api/group-wide</code>, <code>/api/db-status</code>.</p></section>
  </main>
</body>
</html>"""
    return html_doc


class DashboardHandler(BaseHTTPRequestHandler):
    data: DashboardData

    def send_json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_html(self, body_text: str) -> None:
        body = body_text.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path in {"/", "/dashboard"}:
            self.send_html(render_dashboard(self.data))
        elif parsed.path == "/api/summary":
            self.send_json(self.data.summary())
        elif parsed.path == "/api/indicators":
            self.send_json(self.data.indicators())
        elif parsed.path == "/api/validation":
            self.send_json(self.data.validation())
        elif parsed.path == "/api/group-wide":
            self.send_json(self.data.group_wide())
        elif parsed.path == "/api/db-status":
            self.send_json(self.data.db_status())
        elif parsed.path == "/health":
            self.send_json({"status": "ok"})
        else:
            self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return


def make_handler(data: DashboardData) -> type[DashboardHandler]:
    class BoundDashboardHandler(DashboardHandler):
        pass
    BoundDashboardHandler.data = data
    return BoundDashboardHandler


def validate_dashboard_data(data: DashboardData) -> dict[str, Any]:
    summary = data.summary()
    validation_statuses = set(summary.get("validation_statuses", []))
    if not data.indicators():
        raise SystemExit("No financial indicators found. Run ETL first.")
    if validation_statuses and validation_statuses != {"OK"}:
        raise SystemExit(f"Validation is not clean: {sorted(validation_statuses)}")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve EWS Group Financials dashboard")
    parser.add_argument("--output-dir", default="output")
    parser.add_argument("--env-file", default="python/config.example.env")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--check", action="store_true", help="Validate data and print summary JSON without serving")
    parser.add_argument("--export-html", help="Write a static HTML snapshot and exit")
    args = parser.parse_args()

    data = DashboardData(Path(args.output_dir), Path(args.env_file) if args.env_file else None)
    if args.check:
        print(json.dumps(validate_dashboard_data(data), ensure_ascii=False, indent=2))
        return
    if args.export_html:
        Path(args.export_html).parent.mkdir(parents=True, exist_ok=True)
        Path(args.export_html).write_text(render_dashboard(data), encoding="utf-8")
        return
    validate_dashboard_data(data)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(data))
    print(f"EWS dashboard available at http://{args.host}:{args.port}/dashboard")
    server.serve_forever()


if __name__ == "__main__":
    main()
