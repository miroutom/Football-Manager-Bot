@echo off
REM Хост Transfer Window + публичная ссылка (cloudflared). Напарник открывает только URL в браузере.
setlocal
cd /d %~dp0
set ROOT=%~dp0..\..
cd /d "%ROOT%"

if not exist "tools\transfer_window_app\rosters.json" (
  echo Нет rosters.json — сначала:
  echo   python tools\transfer_window_app\export_rosters.py
  exit /b 1
)

if defined TW_TUNNEL_URL (
  python tools\transfer_window_app\main.py --tunnel --tunnel-url "%TW_TUNNEL_URL%" %*
  exit /b %ERRORLEVEL%
)

where cloudflared >nul 2>&1
if errorlevel 1 (
  if not defined CLOUDFLARED_BIN (
    echo Нужен cloudflared:
    echo   winget install Cloudflare.cloudflared
    echo   или скачай: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/
    exit /b 1
  )
)

python tools\transfer_window_app\main.py --tunnel %*
exit /b %ERRORLEVEL%
