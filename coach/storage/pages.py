"""Lecture d'une table par pages sur une base distante, dont les réponses sont limitées (environ 10 Mo)."""

from typing import NamedTuple

from sqlalchemy import LargeBinary, Table, cast, func, literal_column, select
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.sql import ColumnElement

PAGE_BYTES = 1_000_000  # en JSON, blobs en base64 et guillemets échappés peuvent doubler
PAGE_ROWS = 500
# ordre des rowid : celui d'une lecture complète, présent quelle que soit la clé (texte, composée)
ROWID = literal_column("rowid")


class Page(NamedTuple):
    """Lignes de rowid compris entre `first` et `last`."""

    first: int
    last: int
    rows: int
    size: int

    def where(self) -> ColumnElement[bool]:
        return ROWID.between(self.first, self.last)


def is_remote(engine: Engine) -> bool:
    return engine.dialect.driver == "libsql"


def pages(conn: Connection, table: Table, *where) -> list[Page]:
    """Découpage de la table, dans l'ordre des rowid (une requête, sans les données).

    Une page a au plus `PAGE_ROWS` lignes et dépasse `PAGE_BYTES` d'une ligne au plus.
    """
    weight = literal_column("0")
    for column in table.columns:
        # taille en octets (celle d'un texte se compte en caractères) et habillage JSON de la valeur
        weight = weight + func.coalesce(func.length(cast(column, LargeBinary)), 0) + 40
    # poids minimal d'une ligne : borne aussi leur nombre
    weight = func.max(weight, PAGE_BYTES // PAGE_ROWS)
    sized = select(ROWID.label("rid"), weight.label("size")).select_from(table).where(*where).subquery()
    end = func.sum(sized.c.size).over(order_by=sized.c.rid)
    numbered = select(sized.c.rid, sized.c.size, ((end - 1) // PAGE_BYTES).label("page")).subquery()
    stmt = (
        select(func.min(numbered.c.rid), func.max(numbered.c.rid), func.count(), func.sum(numbered.c.size))
        .group_by(numbered.c.page)
        .order_by(numbered.c.page)
    )
    return [Page(*row) for row in conn.execute(stmt)]
