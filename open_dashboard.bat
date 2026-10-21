@echo off
chcp 65001 >nul
setlocal EnableExtensions
rem EVE Log Watcher: открыть страницу в браузере
cd /d "%~dp0"
set "PORT=47322"
for /f "tokens=2 delims=:, " %%p in ('findstr /c:"\"web_port\"" config.json 2^>nul') do set "PORT=%%p"
start "" "http://localhost:%PORT%"
