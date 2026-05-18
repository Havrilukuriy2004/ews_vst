/*
04_metric_views.sql
Purpose: calculate EWS-ready indicators for company and group entities.

Rules:
- company indicators use dbo.ews_financials_raw_long;
- group indicators use dbo.ews_financials_group_long;
- formulas follow docs/TZ_Group_Financials_EWS.md and data/metric_mapping.csv.
*/

CREATE OR ALTER VIEW dbo.ews_vw_financial_core AS
SELECT
    'COMPANY' AS entity_type,
    edrpou AS entity_id,
    MAX(client_name) AS entity_name,
    report_year,
    report_date,
    SUM(CASE WHEN line_code = N'2000' THEN line_value ELSE 0 END) AS revenue,
    SUM(CASE WHEN line_code = N'2050' THEN line_value ELSE 0 END) AS cogs,
    SUM(CASE WHEN line_code = N'2090' THEN line_value ELSE 0 END) - SUM(CASE WHEN line_code = N'2095' THEN line_value ELSE 0 END) AS gross_profit,
    SUM(CASE WHEN line_code = N'2190' THEN line_value ELSE 0 END) - SUM(CASE WHEN line_code = N'2195' THEN line_value ELSE 0 END) AS ebit,
    SUM(CASE WHEN line_code = N'2515' THEN line_value ELSE 0 END) AS depreciation,
    SUM(CASE WHEN line_code = N'2250' THEN line_value ELSE 0 END) - SUM(CASE WHEN line_code = N'2220' THEN line_value ELSE 0 END) AS nie,
    SUM(CASE WHEN line_code = N'2350' THEN line_value ELSE 0 END) - SUM(CASE WHEN line_code = N'2355' THEN line_value ELSE 0 END) AS net_income,
    SUM(CASE WHEN line_code = N'1165' THEN line_value ELSE 0 END) AS cash,
    SUM(CASE WHEN line_code IN (N'1120', N'1125') THEN line_value ELSE 0 END) AS accounts_receivable,
    SUM(CASE WHEN line_code IN (N'1100', N'1110') THEN line_value ELSE 0 END) AS inventory,
    SUM(CASE WHEN line_code IN (N'1605', N'1615') THEN line_value ELSE 0 END) AS accounts_payable,
    SUM(CASE WHEN line_code = N'1195' THEN line_value ELSE 0 END) AS current_assets,
    SUM(CASE WHEN line_code = N'1300' THEN line_value ELSE 0 END) AS total_assets,
    SUM(CASE WHEN line_code = N'1695' THEN line_value ELSE 0 END) AS current_liabilities,
    SUM(CASE WHEN line_code IN (N'1510', N'1515', N'1600', N'1610') THEN line_value ELSE 0 END) AS total_interest_bearing_debt,
    SUM(CASE WHEN line_code = N'1495' THEN line_value ELSE 0 END) AS equity
FROM dbo.ews_financials_raw_long
GROUP BY edrpou, report_year, report_date
UNION ALL
SELECT
    'GROUP' AS entity_type,
    group_id AS entity_id,
    MAX(group_name) AS entity_name,
    report_year,
    report_date,
    SUM(CASE WHEN line_code = N'2000' THEN line_value ELSE 0 END) AS revenue,
    SUM(CASE WHEN line_code = N'2050' THEN line_value ELSE 0 END) AS cogs,
    SUM(CASE WHEN line_code = N'2090' THEN line_value ELSE 0 END) - SUM(CASE WHEN line_code = N'2095' THEN line_value ELSE 0 END) AS gross_profit,
    SUM(CASE WHEN line_code = N'2190' THEN line_value ELSE 0 END) - SUM(CASE WHEN line_code = N'2195' THEN line_value ELSE 0 END) AS ebit,
    SUM(CASE WHEN line_code = N'2515' THEN line_value ELSE 0 END) AS depreciation,
    SUM(CASE WHEN line_code = N'2250' THEN line_value ELSE 0 END) - SUM(CASE WHEN line_code = N'2220' THEN line_value ELSE 0 END) AS nie,
    SUM(CASE WHEN line_code = N'2350' THEN line_value ELSE 0 END) - SUM(CASE WHEN line_code = N'2355' THEN line_value ELSE 0 END) AS net_income,
    SUM(CASE WHEN line_code = N'1165' THEN line_value ELSE 0 END) AS cash,
    SUM(CASE WHEN line_code IN (N'1120', N'1125') THEN line_value ELSE 0 END) AS accounts_receivable,
    SUM(CASE WHEN line_code IN (N'1100', N'1110') THEN line_value ELSE 0 END) AS inventory,
    SUM(CASE WHEN line_code IN (N'1605', N'1615') THEN line_value ELSE 0 END) AS accounts_payable,
    SUM(CASE WHEN line_code = N'1195' THEN line_value ELSE 0 END) AS current_assets,
    SUM(CASE WHEN line_code = N'1300' THEN line_value ELSE 0 END) AS total_assets,
    SUM(CASE WHEN line_code = N'1695' THEN line_value ELSE 0 END) AS current_liabilities,
    SUM(CASE WHEN line_code IN (N'1510', N'1515', N'1600', N'1610') THEN line_value ELSE 0 END) AS total_interest_bearing_debt,
    SUM(CASE WHEN line_code = N'1495' THEN line_value ELSE 0 END) AS equity
FROM dbo.ews_financials_group_long
GROUP BY group_id, report_year, report_date;

CREATE OR ALTER VIEW dbo.ews_vw_financial_indicators AS
WITH indicators AS (
    SELECT
        c.*,
        c.ebit + c.depreciation AS ebitda,
        CASE WHEN c.revenue = 0 THEN NULL ELSE (c.ebit + c.depreciation) / c.revenue END AS ebitda_margin,
        c.total_interest_bearing_debt - c.cash AS net_debt,
        CASE WHEN c.total_assets = 0 THEN NULL ELSE c.equity / c.total_assets END AS equity_ratio,
        CASE WHEN c.current_liabilities = 0 THEN NULL ELSE c.current_assets / c.current_liabilities END AS current_ratio,
        CASE WHEN (c.ebit + c.depreciation) <= 0 THEN NULL ELSE (c.total_interest_bearing_debt - c.cash) / (c.ebit + c.depreciation) END AS net_debt_to_ebitda,
        CASE WHEN ABS(c.nie) < 1 THEN NULL ELSE (c.ebit + c.depreciation) / ABS(c.nie) END AS icrm,
        CASE WHEN c.revenue = 0 THEN NULL ELSE c.accounts_receivable / c.revenue * 365 END AS dso_days,
        CASE WHEN ABS(c.cogs - c.depreciation) < 1 THEN NULL ELSE c.inventory / ABS(c.cogs - c.depreciation) * 365 END AS dio_days,
        CASE WHEN ABS(c.cogs - c.depreciation) < 1 THEN NULL ELSE c.accounts_payable / ABS(c.cogs - c.depreciation) * 365 END AS dpo_days
    FROM dbo.ews_vw_financial_core c
)
SELECT
    i.*,
    CASE WHEN prev.revenue IS NULL OR prev.revenue = 0 THEN NULL ELSE i.revenue / prev.revenue - 1 END AS revenue_growth_pct,
    CASE WHEN i.dso_days IS NULL OR i.dio_days IS NULL OR i.dpo_days IS NULL THEN NULL ELSE i.dso_days + i.dio_days - i.dpo_days END AS financial_cycle_days,
    CASE WHEN i.dso_days IS NULL OR i.dio_days IS NULL OR i.dpo_days IS NULL THEN NULL ELSE ABS(i.cogs) * (i.dso_days + i.dio_days - i.dpo_days) / 365 END AS avg_capital_need
FROM indicators i
OUTER APPLY (
    SELECT TOP 1 p.revenue
    FROM indicators p
    WHERE p.entity_type = i.entity_type
      AND p.entity_id = i.entity_id
      AND p.report_date < i.report_date
    ORDER BY p.report_date DESC
) prev;

CREATE OR ALTER VIEW dbo.ews_vw_group_financial_indicators AS
SELECT *
FROM dbo.ews_vw_financial_indicators
WHERE entity_type = N'GROUP';
