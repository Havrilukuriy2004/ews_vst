import argparse
import json
import unittest
from pathlib import Path
import tempfile
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))

from dashboard_app import DashboardData, render_dashboard, validate_dashboard_data  # noqa: E402
from db_connectors import clientprofile_finrep_sql, is_sql_readonly, connector_statuses  # noqa: E402
from dependency_report import build_dependency_report, assert_required_dependency_metadata  # noqa: E402
from build_mandatory_matching import build_matching_rows, validate_mandatory_rows  # noqa: E402
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
            data = DashboardData(out_dir, root / "python" / "config.example.env")
            summary = validate_dashboard_data(data)
            self.assertGreaterEqual(summary["counts"]["group_wide_rows"], 1)
            html = render_dashboard(data)
        self.assertIn("EWS Group Financials Dashboard", html)
        self.assertIn("Database connections", html)
        statuses = connector_statuses(root / "python" / "config.example.env")
        self.assertEqual({status.name for status in statuses}, {"clientprofile_sql_server", "oracle_ews"})

    def test_internal_db_dependency_manifest(self):
        root = Path(__file__).resolve().parents[1]
        report = build_dependency_report(root / "config" / "internal_db_dependencies.json", root / "python" / "config.example.env")
        assert_required_dependency_metadata(report)
        package_names = {package["name"] for package in report["python_optional_packages"]}
        self.assertTrue({"pyodbc", "oracledb", "openpyxl"}.issubset(package_names))
        db_names = {database["logical_name"] for database in report["internal_databases"]}
        self.assertEqual(db_names, {"clientprofile_sql_server", "oracle_ews"})
        for database in report["internal_databases"]:
            self.assertEqual(database["access"], "read-only")
            self.assertIn("CREATE_DOC", database["forbidden_operations"])

    def test_mandatory_client_population_is_complete(self):
        import csv
        root = Path(__file__).resolve().parents[1]
        with (root / "data" / "mandatory_clients_2025.csv").open(encoding="utf-8-sig", newline="") as f:
            mandatory = list(csv.DictReader(f))
        with (root / "data" / "group_directory.csv").open(encoding="utf-8-sig", newline="") as f:
            directory = list(csv.DictReader(f))
        self.assertEqual(len(mandatory), 96)
        self.assertEqual(validate_mandatory_rows(mandatory, 96), [])
        matching = build_matching_rows(mandatory, directory, 2025)
        self.assertEqual(len(matching), 96)
        self.assertTrue(all(row["inclusion_flag"] == "1" for row in matching))
        self.assertEqual({row["edrpou"] for row in matching}, {row["edrpou"] for row in mandatory})
        self.assertIn("42751799", {row["edrpou"] for row in matching})
        self.assertIn("00178353", {row["edrpou"] for row in matching})


if __name__ == "__main__":
    unittest.main()
