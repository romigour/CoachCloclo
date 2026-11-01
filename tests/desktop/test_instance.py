import pytest

from coach.desktop.instance import (
    NoFreePort,
    acquire_mutex,
    pick_port,
    read_state,
    release_mutex,
    write_state,
)


def test_pick_port_default():
    assert pick_port(lambda p: True) == 8765


def test_pick_port_fallback():
    assert pick_port(lambda p: p >= 8767) == 8767


def test_pick_port_none_free():
    with pytest.raises(NoFreePort):
        pick_port(lambda p: False)


def test_pick_port_lit_les_attributs_du_module_a_l_appel(monkeypatch):
    from coach.desktop import instance

    monkeypatch.setattr(instance, "PORTS", (9001, 9002))
    monkeypatch.setattr(instance, "port_free", lambda p: p == 9002)
    assert pick_port() == 9002


def test_state_roundtrip(coach_home):
    write_state(8766, 42)
    assert read_state() == {"port": 8766, "pid": 42}


def test_state_absent(coach_home):
    assert read_state() is None


def test_state_corrupt(coach_home):
    (coach_home / "desktop.json").write_text("{")
    assert read_state() is None


def test_mutex_is_exclusive(coach_home):
    h = acquire_mutex("CoachCloclo.Test")
    assert h is not None
    assert acquire_mutex("CoachCloclo.Test") is None
    release_mutex(h)
    h2 = acquire_mutex("CoachCloclo.Test")
    assert h2 is not None
    release_mutex(h2)
