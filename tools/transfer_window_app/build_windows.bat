@echo off
REM Сборка TransferWindow.exe — запускать ИЗ ЭТОЙ ПАПКИ (где main.py, web\, rosters.json).
REM Требуется: pip install pyinstaller openpyxl

cd /d %~dp0

if not exist rosters.json (
  echo ОШИБКА: нет rosters.json в этой папке.
  pause
  exit /b 1
)
if not exist main.py (
  echo ОШИБКА: нет main.py в этой папке.
  pause
  exit /b 1
)
if not exist web\index.html (
  echo ОШИБКА: нет папки web\ в этой папке.
  pause
  exit /b 1
)

echo Проверка pyinstaller...
py -m pip install pyinstaller openpyxl -q 2>nul
python -m pip install pyinstaller openpyxl -q 2>nul

pyinstaller --noconfirm --onefile --name TransferWindow ^
  --add-data "web;web" ^
  --add-data "rosters.json;." ^
  --hidden-import openpyxl ^
  main.py

if errorlevel 1 (
  echo.
  echo Не удалось собрать. Попробуйте: pip install pyinstaller openpyxl
  pause
  exit /b 1
)

copy /Y rosters.json dist\rosters.json
echo.
echo Готово:
echo   dist\TransferWindow.exe
echo   dist\rosters.json
echo Скопируйте ОБА файла в одну папку и запускайте exe.
pause
