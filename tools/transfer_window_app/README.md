# Трансферное окно — portable app (лето / зима)

Одно приложение, переключатель в шапке:

| Окно | Лимит |
|------|--------|
| **Лето** | 5 IN / 5 OUT |
| **Зима** | 2 IN / 2 OUT |

Сохранения раздельные: `transfer_window_state_summer.json` и `transfer_window_state_winter.json`.

## Запуск (из корня проекта, с БД)

```bash
python3 tools/transfer_window_app/export_rosters.py   # актуальные составы из season DB
./tools/transfer_window_app/run.sh
# или: python3 tools/transfer_window_app/main.py
```

Браузер: `http://127.0.0.1:8765/` (порт: `--port N`).

## macOS

```bash
cd tools/transfer_window_app
./run.sh                 # нужен Python 3
# или сборка .app:
./build_macos.sh
open dist/TransferWindow.app
# если macOS ругается:
xattr -dr com.apple.quarantine dist/TransferWindow.app
```

Рядом с `.app` держите `rosters.json`. Состояние пишется в ту же папку.

## Windows

1. `pip install pyinstaller openpyxl`
2. `build_windows.bat` из этой папки
3. `dist/TransferWindow.exe` + `rosters.json`

## Функции

- 40 клубов, схемы как в боте, drag-and-drop
- Счётчики IN/OUT по выбранному окну; красная рамка, если лимит превышен
- Сохранить / выгрузить составы и переходы (файлы с суффиксом `_summer` / `_winter`)
