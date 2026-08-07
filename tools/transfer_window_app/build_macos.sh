#!/bin/bash
# Сборка Transfer Window для macOS (PyInstaller, облегчённая).
# Запускать ИЗ ЭТОЙ ПАПКИ (где main.py, web/, rosters.json).
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

python3 -m pip install -q 'pyinstaller>=6' openpyxl

# Без --windowed нельзя: нужен .app. Но выкидываем тяжёлые пакеты (PIL и т.п.),
# из‑за них холодный старт был несколько секунд.
# Важно: сейвы лежат НЕ в dist/, а в
#   ~/Library/Application Support/FootballManagerBot/transfer_window
# rm -rf dist безопасен для пользовательских сохранений.
rm -rf build dist TransferWindow.spec

pyinstaller --noconfirm --windowed --name TransferWindow \
  --add-data "web:web" \
  --add-data "rosters.json:." \
  --add-data "../../data/nations_all.json:data" \
  --add-data "../../data/world_cup_config.json:data" \
  --exclude-module PIL \
  --exclude-module pillow \
  --exclude-module numpy \
  --exclude-module pandas \
  --exclude-module matplotlib \
  --exclude-module scipy \
  --exclude-module cv2 \
  --exclude-module tkinter \
  --exclude-module test \
  --exclude-module unittest \
  --collect-submodules openpyxl \
  main.py

cp -f rosters.json dist/rosters.json
if [[ -d dist/TransferWindow.app ]]; then
  cp -f rosters.json "dist/TransferWindow.app/Contents/MacOS/rosters.json" 2>/dev/null || true
fi

echo ""
echo "Готово: dist/TransferWindow.app (+ dist/rosters.json рядом)"
echo "Первый запуск .app на Mac всё равно ~1–2 с (загрузка Python-рантайма)."
echo "Повторный клик, если сервер уже запущен — почти мгновенно откроет браузер."
echo ""
echo "Быстрее без сборки:"
echo "  ./run.sh"
echo "  или двойной клик: Start Transfer Window.command"
echo ""
echo "  open dist/TransferWindow.app"
echo "  xattr -dr com.apple.quarantine dist/TransferWindow.app"
