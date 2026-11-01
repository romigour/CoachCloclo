import logging
import sys

import pytest

from coach.desktop.logs import setup_logging, teardown_logging


@pytest.fixture(autouse=True)
def _nettoyage():
    yield
    teardown_logging()


def flush_handlers():
    for h in logging.getLogger().handlers:
        h.flush()


def test_logging_redirects_missing_stdout(coach_home, monkeypatch):
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    path = setup_logging()
    print("bonjour")
    logging.getLogger("uvicorn.error").info("prêt")
    flush_handlers()
    text = path.read_text(encoding="utf-8")
    assert "bonjour" in text and "prêt" in text
    assert path == coach_home / "logs" / "coachcloclo.log"


def test_excepthook_journalise(coach_home):
    path = setup_logging()
    try:
        raise ValueError("boum")
    except ValueError:
        sys.excepthook(*sys.exc_info())
    flush_handlers()
    assert "boum" in path.read_text(encoding="utf-8")


def test_teardown_restaure(coach_home, monkeypatch):
    monkeypatch.setattr(sys, "stdout", None)
    hook = sys.excepthook
    avant = list(logging.getLogger().handlers)
    setup_logging()
    teardown_logging()
    assert sys.stdout is None
    assert sys.excepthook is hook
    assert logging.getLogger().handlers == avant
