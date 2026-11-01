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
