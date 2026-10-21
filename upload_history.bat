@echo off
chcp 65001 >nul
setlocal EnableExtensions
rem EVE Log Watcher: отправить накопленную историю в Alliance Auth
rem Повторный запуск безопасен: сервер не создаёт дублей. Другой срок: upload_history.bat 90
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

set "DAYS="
if not "%~1"=="" set "DAYS=--days %~1"
"%PY%" %PYARG% "%SCRIPT%" --aa-upload-history %DAYS%
echo.
pause
