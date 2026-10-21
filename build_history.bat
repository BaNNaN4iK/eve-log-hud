@echo off
chcp 65001 >nul
setlocal EnableExtensions
rem EVE Log Watcher: пересобрать историю из существующих логов (--backfill)
cd /d "%~dp0"
set "SCRIPT=%~dp0eve_log_watcher.py"

rem --- поиск Python 3.9+ (python.exe рядом с pythonw.exe; заглушки Microsoft Store отсеиваются проверкой версии) ---
set "PY="
set "PYARG="
for /f "delims=" %%i in ('where python.exe 2^>nul') do if not defined PY (
  "%%i" -c "import sys;sys.exit(0 if sys.version_info>=(3,9) else 1)" >nul 2>&1 && set "PY=%%i"
)
if not defined PY for /f "delims=" %%i in ('where py.exe 2^>nul') do if not defined PY (
  "%%i" -3 -c "import sys;sys.exit(0 if sys.version_info>=(3,9) else 1)" >nul 2>&1 && ( set "PY=%%i" & set "PYARG=-3" )
)
if not defined PY (
  echo [ОШИБКА] Не найден Python 3.9 или новее.
  echo Установите Python с https://www.python.org/downloads/ ^(отметьте "Add python.exe to PATH"^) и запустите файл снова.
  echo.
  pause
  exit /b 1
)

echo Будут удалены history.csv, sessions.jsonl и state.json, а история пересобрана из логов
echo за период import_days из config.json (по умолчанию 30 дней).
echo Чтобы взять другой срок: build_history.bat 90
echo.
set "DAYS="
if not "%~1"=="" set "DAYS=--days %~1"
"%PY%" %PYARG% "%SCRIPT%" --backfill %DAYS%
if errorlevel 2 (
  echo.
  echo Сначала остановите фоновую версию: uninstall_autostart.bat ^(после пересборки снова install_autostart.bat^).
)
echo.
pause
