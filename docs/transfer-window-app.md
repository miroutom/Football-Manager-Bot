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

---

## Остановка и перезапуск

### Остановить сервер

Сервер крутится в **терминале**, пока вы его не остановите. Закрытие вкладки браузера сервер **не** гасит.

| Способ | Действие |
|--------|----------|
| **Терминал** | Клик в окно, где запущен app → **Ctrl+C** (Mac/Linux) |
| **macOS .app** | Закрыть окно терминала или **Cmd+Q** в TransferWindow.app |
| **Принудительно** | см. «Порт занят» ниже |

Перед остановкой в мультиплеере live-правки уже на диске хоста; отдельно «Сохранить» не обязательно.

### Перезапустить (тот же режим)

Из **корня проекта**:

```bash
# 1. Остановить старый процесс (Ctrl+C в терминале)
#    или, если терминал потеряли:
lsof -i :8765
kill <PID>          # подставь число из колонки PID

# 2. Запустить снова — той же командой, что и в первый раз:

# solo (только ты):
python3 tools/transfer_window_app/main.py

# мультиплеер, разные квартиры:
./tools/transfer_window_app/share_remote.sh
# или: python3 tools/transfer_window_app/main.py --tunnel

# мультиплеер, одна Wi‑Fi:
python3 tools/transfer_window_app/main.py --lan
```

Браузер у хоста: **http://127.0.0.1:8765/** (обнови страницу или открой заново).

### После перезапуска `--tunnel`

- Старая ссылка `https://….trycloudflare.com` **перестаёт работать** после перезапуска.
- В терминале появится **новая** ссылка (~10–30 с) — отправь её другу снова.
- В шапке app: **«Ссылка для друга» → Копировать** (когда ссылка готова).
- У друга должна быть метка **● live** — иначе перезагрузи страницу по новой ссылке.

### Переключить режим (solo ↔ tunnel ↔ lan)

Нельзя «докинуть» `--tunnel` к уже запущенному процессу — нужен **полный перезапуск**:

```bash
lsof -i :8765
kill <PID>
python3 tools/transfer_window_app/main.py --tunnel   # или --lan, или без флагов
```

Если после `--lan` или `--tunnel` **сразу вернулся prompt** и нет строки про LAN/туннель — порт всё ещё занят **старым** сервером (часто без LAN). Снова `lsof` → `kill` → запуск с нужным флагом.

### `run.sh` и «Уже запущено»

`./tools/transfer_window_app/run.sh` **не перезапускает** сервер, если порт 8765 занят — только откроет браузер. Для смены режима или `--tunnel` сначала **останови** старый процесс (Ctrl+C или `kill`).

### Другой порт

```bash
python3 tools/transfer_window_app/main.py --tunnel --port 9000
```

У напарника в ссылке будет `:9000` (для tunnel — новый URL от cloudflared).

---

## Мультиплеер (два компа, одно окно)

Один человек **хостит** на своём компе (нужен проект + БД). Второй подключается **только браузером**.

#### Из разных квартир (рекомендуется)

Один **хостит** (Windows/Mac/Linux + проект + БД). Второй **только открывает ссылку в браузере** — cloudflared на машине напарника **не нужен**.

**Windows (хост):**

```bat
python tools\transfer_window_app\export_rosters.py
tools\transfer_window_app\share_remote.bat
```

Один раз: `winget install Cloudflare.cloudflared`

**macOS (хост):**

```bash
python3 tools/transfer_window_app/export_rosters.py
./tools/transfer_window_app/share_remote.sh
```

Один раз: `brew install cloudflared`

**macOS / телефон (напарник):** открыть `https://….trycloudflare.com` из терминала хоста — больше ничего ставить не надо.

Через ~10–30 с появится **`https://….trycloudflare.com`** — эту ссылку отправляешь напарнику.

- Держите терминал хоста **открытым**, пока играете.
- Ссылка **временная** — только для доверенного напарника.
- В шапке app: **«Ссылка для друга» → Копировать**.

**Корп. tunneler (опционально):** `set TW_TUNNEL_BACKEND=tunneler` (Windows) / `export TW_TUNNEL_BACKEND=tunneler` (Mac) — см. [si-infra tunneler](https://docs.yandex-team.ru/si-infra/tunneler/tunneler).

**Альтернатива:** [Tailscale](https://tailscale.com) на обоих → хост `--lan`, друг открывает **`100.x.x.x`**.

#### Одна Wi‑Fi / одна квартира

```bash
python3 tools/transfer_window_app/export_rosters.py
python3 tools/transfer_window_app/main.py --lan
```

В терминале — **`http://192.168.x.x:8765/`** (не `172.31.x.x` — это часто VPN).

**Как работает (общее)**

- Общий сейв на машине хоста; у каждого сохранения растёт **revision** (`rev N` в шапке).
- В мультиплеере (**`--tunnel` / `--lan`**) включён режим **live** (зелёная метка **● live**): правки **автоматически сохраняются** (~0.7 с после действия) и подтягиваются у напарника (~1 с).
- Кнопка **Сохранить** по-прежнему есть — для явного сохранения с предупреждением о неполных заявках.
- Если оба правите **одновременно** одно и то же — возможен конфликт: жёлтая плашка «Обновить» или перезапишите сохранением.
- Трансферы **между клубами друг друга** — нормально: один общий стейт всех 40 команд.

**Важно:** хост должен держать app запущенным; экспорт в бот делает любой, кто подключён к хосту (файлы пишутся на комп хоста).

Подробнее про остановку и перезапуск: раздел [Остановка и перезапуск](#остановка-и-перезапуск) выше.

**Ссылка не открывается у друга (LAN)**

1. Вы в **разных квартирах** → используйте **`--tunnel`**, не `--lan`.
2. Для LAN: отправляй **Wi‑Fi IP** (`192.168.x.x`), не `172.31.x.x` — последний часто VPN.
3. Оба в **одной Wi‑Fi** (не мобильный интернет у друга).
4. На Mac: *Системные настройки → Сеть → Firewall* — разреши входящие для **Python**.
5. Проверка у себя: открой `http://192.168.1.124:8765/` (свой IP из `ifconfig en0`).

См. также [Остановка и перезапуск](#остановка-и-перезапуск).

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
