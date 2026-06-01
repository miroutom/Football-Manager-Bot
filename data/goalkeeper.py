# -*- coding: utf-8 -*-

from sqlalchemy import Boolean, Column, Integer, String

from utils.utils import Base

positions = ["ВРТ"]


def update_goalkeeper_stats(
        session,
        name: str,
        overall: int,
        position: str = "",
        team: str = "",
        matches: int = 0,
        trophies: int = 0,
        missed_goals_per_match: int = 0,
        clean_sheet: int = 0,
        golden_ball: bool = False,
):
    query = session.query(Goalkeeper)
    players = query.filter_by(name=name)

    if players.count() > 1:
        players = query.filter_by(name=name, team=team)

    if players.count() > 1:
        players = query.filter_by(name=name, team=team, position=position)

    player = players.first()

    if not player:
        print(f"Игрок {name!r} (клуб {team!r}, поз. {position!r}) не найден.")
        return

    player.matches += matches
    player.overall = overall if overall != 0 else player.overall
    player.clean_sheets += clean_sheet if matches != 0 else 0
    player.missed_goals += missed_goals_per_match if matches != 0 else 0
    player.trophies += trophies
    player.golden_balls += int(golden_ball)

    session.commit()


class Goalkeeper(Base):
    __tablename__ = 'goalkeepers'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    overall = Column(Integer, nullable=False)
    team = Column(String, nullable=False)
    position = Column(String, nullable=False)
    matches = Column(Integer, default=0)
    clean_sheets = Column(Integer, default=0)
    missed_goals = Column(Integer, default=0)
    # БД лиги: трофеи лиги; БД ЛЧ: трофеи ЛЧ; common — сумма.
    trophies = Column(Integer, default=0)
    golden_balls = Column(Integer, default=0)
    golden_boots = Column(Integer, default=0)
    golden_gloves = Column(Integer, default=0)
    golden_boys = Column(Integer, default=0)
    nation = Column(String, nullable=True)
    status = Column(String, nullable=True)
    left_team = Column(Boolean, default=False, nullable=False)
    yellow_cards = Column(Integer, default=0)
    red_cards = Column(Integer, default=0)
