@echo off
chcp 65001 >nul
setlocal EnableExtensions
rem EVE Log Watcher: страница трекера отдельным окном (без вкладок и адресной строки)
cd /d "%~dp0"
set "PORT=47322"
for /f "tokens=2 delims=:, " %%p in ('findstr /c:"\"web_port\"" config.json 2^>nul') do set "PORT=%%p"
set "URL=http://localhost:%PORT%"

set "BROWSER="
for %%b in (
  "%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
  "%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"
  "%ProgramFiles%\Google\Chrome\Application\chrome.exe"
  "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
  "%LocalAppData%\Google\Chrome\Application\chrome.exe"
) do if not defined BROWSER if exist "%%~b" set "BROWSER=%%~b"

if defined BROWSER (
  start "" "%BROWSER%" --app=%URL% --window-size=1280,860
) else (
  rem нет Edge и Chrome — открываем обычной вкладкой
  start "" "%URL%"
)
