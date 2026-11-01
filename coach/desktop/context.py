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


def _primary_ip() -> str | None:
    """IPv4 de la carte qui porte la route par défaut (Wi-Fi ou Ethernet), ou None.

    Un `connect` UDP n'envoie aucun paquet : il fait seulement choisir l'adresse source au système.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return str(s.getsockname()[0])
    except OSError:
        return None


def lan_addresses(port: int) -> list[str]:
    """URLs `http://<ip>:<port>` des IPv4 privées de ce PC (hors boucle locale et lien local).

    Quand la carte de la route par défaut est connue, seule son adresse est donnée : les cartes
    virtuelles (WSL, Hyper-V, VPN…) ont aussi des IPv4 privées mais le téléphone ne les atteint pas.
    """
    primary = _primary_ip()
    if primary and _is_lan_ip(primary):
        return [f"http://{primary}:{port}"]
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except OSError:
        return []
    found: set[str] = set()
    for info in infos:
        ip = str(info[4][0])
        if _is_lan_ip(ip):
            found.add(ip)
    return [f"http://{ip}:{port}" for ip in sorted(found, key=ipaddress.ip_address)]


def _is_lan_ip(ip: str) -> bool:
    if ip.startswith(("127.", "169.254.")):
        return False
    try:
        return ipaddress.ip_address(ip).is_private
    except ValueError:
        return False
