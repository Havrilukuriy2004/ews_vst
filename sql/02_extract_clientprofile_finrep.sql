/*
02_extract_clientprofile_finrep.sql
Purpose: extract financial statements from ClientProfile.finrep using logic found in ClientProfile.xlsm.

Source logic:
EXEC [finrep].[getReportFormInfo] @reportForm, @year, @qr, @edrpou
EXEC [finrep].[getReportFormInfoSQL] @reportForm, @tSQL

Relevant ClientProfile forms:
- finrep.reportForm1
- finrep.reportForm1m2m
- finrep.reportForm1ms2ms
- finrep.reportForm2
- finrep.reportForm3Direct
- finrep.reportForm3Undirect
- finrep.v_CollectReport
- finrep.v_CollectReport_3_33
*/

-- Parameterized example: extract by year, quarter, and EDRPOU list.
DECLARE @reportForm int = 1;
DECLARE @year int = 2025;
DECLARE @qr int = 4;
DECLARE @edrpou nvarchar(max) = N'EDRPOU_1,EDRPOU_2';

EXEC [finrep].[getReportFormInfo]
    @reportForm = @reportForm,
    @year       = @year,
    @qr         = @qr,
    @edrpou     = @edrpou;

-- Alternative SQL filter mode:
DECLARE @tSQL nvarchar(max) =
N'[year] = 2025 AND [Month] IN (12) AND [Edrpou] IN (EDRPOU_1,EDRPOU_2)';

EXEC [finrep].[getReportFormInfoSQL]
    @reportForm = 1,
    @tSQL       = @tSQL;

-- Catalog probes for schema discovery:
SELECT TOP 1 * FROM finrep.reportForm1;
SELECT TOP 1 * FROM finrep.reportForm1m2m;
SELECT TOP 1 * FROM finrep.reportForm1ms2ms;
SELECT TOP 1 * FROM finrep.reportForm2;
SELECT TOP 1 * FROM finrep.reportForm3Direct;
SELECT TOP 1 * FROM finrep.reportForm3Undirect;
SELECT TOP 1 * FROM finrep.v_CollectReport;
SELECT TOP 1 * FROM finrep.v_CollectReport_3_33;