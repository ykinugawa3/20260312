@echo off
chcp 65001 > nul
cd /d "%~dp0"
if not exist .venv\Scripts\activate.bat goto nosetup
call .venv\Scripts\activate.bat

echo 天下布武 Lite を起動しています。まもなくブラウザが開きます。
echo 終了するときは、この黒い画面を閉じてください。
echo.
rem 競馬予想ソフト (8501) と同時に使えるようポートを分ける
start "" /min cmd /c "timeout /t 5 > nul & start http://localhost:8502"
streamlit run sengoku_app.py --server.port 8502 --server.headless true --browser.gatherUsageStats false
pause
exit /b 0

:nosetup
echo 先に sengoku_setup.bat をダブルクリックしてセットアップしてください。
pause
exit /b 1
