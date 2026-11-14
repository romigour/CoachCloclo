"""Reconnaître une base cloud injoignable, quel que soit le driver.

Le paquet `libsql` ne lève pas d'exceptions DBAPI : réseau, authentification et SQL arrivent tous
en `ValueError` brute, non enveloppée par SQLAlchemy (et parfois dès la connexion, hors de portée
de l'événement `handle_error`). Les erreurs du protocole distant commencent par « Hrana: » :
  - réseau : « Hrana: `http error: `error trying to connect: dns error…`` » (relevé à l'essai) ;
  - jeton refusé : « Hrana: `api error: `status=401 …`` » (format du crate libsql 0.9) ;
  - erreur SQL côté serveur : « Hrana: `stream error: …SQLite error…`` » → pas une panne réseau.
Ce classement ne sert qu'en mode cloud : en local, rien n'est traduit.
"""

from sqlalchemy.exc import DBAPIError, OperationalError

UNREACHABLE_MSG = "Base cloud injoignable : vérifie ta connexion"
PROBE_UNREACHABLE_MSG = "Base cloud injoignable : vérifie l'adresse de la base et ta connexion"
BAD_TOKEN_MSG = "Jeton Turso refusé : vérifie-le, ou crée un nouveau jeton pour cette base"

_HRANA = "Hrana:"
_HRANA_SQL = "stream error"
_AUTH_STATUSES = ("status=401", "status=403")


class CloudUnreachable(Exception):
    """La base cloud ne répond pas ou refuse l'accès ; le message s'adresse à l'utilisateur."""


def is_cloud_failure(exc: BaseException) -> bool:
    """Vrai pour une panne réseau ou un refus d'accès (pas pour une erreur SQL ou de programmation)."""
    if isinstance(exc, CloudUnreachable | OperationalError):
        return True
    if isinstance(exc, DBAPIError):
        return exc.connection_invalidated
    if isinstance(exc, ValueError):
        msg = str(exc)
        return msg.startswith(_HRANA) and _HRANA_SQL not in msg
    return False


def is_auth_failure(exc: BaseException) -> bool:
    msg = str(exc)
    return msg.startswith(_HRANA) and any(s in msg for s in _AUTH_STATUSES)


def as_unreachable(exc: BaseException) -> CloudUnreachable:
    """`CloudUnreachable` au message lisible, pour une erreur reconnue par `is_cloud_failure`."""
    if isinstance(exc, CloudUnreachable):
        return exc
    return CloudUnreachable(BAD_TOKEN_MSG if is_auth_failure(exc) else PROBE_UNREACHABLE_MSG)
