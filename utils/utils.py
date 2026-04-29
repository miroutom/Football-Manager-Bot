import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

Base = declarative_base()

# Абсолютный путь к проекту (работает при запуске из любой директории)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DB_DIR = os.path.join(PROJECT_ROOT, "db")

# Пути к рабочим БД: через season_paths (legacy или db/season_n/*.db)
def reinit_db_connections() -> None:
    """Пересоздать движки/сессии (после смены сезона)."""
    from utils import season_paths

    global LEAGUE_DB_PATH, CHAMPIONS_LEAGUE_DB_PATH, COMMON_DB_PATH
    global engine_league, engine_cl, engine_common
    global SessionLeague, SessionCL, SessionCommon
    global session_league, session_cl, session_common

    try:
        engine_league.dispose()
    except Exception:
        pass
    try:
        engine_cl.dispose()
    except Exception:
        pass
    try:
        engine_common.dispose()
    except Exception:
        pass

    LEAGUE_DB_PATH = season_paths.get_league_db_path()
    CHAMPIONS_LEAGUE_DB_PATH = season_paths.get_cl_db_path()
    COMMON_DB_PATH = season_paths.get_common_db_path()

    engine_league = create_engine(f"sqlite:///{LEAGUE_DB_PATH}")
    engine_cl = create_engine(f"sqlite:///{CHAMPIONS_LEAGUE_DB_PATH}")
    engine_common = create_engine(f"sqlite:///{COMMON_DB_PATH}")

    SessionLeague = sessionmaker(bind=engine_league)
    SessionCL = sessionmaker(bind=engine_cl)
    SessionCommon = sessionmaker(bind=engine_common)

    session_league = SessionLeague()
    session_cl = SessionCL()
    session_common = SessionCommon()


reinit_db_connections()

# Синонимы для путей (как раньше)
LEAGUE_DB_FILE = "league.db"  # смысловой label; фактическое имя в season_paths
CHAMPIONS_LEAGUE_DB_FILE = "champions_league.db"
COMMON_DB_FILE = "common.db"

# Для обратной совместимости
engine = engine_league
session = session_league

# Позиции игроков
forwards = ['ФРВ', 'ЛФА', 'ПФА', 'ЦФД', 'ЛФД', 'ПФД']
midfielders = ['ЦАП', 'ЦП', 'ЦОП', 'ЛП', 'ПП', 'ЛЦП', 'ПЦП']
defenders = ['ЦЗ', 'ЛЗ', 'ПЗ', 'ЛФЗ', 'ПФЗ', 'ЛЦЗ', 'ПЦЗ']
goalkeepers = ['ВРТ']


def get_session(tournament: str = 'league'):
    """
    Получить сессию
    tournament: 'league' или 'l' - национальные лиги
                'cl' - Лига Чемпионов
                'common' / 'merged' - объединённая лига+ЛЧ (``common_synced.db``)
    """
    if tournament in ['cl', 'champ_league']:
        return session_cl
    if tournament in ('common', 'merged', 'all'):
        return session_common
    return session_league


def get_engine(tournament: str = 'league'):
    """Получить движок БД"""
    if tournament in ['cl', 'champ_league']:
        return engine_cl
    if tournament in ('common', 'merged', 'all'):
        return engine_common
    return engine_league


def rate_from_ga_forward(ga):
    if ga >= 2.0:
        return 9.0
    elif ga >= 1.5:
        return 8.5
    elif ga >= 1.0:
        return 8.0
    elif ga >= 0.7:
        return 7.5
    elif ga >= 0.5:
        return 7.0
    elif ga >= 0.3:
        return 6.5
    else:
        return 6.0


def rate_from_ga_mid(ga):
    if ga >= 1.5:
        return 9.0
    elif ga >= 1.0:
        return 8.5
    elif ga >= 0.7:
        return 8.0
    elif ga >= 0.5:
        return 7.5
    elif ga >= 0.3:
        return 7.0
    elif ga >= 0.2:
        return 6.5
    else:
        return 6.0
