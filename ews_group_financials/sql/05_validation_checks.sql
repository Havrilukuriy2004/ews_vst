/*
05_validation_checks.sql
Purpose: quality checks before publishing group financials to EWS dashboard.
*/

-- 1. Unmatched EDRPOU
SELECT report_year, edrpou, COUNT(*) AS rows_count
FROM dbo.ews_financials_raw_long
WHERE group_id IS NULL
GROUP BY report_year, edrpou;

-- 2. Balance equation check: assets vs equity + liabilities.
-- Use line 1300 vs line 1900 or reconstructed liabilities.
SELECT
    group_id,
    report_year,
    report_date,
    SUM(CASE WHEN line_code = N'1300' THEN line_value ELSE 0 END) AS assets_1300,
    SUM(CASE WHEN line_code = N'1900' THEN line_value ELSE 0 END) AS liabilities_equity_1900,
    SUM(CASE WHEN line_code = N'1300' THEN line_value ELSE 0 END) -
    SUM(CASE WHEN line_code = N'1900' THEN line_value ELSE 0 END) AS diff
FROM dbo.ews_financials_group_long
GROUP BY group_id, report_year, report_date
HAVING ABS(
    SUM(CASE WHEN line_code = N'1300' THEN line_value ELSE 0 END) -
    SUM(CASE WHEN line_code = N'1900' THEN line_value ELSE 0 END)
) > 1;

-- 3. Duplicate source rows for the same key.
SELECT report_year, report_date, edrpou, report_form, line_code, COUNT(*) AS cnt
FROM dbo.ews_financials_raw_long
GROUP BY report_year, report_date, edrpou, report_form, line_code
HAVING COUNT(*) > 1;

-- 4. Critical missing fields for dashboard.
SELECT *
FROM dbo.ews_vw_group_financial_indicators
WHERE revenue IS NULL OR total_assets IS NULL OR equity IS NULL;