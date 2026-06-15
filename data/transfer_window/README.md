# Трансферное окно

## Запуск (Python 3)

```bash
./run.sh        # Mac/Linux
run.bat         # Windows — двойной клик
```

**Не нужен** весь проект — только эта папка.

## .exe для Windows (без Python)

1. `pip install pyinstaller openpyxl`
2. Запустить **`build_windows.bat`** из этой же папки (не из корня проекта!)
3. Взять из `dist\`: `TransferWindow.exe` + `rosters.json`

## Функции

- 50 клубов, схемы как в боте, прокрутка вниз
- Drag-and-drop, счётчики IN/OUT, жёлтый = новый игрок
- Сохранить → `transfer_window_state.json`
- Выгрузить → `transfers_export.txt` / `.xlsx`
