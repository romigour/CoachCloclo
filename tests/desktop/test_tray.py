import threading
import time

from coach.desktop.tray import Tray


def test_verifier_does_not_block_menu_thread():
    """La vérification (jusqu'à 10 s) tourne hors du fil de messages de pystray."""
    libere = threading.Event()
    notifies: list[str] = []
    fait = threading.Event()

    def check():
        libere.wait(5)
        return "CoachCloclo est à jour"

    tray = Tray.__new__(Tray)  # sans pystray
    tray._check_updates = check
    tray.notify = lambda m: (notifies.append(m), fait.set())

    debut = time.monotonic()
    tray._verifier()
    assert time.monotonic() - debut < 1
    assert notifies == []
    libere.set()
    assert fait.wait(5) and notifies == ["CoachCloclo est à jour"]


def test_verifier_reports_errors():
    fait = threading.Event()
    notifies: list[str] = []

    def check():
        raise RuntimeError("réseau")

    tray = Tray.__new__(Tray)
    tray._check_updates = check
    tray.notify = lambda m: (notifies.append(m), fait.set())
    tray._verifier()
    assert fait.wait(5) and notifies == ["réseau"]
