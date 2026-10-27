"""Dépendances de l'API : PIN, factories par requête."""

import hashlib
import hmac
import secrets

from fastapi import Request

from coach.garmin.port import GarminPort
from coach.llm.provider import LLMProvider

PBKDF2_ITERATIONS = 200_000
_ALGO = "pbkdf2_sha256"


def _derive(pin: str, salt: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, iterations)


def hash_pin(pin: str) -> str:
    """Hash PBKDF2-SHA256 au format `pbkdf2_sha256$<itérations>$<sel>$<hash>`."""
    salt = secrets.token_bytes(16)
    digest = _derive(pin, salt, PBKDF2_ITERATIONS)
    return f"{_ALGO}${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_pin(pin: str, stored: str) -> bool:
    """Compare en temps constant ; un hash mal formé ne valide jamais."""
    try:
        algo, iterations, salt_hex, hash_hex = stored.split("$")
        if algo != _ALGO:
            return False
        expected = bytes.fromhex(hash_hex)
        actual = _derive(pin, bytes.fromhex(salt_hex), int(iterations))
    except ValueError:
        return False
    return hmac.compare_digest(actual, expected)


def get_garmin(request: Request) -> GarminPort:
    """Client Garmin créé à chaque requête (lève GarminAuthRequired sans jetons)."""
    return request.app.state.garmin_factory()


def get_llm(request: Request) -> LLMProvider:
    return request.app.state.llm_factory()
