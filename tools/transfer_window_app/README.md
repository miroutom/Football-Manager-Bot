# Трансферное окно — portable app

## Запуск (из корня проекта, с БД season_3)

```bash
python3 tools/transfer_window_app/export_rosters.py
python3 tools/transfer_window_app/main.py
```

Откроется браузер на `http://127.0.0.1:8765/`.

## Сборка .exe (Windows)

1. Python 3.11+ и `pip install pyinstaller openpyxl`
2. `tools/transfer_window_app/build_windows.bat`
3. Из `dist/`: `TransferWindow.exe` + `rosters.json` в одну папку

Сохранение: `transfer_window_state.json` рядом с exe.  
Экспорт: `transfers_export.txt` / `transfers_export.xlsx`.

## Функции

- 50 клубов, схемы как в боте, прокрутка вниз
- Drag-and-drop игроков
- X/5 IN · Y/5 OUT, жёлтый = новый в клубе
- Сохранить / выгрузить переходы
