import re
import ssl
from pathlib import Path

import certifi

from coach.certs import BUNDLE_NAME, install_system_ca, windows_store_certs

SERVER_AUTH = "1.3.6.1.5.5.7.3.1"


def _certifi_ders(n: int) -> list[bytes]:
    """Quelques vrais certificats (DER), pris dans certifi."""
    text = Path(certifi.where()).read_text(encoding="utf-8")
    blocs = re.findall(r"-----BEGIN CERTIFICATE-----.+?-----END CERTIFICATE-----", text, re.S)
    return [ssl.PEM_cert_to_DER_cert(b) for b in blocs[:n]]


def test_windows_store_certs_garde_les_racines_valides_pour_le_web():
    a, b, c = _certifi_ders(3)
    magasins = {
        "ROOT": [(a, "x509_asn", True), (b, "x509_asn", {"1.3.6.1.5.5.7.3.4"}), (b"pas un cert", "x509_asn", True)],
        "CA": [(c, "x509_asn", {SERVER_AUTH}), (a, "x509_asn", True), (c, "pkcs_7_asn", True)],
    }

    certs = windows_store_certs(lambda nom: magasins[nom])

    assert certs == [a, c]


def test_windows_store_certs_ignore_un_magasin_illisible():
    (a,) = _certifi_ders(1)

    def enum(nom):
        if nom == "CA":
            raise OSError("accès refusé")
        return [(a, "x509_asn", True)]

    assert windows_store_certs(enum) == [a]


def test_install_fusionne_certifi_et_le_magasin_windows(tmp_path):
    (a,) = _certifi_ders(1)
    env: dict[str, str] = {}

    chemin = install_system_ca(tmp_path, environ=env, platform="win32", read_store=lambda: [a])

    assert chemin == tmp_path / BUNDLE_NAME
    contenu = chemin.read_text(encoding="utf-8")
    assert contenu.startswith(Path(certifi.where()).read_text(encoding="utf-8").rstrip())
    assert ssl.DER_cert_to_PEM_cert(a) in contenu
    assert env["SSL_CERT_FILE"] == str(chemin)
    assert env["REQUESTS_CA_BUNDLE"] == str(chemin)
    ssl.create_default_context(cafile=str(chemin))  # OpenSSL relit le fichier sans erreur


def test_install_respecte_une_variable_deja_definie(tmp_path):
    env = {"REQUESTS_CA_BUNDLE": "C:/perso.pem"}

    assert install_system_ca(tmp_path, environ=env, platform="win32", read_store=lambda: []) is None
    assert env == {"REQUESTS_CA_BUNDLE": "C:/perso.pem"}
    assert not (tmp_path / BUNDLE_NAME).exists()


def test_install_ne_fait_rien_hors_windows(tmp_path):
    env: dict[str, str] = {}

    assert install_system_ca(tmp_path, environ=env, platform="linux", read_store=lambda: []) is None
    assert env == {}


def test_install_ne_bloque_pas_le_demarrage_en_cas_d_erreur(tmp_path):
    env: dict[str, str] = {}

    def boum():
        raise RuntimeError("magasin cassé")

    assert install_system_ca(tmp_path, environ=env, platform="win32", read_store=boum) is None
    assert env == {}
