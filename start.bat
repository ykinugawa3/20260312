@echo off
chcp 65001 > nul
cd /d "%~dp0"
if not exist .venv\Scripts\activate.bat goto nosetup
call .venv\Scripts\activate.bat

echo 競馬予想ソフトを起動しています。まもなくブラウザが開きます。
echo 終了するときは、この黒い画面を閉じてください。
echo.
rem サーバーの起動を少し待ってからブラウザを開く
start "" /min cmd /c "timeout /t 5 > nul & start http://localhost:8501"
streamlit run app.py --server.headless true --browser.gatherUsageStats false
pause
exit /b 0

:nosetup
echo 先に setup.bat をダブルクリックしてセットアップしてください。
pause
exit /b 1
