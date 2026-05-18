/*
01_create_staging_tables.sql
Purpose: staging layer for group financial statements and EWS dashboard.

Important:
- EDRPOU is VARCHAR, never numeric.
- Financial reporting line codes are stored in long format for ETL, and can be pivoted to wide.
- Matching is year-specific.
*/

-- SQL Server syntax

CREATE TABLE dbo.ews_group_matching (
    matching_id        bigint IDENTITY(1,1) PRIMARY KEY,
    group_id           nvarchar(100) NOT NULL,
    group_name         nvarchar(500) NULL,
    matching_year      int NOT NULL,
    report_date_from   date NULL,
    report_date_to     date NULL,
    edrpou             nvarchar(20) NOT NULL,
    client_code        nvarchar(50) NULL,
    client_name        nvarchar(500) NULL,
    inclusion_flag     bit NOT NULL DEFAULT 1,
    consolidation_method nvarchar(50) NOT NULL DEFAULT 'SUM',
    ownership_share_pct decimal(9,4) NULL,
    is_main_company    bit NOT NULL DEFAULT 0,
    comment            nvarchar(max) NULL,
    created_at         datetime2 NOT NULL DEFAULT sysdatetime()
);

CREATE TABLE dbo.ews_financials_raw_long (
    load_id            bigint IDENTITY(1,1) PRIMARY KEY,
    source_system      nvarchar(100) NOT NULL DEFAULT 'ClientProfile',
    group_id           nvarchar(100) NULL,
    report_date        date NOT NULL,
    report_year        int NOT NULL,
    edrpou             nvarchar(20) NOT NULL,
    client_name        nvarchar(500) NULL,
    report_form        nvarchar(50) NOT NULL,
    line_code          nvarchar(50) NOT NULL,
    line_value         decimal(28,4) NULL,
    source_report_form nvarchar(100) NULL,
    source_table       nvarchar(200) NULL,
    source_user        nvarchar(200) NULL,
    source_version     nvarchar(50) NULL,
    source_saved_at    datetime2 NULL,
    loaded_at          datetime2 NOT NULL DEFAULT sysdatetime()
);

CREATE INDEX ix_ews_financials_raw_long_key
ON dbo.ews_financials_raw_long (report_year, report_date, edrpou, report_form, line_code);

CREATE TABLE dbo.ews_financials_group_long (
    group_load_id      bigint IDENTITY(1,1) PRIMARY KEY,
    group_id           nvarchar(100) NOT NULL,
    group_name         nvarchar(500) NULL,
    report_date        date NOT NULL,
    report_year        int NOT NULL,
    report_form        nvarchar(50) NOT NULL,
    line_code          nvarchar(50) NOT NULL,
    line_value         decimal(28,4) NULL,
    members_count      int NOT NULL,
    members_edrpou     nvarchar(max) NULL,
    aggregation_rule   nvarchar(50) NOT NULL DEFAULT 'SUM',
    calculated_at      datetime2 NOT NULL DEFAULT sysdatetime()
);

CREATE INDEX ix_ews_financials_group_long_key
ON dbo.ews_financials_group_long (group_id, report_year, report_date, report_form, line_code);

CREATE TABLE dbo.ews_financial_metric_map (
    metric_code        nvarchar(100) PRIMARY KEY,
    metric_name        nvarchar(500) NOT NULL,
    metric_domain      nvarchar(100) NOT NULL,
    formula_logic      nvarchar(max) NOT NULL,
    numerator_logic    nvarchar(max) NULL,
    denominator_logic  nvarchar(max) NULL,
    is_dashboard_metric bit NOT NULL DEFAULT 0,
    sort_order         int NULL
);

CREATE TABLE dbo.ews_group_financial_indicators (
    indicator_id       bigint IDENTITY(1,1) PRIMARY KEY,
    entity_type        nvarchar(20) NOT NULL, -- COMPANY / GROUP
    entity_id          nvarchar(100) NOT NULL, -- EDRPOU or group_id
    entity_name        nvarchar(500) NULL,
    report_year        int NOT NULL,
    report_date        date NOT NULL,
    revenue            decimal(28,4) NULL,
    revenue_growth_pct decimal(18,8) NULL,
    gross_profit       decimal(28,4) NULL,
    ebit               decimal(28,4) NULL,
    ebitda             decimal(28,4) NULL,
    nie                decimal(28,4) NULL,
    depreciation       decimal(28,4) NULL,
    net_income         decimal(28,4) NULL,
    cash               decimal(28,4) NULL,
    accounts_receivable decimal(28,4) NULL,
    inventory          decimal(28,4) NULL,
    accounts_payable   decimal(28,4) NULL,
    current_assets     decimal(28,4) NULL,
    total_assets       decimal(28,4) NULL,
    current_liabilities decimal(28,4) NULL,
    total_interest_bearing_debt decimal(28,4) NULL,
    equity             decimal(28,4) NULL,
    equity_ratio       decimal(18,8) NULL,
    current_ratio      decimal(18,8) NULL,
    net_debt_to_ebitda decimal(18,8) NULL,
    icrm               decimal(18,8) NULL,
    dso_days           decimal(18,4) NULL,
    dio_days           decimal(18,4) NULL,
    dpo_days           decimal(18,4) NULL,
    financial_cycle_days decimal(18,4) NULL,
    avg_capital_need   decimal(28,4) NULL,
    calculated_at      datetime2 NOT NULL DEFAULT sysdatetime()
);