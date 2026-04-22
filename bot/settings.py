"""
Загрузка настроек бота из переменных окружения и файла bot/.env

Создайте файл bot/.env на основе bot/.env.example (секреты не коммитятся).
"""
from __future__ import annotations

import os
from pathlib import Path

_BOT_DIR = Path(__file__).resolve().parent
_ENV_FILE = _BOT_DIR / ".env"

try:
    from dotenv import load_dotenv

    load_dotenv(_ENV_FILE)
except ImportError:
    pass


def get_bot_token() -> str:
    token = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    if not token:
        raise RuntimeError(
            "Не задан TELEGRAM_BOT_TOKEN. Скопируйте bot/.env.example в bot/.env "
            "и впишите токен от @BotFather."
        )
    return token


def get_allowed_user_ids() -> frozenset[int]:
    """
    Пустой набор = проверка отключена (бот доступен всем).
    Ненадолго для отладки; в проде задайте ALLOWED_USER_IDS.
    """
    raw = (os.environ.get("ALLOWED_USER_IDS") or "").strip()
    if not raw:
        return frozenset()
    ids: list[int] = []
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        ids.append(int(part))
    return frozenset(ids)
