"""Certificats racine du système pour les appels HTTPS (Garmin, Claude, GitHub).

Sur un réseau d'entreprise qui inspecte le HTTPS (pare-feu Fortinet par
exemple), les sites présentent un certificat signé par l'autorité du pare-feu.
Windows la connaît, mais Python, `requests` et `curl_cffi` n'utilisent que
`certifi` : la connexion échoue (« self-signed certificate in certificate
chain »).

`install_system_ca` fabrique un fichier PEM qui réunit `certifi` et les
autorités du magasin Windows, puis le désigne par SSL_CERT_FILE et
REQUESTS_CA_BUNDLE. On ne fait qu'ajouter des autorités : hors de ce réseau,
tout se passe comme avec `certifi` seul. À appeler avant l'import de
`garminconnect` : `curl_cffi` lit ces variables une seule fois, à l'import.
"""

from __future__ import annotations

import logging
import os
import ssl
import sys
from collections.abc import Callable, Iterable, MutableMapping
from pathlib import Path

import certifi

_log = logging.getLogger(__name__)

BUNDLE_NAME = "ca-bundle.pem"
_ENV_VARS = ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE")
_SERVER_AUTH = "1.3.6.1.5.5.7.3.1"

StoreEnum = Callable[[str], Iterable[tuple[bytes, str, object]]]


def _valide(der: bytes) -> bool:
    """Un certificat qu'OpenSSL ne sait pas lire ferait échouer tout le fichier."""
    try:
        ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT).load_verify_locations(cadata=der)
    except (ssl.SSLError, ValueError):
        return False
    return True


def windows_store_certs(enum: StoreEnum | None = None) -> list[bytes]:
    """Autorités (DER) des magasins Windows ROOT et CA, valables pour le web."""
    enum = enum or ssl.enum_certificates  # type: ignore[attr-defined]  # Windows seulement
    certs: list[bytes] = []
    for magasin in ("ROOT", "CA"):
        try:
            entrees = list(enum(magasin))
        except OSError as exc:
            _log.warning("Magasin de certificats Windows %s illisible : %s", magasin, exc)
            continue
        for der, encodage, usage in entrees:
            pour_le_web = usage is True or (isinstance(usage, set) and _SERVER_AUTH in usage)
            if encodage == "x509_asn" and pour_le_web and der not in certs and _valide(der):
                certs.append(der)
    return certs


def install_system_ca(
    dest_dir: Path,
    *,
    environ: MutableMapping[str, str] = os.environ,
    platform: str = sys.platform,
    read_store: Callable[[], list[bytes]] = windows_store_certs,
) -> Path | None:
    """Écrit le fichier fusionné et le désigne aux bibliothèques HTTP.

    Ne fait rien hors Windows, ni quand l'utilisateur a déjà choisi son fichier
    de certificats. Une erreur est journalisée sans bloquer le démarrage.
    Renvoie le chemin du fichier, ou None s'il n'a pas été installé.
    """
    if platform != "win32" or any(environ.get(v) for v in _ENV_VARS):
        return None
    try:
        pems = [ssl.DER_cert_to_PEM_cert(der) for der in read_store()]
        contenu = Path(certifi.where()).read_text(encoding="utf-8").rstrip() + "\n\n"
        contenu += "# Autorités du magasin de certificats Windows\n" + "".join(pems)
        dest_dir.mkdir(parents=True, exist_ok=True)
        chemin = dest_dir / BUNDLE_NAME
        tmp = chemin.with_suffix(".tmp")
        tmp.write_text(contenu, encoding="utf-8")
        os.replace(tmp, chemin)
    except Exception:  # noqa: BLE001 — sans ce fichier, on retombe sur certifi
        _log.warning("Certificats Windows non installés ; repli sur certifi", exc_info=True)
        return None
    environ["SSL_CERT_FILE"] = str(chemin)
    environ["REQUESTS_CA_BUNDLE"] = str(chemin)
    return chemin
