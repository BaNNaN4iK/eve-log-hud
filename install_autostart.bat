@echo off
chcp 65001 >nul
setlocal EnableExtensions
rem EVE Log Watcher: автозагрузка при входе в Windows + запуск в фоне (без окна)
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

rem --- pythonw.exe (или pyw.exe) — запуск без консольного окна ---
set "PYW="
for %%d in ("%PY%") do (
  if /i "%%~nxd"=="py.exe" ( if exist "%%~dpdpyw.exe" set "PYW=%%~dpdpyw.exe" ) else ( if exist "%%~dpdpythonw.exe" set "PYW=%%~dpdpythonw.exe" )
)
if not defined PYW for /f "delims=" %%i in ('where pythonw.exe 2^>nul') do if not defined PYW set "PYW=%%i"
if not defined PYW (
  echo [ОШИБКА] Не найден pythonw.exe — без него приложение не может работать в фоне без окна.
  echo Переустановите Python с https://www.python.org/downloads/ ^(стандартная установка содержит pythonw.exe^).
  echo.
  pause
  exit /b 1
)
echo Python:   %PY% %PYARG%
echo Без окна: %PYW%

rem --- остановить уже работающую копию (если есть) ---
"%PY%" %PYARG% "%SCRIPT%" --stop >nul 2>&1

rem --- запись автозагрузки (только для текущего пользователя) ---
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v EVELogWatcher /t REG_SZ /d "\"%PYW%\" %PYARG% \"%SCRIPT%\"" /f >nul
if errorlevel 1 (
  echo [ОШИБКА] Не удалось записать автозагрузку в реестр.
  pause
  exit /b 1
)
echo Автозагрузка включена ^(HKCU\...\Run\EVELogWatcher^).

rem --- запуск в фоне ---
start "" "%PYW%" %PYARG% "%SCRIPT%"

set "PORT=47322"
for /f "tokens=2 delims=:, " %%p in ('findstr /c:"\"web_port\"" config.json 2^>nul') do set "PORT=%%p"
timeout /t 3 /nobreak >nul
"%PY%" %PYARG% -c "import urllib.request,sys;urllib.request.urlopen('http://localhost:%PORT%/api/live',timeout=5)" >nul 2>&1
if errorlevel 1 (
  echo.
  echo Приложение запущено, но страница пока не отвечает. Подождите несколько секунд
  echo или посмотрите watcher.log. Проверить с окном: test_in_window.bat
) else (
  echo.
  echo Готово! EVE Log Watcher работает в фоне.
)
echo Страница: http://localhost:%PORT%
echo.
pause
