"""LibreOffice の VBA 互換モードで SpecWizard.bas を動かす簡易テスト.

Excel が無い環境での動作確認用。MsgBox / InputBox / 保存ダイアログはテスト用の関数に差し替える。
LibreOffice では図形ボタンの OnAction や PDF 出力などは確認できないので、最終確認は Excel で行うこと。

    python3 macro/spec_wizard/tools/smoke_test_libreoffice.py
"""
import re, subprocess, time, sys, uno
from com.sun.star.beans import PropertyValue

from pathlib import Path
import tempfile
SRC = Path(__file__).resolve().parent.parent / "src" / "SpecWizard.bas"
OUT_MD = str(Path(tempfile.mkdtemp()) / "out.md")
code = open(SRC, encoding="utf-8").read()
code = re.sub(r'^Attribute VB_Name.*\n', '', code)
code = code.replace("Option Explicit", "Option VBASupport 1\nOption Explicit", 1)
# ダイアログをテスト用に差し替え
code = re.sub(r'\bMsgBox\(', 'TMsg(', code)
code = re.sub(r'\bMsgBox ', 'TMsg ', code)
code = code.replace("Application.InputBox(", "TInput(").replace("CurrentStep(), Type:=1)", "CurrentStep())")
code = code.replace("Application.GetSaveAsFilename(", "TSave(")
code += '''
Public gLog As String
Public gInput As Variant
Public gSave As String
Public Function TMsg(Optional p As Variant, Optional b As Variant, Optional t As Variant) As Long
    gLog = gLog & "[MSG] " & p & Chr(10)
    TMsg = 6
End Function
Public Function TInput(Optional p As Variant, Optional t As Variant, Optional d As Variant) As Variant
    TInput = gInput
End Function
Public Function TSave(Optional InitialFileName As Variant, Optional FileFilter As Variant) As Variant
    TSave = gSave
End Function
Public Function T_GetLog() As String
    T_GetLog = gLog
End Function
Public Sub T_SetInput(v As Variant)
    gInput = v
End Sub
Public Sub T_SetSave(v As String)
    gSave = v
End Sub
Public Sub T_Debug()
    Dim ws As Worksheet: Set ws = ThisWorkbook.Worksheets("回答")
    Dim c As Range: Set c = ws.Cells(10, 2)
    gLog = gLog & "LastRow=" & LastRow(ws, 1) & " match=" & CStr(FindAnswerRow("Q0101")) & Chr(10)
    WriteCellValue c, "abc"
    gLog = gLog & "write abc -> [" & c.Value & "] type " & VarType(c.Value) & Chr(10)
    c.Value = "'xyz"
    gLog = gLog & "apos -> [" & c.Value & "]" & Chr(10)
    Dim w As Worksheet: Set w = ThisWorkbook.Worksheets("ウィザード")
    gLog = gLog & "wz C6=[" & w.Cells(6, 3).Value & "] A6=[" & w.Cells(6, 1).Value & "] fmt=" & w.Cells(6, 3).NumberFormat & Chr(10)
End Sub
Public Sub T_Debug2()
    Dim ws As Worksheet: Set ws = ThisWorkbook.Worksheets("回答")
    SetAnswer "QX1", "a"
    gLog = gLog & "after1 LastRow=" & LastRow(ws, 1) & " A2=" & ws.Cells(2, 1).Value & " B2=" & ws.Cells(2, 2).Value & " find=" & FindAnswerRow("QX1") & Chr(10)
    SetAnswer "QX2", "b"
    gLog = gLog & "after2 LastRow=" & LastRow(ws, 1) & " A2=" & ws.Cells(2, 1).Value & " A3=" & ws.Cells(3, 1).Value & Chr(10)
End Sub
Public Sub T_TypeIn(r As Long, v As Variant)
    ThisWorkbook.Worksheets("ウィザード").Cells(r, 3).Value = v
End Sub
'''

proc = subprocess.Popen(["soffice", "--headless", "--invisible", "--norestore",
    '--accept=socket,host=localhost,port=2002;urp;'])
ctx = None
local = uno.getComponentContext()
resolver = local.ServiceManager.createInstanceWithContext("com.sun.star.bridge.UnoUrlResolver", local)
for _ in range(60):
    try:
        ctx = resolver.resolve("uno:socket,host=localhost,port=2002;urp;StarOffice.ComponentContext"); break
    except Exception:
        time.sleep(0.5)
smgr = ctx.ServiceManager
desktop = smgr.createInstanceWithContext("com.sun.star.frame.Desktop", ctx)
def pv(n, v):
    p = PropertyValue(); p.Name = n; p.Value = v; return p
doc = desktop.loadComponentFromURL("private:factory/scalc", "_blank", 0, ())
libs = doc.BasicLibraries
libs.VBACompatibilityMode = True
if not libs.hasByName("Standard"): libs.createLibrary("Standard")
lib = libs.getByName("Standard")
lib.insertByName("SW", code)
sp = doc.getScriptProvider()
def run(name, *args):
    s = sp.getScript(f"vnd.sun.star.script:Standard.SW.{name}?language=Basic&location=document")
    return s.invoke(args, (), ())[0]

def sheet(n): return doc.Sheets.getByName(n)
def cell(sh, r, c): return sheet(sh).getCellByPosition(c-1, r-1).getString()
fails = []
def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg)
    if not cond: fails.append(msg)

try:
    run("SpecWizard_Start")
    names = list(doc.Sheets.ElementNames)
    print("sheets:", names)
    check(all(n in names for n in ["ウィザード","設問","回答"]), "シート作成")
    check(cell("ウィザード",2,2).startswith("ステップ 1 / 15"), "ステップ1表示: " + cell("ウィザード",2,2))
    check(cell("ウィザード",6,1) == "Q0101", "ID列")
    check(cell("ウィザード",7,7) == "2. 概要・目的", "ステップ一覧")
    # 入力して次へ
    run("T_TypeIn", 6, "テスト集計マクロ")
    run("T_TypeIn", 7, "1.0")
    run("SpecWizard_Next")
    check(cell("ウィザード",2,2).startswith("ステップ 2 / 15"), "次へ: " + cell("ウィザード",2,2))
    check(cell("回答",2,1) == "Q0101" and cell("回答",2,2) == "テスト集計マクロ", "回答保存")
    run("T_TypeIn", 6, "- 手作業が多い\n・ミスが出る")
    run("T_TypeIn", 9, "'=危険な入力")
    run("SpecWizard_Prev")
    check(cell("ウィザード",6,3) == "テスト集計マクロ", "戻ると回答が復元: " + cell("ウィザード",6,3))
    check(cell("ウィザード",6,8) == "必須未入力", "状態: " + cell("ウィザード",6,8))
    # ボタンを押さずに再度開いた場合も入力が残る
    run("T_TypeIn", 7, "受注処理")
    run("SpecWizard_Start")
    check(cell("ウィザード",7,3) == "受注処理", "Start で未保存入力を拾う: " + cell("ウィザード",7,3))
    run("T_SetInput", 3)
    run("SpecWizard_Jump")
    check(cell("ウィザード",2,2).startswith("ステップ 3 / 15"), "ステップ移動")
    run("SpecWizard_Check")
    run("SpecWizard_Generate")
    check("仕様書" in doc.Sheets.ElementNames, "仕様書シート")
    check(cell("仕様書",2,2) == "テスト集計マクロ", "表題")
    sp_ = sheet("仕様書")
    texts = [sp_.getCellByPosition(c, r).getString() for r in range(0, 200) for c in (1, 2)]
    check("=危険な入力" in texts, "数式に化けない")
    check("未決事項（自動抽出）" in texts, "未決事項")
    run("T_SetSave", OUT_MD)
    run("SpecWizard_ExportMarkdown")
    md = open(OUT_MD, encoding="utf-8", errors="replace").read()
    check(md.startswith("# マクロ開発仕様書：テスト集計マクロ"), "Markdown 表題")
    check("- 手作業が多い\n- ミスが出る" in md, "Markdown 箇条書き")
    run("SpecWizard_ClearAnswers")
    check(cell("回答",2,1) == "", "回答消去")
finally:
    print("---- log ----")
    try: print(run("T_GetLog"))
    except Exception as e: print(e)
    doc.close(True)
    try: desktop.terminate()
    except Exception: pass
    proc.wait(timeout=20)
print("FAILS:", fails)
sys.exit(1 if fails else 0)
