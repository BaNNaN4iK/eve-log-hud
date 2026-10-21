@echo off
chcp 65001 >nul
setlocal EnableExtensions
rem EVE Log HUD: окно поверх игры с данными трекера. Закрыть — крестик на окне.
cd /d "%~dp0"
set "SCRIPT=%~dp0modules\overlay\overlay.py"

rem --- поиск Python 3.9+ ---
set "PY="
for /f "delims=" %%i in ('where python.exe 2^>nul') do if not defined PY (
  "%%i" -c "import sys;sys.exit(0 if sys.version_info>=(3,9) else 1)" >nul 2>&1 && set "PY=%%i"
)
if not defined PY (
  echo [ОШИБКА] Не найден Python 3.9 или новее.
  echo Установите Python с https://www.python.org/downloads/ ^(отметьте "Add python.exe to PATH"^) и запустите файл снова.
  echo.
  pause
  exit /b 1
)

rem --- pythonw.exe — запуск без консольного окна ---
set "PYW="
for %%d in ("%PY%") do if exist "%%~dpdpythonw.exe" set "PYW=%%~dpdpythonw.exe"
if not defined PYW set "PYW=%PY%"

start "" "%PYW%" "%SCRIPT%" %*
