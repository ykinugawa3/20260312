@echo off
chcp 65001 > nul
cd /d "%~dp0"
if exist .venv\Scripts\activate.bat goto ready

rem 初回のみ: Python 環境を作って必要なライブラリを入れる
python --version > nul 2>&1
if errorlevel 1 goto nopython
echo 初回セットアップ中です (数分かかります)...
python -m venv .venv
if errorlevel 1 goto fail
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip > nul
pip install -e ".[ui]"
if errorlevel 1 goto fail
goto run

:ready
call .venv\Scripts\activate.bat

:run
echo TODO アプリを起動しています。まもなくブラウザが開きます。
echo 終了するときは、この黒い画面を閉じてください。
echo.
rem 競馬予想ソフト (8501) と同時に使えるようにポートを分ける
start "" /min cmd /c "timeout /t 5 > nul & start http://localhost:8502"
streamlit run todo\app.py --server.port 8502 --server.headless true --browser.gatherUsageStats false
pause
exit /b 0

:nopython
echo Python が見つかりません。
echo https://www.python.org/downloads/ から Python 3.10 以上をインストールしてください。
echo インストール画面の最初で "Add python.exe to PATH" に必ずチェックを入れてください。
pause
exit /b 1

:fail
echo.
echo エラーが発生しました。上に表示されたメッセージを確認してください。
pause
exit /b 1
