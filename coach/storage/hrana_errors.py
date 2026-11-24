"""Exceptions du pilote `hrana` (PEP 249), à part pour les reconnaître sans charger `httpx`."""


class Warning(Exception):  # noqa: A001  (nom imposé par la PEP 249)
    pass


class Error(Exception):
    # vrai si l'erreur n'annule que sa requête, la transaction restant ouverte
    statement_only = False


class InterfaceError(Error):
    pass


class DatabaseError(Error):
    pass


class DataError(DatabaseError):
    pass


class OperationalError(DatabaseError):
    pass


class IntegrityError(DatabaseError):
    pass


class InternalError(DatabaseError):
    pass


class ProgrammingError(DatabaseError):
    pass


class NotSupportedError(DatabaseError):
    pass


class CloudNetworkError(OperationalError):
    """Base injoignable, réponse inexploitable ou flux expiré."""


class CloudAuthError(OperationalError):
    """Jeton refusé."""
