"""Consommation des appels Claude : tokens, durée et coût estimé."""

from dataclasses import dataclass

# Tarifs de l'API Anthropic en $ par million de tokens, relevés le 2026-11-15 :
# (entrée, sortie, écriture de cache, lecture de cache). Écriture de cache = 1,25 × entrée.
PRICES_PER_MTOK: dict[str, tuple[float, float, float, float]] = {
    "claude-fable-5-2": (8.00, 40.00, 10.00, 0.20),
    "claude-opus-5-5": (4.00, 20.00, 5.00, 0.20),
    "claude-sonnet-5-5": (2.00, 10.00, 2.50, 0.10),
    "claude-haiku-5-5": (0.10, 0.50, 0.125, 0.01),
}

# Taux fixe : l'affichage est un ordre de grandeur (« ≈ »), pas une conversion exacte.
USD_TO_EUR = 0.92


@dataclass(frozen=True)
class CallUsage:
    """Usage d'un appel à Claude. `input_tokens` = taille totale du prompt (cache compris)."""

    mode: str
    model: str | None
    input_tokens: int
    output_tokens: int
    cost_usd: float | None
    duration_ms: int


def api_cost_usd(model: str, input_tokens: int, output_tokens: int,
                 cache_write: int = 0, cache_read: int = 0) -> float | None:
    """Coût estimé d'un appel API ; None si le modèle n'est pas dans la table des tarifs."""
    prices = PRICES_PER_MTOK.get(model)
    if prices is None:
        return None
    p_in, p_out, p_write, p_read = prices
    return (input_tokens * p_in + output_tokens * p_out + cache_write * p_write + cache_read * p_read) / 1_000_000


def to_eur(usd: float | None) -> float | None:
    return None if usd is None else round(usd * USD_TO_EUR, 4)
