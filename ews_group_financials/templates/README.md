# Text templates for EWS Group Financials

Binary workbook files are intentionally not stored in the repository.
Use these CSV files as the canonical text template/input pair:

- `01_Group_Matching.csv` — year-specific group membership rules.
- `02_Raw_Wide.csv` — ClientProfile-style wide financial rows with canonical headers.

The generated CSV deliverables under `output/` are the supported repository artifacts.
If an `.xlsx` workbook is required for a local handoff, generate it outside version control from these CSVs or from an external workbook template.
