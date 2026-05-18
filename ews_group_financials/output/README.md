# Generated outputs

This directory is intentionally kept in git only as a placeholder/documentation folder.

Run the pipeline to regenerate local deliverables:

```bash
./scripts/run_group_financials.sh
```

Generated CSV/JSON/HTML files are ignored by git to keep pull requests small and avoid merge conflicts:

- `company_financials_long.csv`
- `group_financials_long.csv`
- `group_financials_wide.csv`
- `financial_indicators.csv`
- `validation_report.csv`
- `run_manifest.json`
- `dashboard_snapshot.html`
