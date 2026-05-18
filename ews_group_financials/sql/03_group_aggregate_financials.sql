/*
03_group_aggregate_financials.sql
Purpose: aggregate company financial rows into group-level rows according to year-specific matching.

Mandatory TZ rules implemented here:
- match by matching_year + edrpou;
- aggregate only inclusion_flag = 1;
- numeric line codes 1000...2650 use SUM;
- EDRPOU is nvarchar, not numeric;
- source ClientProfile/Oracle objects remain read-only; only EWS staging tables are updated.
*/

DECLARE @ReportYear int = 2025;

-- Step 1. Assign group_id to raw financials using the exact matching-year.
UPDATE r
SET r.group_id = m.group_id
FROM dbo.ews_financials_raw_long r
JOIN dbo.ews_group_matching m
  ON m.edrpou = r.edrpou
 AND m.matching_year = r.report_year
 AND m.inclusion_flag = 1
WHERE r.report_year = @ReportYear;

-- Step 2. Rebuild group long data for the selected year only.
DELETE FROM dbo.ews_financials_group_long
WHERE report_year = @ReportYear;

INSERT INTO dbo.ews_financials_group_long (
    group_id,
    group_name,
    report_date,
    report_year,
    report_form,
    line_code,
    line_value,
    members_count,
    members_edrpou,
    aggregation_rule
)
SELECT
    m.group_id,
    MAX(m.group_name) AS group_name,
    r.report_date,
    r.report_year,
    r.report_form,
    r.line_code,
    SUM(COALESCE(r.line_value, 0)) AS line_value,
    COUNT(DISTINCT r.edrpou) AS members_count,
    STRING_AGG(CONVERT(nvarchar(max), r.edrpou), N'; ') WITHIN GROUP (ORDER BY r.edrpou) AS members_edrpou,
    N'SUM' AS aggregation_rule
FROM dbo.ews_financials_raw_long r
JOIN dbo.ews_group_matching m
  ON m.edrpou = r.edrpou
 AND m.matching_year = r.report_year
 AND m.inclusion_flag = 1
WHERE r.report_year = @ReportYear
  AND r.line_code IN (
      N'1000',N'1001',N'1002',N'1005',N'1010',N'1011',N'1012',N'1015',N'1020',N'1030',N'1035',N'1040',N'1045',N'1050',N'1060',N'1065',
      N'1090',N'1095',N'1100',N'1101',N'1102',N'1103',N'1104',N'1110',N'1115',N'1120',N'1125',N'1130',N'1135',N'1136',N'1140',N'1145',
      N'1155',N'1160',N'1165',N'1166',N'1167',N'1170',N'1180',N'1190',N'1195',N'1200',N'1300',N'1400',N'1405',N'1410',N'1415',N'1420',
      N'1425',N'1430',N'1435',N'1495',N'1500',N'1505',N'1510',N'1515',N'1520',N'1525',N'1530',N'1535',N'1540',N'1545',N'1595м',N'1595',
      N'1600',N'1605',N'1610',N'1615',N'1620',N'1621',N'1625',N'1630',N'1635',N'1640',N'1645',N'1650',N'1660',N'1665',N'1670',N'1690',
      N'1695',N'1700',N'1800',N'1900',N'2000',N'2010',N'2011',N'2012',N'2013',N'2014',N'2050',N'2070',N'2090',N'2095',N'2105',N'2110',
      N'2111',N'2112',N'2120',N'2121',N'2122',N'2130',N'2150',N'2160',N'2165',N'2180',N'2190',N'2195',N'2200',N'2220',N'2240',N'2250',
      N'2255',N'2270',N'2275',N'2280',N'2285',N'2290',N'2295',N'2300',N'2305',N'2310',N'2350',N'2355',N'2400',N'2405',N'2410',N'2415',
      N'2445',N'2450',N'2455',N'2460',N'2465',N'2500',N'2505',N'2510',N'2515',N'2520',N'2550',N'2600',N'2605',N'2610',N'2615',N'2650'
  )
GROUP BY
    m.group_id,
    r.report_date,
    r.report_year,
    r.report_form,
    r.line_code;

-- Step 3. Long-to-wide view. The view is dynamic in deployment so it always follows
-- data/field_codes_catalog.csv when that catalog is loaded into dbo.ews_field_codes_catalog.
DECLARE @cols nvarchar(max) = (
    SELECT STRING_AGG(
        N'SUM(CASE WHEN line_code = N''' + REPLACE(line_code, '''', '''''') + N''' THEN line_value ELSE 0 END) AS ' + QUOTENAME(line_code),
        N',' + CHAR(10) + N'    '
    ) WITHIN GROUP (ORDER BY line_code)
    FROM (
        SELECT DISTINCT line_code
        FROM dbo.ews_financials_group_long
        WHERE report_year = @ReportYear
    ) c
);

DECLARE @sql nvarchar(max) = N'
CREATE OR ALTER VIEW dbo.ews_vw_group_financials_wide AS
SELECT
    group_id AS [Ідентифікатор],
    report_date AS [Звітна дата],
    CAST(group_id AS nvarchar(20)) AS [Код ЄДРПОУ],
    report_form AS [Форма звітності],
    ' + @cols + N',
    CAST(NULL AS decimal(28,4)) AS [Середня чисельність працівників],
    CAST(NULL AS nvarchar(50)) AS [Клас КВЕД2010],
    CAST(NULL AS nvarchar(10)) AS [Секція КВЕД2010],
    N''EWS_ETL'' AS [Користувач],
    N''group-financials-1.0'' AS [Версія 0.10.005],
    MAX(calculated_at) AS [Дата та час збереження інформації]
FROM dbo.ews_financials_group_long
GROUP BY group_id, report_date, report_form;';

EXEC sys.sp_executesql @sql;
