Option Explicit

' ProcessReports_GroupAggregation.bas
' Purpose:
' 1) Fetch financial statements for two or more EDRPOU from ClientProfile.
' 2) Save company-level wide financials.
' 3) Build group-level aggregation using year-specific matching.
'
' This macro is a skeleton and must be adjusted to exact sheet names and range names.

Const adInteger = 3
Const adVarWChar = 202
Const adParamInput = 1
Const adCmdStoredProc = 4
Const adStateOpen = 1
Const adUseClient = 3
Const adOpenStatic = 3
Const adLockReadOnly = 1

Sub ProcessReports_GroupFinancials()

    Dim cn As Object, cmd As Object, rs As Object
    Dim connString As String
    Dim DB_SERVER As String, DB_NAME As String
    Dim reportForm As Long, reportYear As Long, reportQuarter As Long
    Dim edrpouList As String

    DB_SERVER = "clientprofile-db-sqls.bank.lan"
    DB_NAME = "ClientProfile"

    connString = "Provider=SQLOLEDB;" & _
                 "Data Source=" & DB_SERVER & ";" & _
                 "Initial Catalog=" & DB_NAME & ";" & _
                 "Integrated Security=SSPI;"

    reportYear = CLng(ThisWorkbook.Worksheets("01_Group_Matching").Range("B2").Value)
    reportQuarter = 4
    edrpouList = BuildEdrpouList(reportYear)

    Set cn = CreateObject("ADODB.Connection")
    cn.Open connString

    ' Form 1: Balance
    reportForm = 1
    Set rs = FetchReportForm(cn, reportForm, reportYear, reportQuarter, edrpouList)
    WriteRecordsetToSheet rs, "RAW_Form1"

    ' Form 2: P&L
    reportForm = 2
    Set rs = FetchReportForm(cn, reportForm, reportYear, reportQuarter, edrpouList)
    WriteRecordsetToSheet rs, "RAW_Form2"

    ' Optional Form 3 direct/undirect if available
    ' reportForm = 3
    ' Set rs = FetchReportForm(cn, reportForm, reportYear, reportQuarter, edrpouList)

    cn.Close
    Set cn = Nothing

    Call BuildWideFinancials
    Call BuildGroupAggregation
    Call BuildFinancialIndicators

    MsgBox "Group financials have been updated.", vbInformation

End Sub

Function FetchReportForm(cn As Object, reportForm As Long, reportYear As Long, reportQuarter As Long, edrpouList As String) As Object

    Dim cmd As Object
    Set cmd = CreateObject("ADODB.Command")
    Set cmd.ActiveConnection = cn
    cmd.CommandType = adCmdStoredProc
    cmd.CommandText = "[finrep].[getReportFormInfo]"
    cmd.Parameters.Append cmd.CreateParameter("@reportForm", adInteger, adParamInput, , reportForm)
    cmd.Parameters.Append cmd.CreateParameter("@year", adInteger, adParamInput, , reportYear)
    cmd.Parameters.Append cmd.CreateParameter("@qr", adInteger, adParamInput, , reportQuarter)
    cmd.Parameters.Append cmd.CreateParameter("@edrpou", adVarWChar, adParamInput, Len(edrpouList), edrpouList)

    Set FetchReportForm = cmd.Execute

End Function

Function BuildEdrpouList(reportYear As Long) As String
    Dim ws As Worksheet
    Dim lastRow As Long, i As Long
    Dim tmp As String

    Set ws = ThisWorkbook.Worksheets("01_Group_Matching")
    lastRow = ws.Cells(ws.Rows.Count, "D").End(xlUp).Row

    For i = 2 To lastRow
        If CLng(ws.Cells(i, "B").Value) = reportYear And ws.Cells(i, "F").Value = 1 Then
            If Len(tmp) > 0 Then tmp = tmp & ","
            tmp = tmp & CStr(ws.Cells(i, "D").Value)
        End If
    Next i

    BuildEdrpouList = tmp
End Function

Sub WriteRecordsetToSheet(rs As Object, sheetName As String)
    Dim ws As Worksheet, i As Long

    On Error Resume Next
    Set ws = ThisWorkbook.Worksheets(sheetName)
    On Error GoTo 0

    If ws Is Nothing Then
        Set ws = ThisWorkbook.Worksheets.Add
        ws.Name = sheetName
    End If

    ws.Cells.Clear

    For i = 0 To rs.Fields.Count - 1
        ws.Cells(1, i + 1).Value = rs.Fields(i).Name
        ws.Cells(1, i + 1).Font.Bold = True
    Next i

    ws.Range("A2").CopyFromRecordset rs
    ws.Columns.AutoFit
End Sub

Sub BuildWideFinancials()
    ' Implement mapping from raw ClientProfile fields to the canonical wide structure:
    ' Ідентифікатор | Звітна дата | Код ЄДРПОУ | Форма звітності | 1000 | ... | 2650 | metadata
    ' This step can be formula-based or PowerQuery-based.
End Sub

Sub BuildGroupAggregation()
    ' Implement SUMIFS by:
    ' - Ідентифікатор / group_id
    ' - Звітна дата
    ' - Форма звітності
    ' - matching_year
End Sub

Sub BuildFinancialIndicators()
    ' Calculate Revenue, EBITDA, ICRm, Net Debt/EBITDA, Financial Cycle etc.
End Sub