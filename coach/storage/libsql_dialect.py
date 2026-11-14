"""Dialecte SQLAlchemy minimal pour libSQL/Turso, au-dessus du paquet `libsql`.

URL : `sqlite+libsql://<hôte>?secure=true` (https ; sans `secure`, http) ;
sans hôte, fichier local : `sqlite+libsql:///chemin/fichier.db`.
Le jeton passe par `connect_args={"auth_token": ...}`.
"""

import os

from sqlalchemy import create_engine, pool, util
from sqlalchemy.engine import Engine
from sqlalchemy.dialects import registry
from sqlalchemy.dialects.sqlite.pysqlite import SQLiteDialect_pysqlite


class SQLiteDialect_libsql(SQLiteDialect_pysqlite):
    driver = "libsql"
    supports_statement_cache = True

    @classmethod
    def import_dbapi(cls):
        import libsql

        if not hasattr(libsql, "Binary"):
            # SQLAlchemy l'exige pour lier les colonnes LargeBinary (GPX) ; bytes suffit.
            libsql.Binary = bytes
        return libsql

    def on_connect(self):
        # Volontairement None : on saute le réglage de pysqlite (isolation_level, regexp via
        # create_function), que libsql ne supporte pas. Rien à configurer à la connexion.
        return None

    @classmethod
    def get_pool_class(cls, url):
        if url.host:
            # distant : SingletonThreadPool (défaut pysqlite) fermerait une connexion encore
            # utilisée par un autre thread (threadpool FastAPI) ; on veut un pool partagé.
            return pool.QueuePool
        return super().get_pool_class(url)

    def create_connect_args(self, url):
        opts = dict(url.query)
        secure = bool(util.asbool(opts.pop("secure", "false")))
        if url.host:
            netloc = url.host + (f":{url.port}" if url.port else "")
            target = f"{'https' if secure else 'http'}://{netloc}"
        else:
            target = url.database or ":memory:"
            if target != ":memory:":
                target = os.path.abspath(target)
        return ([target], {})


dialect = SQLiteDialect_libsql

registry.register("sqlite.libsql", "coach.storage.libsql_dialect", "SQLiteDialect_libsql")


def remote_engine(url: str, token: str) -> Engine:
    """Moteur sur une base libSQL/Turso distante (`libsql://hôte`, `https://hôte` ou hôte nu)."""
    host = url.split("://", 1)[-1].rstrip("/")
    return create_engine(
        f"sqlite+libsql://{host}?secure=true",
        connect_args={"auth_token": token},
        poolclass=pool.QueuePool,
        pool_pre_ping=True,
        pool_recycle=60,
    )
