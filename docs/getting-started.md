# Запуск бота

## Требования

- Python 3.10+ (рекомендуется 3.11+)
- SQLite-базы в `db/` (см. [project-structure.md](project-structure.md))

## Установка зависимостей

Из **корня проекта**:

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Конфигурация

```bash
cp bot/.env.example bot/.env
```

В `bot/.env`:

- `TELEGRAM_BOT_TOKEN` — токен от [@BotFather](https://t.me/BotFather)
- `ALLOWED_USER_IDS` — необязательно; если задан, бот отвечает только этим id

Файл `.env` в git не коммитится.

## Запуск

Из корня проекта:

```bash
python -m bot
```

или:

```bash
python bot/run_bot.py
```

Бот стартует в режиме long polling. При первом запуске выполняются миграции SQLite (колонки status, left_team, discipline и т.д.).

## Полезные команды в Telegram

| Команда | Назначение |
|---------|------------|
| `/start` | Главное меню |
| `/wc` | Меню чемпионата мира |
| `/season` | Сезон, переключение (если настроено) |

Точный список команд задаётся в `bot/bot_commands.py`.

## Типичные проблемы

**«Не задан TELEGRAM_BOT_TOKEN»** — нет `bot/.env` или пустой токен.

**Бот молчит** — проверь `ALLOWED_USER_IDS`: твой Telegram id должен быть в списке.

**Нет игроков / пустые составы** — проверь `db/season_state.json` и активную БД сезона (`utils/season_paths.py`).

## Связанные документы

- [transfer-window-app.md](transfer-window-app.md) — desktop/web app для трансферного окна
- [project-structure.md](project-structure.md) — где лежат БД и данные
