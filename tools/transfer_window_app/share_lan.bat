@echo off
REM LAN-мультиплеер: одна Wi‑Fi. Напарник открывает http://192.168.x.x:8765/
setlocal
cd /d %~dp0
set ROOT=%~dp0..\..
cd /d "%ROOT%"

if not exist "tools\transfer_window_app\rosters.json" (
  echo Нет rosters.json — сначала:
  echo   python tools\transfer_window_app\export_rosters.py
  exit /b 1
)

set PORT=8765
if defined TW_PORT set PORT=%TW_PORT%

curl -sf -o nul http://127.0.0.1:%PORT%/ 2>nul
if not errorlevel 1 (
  curl -sf http://127.0.0.1:%PORT%/api/config 2>nul | findstr /C:"\"lan_mode\": true" >nul
  if errorlevel 1 (
    echo.
    echo ⚠️  На порту %PORT% уже сервер БЕЗ LAN ^(только этот ПК^).
    echo     Останови старый процесс ^(Ctrl+C^) и запусти share_lan.bat снова.
    exit /b 1
  )
  echo Уже запущено в LAN — см. IP в терминале хоста или «Ссылка для друга» в app.
  exit /b 0
)

echo.
echo Если друг не подключается — разреши Python в брандмауэре Windows
echo или: netsh advfirewall firewall add rule name="Transfer Window %PORT%" dir=in action=allow protocol=TCP localport=%PORT%
echo.

python tools\transfer_window_app\main.py --lan --port %PORT% %*
exit /b %ERRORLEVEL%
