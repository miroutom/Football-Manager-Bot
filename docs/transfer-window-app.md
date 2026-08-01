# Transfer Window App

Локальное приложение для расстановки составов и трансферов **40 клубов** в летнее / зимнее окно.

| Окно | Лимит |
|------|--------|
| **Лето** | 5 IN / 5 OUT |
| **Зима** | 2 IN / 2 OUT |

UI открывается в браузере. Сохранения: `transfer_window_state_summer.json` и `transfer_window_state_winter.json` (рядом с app).

---

## Запуск (macOS / Linux)

Из **корня проекта**, когда БД сезона актуальны:

```bash
# 1. Выгрузить составы из SQLite в rosters.json
python3 tools/transfer_window_app/export_rosters.py

# 2. Запустить сервер
./tools/transfer_window_app/run.sh
```

Альтернатива без shell-скрипта:

```bash
python3 tools/transfer_window_app/main.py
```

Открой в браузере: **http://127.0.0.1:8765/**

Другой порт:

```bash
python3 tools/transfer_window_app/main.py --port 9000
```

### macOS: двойной клик

В папке `tools/transfer_window_app/` есть `Start Transfer Window.command` — запускает тот же сервер (нужен Python 3 и уже собранный `rosters.json`).

### Если «уже запущено»

`run.sh` проверяет порт 8765 и просто откроет браузер, если сервер уже работает.

---

## Сборка standalone (без Python у пользователя)

**macOS:**

```bash
cd tools/transfer_window_app
./build_macos.sh
open dist/TransferWindow.app
# если Gatekeeper ругается:
xattr -dr com.apple.quarantine dist/TransferWindow.app
```

**Windows:**

```bat
cd tools\transfer_window_app
pip install pyinstaller openpyxl
build_windows.bat
```

Рядом с `.app` / `.exe` держи `rosters.json`. Состояние пишется в ту же папку.

---

## Основные функции

- 40 клубов, схемы как в боте, drag-and-drop
- Счётчики IN/OUT; красная рамка при превышении лимита
- 🏥 — травма на 6-й месяц (из `data/player_discipline.json`)
- Смена схемы 1–10 на карточке клуба
- Сохранить / выгрузить составы и переходы (`*_summer` / `*_winter`)
- Клик по рейтингу — правка OVR (1–99)
- **×** у игрока в пуле FA — удалить из `free_agents.db` (с подтверждением)

---

## Связь с ботом

1. В transfer app: **Сохранить** → выгрузить `squads_export_*.txt` и `transfers_export_*.txt` (или `transfer_window_state_*.json`).
2. В боте: **🔄 Трансферы** → загрузить файлы (сначала составы, потом переходы).

Обратно из бота в app: в transfer app есть **«Загрузить из бота»** (актуальные составы 40 клубов).

---

## Подробности реализации

- Код: `tools/transfer_window_app/`
- Web UI: `tools/transfer_window_app/web/`
- Экспорт составов: `export_rosters.py`
- Применение в БД: `utils/transfer_window_apply.py`, `scripts/apply_transfer_window_state.py`

См. также [../tools/transfer_window_app/README.md](../tools/transfer_window_app/README.md).
