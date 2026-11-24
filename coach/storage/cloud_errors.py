"""Reconnaître une base cloud injoignable.

Les erreurs du pilote `hrana` arrivent enveloppées par SQLAlchemy (`OperationalError`), ou brutes
hors d'une exécution de requête (ouverture d'une connexion).
Ce classement ne sert qu'en mode cloud : en local, rien n'est traduit.
"""

from sqlalchemy.exc import DBAPIError, OperationalError

from coach.storage.hrana_errors import CloudAuthError, CloudNetworkError

UNREACHABLE_MSG = "Base cloud injoignable : vérifie ta connexion"
PROBE_UNREACHABLE_MSG = "Base cloud injoignable : vérifie l'adresse de la base et ta connexion"
BAD_TOKEN_MSG = "Jeton Turso refusé : vérifie-le, ou crée un nouveau jeton pour cette base"


class CloudUnreachable(Exception):
    """La base cloud ne répond pas ou refuse l'accès ; le message s'adresse à l'utilisateur."""


def is_cloud_failure(exc: BaseException) -> bool:
    """Vrai pour une panne réseau ou un refus d'accès (pas pour une erreur SQL ou de programmation)."""
    return isinstance(exc, CloudUnreachable | OperationalError | CloudNetworkError | CloudAuthError)


def is_auth_failure(exc: BaseException) -> bool:
    """Vrai pour un jeton refusé."""
    return isinstance(exc.orig if isinstance(exc, DBAPIError) else exc, CloudAuthError)


def as_unreachable(exc: BaseException) -> CloudUnreachable:
    """`CloudUnreachable` au message lisible, pour une erreur reconnue par `is_cloud_failure`."""
    if isinstance(exc, CloudUnreachable):
        return exc
    return CloudUnreachable(BAD_TOKEN_MSG if is_auth_failure(exc) else PROBE_UNREACHABLE_MSG)
