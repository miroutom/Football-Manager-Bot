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
# мультиплеер по Wi‑Fi:
# python3 tools/transfer_window_app/main.py --lan
```

Альтернатива без shell-скрипта:

```bash
python3 tools/transfer_window_app/main.py
```

Открой в браузере: **http://127.0.0.1:8765/**

### Мультиплеер (два компа, одно окно)

Один человек **хостит** на своём компе (нужен проект + БД). Второй подключается **только браузером**.

#### Из разных квартир (рекомендуется)

Wi‑Fi/LAN не подходит, если вы в разных сетях. Поднимите **публичный туннель**:

```bash
python3 tools/transfer_window_app/export_rosters.py
brew install cloudflared   # один раз
./tools/transfer_window_app/share_remote.sh
# или:
python3 tools/transfer_window_app/main.py --tunnel
```

Через ~10–30 с в терминале появится **`https://….trycloudflare.com`** — эту ссылку открывает напарник (с телефона, другой квартиры, мобильного интернета).

- Держите терминал с `--tunnel` **открытым**, пока играете.
- Ссылка **временная** и **без пароля** — только для доверенного напарника.
- В шапке app есть **«Ссылка для друга» → Копировать**.

**Альтернатива:** [Tailscale](https://tailscale.com) на обоих Mac/PC → хост запускает `--lan`, друг открывает адрес **`100.x.x.x`** из терминала (строка «Tailscale»).

#### Одна Wi‑Fi / одна квартира

```bash
python3 tools/transfer_window_app/export_rosters.py
python3 tools/transfer_window_app/main.py --lan
```

В терминале — **`http://192.168.x.x:8765/`** (не `172.31.x.x` — это часто VPN).

**Как работает (общее)**

- Общий сейв на машине хоста; у каждого сохранения растёт **revision** (`rev N` в шапке).
- После правок жмите **Сохранить** — напарник подтянет изменения (~2.5 с) или увидит жёлтую плашку «Обновить».
- Если оба сохранили одновременно — конфликт: можно загрузить версию напарника или договориться и сохранить снова.
- Трансферы **между клубами друг друга** — нормально: один общий стейт всех 40 команд.

**Важно:** хост должен держать app запущенным; экспорт в бот делает любой, кто подключён к хосту (файлы пишутся на комп хоста).

Если после `--lan` **сразу вернулся prompt** без строки LAN — порт занят старым сервером (localhost). Перезапуск:

```bash
lsof -i :8765
kill <PID>
python3 tools/transfer_window_app/main.py --lan
```

**Ссылка не открывается у друга (LAN)**

1. Вы в **разных квартирах** → используйте **`--tunnel`**, не `--lan`.
2. Для LAN: отправляй **Wi‑Fi IP** (`192.168.x.x`), не `172.31.x.x` — последний часто VPN.
3. Оба в **одной Wi‑Fi** (не мобильный интернет у друга).
4. На Mac: *Системные настройки → Сеть → Firewall* — разреши входящие для **Python**.
5. Проверка у себя: открой `http://192.168.1.124:8765/` (свой IP из `ifconfig en0`).

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

**FA (свободные агенты):** в боте **📥 Свободные агенты** → `free_agents.json` → в app **«Загрузить FA из бота»**. Или **↻ FA из БД** на машине хоста (если пул уже в `free_agents.db`).

Обратно из бота в app: в transfer app есть **«Загрузить из бота»** (актуальные составы 40 клубов).

---

## Подробности реализации

- Код: `tools/transfer_window_app/`
- Web UI: `tools/transfer_window_app/web/`
- Экспорт составов: `export_rosters.py`
- Применение в БД: `utils/transfer_window_apply.py`, `scripts/apply_transfer_window_state.py`

См. также [../tools/transfer_window_app/README.md](../tools/transfer_window_app/README.md).
