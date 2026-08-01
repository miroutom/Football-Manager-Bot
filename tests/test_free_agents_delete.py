# -*- coding: utf-8 -*-
from utils.free_agents_db import (
    add_free_agent_player,
    delete_free_agent_player,
    list_free_agents,
    open_fa_session,
)


def test_delete_free_agent_player(monkeypatch):
    import utils.free_agents_db as mod

    store: list[dict] = []

    class FakeRow:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    class FakeQuery:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return list(self._rows)

        def filter(self, *a, **k):
            return self

    class FakeSession:
        def query(self, Cls):
            return FakeQuery(r for r in store if r.get("_cls") is Cls)

        def delete(self, row):
            store[:] = [r for r in store if r is not row]

        def commit(self):
            pass

        def close(self):
            pass

    class FakeEng:
        def dispose(self):
            pass

    monkeypatch.setattr(mod, "open_fa_session", lambda: (FakeSession(), FakeEng()))
    monkeypatch.setattr(mod, "remove_free_agent_after_signing", lambda n, p: True)

    assert delete_free_agent_player(name="Test", position="ST") is True
    assert delete_free_agent_player(name="", position="") is False


def test_delete_free_agent_by_person_id(monkeypatch):
    import utils.free_agents_db as mod
    from data.forward import Forward

    rows = [type("R", (), {"person_id": 42, "name": "X", "position": "ST"})()]

    class FakeSession:
        def query(self, Cls):
            class Q:
                def all(inner):
                    return list(rows)

            return Q()

        def delete(self, row):
            rows.remove(row)

        def commit(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(mod, "open_fa_session", lambda: (FakeSession(), type("E", (), {"dispose": lambda s: None})()))
    monkeypatch.setattr(mod, "_ALL", (Forward,))

    assert delete_free_agent_player(person_id=42) is True
    assert rows == []
