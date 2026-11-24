"""Relevé des écritures SQL d'un moteur, pour les tests."""

import re
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import event
from sqlalchemy.engine import Engine

_WRITE = re.compile(r'\s*(?:(?:INSERT|REPLACE)\b.*?\bINTO|UPDATE|DELETE\s+FROM)\s+"?(\w+)', re.I | re.S)


@contextmanager
def recorded_writes(engine: Engine) -> Iterator[list[tuple[str, object]]]:
    """Liste (table, paramètres) des écritures envoyées pendant le bloc."""
    writes: list[tuple[str, object]] = []

    def listen(conn, cursor, statement, parameters, context, executemany):
        if m := _WRITE.match(statement):
            writes.append((m.group(1), parameters))

    event.listen(engine, "before_cursor_execute", listen)
    try:
        yield writes
    finally:
        event.remove(engine, "before_cursor_execute", listen)
