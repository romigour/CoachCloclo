"""Dialecte SQLAlchemy pour une base libSQL/Turso distante, au-dessus du pilote HTTP `coach.storage.hrana`.

URL : `sqlite+libsql://<hôte>?secure=true`, toujours en https.
Le jeton et le client HTTP partagé passent par `connect_args` (voir `remote_engine`).
"""

import re
from typing import TYPE_CHECKING

from sqlalchemy import create_engine, event, pool
from sqlalchemy.dialects import registry
from sqlalchemy.dialects.sqlite.pysqlite import SQLiteDialect_pysqlite
from sqlalchemy.engine import Engine

if TYPE_CHECKING:
    import httpx


class SQLiteDialect_libsql(SQLiteDialect_pysqlite):
    driver = "libsql"
    supports_statement_cache = True

    @classmethod
    def import_dbapi(cls):
        from coach.storage import hrana

        return hrana

    def on_connect(self):
        # Volontairement None : le réglage de pysqlite (isolation_level, regexp) ne s'applique pas à distance.
        return None

    @classmethod
    def get_pool_class(cls, url):
        return pool.NullPool

    def create_connect_args(self, url):
        return ([f"https://{url.host}" + (f":{url.port}" if url.port else "")], {})


dialect = SQLiteDialect_libsql

registry.register("sqlite.libsql", "coach.storage.libsql_dialect", "SQLiteDialect_libsql")


def remote_engine(url: str, token: str, *, transport: "httpx.BaseTransport | None" = None) -> Engine:
    """Moteur sur une base libSQL/Turso distante (`libsql://hôte`, `https://hôte` ou hôte nu).

    Sans pool SQLAlchemy : une connexion n'a d'état que pendant une transaction, et les connexions
    réseau sont partagées par le client HTTP du moteur, fermé avec lui. `transport` : pour les tests.
    """
    from coach.storage import hrana  # charge httpx : jamais en mode local

    # l'hôte seul : un jeton collé dans l'URL s'afficherait avec elle
    host = re.split(r"[/?#]", url.split("://", 1)[-1])[0]
    client = hrana.make_client(transport)
    engine = create_engine(
        f"sqlite+libsql://{host}?secure=true", connect_args={"auth_token": token, "client": client}
    )
    event.listen(engine, "engine_disposed", lambda _: client.close())
    return engine
