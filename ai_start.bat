@echo off
chcp 65001 > nul
cd /d "%~dp0"
if not exist .venv\Scripts\activate.bat goto nosetup
call .venv\Scripts\activate.bat

rem Claude API キーを環境変数 ANTHROPIC_API_KEY に設定しておくと、画面での入力が不要になる
echo AI 全頭分析を起動しています。まもなくブラウザが開きます。
echo 終了するときは、この黒い画面を閉じてください。
echo.
start "" /min cmd /c "timeout /t 5 > nul & start http://localhost:8502"
streamlit run ai_app.py --server.port 8502 --server.headless true --browser.gatherUsageStats false
pause
exit /b 0

:nosetup
echo 先に setup.bat をダブルクリックしてセットアップしてください。
pause
exit /b 1
