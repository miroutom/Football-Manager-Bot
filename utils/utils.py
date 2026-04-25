import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

Base = declarative_base()

# Абсолютный путь к проекту (работает при запуске из любой директории)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DB_DIR = os.path.join(PROJECT_ROOT, 'db')

# Рабочие БД (заявки + стата после синка). Снимок «до переноса»: league_new.db / champions_league_new.db / common.db.
LEAGUE_DB_FILE = "league_synced.db"
CHAMPIONS_LEAGUE_DB_FILE = "champions_league_synced.db"
COMMON_DB_FILE = "common_synced.db"
LEAGUE_DB_PATH = os.path.join(_DB_DIR, LEAGUE_DB_FILE)
CHAMPIONS_LEAGUE_DB_PATH = os.path.join(_DB_DIR, CHAMPIONS_LEAGUE_DB_FILE)
COMMON_DB_PATH = os.path.join(_DB_DIR, COMMON_DB_FILE)

# Три БД: национальные лиги, ЛЧ, объединённая (лига + ЛЧ)
engine_league = create_engine(f"sqlite:///{LEAGUE_DB_PATH}")
engine_cl = create_engine(f"sqlite:///{CHAMPIONS_LEAGUE_DB_PATH}")
engine_common = create_engine(f"sqlite:///{COMMON_DB_PATH}")

SessionLeague = sessionmaker(bind=engine_league)
SessionCL = sessionmaker(bind=engine_cl)
SessionCommon = sessionmaker(bind=engine_common)

session_league = SessionLeague()
session_cl = SessionCL()
session_common = SessionCommon()

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
