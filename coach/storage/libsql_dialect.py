"""Dialecte SQLAlchemy minimal pour libSQL/Turso, au-dessus du paquet `libsql`.

URL : `sqlite+libsql://<hôte>?secure=true` (https ; sans `secure`, http) ;
sans hôte, fichier local : `sqlite+libsql:///chemin/fichier.db`.
Le jeton passe par `connect_args={"auth_token": ...}`.
"""

import os

from sqlalchemy import util
from sqlalchemy.dialects import registry
from sqlalchemy.dialects.sqlite.pysqlite import SQLiteDialect_pysqlite


class SQLiteDialect_libsql(SQLiteDialect_pysqlite):
    driver = "libsql"
    supports_statement_cache = True

    @classmethod
    def import_dbapi(cls):
        import libsql

        return libsql

    def on_connect(self):
        # libsql n'a pas create_function (regexp) : rien à configurer à la connexion
        return None

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
