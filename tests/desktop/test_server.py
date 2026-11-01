import socket

import httpx

from coach.api.app import create_app
from coach.desktop.server import AppServer
from coach.garmin.port import FakeGarminClient, Metrics
from coach.llm.provider import FakeLLMProvider


def _port_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _app():
    metrics = Metrics(hr_max=190, hr_rest=50, threshold_pace_s_km=300)
    return create_app(
        lan=False,
        garmin_factory=lambda: FakeGarminClient(metrics=metrics),
        llm_factory=lambda: FakeLLMProvider([]),
    )


def test_restart_keeps_app_and_port(coach_home):
    app = _app()
    port = _port_libre()
    srv = AppServer(app, port)
    srv.start("127.0.0.1")
    try:
        app.state.marker = "même app"
        assert httpx.get(f"http://127.0.0.1:{port}/api/version").status_code == 200
        srv.restart("0.0.0.0")
        assert srv.host == "0.0.0.0"
        assert httpx.get(f"http://127.0.0.1:{port}/api/version").status_code == 200
        assert app.state.marker == "même app"
    finally:
        srv.stop()


def test_stop_releases_port_and_is_idempotent(coach_home):
    port = _port_libre()
    srv = AppServer(_app(), port)
    srv.start("127.0.0.1")
    srv.stop()
    srv.stop()
    with socket.socket() as s:
        s.bind(("127.0.0.1", port))


def test_start_on_occupied_port_raises_quickly(coach_home):
    import time

    with socket.socket() as occupe:
        occupe.bind(("127.0.0.1", 0))
        occupe.listen()
        srv = AppServer(_app(), occupe.getsockname()[1])
        debut = time.monotonic()
        try:
            srv.start("127.0.0.1")
            raise AssertionError("RuntimeError attendue")
        except RuntimeError:
            pass
        assert time.monotonic() - debut < 5
        assert srv.host == ""


def test_failed_restart_falls_back_to_previous_host(coach_home, monkeypatch):
    import pytest

    port = _port_libre()
    srv = AppServer(_app(), port)
    srv.start("127.0.0.1")
    try:
        reel = srv._lancer

        def lancer(host):
            if host == "0.0.0.0":
                raise RuntimeError("échec simulé")
            reel(host)

        monkeypatch.setattr(srv, "_lancer", lancer)
        with pytest.raises(RuntimeError):
            srv.restart("0.0.0.0")
        assert srv.host == "127.0.0.1"
        assert httpx.get(f"http://127.0.0.1:{port}/api/version").status_code == 200
    finally:
        srv.stop()


def test_concurrent_restarts_leave_one_server(coach_home):
    import threading

    port = _port_libre()
    srv = AppServer(_app(), port)
    srv.start("127.0.0.1")
    try:
        ts = [threading.Thread(target=srv.restart, args=(h,)) for h in ("0.0.0.0", "127.0.0.1")]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        vivants = [t for t in threading.enumerate() if t.name == "coach-uvicorn"]
        assert len(vivants) == 1
        assert httpx.get(f"http://127.0.0.1:{port}/api/version").status_code == 200
    finally:
        srv.stop()
