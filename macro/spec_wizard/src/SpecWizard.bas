Attribute VB_Name = "SpecWizard"
'==============================================================================
' マクロ開発 仕様書ウィザード
'
' 質問に順番に答えていくと、マクロ開発の仕様書（Excel シート / Markdown / PDF）が
' できあがる。
'
' 使い方:
'   1. このモジュールを .xlsm ブックにインポートする
'   2. マクロ「SpecWizard_Start」を実行する（初回はシートが自動で作られる）
'   3. 「ウィザード」シートの黄色いセルに入力し、「次へ」で進む
'   4. 「仕様書を作成」で「仕様書」シートを作る。Markdown / PDF にも書き出せる
'
' シート:
'   ウィザード … 入力画面（ボタンで操作する）
'   設問       … 質問の一覧。行を足したり書き換えたりすると質問を変えられる
'   仕様書     … 作成した仕様書
'   回答       … 回答の保存先（非表示）
'
' そのほかのマクロ:
'   SpecWizard_ClearAnswers           回答をすべて消す
'   SpecWizard_RestoreDefaultQuestions 設問を既定の内容に戻す
'   SpecWizard_RebuildScreen          ウィザード画面を作り直す（回答は残る）
'==============================================================================
Option Explicit

Private Const SH_WIZ As String = "ウィザード"
Private Const SH_Q As String = "設問"
Private Const SH_ANS As String = "回答"
Private Const SH_SPEC As String = "仕様書"

' 設問シートの列
Private Const QC_STEP As Long = 1
Private Const QC_STEPNAME As Long = 2
Private Const QC_ID As Long = 3
Private Const QC_LABEL As Long = 4
Private Const QC_TYPE As Long = 5
Private Const QC_CHOICES As Long = 6
Private Const QC_REQ As Long = 7
Private Const QC_HINT As Long = 8

' ウィザードシートのレイアウト
Private Const WZ_FIRST_ROW As Long = 6
Private Const WZ_COL_ID As Long = 1
Private Const WZ_COL_LABEL As Long = 2
Private Const WZ_COL_INPUT As Long = 3
Private Const WZ_COL_REQ As Long = 4
Private Const WZ_COL_HINT As Long = 5
Private Const WZ_COL_STEP As Long = 7
Private Const WZ_COL_STATUS As Long = 8
Private Const WZ_CLEAR_ROWS As Long = 200
Private Const WZ_MULTI_HEIGHT As Double = 64

' 回答シート: A=項目ID, B=回答, C=更新日時。現在のステップは F1 に持つ
Private Const ANS_CUR_STEP As String = "F1"

' 入力形式
Private Const T_LINE As String = "1行"
Private Const T_MULTI As String = "複数行"
Private Const T_CHOICE As String = "選択"
Private Const T_DATE As String = "日付"

' 仕様書の表題に使う項目
Private Const ID_TITLE As String = "Q0101"

' 既定の設問を書き込むときの作業用
Private mQSheet As Worksheet
Private mQRow As Long
Private mStepNo As Long
Private mStepName As String

'==============================================================================
' ボタン・マクロ一覧から呼ぶ処理
'==============================================================================

' ウィザードを開く（初回はシートを作る）
Public Sub SpecWizard_Start()
    If Not PrepareSheets() Then Exit Sub
    ' ボタンを押さずに保存・終了した入力も拾う
    SaveCurrentStep
    ShowStep CurrentStep()
End Sub

Public Sub SpecWizard_Next()
    Dim cur As Long
    If Not PrepareSheets() Then Exit Sub
    SaveCurrentStep
    cur = CurrentStep()
    If cur >= StepCount() Then
        If MsgBox("最後のステップです。仕様書を作成しますか？", vbYesNo + vbQuestion) = vbYes Then
            SpecWizard_Generate
        End If
        Exit Sub
    End If
    ShowStep cur + 1
End Sub

Public Sub SpecWizard_Prev()
    Dim cur As Long
    If Not PrepareSheets() Then Exit Sub
    SaveCurrentStep
    cur = CurrentStep()
    If cur > 1 Then ShowStep cur - 1
End Sub

Public Sub SpecWizard_Jump()
    Dim n As Long, s As Long, msg As String, v As Variant
    If Not PrepareSheets() Then Exit Sub
    SaveCurrentStep
    n = StepCount()
    msg = "移動するステップの番号を入力してください。" & vbLf & vbLf
    For s = 1 To n
        msg = msg & s & ". " & StepName(s) & "（" & StepStatus(s) & "）" & vbLf
    Next s
    v = Application.InputBox(msg, "ステップ移動", CurrentStep(), Type:=1)
    If VarType(v) = vbBoolean Then Exit Sub
    ShowStep CLng(v)
End Sub

' 必須項目の未入力を一覧で表示する
Public Sub SpecWizard_Check()
    Dim missing As Collection, msg As String, i As Long, qr As Long
    Dim qs As Worksheet
    If Not PrepareSheets() Then Exit Sub
    SaveCurrentStep
    UpdateProgress
    Set qs = GetSheet(SH_Q)
    Set missing = MissingRequiredRows()
    If missing.Count = 0 Then
        MsgBox "必須項目はすべて入力済みです。「仕様書を作成」で仕様書を作れます。", vbInformation
        Exit Sub
    End If
    msg = "必須項目のうち " & missing.Count & " 件が未入力です。" & vbLf & vbLf
    For i = 1 To missing.Count
        If i > 15 Then
            msg = msg & "ほか " & (missing.Count - 15) & " 件" & vbLf
            Exit For
        End If
        qr = missing(i)
        msg = msg & "ステップ " & qs.Cells(qr, QC_STEP).Value & "：" & qs.Cells(qr, QC_LABEL).Value & vbLf
    Next i
    msg = msg & vbLf & "最初の未入力のステップへ移動しますか？"
    If MsgBox(msg, vbYesNo + vbExclamation, "入力チェック") = vbYes Then
        ShowStep CLng(qs.Cells(missing(1), QC_STEP).Value)
    End If
End Sub

' 「仕様書」シートを作る
Public Sub SpecWizard_Generate()
    If Not PrepareSheets() Then Exit Sub
    SaveCurrentStep
    If Not ConfirmMissing() Then Exit Sub
    BuildSpecSheet
    MsgBox "「" & SH_SPEC & "」シートを作成しました。" & vbLf & _
           "回答を直したら、もう一度「仕様書を作成」を押すと作り直されます。", vbInformation
End Sub

Public Sub SpecWizard_ExportMarkdown()
    Dim path As Variant
    If Not PrepareSheets() Then Exit Sub
    SaveCurrentStep
    If Not ConfirmMissing() Then Exit Sub
    path = Application.GetSaveAsFilename(InitialFileName:=DefaultFileName("md"), _
                                         FileFilter:="Markdown (*.md),*.md")
    If VarType(path) = vbBoolean Then Exit Sub
    If WriteUtf8(CStr(path), BuildMarkdown()) Then
        MsgBox "Markdown を出力しました。" & vbLf & path, vbInformation
    End If
End Sub

Public Sub SpecWizard_ExportPdf()
    Dim path As Variant, ws As Worksheet
    If Not PrepareSheets() Then Exit Sub
    SaveCurrentStep
    If Not ConfirmMissing() Then Exit Sub
    path = Application.GetSaveAsFilename(InitialFileName:=DefaultFileName("pdf"), _
                                         FileFilter:="PDF (*.pdf),*.pdf")
    If VarType(path) = vbBoolean Then Exit Sub
    Set ws = BuildSpecSheet()
    On Error GoTo Failed
    ws.ExportAsFixedFormat Type:=xlTypePDF, Filename:=CStr(path), _
        Quality:=xlQualityStandard, IncludeDocProperties:=True, _
        IgnorePrintAreas:=False, OpenAfterPublish:=True
    Exit Sub
Failed:
    MsgBox "PDF を出力できませんでした。" & vbLf & Err.Description, vbExclamation
End Sub

Public Sub SpecWizard_ClearAnswers()
    Dim ws As Worksheet, last As Long
    If Not PrepareSheets() Then Exit Sub
    If MsgBox("入力した回答をすべて消去します。よろしいですか？" & vbLf & _
              "（元に戻せません）", vbYesNo + vbExclamation + vbDefaultButton2) = vbNo Then Exit Sub
    Set ws = GetSheet(SH_ANS)
    last = LastRow(ws, 1)
    If last >= 2 Then ws.Range(ws.Cells(2, 1), ws.Cells(last, 3)).Clear
    SetCurrentStep 1
    ShowStep 1
End Sub

Public Sub SpecWizard_RestoreDefaultQuestions()
    If MsgBox("「" & SH_Q & "」シートを既定の内容に戻します。" & vbLf & _
              "設問を書き換えていた場合、その変更は失われます（回答は残ります）。" & vbLf & _
              "よろしいですか？", vbYesNo + vbExclamation + vbDefaultButton2) = vbNo Then Exit Sub
    If Not PrepareSheets() Then Exit Sub
    SaveCurrentStep
    WriteDefaultQuestions GetSheet(SH_Q)
    ShowStep 1
End Sub

Public Sub SpecWizard_RebuildScreen()
    Dim ws As Worksheet
    If Not PrepareSheets() Then Exit Sub
    SaveCurrentStep
    Set ws = GetSheet(SH_WIZ)
    Application.DisplayAlerts = False
    ws.Delete
    Application.DisplayAlerts = True
    SpecWizard_Start
End Sub

'==============================================================================
' シートの準備
'==============================================================================

' 必要なシートがなければ作る。作れなければ False
Private Function PrepareSheets() As Boolean
    Dim ws As Worksheet
    On Error GoTo Failed
    If GetSheet(SH_Q) Is Nothing Then
        Set ws = ThisWorkbook.Worksheets.Add(After:=ThisWorkbook.Worksheets(ThisWorkbook.Worksheets.Count))
        ws.Name = SH_Q
        WriteDefaultQuestions ws
    End If
    If GetSheet(SH_ANS) Is Nothing Then
        Set ws = ThisWorkbook.Worksheets.Add(After:=ThisWorkbook.Worksheets(ThisWorkbook.Worksheets.Count))
        ws.Name = SH_ANS
        ws.Range("A1:C1").Value = Array("項目ID", "回答", "更新日時")
        ws.Range("E1").Value = "現在のステップ"
        ws.Range(ANS_CUR_STEP).Value = 1
        ws.Columns(2).ColumnWidth = 60
        ws.Columns(3).ColumnWidth = 18
        ws.Columns(3).NumberFormat = "yyyy/mm/dd hh:mm"
        ws.Visible = xlSheetHidden
    End If
    If GetSheet(SH_WIZ) Is Nothing Then
        Set ws = ThisWorkbook.Worksheets.Add(Before:=ThisWorkbook.Worksheets(1))
        ws.Name = SH_WIZ
        BuildWizardFrame ws
    End If
    If StepCount() = 0 Then
        MsgBox "「" & SH_Q & "」シートに設問がありません。" & vbLf & _
               "マクロ SpecWizard_RestoreDefaultQuestions で既定の設問に戻せます。", vbExclamation
        Exit Function
    End If
    PrepareSheets = True
    Exit Function
Failed:
    Application.ScreenUpdating = True
    MsgBox "シートを準備できませんでした。ブックが保護されている場合は解除してから実行してください。" & vbLf & _
           Err.Description, vbExclamation
End Function

' ウィザード画面の枠（見出し・ボタン・列幅）を作る
Private Sub BuildWizardFrame(ByVal ws As Worksheet)
    Dim x As Double, y As Double, h As Double

    ws.Cells.Font.Size = 10
    ws.Columns(WZ_COL_ID).Hidden = True
    ws.Columns(WZ_COL_LABEL).ColumnWidth = 28
    ws.Columns(WZ_COL_INPUT).ColumnWidth = 62
    ws.Columns(WZ_COL_REQ).ColumnWidth = 6
    ws.Columns(WZ_COL_HINT).ColumnWidth = 44
    ws.Columns(6).ColumnWidth = 2
    ws.Columns(WZ_COL_STEP).ColumnWidth = 24
    ws.Columns(WZ_COL_STATUS).ColumnWidth = 11

    With ws.Cells(1, WZ_COL_LABEL)
        .Value = "マクロ開発 仕様書ウィザード"
        .Font.Size = 16
        .Font.Bold = True
    End With
    With ws.Cells(2, WZ_COL_LABEL)
        .Font.Size = 13
        .Font.Bold = True
        .Font.Color = RGB(31, 78, 121)
    End With
    ws.Cells(2, WZ_COL_HINT).Font.Color = RGB(89, 89, 89)
    ws.Rows(3).RowHeight = 32
    With ws.Cells(4, WZ_COL_LABEL)
        .Value = "黄色いセルに入力してください。セル内の改行は Alt+Enter。" & _
                 "入力内容はボタンを押したときに保存されます。"
        .Font.Size = 9
        .Font.Color = RGB(89, 89, 89)
    End With

    With ws.Range(ws.Cells(5, WZ_COL_LABEL), ws.Cells(5, WZ_COL_HINT))
        .Value = Array("項目", "入力欄", "必須", "入力例・ヒント")
        .Font.Bold = True
        .Interior.Color = RGB(217, 225, 242)
    End With
    With ws.Range(ws.Cells(5, WZ_COL_STEP), ws.Cells(5, WZ_COL_STATUS))
        .Value = Array("ステップ一覧", "状態")
        .Font.Bold = True
        .Interior.Color = RGB(217, 225, 242)
    End With

    y = ws.Rows(3).Top + 3
    h = 26
    x = ws.Columns(WZ_COL_LABEL).Left
    x = x + AddButton(ws, "← 戻る", "SpecWizard_Prev", x, y, 72, h, RGB(47, 84, 150)) + 4
    x = x + AddButton(ws, "次へ →", "SpecWizard_Next", x, y, 72, h, RGB(47, 84, 150)) + 16
    x = x + AddButton(ws, "ステップ移動", "SpecWizard_Jump", x, y, 84, h, RGB(118, 118, 118)) + 4
    x = x + AddButton(ws, "入力チェック", "SpecWizard_Check", x, y, 84, h, RGB(118, 118, 118)) + 16
    x = x + AddButton(ws, "仕様書を作成", "SpecWizard_Generate", x, y, 92, h, RGB(56, 118, 29)) + 4
    x = x + AddButton(ws, "Markdown 出力", "SpecWizard_ExportMarkdown", x, y, 96, h, RGB(56, 118, 29)) + 4
    x = x + AddButton(ws, "PDF 出力", "SpecWizard_ExportPdf", x, y, 72, h, RGB(56, 118, 29))

    On Error Resume Next
    ws.Activate
    ActiveWindow.DisplayGridlines = False
    ActiveWindow.FreezePanes = False
    ActiveWindow.SplitColumn = 0
    ActiveWindow.SplitRow = WZ_FIRST_ROW - 1
    ActiveWindow.FreezePanes = True
    On Error GoTo 0

    ProtectWizard ws
End Sub

' 入力欄以外を保護する（パスワードなし）。行の高さ・列幅は変えられるようにする
Private Sub ProtectWizard(ByVal ws As Worksheet)
    On Error Resume Next
    ws.Protect DrawingObjects:=True, Contents:=True, AllowFormattingRows:=True, AllowFormattingColumns:=True
    If Err.Number <> 0 Then
        Err.Clear
        ws.Protect
    End If
    On Error GoTo 0
End Sub

' 角丸のボタンを置いて、幅を返す。図形が使えない環境ではフォームのボタンにする
Private Function AddButton(ByVal ws As Worksheet, ByVal caption As String, ByVal macroName As String, _
                           ByVal x As Double, ByVal y As Double, ByVal w As Double, ByVal h As Double, _
                           ByVal fillColor As Long) As Double
    Dim shp As Shape, btn As Object
    AddButton = w
    On Error GoTo Failed
    Set shp = ws.Shapes.AddShape(msoShapeRoundedRectangle, x, y, w, h)
    shp.Name = "btn_" & macroName
    shp.OnAction = macroName
    shp.Placement = xlFreeFloating
    shp.Fill.ForeColor.RGB = fillColor
    shp.Line.Visible = msoFalse
    With shp.TextFrame
        .Characters.Text = caption
        .Characters.Font.Size = 10
        .Characters.Font.Bold = True
        .Characters.Font.Color = RGB(255, 255, 255)
        .HorizontalAlignment = xlHAlignCenter
        .VerticalAlignment = xlVAlignCenter
    End With
    Exit Function
Failed:
    Resume UseFormButton
UseFormButton:
    On Error Resume Next
    If Not shp Is Nothing Then shp.Delete
    Set btn = ws.Buttons.Add(x, y, w, h)
    btn.Caption = caption
    btn.OnAction = macroName
    btn.Name = "btn_" & macroName
End Function

'==============================================================================
' ステップの表示と保存
'==============================================================================

Private Sub ShowStep(ByVal stepNo As Long)
    Dim wz As Worksheet, qs As Worksheet, qRows As Collection
    Dim n As Long, i As Long, qr As Long, r As Long
    Dim id As String, qType As String, choices As String

    n = StepCount()
    If stepNo < 1 Then stepNo = 1
    If stepNo > n Then stepNo = n
    Set wz = GetSheet(SH_WIZ)
    Set qs = GetSheet(SH_Q)

    Application.ScreenUpdating = False
    wz.Unprotect
    With wz.Range(wz.Cells(WZ_FIRST_ROW, 1), wz.Cells(WZ_FIRST_ROW + WZ_CLEAR_ROWS, WZ_COL_STATUS))
        .Validation.Delete
        .Clear
        .RowHeight = 18
    End With

    wz.Cells(2, WZ_COL_LABEL).Value = "ステップ " & stepNo & " / " & n & "：" & StepName(stepNo)

    Set qRows = StepRows(stepNo)
    r = WZ_FIRST_ROW
    For i = 1 To qRows.Count
        qr = qRows(i)
        id = CStr(qs.Cells(qr, QC_ID).Value)
        qType = QuestionType(qr)
        choices = Trim$(CStr(qs.Cells(qr, QC_CHOICES).Value))

        wz.Cells(r, WZ_COL_ID).Value = id
        With wz.Cells(r, WZ_COL_LABEL)
            .Value = stepNo & "." & i & " " & qs.Cells(qr, QC_LABEL).Value
            .Font.Bold = True
            .WrapText = True
            .VerticalAlignment = xlTop
        End With
        With wz.Cells(r, WZ_COL_REQ)
            If IsRequired(qr) Then .Value = "必須"
            .Font.Color = RGB(192, 0, 0)
            .Font.Bold = True
            .HorizontalAlignment = xlCenter
            .VerticalAlignment = xlTop
        End With
        With wz.Cells(r, WZ_COL_HINT)
            WriteCellValue wz.Cells(r, WZ_COL_HINT), CStr(qs.Cells(qr, QC_HINT).Value)
            .Font.Size = 9
            .Font.Color = RGB(89, 89, 89)
            .WrapText = True
            .VerticalAlignment = xlTop
        End With
        With wz.Cells(r, WZ_COL_INPUT)
            .Locked = False
            .WrapText = True
            .VerticalAlignment = xlTop
            .Interior.Color = RGB(255, 255, 204)
            .Borders.LineStyle = xlContinuous
            .Borders.Color = RGB(191, 191, 191)
            Select Case qType
            Case T_DATE
                .NumberFormat = "yyyy/mm/dd"
            Case T_MULTI
                .NumberFormat = "General"
            Case Else
                ' 「10/20」などが日付に化けないよう文字列にする
                .NumberFormat = "@"
            End Select
            If qType = T_CHOICE And Len(choices) > 0 Then
                .Validation.Add Type:=xlValidateList, AlertStyle:=xlValidAlertInformation, Formula1:=choices
                .Validation.IgnoreBlank = True
                .Validation.InCellDropdown = True
                .Validation.ShowError = False
            End If
        End With
        WriteCellValue wz.Cells(r, WZ_COL_INPUT), GetAnswer(id)

        wz.Rows(r).AutoFit
        If qType = T_MULTI And wz.Rows(r).RowHeight < WZ_MULTI_HEIGHT Then wz.Rows(r).RowHeight = WZ_MULTI_HEIGHT
        If wz.Rows(r).RowHeight < 20 Then wz.Rows(r).RowHeight = 20
        r = r + 1
    Next i
    If qRows.Count = 0 Then wz.Cells(r, WZ_COL_LABEL).Value = "（このステップには設問がありません）"

    SetCurrentStep stepNo
    WriteStepList wz, stepNo
    UpdateProgressOn wz

    ProtectWizard wz
    Application.ScreenUpdating = True
    wz.Activate
    If qRows.Count > 0 Then wz.Cells(WZ_FIRST_ROW, WZ_COL_INPUT).Select
End Sub

' 右側のステップ一覧（シートは保護解除済みで呼ぶ）
Private Sub WriteStepList(ByVal wz As Worksheet, ByVal current As Long)
    Dim s As Long, r As Long, st As String
    For s = 1 To StepCount()
        r = WZ_FIRST_ROW + s - 1
        wz.Cells(r, WZ_COL_STEP).Value = s & ". " & StepName(s)
        st = StepStatus(s)
        wz.Cells(r, WZ_COL_STATUS).Value = st
        Select Case st
        Case "済"
            wz.Cells(r, WZ_COL_STATUS).Font.Color = RGB(56, 118, 29)
        Case "必須未入力"
            wz.Cells(r, WZ_COL_STATUS).Font.Color = RGB(192, 0, 0)
        Case Else
            wz.Cells(r, WZ_COL_STATUS).Font.Color = RGB(128, 128, 128)
        End Select
        If s = current Then
            With wz.Range(wz.Cells(r, WZ_COL_STEP), wz.Cells(r, WZ_COL_STATUS))
                .Interior.Color = RGB(255, 242, 204)
                .Font.Bold = True
            End With
        End If
    Next s
End Sub

Private Sub UpdateProgress()
    Dim wz As Worksheet
    Set wz = GetSheet(SH_WIZ)
    If wz Is Nothing Then Exit Sub
    wz.Unprotect
    WriteStepList wz, CurrentStep()
    UpdateProgressOn wz
    ProtectWizard wz
End Sub

Private Sub UpdateProgressOn(ByVal wz As Worksheet)
    Dim qs As Worksheet, r As Long, total As Long, answered As Long
    Set qs = GetSheet(SH_Q)
    For r = 2 To LastRow(qs, QC_ID)
        If IsQuestionRow(qs, r) Then
            total = total + 1
            If IsAnswered(CStr(qs.Cells(r, QC_ID).Value)) Then answered = answered + 1
        End If
    Next r
    wz.Cells(2, WZ_COL_HINT).Value = "入力済み " & answered & " / " & total & " 項目（必須の未入力 " & _
                                     MissingRequiredRows().Count & " 件）"
End Sub

' 画面に出ているステップの入力を回答シートへ保存する
Private Sub SaveCurrentStep()
    Dim wz As Worksheet, r As Long, v As Variant
    Set wz = GetSheet(SH_WIZ)
    If wz Is Nothing Then Exit Sub
    r = WZ_FIRST_ROW
    Do While Len(CStr(wz.Cells(r, WZ_COL_ID).Value)) > 0
        v = wz.Cells(r, WZ_COL_INPUT).Value
        If IsError(v) Then v = wz.Cells(r, WZ_COL_INPUT).Text
        SetAnswer CStr(wz.Cells(r, WZ_COL_ID).Value), v
        r = r + 1
    Loop
End Sub

'==============================================================================
' 仕様書の作成
'==============================================================================

' 必須の未入力があれば確認する。続けるなら True
Private Function ConfirmMissing() As Boolean
    Dim n As Long
    n = MissingRequiredRows().Count
    If n = 0 Then
        ConfirmMissing = True
    Else
        ConfirmMissing = (MsgBox("必須項目が " & n & " 件未入力です。このまま作成しますか？" & vbLf & _
                                 "（未入力の項目は末尾の「未決事項（自動抽出）」に一覧で出ます）", _
                                 vbYesNo + vbQuestion) = vbYes)
    End If
End Function

Private Function BuildSpecSheet() As Worksheet
    Dim ws As Worksheet, qs As Worksheet, qRows As Collection, missing As Collection
    Dim n As Long, s As Long, i As Long, qr As Long, r As Long
    Dim title As String, ans As String

    Application.ScreenUpdating = False
    Set qs = GetSheet(SH_Q)
    Set ws = GetSheet(SH_SPEC)
    If ws Is Nothing Then
        Set ws = ThisWorkbook.Worksheets.Add(After:=GetSheet(SH_WIZ))
        ws.Name = SH_SPEC
    Else
        ws.Cells.Clear
        ws.Rows.RowHeight = ws.StandardHeight
    End If
    Set missing = New Collection

    ws.Cells.Font.Size = 10
    ws.Columns(1).ColumnWidth = 2
    ws.Columns(2).ColumnWidth = 28
    ws.Columns(3).ColumnWidth = 72

    title = AnswerText(ID_TITLE)
    If Len(title) = 0 Then title = "（案件名未記入）"
    With ws.Cells(1, 2)
        .Value = "マクロ開発仕様書"
        .Font.Size = 16
        .Font.Bold = True
    End With
    With ws.Cells(2, 2)
        WriteCellValue ws.Cells(2, 2), title
        .Font.Size = 13
        .Font.Bold = True
    End With
    With ws.Cells(3, 2)
        .Value = "出力日時：" & Format$(Now, "yyyy/mm/dd hh:mm") & "（仕様書ウィザードで作成）"
        .Font.Size = 9
        .Font.Color = RGB(128, 128, 128)
    End With
    r = 5

    n = StepCount()
    For s = 1 To n
        With ws.Range(ws.Cells(r, 2), ws.Cells(r, 3))
            .Interior.Color = RGB(31, 78, 121)
            .Font.Color = RGB(255, 255, 255)
            .Font.Bold = True
            .Font.Size = 12
        End With
        ws.Cells(r, 2).Value = s & ". " & StepName(s)
        ws.Rows(r).RowHeight = 22
        r = r + 1

        Set qRows = StepRows(s)
        For i = 1 To qRows.Count
            qr = qRows(i)
            ans = AnswerText(CStr(qs.Cells(qr, QC_ID).Value))
            With ws.Cells(r, 2)
                .Value = s & "." & i & " " & qs.Cells(qr, QC_LABEL).Value
                .Interior.Color = RGB(242, 242, 242)
                .Font.Bold = True
            End With
            If Len(ans) > 0 Then
                WriteCellValue ws.Cells(r, 3), ans
            Else
                ws.Cells(r, 3).Value = "（未記入）"
                ws.Cells(r, 3).Font.Color = RGB(192, 0, 0)
                If IsRequired(qr) Then missing.Add s & "." & i & " " & qs.Cells(qr, QC_LABEL).Value
            End If
            With ws.Range(ws.Cells(r, 2), ws.Cells(r, 3))
                .WrapText = True
                .VerticalAlignment = xlTop
                .Borders.LineStyle = xlContinuous
                .Borders.Color = RGB(191, 191, 191)
            End With
            ws.Rows(r).AutoFit
            r = r + 1
        Next i
        r = r + 1
    Next s

    ' 末尾に必須の未入力を未決事項として並べる
    With ws.Range(ws.Cells(r, 2), ws.Cells(r, 3))
        .Interior.Color = RGB(192, 0, 0)
        .Font.Color = RGB(255, 255, 255)
        .Font.Bold = True
        .Font.Size = 12
    End With
    ws.Cells(r, 2).Value = "未決事項（自動抽出）"
    ws.Rows(r).RowHeight = 22
    r = r + 1
    If missing.Count = 0 Then
        ws.Cells(r, 2).Value = "必須項目はすべて記入済み"
        r = r + 1
    Else
        For i = 1 To missing.Count
            WriteCellValue ws.Cells(r, 2), missing(i)
            ws.Cells(r, 3).Value = "必須項目が未記入。決める人と期限を確認する"
            With ws.Range(ws.Cells(r, 2), ws.Cells(r, 3))
                .WrapText = True
                .VerticalAlignment = xlTop
                .Borders.LineStyle = xlContinuous
                .Borders.Color = RGB(191, 191, 191)
            End With
            ws.Rows(r).AutoFit
            r = r + 1
        Next i
    End If

    SetupPrint ws, title, r - 1
    Application.ScreenUpdating = True
    ws.Activate
    On Error Resume Next
    ActiveWindow.DisplayGridlines = False
    ws.Range("A1").Select
    On Error GoTo 0
    Set BuildSpecSheet = ws
End Function

Private Sub SetupPrint(ByVal ws As Worksheet, ByVal title As String, ByVal lastRowNo As Long)
    ' プリンタが無い環境では PageSetup が失敗することがあるので、失敗しても続ける
    On Error Resume Next
    Application.PrintCommunication = False
    With ws.PageSetup
        .PrintArea = "$B$1:$C$" & lastRowNo
        .Orientation = xlPortrait
        .PaperSize = xlPaperA4
        .Zoom = False
        .FitToPagesWide = 1
        .FitToPagesTall = False
        .LeftHeader = "マクロ開発仕様書：" & Replace(title, "&", "&&")
        .CenterFooter = "&P / &N"
    End With
    Application.PrintCommunication = True
    On Error GoTo 0
End Sub

Private Function BuildMarkdown() As String
    Dim qs As Worksheet, qRows As Collection, missing As Collection
    Dim n As Long, s As Long, i As Long, qr As Long
    Dim md As String, title As String, ans As String, label As String

    Set qs = GetSheet(SH_Q)
    Set missing = New Collection
    title = AnswerText(ID_TITLE)
    If Len(title) = 0 Then title = "（案件名未記入）"

    md = "# マクロ開発仕様書：" & title & vbLf & vbLf
    md = md & "出力日時：" & Format$(Now, "yyyy/mm/dd hh:mm") & "（仕様書ウィザードで作成）" & vbLf

    n = StepCount()
    For s = 1 To n
        md = md & vbLf & "## " & s & ". " & StepName(s) & vbLf
        Set qRows = StepRows(s)
        For i = 1 To qRows.Count
            qr = qRows(i)
            label = s & "." & i & " " & qs.Cells(qr, QC_LABEL).Value
            ans = AnswerText(CStr(qs.Cells(qr, QC_ID).Value))
            md = md & vbLf & "### " & label & vbLf & vbLf
            If Len(ans) = 0 Then
                md = md & "（未記入）" & vbLf
                If IsRequired(qr) Then missing.Add label
            Else
                md = md & MarkdownBody(ans) & vbLf
            End If
        Next i
    Next s

    md = md & vbLf & "## 未決事項（自動抽出）" & vbLf & vbLf
    If missing.Count = 0 Then
        md = md & "必須項目はすべて記入済み" & vbLf
    Else
        For i = 1 To missing.Count
            md = md & "- " & missing(i) & "（必須項目が未記入）" & vbLf
        Next i
    End If
    BuildMarkdown = md
End Function

' 複数行の回答は箇条書きにする（「・」「-」で始まる行は記号をそろえる）
Private Function MarkdownBody(ByVal ans As String) As String
    Dim lines() As String, i As Long, ln As String, out As String
    If InStr(ans, vbLf) = 0 Then
        MarkdownBody = ans
        Exit Function
    End If
    lines = Split(ans, vbLf)
    For i = LBound(lines) To UBound(lines)
        ln = Trim$(Replace(lines(i), vbCr, ""))
        If Len(ln) > 0 Then
            If ln Like "#.*" Or ln Like "##.*" Or ln Like "#)*" Or ln Like "##)*" Then
                out = out & ln & vbLf
            Else
                Do While Left$(ln, 1) = "・" Or Left$(ln, 1) = "-" Or Left$(ln, 1) = "*" Or Left$(ln, 1) = "●"
                    ln = Trim$(Mid$(ln, 2))
                Loop
                out = out & "- " & ln & vbLf
            End If
        End If
    Next i
    If Right$(out, 1) = vbLf Then out = Left$(out, Len(out) - 1)
    MarkdownBody = out
End Function

Private Function DefaultFileName(ByVal ext As String) As String
    Dim folder As String, fileName As String, title As String
    title = AnswerText(ID_TITLE)
    If Len(title) = 0 Then title = "未定"
    fileName = "仕様書_" & SafeFileName(title) & "_" & Format$(Date, "yyyymmdd") & "." & ext
    folder = ThisWorkbook.Path
    ' OneDrive 上のブックは Path が URL になるので、そのときはフォルダを指定しない
    If Len(folder) = 0 Or LCase$(Left$(folder, 4)) = "http" Then
        DefaultFileName = fileName
    Else
        DefaultFileName = folder & Application.PathSeparator & fileName
    End If
End Function

Private Function SafeFileName(ByVal s As String) As String
    Dim ch As Variant
    For Each ch In Array("\", "/", ":", "*", "?", Chr$(34), "<", ">", "|", vbLf, vbCr, vbTab)
        s = Replace(s, ch, "_")
    Next ch
    SafeFileName = Left$(s, 60)
End Function

' UTF-8（BOM なし）で書き出す。ADODB が無い環境（Mac 等）では OS 既定の文字コードで書く
Private Function WriteUtf8(ByVal path As String, ByVal text As String) As Boolean
    If WriteUtf8WithAdodb(path, text) Then
        WriteUtf8 = True
        Exit Function
    End If
    Dim f As Integer
    On Error GoTo Failed
    f = FreeFile
    Open path For Output As #f
    Print #f, text;
    Close #f
    MsgBox "この環境では UTF-8 で保存できないため、OS の既定の文字コードで保存しました。", vbInformation
    WriteUtf8 = True
    Exit Function
Failed:
    MsgBox "ファイルを保存できませんでした。" & vbLf & Err.Description, vbExclamation
End Function

Private Function WriteUtf8WithAdodb(ByVal path As String, ByVal text As String) As Boolean
    Dim st As Object, bin As Object
    On Error GoTo Failed
    Set st = CreateObject("ADODB.Stream")
    st.Type = 2          ' adTypeText
    st.Charset = "UTF-8"
    st.Open
    st.WriteText text
    st.Position = 0
    st.Type = 1          ' adTypeBinary
    st.Position = 3      ' 先頭の BOM を飛ばす
    Set bin = CreateObject("ADODB.Stream")
    bin.Type = 1
    bin.Open
    st.CopyTo bin
    bin.SaveToFile path, 2   ' adSaveCreateOverWrite
    bin.Close
    st.Close
    WriteUtf8WithAdodb = True
Failed:
End Function

'==============================================================================
' 設問の読み取り
'==============================================================================

Private Function IsQuestionRow(ByVal qs As Worksheet, ByVal r As Long) As Boolean
    Dim v As Variant
    v = qs.Cells(r, QC_STEP).Value
    If IsError(v) Or IsEmpty(v) Then Exit Function
    If Not IsNumeric(v) Then Exit Function
    If CLng(v) < 1 Then Exit Function
    IsQuestionRow = Len(Trim$(CStr(qs.Cells(r, QC_ID).Value))) > 0
End Function

Private Function StepCount() As Long
    Dim qs As Worksheet, r As Long, n As Long
    Set qs = GetSheet(SH_Q)
    If qs Is Nothing Then Exit Function
    For r = 2 To LastRow(qs, QC_STEP)
        If IsQuestionRow(qs, r) Then
            If CLng(qs.Cells(r, QC_STEP).Value) > n Then n = CLng(qs.Cells(r, QC_STEP).Value)
        End If
    Next r
    StepCount = n
End Function

Private Function StepName(ByVal stepNo As Long) As String
    Dim qs As Worksheet, r As Long
    Set qs = GetSheet(SH_Q)
    For r = 2 To LastRow(qs, QC_STEP)
        If IsQuestionRow(qs, r) Then
            If CLng(qs.Cells(r, QC_STEP).Value) = stepNo Then
                StepName = Trim$(CStr(qs.Cells(r, QC_STEPNAME).Value))
                If Len(StepName) > 0 Then Exit Function
            End If
        End If
    Next r
    StepName = "ステップ " & stepNo
End Function

' そのステップの設問がある行番号を上から順に返す
Private Function StepRows(ByVal stepNo As Long) As Collection
    Dim qs As Worksheet, r As Long, c As New Collection
    Set qs = GetSheet(SH_Q)
    For r = 2 To LastRow(qs, QC_STEP)
        If IsQuestionRow(qs, r) Then
            If CLng(qs.Cells(r, QC_STEP).Value) = stepNo Then c.Add r
        End If
    Next r
    Set StepRows = c
End Function

Private Function StepStatus(ByVal stepNo As Long) As String
    Dim qs As Worksheet, qRows As Collection, i As Long, qr As Long
    Dim answered As Long, missingReq As Long
    Set qs = GetSheet(SH_Q)
    Set qRows = StepRows(stepNo)
    For i = 1 To qRows.Count
        qr = qRows(i)
        If IsAnswered(CStr(qs.Cells(qr, QC_ID).Value)) Then
            answered = answered + 1
        ElseIf IsRequired(qr) Then
            missingReq = missingReq + 1
        End If
    Next i
    If answered = 0 And qRows.Count > 0 Then
        StepStatus = "未着手"
    ElseIf missingReq > 0 Then
        StepStatus = "必須未入力"
    Else
        StepStatus = "済"
    End If
End Function

' 必須で未入力の設問の行番号（ステップ順）
Private Function MissingRequiredRows() As Collection
    Dim c As New Collection, s As Long, i As Long, qRows As Collection, qs As Worksheet
    Set qs = GetSheet(SH_Q)
    For s = 1 To StepCount()
        Set qRows = StepRows(s)
        For i = 1 To qRows.Count
            If IsRequired(qRows(i)) Then
                If Not IsAnswered(CStr(qs.Cells(qRows(i), QC_ID).Value)) Then c.Add qRows(i)
            End If
        Next i
    Next s
    Set MissingRequiredRows = c
End Function

' 必須欄に何か入っていれば必須とみなす
Private Function IsRequired(ByVal qr As Long) As Boolean
    IsRequired = Len(Trim$(CStr(GetSheet(SH_Q).Cells(qr, QC_REQ).Value))) > 0
End Function

Private Function QuestionType(ByVal qr As Long) As String
    Dim t As String
    t = Trim$(CStr(GetSheet(SH_Q).Cells(qr, QC_TYPE).Value))
    Select Case t
    Case T_MULTI, T_CHOICE, T_DATE
        QuestionType = t
    Case Else
        QuestionType = T_LINE
    End Select
End Function

'==============================================================================
' 回答の読み書き
'==============================================================================

Private Function FindAnswerRow(ByVal id As String) As Long
    Dim m As Variant
    m = Application.Match(id, GetSheet(SH_ANS).Columns(1), 0)
    If Not IsError(m) Then FindAnswerRow = CLng(m)
End Function

Private Function GetAnswer(ByVal id As String) As Variant
    Dim r As Long
    r = FindAnswerRow(id)
    If r > 0 Then GetAnswer = GetSheet(SH_ANS).Cells(r, 2).Value
End Function

Private Sub SetAnswer(ByVal id As String, ByVal v As Variant)
    Dim ws As Worksheet, r As Long
    Set ws = GetSheet(SH_ANS)
    r = FindAnswerRow(id)
    If r = 0 Then
        If Len(ValueText(v)) = 0 Then Exit Sub
        r = LastRow(ws, 1) + 1
        ws.Cells(r, 1).Value = id
    End If
    If ValueText(ws.Cells(r, 2).Value) = ValueText(v) Then Exit Sub
    WriteCellValue ws.Cells(r, 2), v
    ws.Cells(r, 3).Value = Now
End Sub

Private Function AnswerText(ByVal id As String) As String
    AnswerText = ValueText(GetAnswer(id))
End Function

Private Function IsAnswered(ByVal id As String) As Boolean
    IsAnswered = Len(AnswerText(id)) > 0
End Function

' セルの値を文字列にする（日付は yyyy/mm/dd、前後の空白・改行は落とす）
Private Function ValueText(ByVal v As Variant) As String
    Dim s As String
    If IsEmpty(v) Or IsError(v) Or IsNull(v) Then Exit Function
    If VarType(v) = vbDate Then
        s = Format$(v, "yyyy/mm/dd")
    Else
        s = Replace(CStr(v), vbCr, "")
    End If
    Do While Len(s) > 0 And (Left$(s, 1) = vbLf Or Left$(s, 1) = " " Or Left$(s, 1) = "　")
        s = Mid$(s, 2)
    Loop
    Do While Len(s) > 0 And (Right$(s, 1) = vbLf Or Right$(s, 1) = " " Or Right$(s, 1) = "　")
        s = Left$(s, Len(s) - 1)
    Loop
    ValueText = s
End Function

' 文字列が数式や日付に化けないように書き込む
Private Sub WriteCellValue(ByVal c As Range, ByVal v As Variant)
    If IsEmpty(v) Or IsNull(v) Then
        c.ClearContents
    ElseIf VarType(v) = vbString Then
        If Len(v) = 0 Then
            c.ClearContents
        ElseIf c.NumberFormat = "@" Then
            c.Value = v
        Else
            c.Value = "'" & v
        End If
    Else
        c.Value = v
    End If
End Sub

Private Function CurrentStep() As Long
    Dim v As Variant
    v = GetSheet(SH_ANS).Range(ANS_CUR_STEP).Value
    If IsNumeric(v) And Not IsEmpty(v) Then CurrentStep = CLng(v)
    If CurrentStep < 1 Then CurrentStep = 1
    If CurrentStep > StepCount() Then CurrentStep = StepCount()
End Function

Private Sub SetCurrentStep(ByVal stepNo As Long)
    GetSheet(SH_ANS).Range(ANS_CUR_STEP).Value = stepNo
End Sub

'==============================================================================
' 共通
'==============================================================================

Private Function GetSheet(ByVal sheetName As String) As Worksheet
    On Error Resume Next
    Set GetSheet = ThisWorkbook.Worksheets(sheetName)
    On Error GoTo 0
End Function

' 非表示シート（回答）でも確実に動くよう、End(xlUp) ではなく UsedRange の下端から探す
Private Function LastRow(ByVal ws As Worksheet, ByVal col As Long) As Long
    Dim r As Long
    r = ws.UsedRange.Row + ws.UsedRange.Rows.Count - 1
    Do While r > 1 And Len(CStr(ws.Cells(r, col).Formula)) = 0
        r = r - 1
    Loop
    LastRow = r
End Function

'==============================================================================
' 既定の設問
'   入力形式: 1行 / 複数行 / 選択（選択肢は半角カンマ区切り）/ 日付
'   「設問」シートを直接編集しても変えられる
'==============================================================================

Private Sub WriteDefaultQuestions(ByVal ws As Worksheet)
    ws.Cells.Clear
    ws.Range("A1:H1").Value = Array("ステップ", "ステップ名", "項目ID", "項目", "入力形式", _
                                    "選択肢（半角カンマ区切り）", "必須", "入力例・ヒント")
    With ws.Range("A1:H1")
        .Font.Bold = True
        .Interior.Color = RGB(217, 225, 242)
    End With
    ws.Range("J1").Value = "この表を書き換えると設問を変えられます。"
    ws.Range("J2").Value = "入力形式：1行 / 複数行 / 選択 / 日付。必須欄に何か入っていれば必須。"
    ws.Range("J3").Value = "項目ID は回答の保存に使うので重複させないこと（変えると以前の回答とひもづかなくなる）。"
    ws.Range("J1:J3").Font.Color = RGB(89, 89, 89)

    Set mQSheet = ws
    mQRow = 2

    BeginStep 1, "基本情報"
    AddQ "Q0101", "案件名", T_LINE, "", True, "例：月次売上集計マクロ"
    AddQ "Q0102", "文書の版数", T_LINE, "", True, "例：1.0（初版）"
    AddQ "Q0103", "作成日", T_DATE, "", True, "例：2026/10/15"
    AddQ "Q0104", "作成者", T_LINE, "", True, ""
    AddQ "Q0105", "依頼部署・依頼者", T_LINE, "", True, ""
    AddQ "Q0106", "承認者", T_LINE, "", False, ""

    BeginStep 2, "概要・目的"
    AddQ "Q0201", "目的・背景（今の課題）", T_MULTI, "", True, _
         "例：手作業で毎月 8 時間かかる／転記ミスが月 2、3 件ある／担当者しか作業できない"
    AddQ "Q0202", "対象業務", T_MULTI, "", True, "例：営業部の月次売上報告の作成"
    AddQ "Q0203", "マクロで行う範囲", T_MULTI, "", True, "1 行に 1 項目"
    AddQ "Q0204", "マクロで行わない範囲", T_MULTI, "", True, _
         "範囲が広がり続けるのを防ぐため必ず書く。例：元データの修正、他部署分の集計"
    AddQ "Q0205", "期待効果", T_MULTI, "", False, "数字で書く。例：作業時間 8 時間→30 分、転記ミス 0 件"
    AddQ "Q0206", "利用者（人数・スキル・部署）", T_MULTI, "", True, "例：営業事務 3 名。Excel の基本操作はできる"
    AddQ "Q0207", "マクロ以外の手段の検討", T_CHOICE, _
         "マクロで作る,Power Query で代替できる,関数・テーブルで代替できる,Python 等で代替できる,未検討", False, _
         "Power Query や関数で済むなら、その方が保守しやすいことがある"
    AddQ "Q0208", "上の判断の理由", T_MULTI, "", False, ""

    BeginStep 3, "動作環境"
    AddQ "Q0301", "Excel のバージョン", T_CHOICE, "Microsoft 365,Excel 2021,Excel 2019,Excel 2016,混在", True, ""
    AddQ "Q0302", "Office の bit 数", T_CHOICE, "64bit,32bit,混在,不明", True, _
         "混在・不明なら Declare 文を PtrSafe にして両方で動くようにする"
    AddQ "Q0303", "OS", T_CHOICE, "Windows 11,Windows 10,Windows と Mac,Mac", True, _
         "Mac も対象なら ADODB や Windows API は使えない"
    AddQ "Q0304", "ブックの保存場所", T_CHOICE, "ローカル PC,共有フォルダ（NAS）,OneDrive,SharePoint / Teams,その他", True, _
         "OneDrive / SharePoint 上では ThisWorkbook.Path が URL になる点に注意"
    AddQ "Q0305", "マクロのセキュリティ設定", T_MULTI, "", False, "例：共有フォルダを「信頼できる場所」に登録、デジタル署名を付ける"
    AddQ "Q0306", "参照設定・連携するアプリ", T_MULTI, "", False, _
         "例：Outlook（メール送信）、ADO（Access 接続）。配布先の差を避けるため原則は遅延バインディング"

    BeginStep 4, "入力仕様"
    AddQ "Q0401", "入力ファイルの種類と取得元", T_MULTI, "", True, "例：基幹システムから出力した売上明細 CSV"
    AddQ "Q0402", "ファイル名の規則・置き場所", T_MULTI, "", True, "例：\\server\share\売上\uriage_yyyymm.csv"
    AddQ "Q0403", "文字コード", T_CHOICE, "Shift-JIS,UTF-8（BOM あり）,UTF-8（BOM なし）,Excel ファイルのため該当なし,不明", True, ""
    AddQ "Q0404", "シート構成・見出し行の位置", T_MULTI, "", False, "例：1 シート目、1 行目が見出し、2 行目からデータ"
    AddQ "Q0405", "列の定義", T_MULTI, "", True, _
         "1 行に 1 列：列名／型／必須か／桁数／値の範囲。例：売上日／日付／必須／－／当月内"
    AddQ "Q0406", "想定件数（通常・最大）", T_LINE, "", True, "例：通常 5,000 件、最大 30,000 件"
    AddQ "Q0407", "異常データの扱い", T_MULTI, "", True, _
         "仕様漏れが最も多いところ。空欄、全角/半角、日付形式、重複、結合セルの扱いを決める"

    BeginStep 5, "処理仕様"
    AddQ "Q0501", "処理の流れ", T_MULTI, "", True, "1 行に 1 手順。例：1. CSV を読む 2. 担当者別に集計 3. 帳票に転記"
    AddQ "Q0502", "業務ルール（判定・計算・端数処理）", T_MULTI, "", True, _
         "例：税込金額は円未満切り捨て、締め日は 20 日、祝日は翌営業日"
    AddQ "Q0503", "外部連携", T_MULTI, "", False, "例：Outlook でメール送信、PDF 出力、他ブックの操作、DB 接続。無ければ「なし」"
    AddQ "Q0504", "実行のきっかけ", T_CHOICE, _
         "シート上のボタン,リボン・クイックアクセスツールバー,ブックを開いたとき,タスクスケジューラで自動実行,その他", True, ""
    AddQ "Q0505", "実行する頻度・タイミング", T_LINE, "", False, "例：毎月第 1 営業日の朝"

    BeginStep 6, "出力仕様"
    AddQ "Q0601", "出力物の形式", T_MULTI, "", True, "例：集計表（xlsx）、PDF、CSV"
    AddQ "Q0602", "ファイル名の規則・保存先", T_MULTI, "", True, "例：\\server\share\報告\売上報告_yyyymm.xlsx"
    AddQ "Q0603", "帳票のレイアウト", T_MULTI, "", False, "例：別紙レイアウト参照、A4 横、1 ページに収める"
    AddQ "Q0604", "同じ名前のファイルがあるとき", T_CHOICE, _
         "上書きする,確認してから上書き,別名で保存（日時付き）,処理を中止", True, ""
    AddQ "Q0605", "完了時のメッセージ", T_LINE, "", False, "例：処理件数とエラー件数を表示"

    BeginStep 7, "画面（操作）仕様"
    AddQ "Q0701", "操作画面の構成", T_MULTI, "", False, "例：操作シートに「実行」ボタン、ファイル選択ダイアログ"
    AddQ "Q0702", "入力チェックとメッセージ", T_MULTI, "", False, "例：対象月が空欄なら「対象月を入力してください」"
    AddQ "Q0703", "進捗表示・中断", T_CHOICE, "不要,ステータスバーに表示,プログレスバーを表示,表示して中断もできる", False, ""

    BeginStep 8, "エラー処理"
    AddQ "Q0801", "想定するエラーと対応", T_MULTI, "", True, _
         "1 行に 1 件：エラー → 対応。例：入力ファイルがない → メッセージを出して中止"
    AddQ "Q0802", "途中で止まったときの扱い", T_MULTI, "", True, "例：元データは変更しない、処理前にバックアップを作る"
    AddQ "Q0803", "Excel の設定の復元", T_CHOICE, "必ず元に戻す（推奨）,対応しない", False, _
         "ScreenUpdating / Calculation / EnableEvents を、エラー時も含めて元に戻すか"

    BeginStep 9, "ログ・監査"
    AddQ "Q0901", "実行ログ", T_MULTI, "", False, "例：ログシートに日時・実行者・件数・結果を追記"
    AddQ "Q0902", "エラーログ", T_MULTI, "", False, "例：エラー行の内容と理由を別シートに出す"
    AddQ "Q0903", "ログの保存期間", T_LINE, "", False, "例：1 年"

    BeginStep 10, "非機能要件"
    AddQ "Q1001", "処理時間の目標", T_LINE, "", True, "例：最大件数で 1 分以内"
    AddQ "Q1002", "機密情報の扱い", T_MULTI, "", True, "例：個人情報を含むためフォルダの権限を限定、VBA プロジェクトをロック"
    AddQ "Q1003", "同時に使う人数", T_CHOICE, "1 人だけ,複数人（同時には実行しない）,複数人（同時に実行する）", False, ""
    AddQ "Q1004", "保守しやすくする工夫", T_MULTI, "", False, "例：パス・閾値・宛先は設定シートにまとめる"

    BeginStep 11, "設計・コーディング規約"
    AddQ "Q1101", "モジュール構成", T_MULTI, "", False, "例：標準モジュールを処理ごとに分ける、フォームは入力専用"
    AddQ "Q1102", "命名規則・コーディング規約", T_MULTI, "", False, "例：Option Explicit 必須、変数名は役割がわかる名前"
    AddQ "Q1103", "設定値の管理方法", T_MULTI, "", False, "例：「設定」シートに名前付きセルで置く"

    BeginStep 12, "テスト"
    AddQ "Q1201", "テストケース", T_MULTI, "", True, "正常系、境界値、異常系、0 件、最大件数を含める"
    AddQ "Q1202", "テストデータの準備", T_MULTI, "", False, "例：前月の実データを個人名を伏せて使う"
    AddQ "Q1203", "受入基準と承認者", T_MULTI, "", True, "例：手作業の結果と 3 か月分一致すること。承認は課長"

    BeginStep 13, "運用・保守"
    AddQ "Q1301", "マニュアル・問い合わせ先", T_MULTI, "", True, ""
    AddQ "Q1302", "バージョン管理", T_MULTI, "", False, "例：ファイル名に版数、変更履歴シート、VBA をエクスポートして保管"
    AddQ "Q1303", "入力レイアウトが変わったときの対応", T_MULTI, "", False, ""
    AddQ "Q1304", "担当者が変わるときの引き継ぎ", T_MULTI, "", False, ""

    BeginStep 14, "スケジュール・体制"
    AddQ "Q1401", "スケジュール", T_MULTI, "", True, _
         "例：要件定義 10/20、設計 10/31、開発 11/15、テスト 11/22、リリース 11/30"
    AddQ "Q1402", "体制・役割", T_MULTI, "", False, "例：開発 山田、テスト 佐藤、承認 鈴木課長"
    AddQ "Q1403", "成果物", T_MULTI, "", False, "例：仕様書、マクロブック、操作マニュアル、テスト結果"

    BeginStep 15, "前提・制約・未決事項"
    AddQ "Q1501", "前提条件", T_MULTI, "", True, "例：入力 CSV のレイアウトは変わらない"
    AddQ "Q1502", "制約", T_MULTI, "", False, "例：アドインの導入は不可"
    AddQ "Q1503", "未決事項（決める人・期限）", T_MULTI, "", False, "例：PDF の保存先 → 鈴木課長が 10/25 までに決める"

    ws.Columns("A").ColumnWidth = 8
    ws.Columns("B").ColumnWidth = 20
    ws.Columns("C").ColumnWidth = 8
    ws.Columns("D").ColumnWidth = 30
    ws.Columns("E").ColumnWidth = 8
    ws.Columns("F").ColumnWidth = 40
    ws.Columns("G").ColumnWidth = 6
    ws.Columns("H").ColumnWidth = 60
    ws.Range("A1:H" & (mQRow - 1)).VerticalAlignment = xlTop
    ws.Range("F2:F" & (mQRow - 1)).WrapText = True
    ws.Range("H2:H" & (mQRow - 1)).WrapText = True
    Set mQSheet = Nothing
End Sub

Private Sub BeginStep(ByVal stepNo As Long, ByVal stepTitle As String)
    mStepNo = stepNo
    mStepName = stepTitle
End Sub

Private Sub AddQ(ByVal id As String, ByVal label As String, ByVal qType As String, _
                 ByVal choices As String, ByVal required As Boolean, ByVal hint As String)
    With mQSheet
        .Cells(mQRow, QC_STEP).Value = mStepNo
        .Cells(mQRow, QC_STEPNAME).Value = mStepName
        .Cells(mQRow, QC_ID).Value = id
        .Cells(mQRow, QC_LABEL).Value = label
        .Cells(mQRow, QC_TYPE).Value = qType
        WriteCellValue .Cells(mQRow, QC_CHOICES), choices
        If required Then .Cells(mQRow, QC_REQ).Value = "必須"
        WriteCellValue .Cells(mQRow, QC_HINT), hint
    End With
    mQRow = mQRow + 1
End Sub
