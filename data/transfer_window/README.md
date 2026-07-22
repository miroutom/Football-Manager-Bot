# Трансферное окно

Одно приложение: **Лето 5/5** и **Зима 2/2** (переключатель в шапке).

## Запуск (Python 3)

```bash
./run.sh        # Mac/Linux
run.bat         # Windows — двойной клик
```

**Не нужен** весь проект — только эта папка (+ актуальный `rosters.json`).

## macOS .app

```bash
./build_macos.sh
open dist/TransferWindow.app
# если Gatekeeper:
xattr -dr com.apple.quarantine dist/TransferWindow.app
```

Рядом с `.app` — `rosters.json`. Состояния: `transfer_window_state_summer.json` / `_winter.json`.

## .exe для Windows

1. `pip install pyinstaller openpyxl`
2. **`build_windows.bat`** из этой папки
3. `dist\TransferWindow.exe` + `rosters.json`

## Функции

- Drag-and-drop, счётчики IN/OUT по выбранному окну
- Красная рамка клуба при превышении лимита
- Сохранить / выгрузить составы и переходы
