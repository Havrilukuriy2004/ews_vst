import argparse
import unittest
from pathlib import Path
import tempfile
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from dashboard_app import DashboardData, render_dashboard, validate_dashboard_data  # noqa: E402
from db_connectors import clientprofile_finrep_sql, is_sql_readonly, connector_statuses, optional_dependency_statuses  # noqa: E402
from check_runtime_dependencies import dependency_report  # noqa: E402

from build_group_financials import (  # noqa: E402
    aggregate_group_wide,
    build_from_csv_args,
    build_indicator_rows,
    matching_from_dicts,
    parse_number,
    validation_report,
    wide_rows_from_dicts,
)


class GroupFinancialsTests(unittest.TestCase):
    def test_year_specific_matching_and_group_sum(self):
        matching = matching_from_dicts([
            {"group_id": "G1", "matching_year": "2025", "group_name": "Group", "edrpou": "001", "inclusion_flag": "1", "is_main_company": "1"},
            {"group_id": "G1", "matching_year": "2025", "group_name": "Group", "edrpou": "002", "inclusion_flag": "1", "is_main_company": "0"},
            {"group_id": "G1", "matching_year": "2024", "group_name": "Group", "edrpou": "002", "inclusion_flag": "0"},
        ])
        rows = wide_rows_from_dicts([
            {"Звітна дата": "2026-01-01", "Код ЄДРПОУ": "001", "Форма звітності": "Ф1/Ф2", "2000": "100", "2190": "15", "2515": "5", "1300": "80", "1900": "80", "1495": "40", "Клас КВЕД2010": "46.90"},
            {"Звітна дата": "2026-01-01", "Код ЄДРПОУ": "002", "Форма звітності": "Ф1/Ф2", "2000": "50", "2190": "10", "2515": "2", "1300": "70", "1900": "70", "1495": "30", "Клас КВЕД2010": "52.29"},
            {"Звітна дата": "2025-01-01", "Код ЄДРПОУ": "002", "Форма звітності": "Ф1/Ф2", "2000": "999"},
        ], matching)

        self.assertEqual(rows[2].group_id, "UNMATCHED")
        group_rows = aggregate_group_wide(rows)
        self.assertEqual(len(group_rows), 1)
        self.assertEqual(group_rows[0].values["2000"], 150)
        self.assertEqual(group_rows[0].values["1300"], 150)
        self.assertEqual(group_rows[0].kved_class, "46.90")

    def test_indicators_and_validation(self):
        matching = matching_from_dicts([
            {"group_id": "G1", "matching_year": "2025", "group_name": "Group", "edrpou": "001", "inclusion_flag": "1"},
        ])
        rows = wide_rows_from_dicts([
            {"Звітна дата": "2026-01-01", "Код ЄДРПОУ": "001", "Форма звітності": "Ф1/Ф2", "2000": "200", "2050": "100", "2190": "30", "2515": "10", "1300": "100", "1900": "100", "1495": "50"},
        ], matching)
        group_rows = aggregate_group_wide(rows)
        indicators = build_indicator_rows(rows, group_rows)
        group_indicator = [row for row in indicators if row["entity_type"] == "GROUP"][0]
        self.assertEqual(group_indicator["ebitda"], 40)
        self.assertEqual(group_indicator["ebitda_margin"], 0.2)
        checks = validation_report(rows, group_rows, indicators)
        self.assertTrue(all(issue.status == "OK" for issue in checks))

    def test_parse_number_is_tolerant_for_export_noise(self):
        self.assertIsNone(parse_number("not available"))
        self.assertIsNone(parse_number("#VALUE!"))
        self.assertEqual(parse_number("1 234,50"), 1234.5)

    def test_build_from_csv_args_writes_audit_manifest(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "out"
            args = argparse.Namespace(
                matching=str(root / "templates" / "01_Group_Matching.csv"),
                raw_wide=str(root / "templates" / "02_Raw_Wide.csv"),
                out_long=str(out_dir / "company_financials_long.csv"),
                out_group=str(out_dir / "group_financials_long.csv"),
                output_dir=str(out_dir),
                fail_on_check=True,
            )
            build_from_csv_args(args)
            self.assertTrue((out_dir / "run_manifest.json").exists())
            self.assertTrue((out_dir / "group_financials_wide.csv").exists())
            self.assertTrue((out_dir / "validation_report.csv").read_text(encoding="utf-8-sig").count("OK") >= 5)

    def test_readonly_db_guards_and_dry_run_sql(self):
        self.assertTrue(is_sql_readonly("SELECT * FROM finrep.v_CollectReport"))
        self.assertTrue(is_sql_readonly("EXEC [finrep].[getReportFormInfo] @reportForm = 1"))
        self.assertFalse(is_sql_readonly("UPDATE dbo.table SET x = 1"))
        self.assertFalse(is_sql_readonly("EXEC SR_BANK.CREATE_DOC"))
        sql = clientprofile_finrep_sql(1, 2025, 4, ["001", "002"])
        self.assertIn("getReportFormInfo", sql)
        self.assertIn("001,002", sql)

    def test_dashboard_summary_and_html_render(self):
        root = Path(__file__).resolve().parents[1]
        data = DashboardData(root / "output", root / "python" / "config.example.env")
        summary = validate_dashboard_data(data)
        self.assertGreaterEqual(summary["counts"]["group_wide_rows"], 1)
        html = render_dashboard(data)
        self.assertIn("EWS Group Financials Dashboard", html)
        self.assertIn("Database connections", html)
        statuses = connector_statuses(root / "python" / "config.example.env")
        self.assertEqual({status.name for status in statuses}, {"clientprofile_sql_server", "oracle_ews"})

    def test_runtime_dependency_report_declares_db_packages(self):
        deps = optional_dependency_statuses()
        self.assertEqual({dep["name"] for dep in deps}, {"pyodbc", "oracledb", "python-dotenv"})
        report = dependency_report()
        names = {dep["name"] for dep in report["dependencies"]}
        self.assertIn("pyodbc", names)
        self.assertIn("oracledb", names)
        self.assertIn("openpyxl", names)


if __name__ == "__main__":
    unittest.main()
