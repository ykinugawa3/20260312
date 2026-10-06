@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo ============================================
echo   株価予想ソフト (米国株) セットアップ
echo ============================================

rem Python が使えるか確認 (Microsoft Store の仮の python は失敗扱いになる)
python --version > nul 2>&1
if errorlevel 1 goto nopython

if exist .venv\Scripts\activate.bat goto venv_ready
echo [1/4] 専用の Python 環境を作成しています...
python -m venv .venv
if errorlevel 1 goto fail
:venv_ready
call .venv\Scripts\activate.bat

echo [2/4] 必要なライブラリを入れています (数分かかります)...
python -m pip install --upgrade pip > nul
pip install -e ".[dev,fetch]"
if errorlevel 1 goto fail

if exist data\kabu.db goto train
echo [3/4] 仮データを作成しています...
kabu sample
if errorlevel 1 goto fail

:train
echo [4/4] モデルを学習しています (1-2分かかります)...
kabu train
if errorlevel 1 goto fail

echo.
echo セットアップが完了しました。
echo predict.bat をダブルクリックすると銘柄ランキングが表示されます。
pause
exit /b 0

:nopython
echo.
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
