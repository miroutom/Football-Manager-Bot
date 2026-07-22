#!/bin/bash
# Сборка Transfer Window для macOS (PyInstaller).
# Запускать ИЗ ЭТОЙ ПАПКИ (где main.py, web/, rosters.json).
# Требуется: pip3 install pyinstaller openpyxl
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -f rosters.json ]]; then
  echo "ОШИБКА: нет rosters.json — сначала python3 export_rosters.py из корня проекта"
  exit 1
fi
if [[ ! -f main.py || ! -f web/index.html ]]; then
  echo "ОШИБКА: ожидаются main.py и web/index.html в этой папке"
  exit 1
fi

python3 -m pip install -q pyinstaller openpyxl

# onedir .app удобнее для macOS (данные рядом); также onefile binary
pyinstaller --noconfirm --windowed --name TransferWindow \
  --add-data "web:web" \
  --add-data "rosters.json:." \
  --hidden-import openpyxl \
  main.py

mkdir -p dist
cp -f rosters.json dist/rosters.json

# Если собралось .app — положить rosters рядом с .app
if [[ -d dist/TransferWindow.app ]]; then
  cp -f rosters.json dist/TransferWindow.app/../rosters.json 2>/dev/null || true
  # Также внутрь Contents/MacOS для fallback runtime_dir
  cp -f rosters.json "dist/TransferWindow.app/Contents/MacOS/rosters.json" 2>/dev/null || true
fi

echo ""
echo "Готово:"
echo "  dist/TransferWindow.app   (двойной клик) + dist/rosters.json рядом"
echo "  или dist/TransferWindow   (консольный бинарь, если без --windowed layout)"
echo ""
echo "Сохранения: transfer_window_state_summer.json / _winter.json рядом с приложением."
echo "Открыть из терминала (если Gatekeeper блокирует):"
echo "  open dist/TransferWindow.app"
echo "  xattr -dr com.apple.quarantine dist/TransferWindow.app"
