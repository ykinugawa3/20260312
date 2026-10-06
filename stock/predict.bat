@echo off
chcp 65001 > nul
cd /d "%~dp0"
if not exist .venv\Scripts\activate.bat goto nosetup
call .venv\Scripts\activate.bat

rem 実データ (data\real.db) があればそちらを使う
set DB=data\kabu.db
if exist data\real.db set DB=data\real.db
echo データ: %DB%
kabu --db %DB% predict --top-n 30 --output ranking.csv
pause
exit /b 0

:nosetup
echo 先に setup.bat をダブルクリックしてセットアップしてください。
pause
exit /b 1
