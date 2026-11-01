"""Contexte de la version bureau : ce que le routeur desktop peut déclencher."""

import ipaddress
import socket
from collections.abc import Callable
from dataclasses import dataclass

from coach.desktop.claude_setup import ClaudeSetup
from coach.desktop.updater import Updater


@dataclass
class Desktop:
    updater: Updater
    claude: ClaudeSetup
    set_lan: Callable[[bool], None]
    request_exit: Callable[[], None]
    lan_addresses: Callable[[], list[str]]


def lan_addresses(port: int) -> list[str]:
    """URLs `http://<ip>:<port>` des IPv4 privées de ce PC (hors boucle locale et lien local)."""
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except OSError:
        return []
    found: set[str] = set()
    for info in infos:
        ip = str(info[4][0])
        if ip.startswith(("127.", "169.254.")):
            continue
        try:
            if ipaddress.ip_address(ip).is_private:
                found.add(ip)
        except ValueError:
            continue
    return [f"http://{ip}:{port}" for ip in sorted(found, key=ipaddress.ip_address)]
