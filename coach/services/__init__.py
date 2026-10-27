"""Services applicatifs : orchestrent modules purs, dépôt, Garmin et LLM."""


class CoachError(ValueError):
    """Erreur métier dont le message est destiné à l'utilisateur."""
