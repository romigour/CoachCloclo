"""Pilote DBAPI pour une base libSQL/Turso distante : protocole Hrana v2 sur HTTP, avec `httpx`.

Transactions comme pysqlite : `BEGIN` implicite à la première écriture, lectures hors transaction sinon.
Une écriture ou un COMMIT n'est jamais rejoué ; une lecture hors transaction l'est une seule fois.
Une transaction dont l'état côté serveur est douteux refuse tout jusqu'au `rollback()`.
Le jeton ne figure jamais dans un message, une représentation ou un journal.
"""

import base64
import math
import re
import threading
from collections.abc import Callable, Iterable, Iterator, Sequence
from typing import Any, NamedTuple

import httpx

apilevel = "2.0"
threadsafety = 1
paramstyle = "qmark"
sqlite_version_info = (3, 45, 0)
sqlite_version = "3.45.0"
Binary = bytes


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


_BLANK = re.compile(r"(?:\s+|--[^\n]*(?:\n|$)|/\*.*?\*/)+", re.DOTALL)
_WORD = re.compile(r"[a-z]+", re.IGNORECASE)
# `WITH … INSERT` est une écriture. Un faux positif ne coûte qu'une transaction inutile.
_DML = re.compile(r"\b(?:INSERT|UPDATE|DELETE)\b|\bREPLACE\s+INTO\b", re.IGNORECASE)
_ROLLBACK_TO = re.compile(r"ROLLBACK\s+(?:TRANSACTION\s+)?TO\b", re.IGNORECASE)
_TOKEN = re.compile(r"[\x21-\x7e]+")

_REPLAYABLE = (httpx.RemoteProtocolError, httpx.ReadError, httpx.WriteError)
_EXPIRED = ("STREAM_EXPIRED", "TRANSACTION_TIMEOUT", "BATON")
# Erreurs qui n'annulent que leur requête : la transaction reste ouverte côté serveur.
# Toute autre (SQLITE_BUSY, SQLITE_FULL, délai dépassé…) a pu l'annuler.
_STATEMENT_ONLY = ("SQLITE_CONSTRAINT", "SQL_", "ARGS_")
_SLICE_BYTES = 1_000_000
_TIMEOUT = 30
_LIMITS = httpx.Limits(max_connections=20, max_keepalive_connections=20, keepalive_expiry=300)


class _Pool:
    """Jeu de connexions HTTP et nombre de requêtes en cours dessus."""

    def __init__(self, client: httpx.Client) -> None:
        self.client = client
        self.users = 0


class RenewableClient(httpx.Client):
    """Client partagé dont le jeu de connexions se remplace quand l'une d'elles est morte.

    Après une veille, toutes le sont souvent sans que `httpx` le sache. L'ancien jeu n'est fermé
    qu'à la fin de ses requêtes en cours : celles des autres fils ne sont pas coupées.
    """

    def __init__(self) -> None:
        # Les requêtes partent toutes par `pool` : le transport hérité ne sert pas.
        super().__init__(transport=httpx.BaseTransport(), timeout=_TIMEOUT)
        self._ssl = httpx.create_ssl_context()
        self._lock = threading.Lock()
        self.pool = self._new_pool()

    def _new_pool(self) -> _Pool:
        return _Pool(httpx.Client(verify=self._ssl, timeout=_TIMEOUT, limits=_LIMITS))

    def send(self, request: httpx.Request, **kwargs) -> httpx.Response:
        with self._lock:
            pool = self.pool
            pool.users += 1
        try:
            return pool.client.send(request, **kwargs)
        finally:
            with self._lock:
                pool.users -= 1
                finished = pool is not self.pool and pool.users == 0
            if finished:
                pool.client.close()

    def renew(self, failed: _Pool) -> None:
        """Remplace `failed`, sauf si un autre fil l'a déjà fait ou si le client est fermé."""
        with self._lock:
            if self.pool is not failed or self.is_closed:
                return
            self.pool = self._new_pool()
            finished = failed.users == 0
        if finished:
            failed.client.close()

    def close(self) -> None:
        with self._lock:
            super().close()
        self.pool.client.close()

    def __exit__(self, *exc_info) -> None:
        self.close()


def make_client(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    """Client HTTP à partager entre les connexions (`transport` : pour les tests)."""
    if transport is not None:
        return httpx.Client(transport=transport, timeout=_TIMEOUT)
    return RenewableClient()


def connect(base_url: str, *, auth_token: str, client: httpx.Client) -> "Connection":
    """Ouvre une connexion (aucun appel réseau avant la première requête)."""
    return Connection(base_url, auth_token, client)


class _Result(NamedTuple):
    cols: list[str]
    rows: list[tuple]
    affected: int
    last_rowid: int | None


class Connection:
    def __init__(self, base_url: str, auth_token: str, client: httpx.Client) -> None:
        token = auth_token.strip()
        if not _TOKEN.fullmatch(token):
            # httpx citerait le jeton dans son erreur d'en-tête invalide
            raise CloudAuthError("Jeton de la base distante invalide")
        self._headers = {"Authorization": f"Bearer {token}"}
        self._base_url = base_url.rstrip("/")
        self._client = client
        self._closed = False
        self._prefetched: dict[str, _Result] = {}
        self._reset_stream()

    def _reset_stream(self) -> None:
        self._baton: str | None = None
        self._stream_url = self._base_url
        self._failed = False

    # --- DBAPI -----------------------------------------------------------------------------------

    def cursor(self) -> "Cursor":
        self._check_open()
        return Cursor(self)

    def commit(self) -> None:
        self._check_usable()
        self._prefetched.clear()
        if self._baton is None:
            return
        baton, self._baton = self._baton, None
        # Levé seulement si COMMIT est confirmé : sinon, rien ne peut suivre avant un rollback().
        self._failed = True
        body = self._send([_execute("COMMIT"), {"type": "close"}], baton)
        _result(_response(body, 0, "execute"))
        self._reset_stream()

    def rollback(self) -> None:
        self._check_open()
        self._prefetched.clear()
        baton, url = self._baton, self._stream_url
        self._reset_stream()
        if baton is None:
            return
        try:
            self._send([_execute("ROLLBACK"), {"type": "close"}], baton, url=url)
        except OperationalError:
            pass  # sans COMMIT, le serveur annule la transaction en fermant le flux

    def close(self) -> None:
        if not self._closed:
            self.rollback()
            self._closed = True

    def prefetch(self, sqls: list[str]) -> None:
        """Exécute ces lectures sans paramètre en un envoi ; `execute` du même texte les consomme une fois.

        Une lecture en erreur n'est pas gardée : elle échouera à son `execute`, sauf si l'erreur a pu
        annuler la transaction en cours (levée aussitôt).
        """
        self._check_usable()
        if not all(_is_read(sql) for sql in sqls):
            raise ProgrammingError("prefetch n'accepte que des lectures")
        sqls = list(dict.fromkeys(sqls))
        if not sqls:
            return
        batch = {"type": "batch", "batch": {"steps": [{"stmt": _stmt(sql)} for sql in sqls]}}
        body = self._send_read(batch, replay=all(_is_replayable(sql) for sql in sqls))
        in_stream = self._baton is not None or self._failed

        def parse() -> list:
            results, errors = _steps(_response(body, 0, "batch"), len(sqls))
            for error in errors:
                if in_stream and error is not None and not (exc := _sql_error(error)).statement_only:
                    raise exc  # la transaction a pu être annulée
            return results

        results = self._parsed(parse)
        self._prefetched.update((sql, _result(r)) for sql, r in zip(sqls, results, strict=True) if r is not None)

    # --- exécution -------------------------------------------------------------------------------

    def _check_open(self) -> None:
        if self._closed:
            raise ProgrammingError("Connexion fermée")

    def _check_usable(self) -> None:
        self._check_open()
        if self._failed:
            raise DatabaseError("Transaction interrompue : rollback nécessaire")

    def _run_read(self, sql: str, args: list[dict]) -> _Result:
        self._check_usable()
        if not args and (ready := self._prefetched.pop(sql, None)) is not None:
            return ready
        body = self._send_read(_execute(sql, args), replay=_is_replayable(sql))
        return self._parsed(lambda: _result(_response(body, 0, "execute")))

    def _send_read(self, request: dict, *, replay: bool) -> dict:
        if self._baton is not None:
            return self._send_in_stream([request])
        return self._send([request, {"type": "close"}], replay=replay)

    def _run_writes(self, sql: str, args: list[list[dict]]) -> list[_Result]:
        """Écritures en un envoi, dans la transaction (ouverte au besoin)."""
        self._check_usable()
        self._prefetched.clear()
        opening = self._baton is None
        stmts = [_stmt(sql, a) for a in args]
        if opening:
            stmts.insert(0, _stmt("BEGIN"))
        if len(stmts) == 1:
            body = self._send_in_stream([{"type": "execute", "stmt": stmts[0]}])
            return [self._parsed(lambda: _result(_response(body, 0, "execute")))]
        steps: list[dict] = [{"stmt": s, "condition": {"type": "ok", "step": i - 1}} for i, s in enumerate(stmts)]
        del steps[0]["condition"]
        body = self._send_in_stream([{"type": "batch", "batch": {"steps": steps}}])

        # Tant que BEGIN n'est pas confirmé, pas de transaction : rien ne doit s'exécuter hors d'elle.
        stream_lost = self._failed
        self._failed = stream_lost or opening

        def parse() -> list[_Result]:
            results, errors = _steps(_response(body, 0, "batch"), len(stmts))
            if opening and results[0] is not None:
                self._failed = stream_lost
            for error in errors:
                if error is not None:
                    raise _sql_error(error)
            if None in results:
                raise _unreadable()
            return [_result(r) for r in results]

        return self._parsed(parse)[1 if opening else 0 :]

    def _send_in_stream(self, requests: list[dict]) -> dict:
        """Envoi dans la transaction : jamais rejoué, et toute panne la rend inutilisable."""
        baton, failed = self._baton, True
        try:
            body = self._send(requests, baton)
            self._baton = body.get("baton")
            url = body.get("base_url")
            # jamais de https vers http : le jeton partirait en clair
            if url and not (self._base_url.startswith("https:") and not url.startswith("https:")):
                self._stream_url = url.rstrip("/")
            # sans jeton de flux, le serveur a fermé la transaction
            failed = self._baton is None
        finally:
            self._failed = failed
        return body

    def _parsed[T](self, parse: Callable[[], T]) -> T:
        """Lit une réponse ; dans un flux, retient si la transaction a pu être perdue."""
        in_stream = self._baton is not None or self._failed
        try:
            result = parse()
            if self._failed:
                raise CloudNetworkError("Transaction fermée par la base distante")
            return result
        except Error as e:
            if in_stream and not e.statement_only:
                self._failed = True
            raise

    def _send(
        self, requests: list[dict], baton: str | None = None, *, url: str | None = None, replay: bool = False
    ) -> dict:
        request = {"baton": baton, "requests": requests}
        target = f"{url or self._stream_url}/v2/pipeline"
        response, failure = self._post(target, request)
        if replay and isinstance(failure, _REPLAYABLE):
            response, failure = self._post(target, request)
        # Levé hors de tout `except` : l'erreur httpx ne doit pas suivre par __context__.
        if response is None:
            raise CloudNetworkError(f"Base distante injoignable ({type(failure).__name__})")
        if response.status_code in (401, 403):
            raise CloudAuthError(f"Jeton refusé par la base distante (HTTP {response.status_code})")
        if response.status_code != 200:
            raise CloudNetworkError(f"Réponse inattendue de la base distante (HTTP {response.status_code})")
        try:
            body = response.json()
        except ValueError:
            body = None
        if not isinstance(body, dict) or not isinstance(body.get("results"), list):
            raise _unreadable()
        return body

    def _post(self, url: str, request: dict) -> tuple[httpx.Response | None, Exception | None]:
        client = self._client
        pool = client.pool if isinstance(client, RenewableClient) else None
        try:
            return client.post(url, json=request, headers=self._headers), None
        except (httpx.HTTPError, httpx.InvalidURL) as e:
            if pool is not None and isinstance(e, _REPLAYABLE):
                client.renew(pool)  # le rejeu, et tout envoi suivant, part sur une connexion neuve
            return None, e


class Cursor:
    arraysize = 1

    def __init__(self, connection: Connection) -> None:
        self.connection = connection
        self.description: list[tuple] | None = None
        self.rowcount = -1
        self.lastrowid: int | None = None
        self._rows: Iterator[tuple] = iter(())

    def _clear(self) -> None:
        self.description = None
        self.rowcount = -1
        self._rows = iter(())

    def execute(self, sql: str, parameters: Sequence[Any] = ()) -> "Cursor":
        self._clear()
        args = _encode_args(parameters)
        if _is_read(sql):
            result = self.connection._run_read(sql, args)
        else:
            (result,) = self.connection._run_writes(sql, [args])
            self.rowcount = result.affected
            self.lastrowid = result.last_rowid
        if result.cols:
            self.description = [(name, None, None, None, None, None, None) for name in result.cols]
        self._rows = iter(result.rows)
        return self

    def executemany(self, sql: str, seq_of_parameters: Iterable[Sequence[Any]]) -> "Cursor":
        self._clear()
        if _is_read(sql):
            raise ProgrammingError("executemany n'accepte que des écritures")
        total = 0
        # Tout est converti avant le premier envoi : une valeur refusée ne laisse rien à moitié.
        rows = [_encode_args(p) for p in seq_of_parameters]
        for part in _slices(sql, rows):
            total += sum(r.affected for r in self.connection._run_writes(sql, part))
        self.rowcount = total
        return self

    def fetchone(self) -> tuple | None:
        return next(self._rows, None)

    def fetchmany(self, size: int | None = None) -> list[tuple]:
        return [row for _, row in zip(range(self.arraysize if size is None else size), self._rows)]

    def fetchall(self) -> list[tuple]:
        return list(self._rows)

    def __iter__(self) -> Iterator[tuple]:
        return self._rows

    def close(self) -> None:
        self._clear()

    def setinputsizes(self, sizes) -> None:
        pass

    def setoutputsize(self, size, column=None) -> None:
        pass


# --- nature des requêtes -----------------------------------------------------------------------------


def _is_read(sql: str) -> bool:
    start = _BLANK.match(sql)
    body = sql[start.end() :] if start else sql
    word = _WORD.match(body)
    first = word.group().upper() if word else ""
    if first in ("BEGIN", "COMMIT", "END") or (first == "ROLLBACK" and not _ROLLBACK_TO.match(body)):
        raise ProgrammingError("Transaction à piloter par commit() et rollback()")
    if first == "WITH":
        return not _DML.search(body)
    return first in ("SELECT", "PRAGMA", "EXPLAIN")


def _is_replayable(sql: str) -> bool:
    """Lecture rejouable : toutes, sauf un `PRAGMA x = …` qui modifie la base."""
    start = _BLANK.match(sql)
    body = sql[start.end() :] if start else sql
    return not (body[:6].upper() == "PRAGMA" and "=" in body)


# --- format Hrana ------------------------------------------------------------------------------------


def _stmt(sql: str, args: list[dict] | None = None) -> dict:
    return {"sql": sql, "args": args or [], "want_rows": True}


def _execute(sql: str, args: list[dict] | None = None) -> dict:
    return {"type": "execute", "stmt": _stmt(sql, args)}


def _encode_args(parameters: Sequence[Any]) -> list[dict]:
    if isinstance(parameters, (dict, str, bytes)):
        raise ProgrammingError("Paramètres positionnels attendus")
    return [_encode(v) for v in parameters]


def _encode(value: Any) -> dict:
    if value is None:
        return {"type": "null"}
    if isinstance(value, int):  # bool compris
        if not -(2**63) <= value < 2**63:
            raise DataError("Entier hors de la plage 64 bits")
        return {"type": "integer", "value": str(int(value))}
    if isinstance(value, float):
        if math.isnan(value):
            return {"type": "null"}  # comme SQLite
        if math.isinf(value):
            raise DataError("Nombre infini non transmissible")
        return {"type": "float", "value": value}
    if isinstance(value, str):
        return {"type": "text", "value": value}
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"type": "blob", "base64": base64.b64encode(value).decode()}
    raise ProgrammingError(f"Type de paramètre non géré : {type(value).__name__}")


def _decode(value: dict) -> Any:
    kind = value["type"]
    if kind == "null":
        return None
    if kind == "integer":
        return int(value["value"])
    if kind == "float":
        return float(value["value"])
    if kind == "text":
        return value["value"]
    if kind == "blob":
        data = value["base64"]
        return base64.b64decode(data + "=" * (-len(data) % 4))
    raise ValueError(kind)


def _slices(sql: str, rows: list[list[dict]]) -> Iterator[list[list[dict]]]:
    """Tranches d'environ 1 Mo (le SQL, répété à chaque étape, et l'habillage JSON comptent)."""
    part: list[list[dict]] = []
    size = 0
    for row in rows:
        part.append(row)
        size += len(sql) + sum(40 + len(str(a.get("value", a.get("base64", "")))) for a in row)
        if size >= _SLICE_BYTES:
            yield part
            part, size = [], 0
    if part:
        yield part


def _response(body: dict, index: int, kind: str) -> dict:
    """Résultat de la requête `index` de la pipeline, ou son erreur."""
    try:
        entry = body["results"][index]
        if entry["type"] == "error":
            error = entry["error"]
        else:
            error = None
            response = entry["response"]
            if response["type"] == kind:
                return response["result"]
    except (LookupError, TypeError):
        error = None
    if error is not None:
        raise _sql_error(error)
    raise _unreadable()


def _steps(result: dict, count: int) -> tuple[list, list]:
    try:
        results, errors = result["step_results"], result["step_errors"]
        if len(results) == len(errors) == count:
            return results, errors
    except (LookupError, TypeError):
        pass
    raise _unreadable()


def _result(result: dict) -> _Result:
    try:
        rowid = result.get("last_insert_rowid")
        return _Result(
            cols=[c.get("name") or "" for c in result["cols"]],
            rows=[tuple(_decode(v) for v in row) for row in result["rows"]],
            affected=int(result["affected_row_count"]),
            last_rowid=None if rowid is None else int(rowid),
        )
    except (LookupError, TypeError, ValueError, AttributeError):
        pass
    raise _unreadable()


def _sql_error(error: dict) -> Error:
    code = message = ""
    if isinstance(error, dict):
        code, message = str(error.get("code") or ""), str(error.get("message") or "")
    if code.startswith(_EXPIRED):
        return CloudNetworkError("Transaction expirée côté base distante")
    kind = IntegrityError if code.startswith("SQLITE_CONSTRAINT") else DatabaseError
    exc = kind(message or code)
    exc.statement_only = code == "SQLITE_ERROR" or code.startswith(_STATEMENT_ONLY)
    return exc


def _unreadable() -> CloudNetworkError:
    return CloudNetworkError("Réponse illisible de la base distante")
