# -*- coding: utf-8 -*-
"""
Имена команд в data/squads_canonical/*.txt → как в pickle/БД (teams.py, .title() от leagues_config).
Если строка уже совпадает с ключом в словаре команд — алиас не нужен.
"""
SQUAD_TEAM_TO_DB = {
    # Ла Лига
    "Барса": "Барселона",
    "Атлетик Бильбао": "Атлетик",
    "Атлетико Мадрид": "Атлетико",
    "Райо": "Райо Вальекано",
}


def canonical_team_name(squad_name: str) -> str:
    """Преобразовать название из txt в то, что хранится в team у игроков."""
    s = squad_name.strip()
    return SQUAD_TEAM_TO_DB.get(s, s)
