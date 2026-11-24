import logging
import sqlite3
import threading
import time
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from coach.storage import hrana
from tests.storage.fake_hrana import FakeHrana

BASE = "https://base.turso.io"
TOKEN = "secret-token"


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "cloud.db"
    _local(path, "CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT UNIQUE, v)")
    return path


@pytest.fixture
def fake(db_path):
    server = FakeHrana(db_path)
    yield server
    server.expire_streams()


@pytest.fixture
def client(fake):
    with hrana.make_client(fake.transport) as c:
        yield c


@pytest.fixture
def conn(client):
    return hrana.connect(BASE, auth_token=TOKEN, client=client)


def _local(path, sql):
    """Exécute une requête par une connexion SQLite indépendante du pilote."""
    with closing(sqlite3.connect(path)) as db, db:
        return db.execute(sql).fetchall()


def _names(path):
    return [r[0] for r in _local(path, "SELECT name FROM t ORDER BY id")]


def _served(handler):
    """Connexion du pilote sur un serveur réduit à une fonction."""
    return hrana.connect(BASE, auth_token=TOKEN, client=hrana.make_client(httpx.MockTransport(handler)))


def test_module_attributes():
    assert (hrana.paramstyle, hrana.threadsafety, hrana.apilevel) == ("qmark", 1, "2.0")
    assert (hrana.sqlite_version_info, hrana.sqlite_version) == ((3, 45, 0), "3.45.0")
    assert hrana.Binary is bytes
    assert issubclass(hrana.IntegrityError, hrana.DatabaseError)
    assert issubclass(hrana.CloudNetworkError, hrana.OperationalError)
    assert issubclass(hrana.CloudAuthError, hrana.OperationalError)


def test_types_roundtrip(conn):
    values = (None, 2**62, 1.5, "é", b"\x00\xff", True)
    row = conn.cursor().execute("SELECT ?, ?, ?, ?, ?, ?", values).fetchone()
    assert row == (None, 2**62, 1.5, "é", b"\x00\xff", 1)
    assert [type(v) for v in row] == [type(None), int, float, str, bytes, int]


@pytest.mark.parametrize(
    ("value", "error"),
    [(object(), hrana.ProgrammingError), (2**63, hrana.DataError), (float("inf"), hrana.DataError)],
)
def test_unsendable_values_are_refused(conn, fake, value, error):
    with pytest.raises(error):
        conn.cursor().execute("SELECT ?", (value,))
    assert fake.sends == 0


def test_read_is_one_send(conn, fake):
    assert conn.cursor().execute("SELECT 1").fetchall() == [(1,)]
    conn.commit()
    conn.close()
    assert fake.sends == 1
    assert [r["type"] for r in fake.requests[0]["requests"]] == ["execute", "close"]
    assert "BEGIN" not in str(fake.requests)
    assert fake.urls == [f"{BASE}/v2/pipeline"]
    assert fake.headers[0]["authorization"] == f"Bearer {TOKEN}"
    assert fake.open_streams() == 0


def test_fetch_methods(conn):
    cur = conn.cursor()
    cur.execute("SELECT 1 AS a UNION SELECT 2 UNION SELECT 3 UNION SELECT 4")
    assert [c[0] for c in cur.description] == ["a"]
    assert len(cur.description[0]) == 7
    assert cur.rowcount == -1
    assert cur.fetchone() == (1,)
    assert cur.fetchmany(2) == [(2,), (3,)]
    assert cur.fetchall() == [(4,)]
    assert cur.fetchone() is None


def test_first_write_begins(conn, fake, db_path):
    conn.cursor().execute("INSERT INTO t (name) VALUES (?)", ("a",))
    (request,) = fake.requests[0]["requests"]
    steps = request["batch"]["steps"]
    assert [s["stmt"]["sql"] for s in steps] == ["BEGIN", "INSERT INTO t (name) VALUES (?)"]
    assert steps[1]["condition"] == {"type": "ok", "step": 0}
    assert _names(db_path) == []
    conn.commit()
    assert fake.sends == 2
    assert [r["type"] for r in fake.requests[1]["requests"]] == ["execute", "close"]
    assert _names(db_path) == ["a"]
    assert fake.open_streams() == 0


def test_transaction_stays_on_stream_base_url(conn, fake, db_path):
    fake.base_url = "https://noeud-3.turso.io"
    cur = conn.cursor()
    cur.execute("INSERT INTO t (name) VALUES ('a')")
    assert cur.execute("SELECT name FROM t").fetchall() == [("a",)]
    conn.commit()
    conn.cursor().execute("SELECT 1")
    assert [u.split("/v2")[0] for u in fake.urls] == [BASE, fake.base_url, fake.base_url, BASE]
    assert _names(db_path) == ["a"]


def test_rollback_stays_on_stream_base_url(conn, fake):
    fake.base_url = "https://noeud-3.turso.io"
    conn.cursor().execute("INSERT INTO t (name) VALUES ('a')")
    conn.rollback()
    assert [u.split("/v2")[0] for u in fake.urls] == [BASE, fake.base_url]


def test_stream_base_url_never_leaves_https(conn, fake):
    """Le jeton ne doit pas partir en clair vers une adresse renvoyée par le serveur."""
    fake.base_url = "http://noeud-3.turso.io"
    conn.cursor().execute("INSERT INTO t (name) VALUES ('a')")
    conn.commit()
    assert [u.split("/v2")[0] for u in fake.urls] == [BASE, BASE]


def test_rollback_discards(conn, fake, db_path):
    conn.cursor().execute("INSERT INTO t (name) VALUES ('a')")
    conn.rollback()
    conn.rollback()
    assert fake.sends == 2
    assert _names(db_path) == []
    conn.cursor().execute("INSERT INTO t (name) VALUES ('b')")
    conn.commit()
    assert _names(db_path) == ["b"]


@pytest.mark.parametrize("kind", ["drop_before", "drop_after", "http_500"])
def test_rollback_ignores_network_failure(conn, fake, db_path, kind):
    conn.cursor().execute("INSERT INTO t (name) VALUES ('a')")
    fake.fail_next(kind)
    conn.rollback()
    assert fake.sends == 2
    fake.expire_streams()  # ce que fait le serveur au bout de quelques secondes
    conn.cursor().execute("INSERT INTO t (name) VALUES ('b')")
    conn.commit()
    assert _names(db_path) == ["b"]


def test_close_discards_transaction(conn, fake, db_path):
    conn.cursor().execute("INSERT INTO t (name) VALUES ('a')")
    conn.close()
    conn.close()
    assert _names(db_path) == []
    assert fake.open_streams() == 0
    with pytest.raises(hrana.ProgrammingError):
        conn.cursor()


def test_error_in_batch_skips_rest(conn, db_path):
    cur = conn.cursor()
    with pytest.raises(hrana.IntegrityError):
        cur.executemany("INSERT INTO t (name) VALUES (?)", [("a",), ("a",), ("b",)])
    # la 3e ligne n'a pas été exécutée : seule la 1re est dans la transaction
    assert cur.execute("SELECT name FROM t").fetchall() == [("a",)]
    conn.rollback()
    assert _names(db_path) == []


def test_transaction_goes_on_after_integrity_error(conn, db_path):
    """Comme SQLite : une contrainte violée n'annule que sa requête."""
    cur = conn.cursor()
    cur.execute("INSERT INTO t (name) VALUES ('a')")
    with pytest.raises(hrana.IntegrityError):
        cur.execute("INSERT INTO t (name) VALUES ('a')")
    cur.execute("INSERT INTO t (name) VALUES ('b')")
    conn.commit()
    assert _names(db_path) == ["a", "b"]


def test_first_write_error_keeps_transaction(conn, fake, db_path):
    _local(db_path, "INSERT INTO t (name) VALUES ('a')")
    cur = conn.cursor()
    with pytest.raises(hrana.IntegrityError):
        cur.execute("INSERT INTO t (name) VALUES ('a')")
    cur.execute("INSERT INTO t (name) VALUES ('b')")
    conn.commit()
    assert _names(db_path) == ["a", "b"]
    assert fake.statements().count("BEGIN") == 1


def test_server_abort_blocks_transaction_until_rollback(conn, fake, db_path):
    """Une erreur qui a pu annuler la transaction côté serveur ne doit pas laisser écrire hors transaction."""
    cur = conn.cursor()
    with closing(sqlite3.connect(db_path, isolation_level=None)) as other:
        other.execute("BEGIN IMMEDIATE")
        with pytest.raises(hrana.DatabaseError):  # SQLITE_BUSY
            cur.execute("INSERT INTO t (name) VALUES ('a')")
    sends = fake.sends
    for action in (
        lambda: cur.execute("INSERT INTO t (name) VALUES ('b')"),
        lambda: cur.execute("SELECT 1"),
        lambda: conn.prefetch(["SELECT 1"]),
        conn.commit,
    ):
        with pytest.raises(hrana.DatabaseError):
            action()
    assert fake.sends == sends
    conn.rollback()
    cur.execute("INSERT INTO t (name) VALUES ('c')")
    conn.commit()
    assert _names(db_path) == ["c"]


def test_refused_begin_blocks_transaction():
    """BEGIN refusé : une écriture suivante partirait en validation automatique."""
    sends = []

    def handler(request):
        sends.append(request)
        result = {"step_results": [None, None], "step_errors": [{"message": "x", "code": "SQLITE_ERROR"}, None]}
        entry = {"type": "ok", "response": {"type": "batch", "result": result}}
        return httpx.Response(200, json={"baton": "b", "base_url": None, "results": [entry]})

    conn = _served(handler)
    for _ in range(2):
        with pytest.raises(hrana.DatabaseError):
            conn.cursor().execute("DELETE FROM t")
    assert len(sends) == 1


@pytest.mark.parametrize("sql", ["BEGIN", "COMMIT", "end", "ROLLBACK"])
def test_explicit_transaction_control_refused(conn, fake, sql):
    with pytest.raises(hrana.ProgrammingError):
        conn.cursor().execute(sql)
    assert fake.sends == 0


def test_savepoint(conn, db_path):
    cur = conn.cursor()
    cur.execute("INSERT INTO t (name) VALUES ('a')")
    cur.execute("SAVEPOINT s")
    cur.execute("INSERT INTO t (name) VALUES ('b')")
    cur.execute("ROLLBACK TO SAVEPOINT s")
    cur.execute("RELEASE SAVEPOINT s")
    conn.commit()
    assert _names(db_path) == ["a"]


def test_rowcount_and_lastrowid(conn):
    cur = conn.cursor()
    cur.execute("INSERT INTO t (name) VALUES ('a')")
    assert (cur.rowcount, cur.lastrowid) == (1, 1)
    cur.execute("INSERT INTO t (name) VALUES ('b')")
    assert cur.lastrowid == 2
    cur.execute("UPDATE t SET v = 1")
    assert cur.rowcount == 2
    cur.execute("INSERT OR IGNORE INTO t (name) VALUES ('a')")
    assert cur.rowcount == 0


def test_pragma_and_returning_rows(conn):
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(t)")
    assert [r[1] for r in cur.fetchall()] == ["id", "name", "v"]
    cur.execute("INSERT INTO t (name) VALUES ('a'), ('b') RETURNING id, name")
    assert [c[0] for c in cur.description] == ["id", "name"]
    assert cur.fetchall() == [(1, "a"), (2, "b")]
    cur.execute("DELETE FROM t")
    assert cur.description is None
    conn.rollback()


def test_executemany_slices(conn, fake, db_path):
    cur = conn.cursor()
    cur.executemany("INSERT INTO t (name, v) VALUES (?, ?)", [(str(i), b"x" * 200_000) for i in range(12)])
    assert cur.rowcount == 12
    assert 2 <= fake.sends <= 4
    conn.commit()
    assert _names(db_path) == [str(i) for i in range(12)]
    assert fake.statements().count("BEGIN") == 1


def test_executemany_empty(conn, fake):
    cur = conn.cursor()
    cur.executemany("INSERT INTO t (name) VALUES (?)", [])
    assert (cur.rowcount, fake.sends) == (0, 0)


@pytest.mark.parametrize("kind", ["drop_before", "drop_after"])
def test_read_retried_once(conn, fake, kind):
    fake.fail_next(kind)
    assert conn.cursor().execute("SELECT 1").fetchall() == [(1,)]
    assert fake.sends == 2
    fake.fail_next(kind)
    fake.fail_next(kind)
    with pytest.raises(hrana.CloudNetworkError):
        conn.cursor().execute("SELECT 1")
    assert fake.sends == 4
    assert conn.cursor().execute("SELECT 1").fetchall() == [(1,)]


@pytest.mark.parametrize("error", [httpx.ConnectError, httpx.ReadTimeout])
def test_other_transport_errors_not_retried(error):
    sends = []

    def handler(request):
        sends.append(request)
        raise error("x")

    with pytest.raises(hrana.CloudNetworkError):
        _served(handler).cursor().execute("SELECT 1")
    assert len(sends) == 1


def test_write_never_retried(conn, fake, db_path):
    fake.fail_next("drop_after")
    with pytest.raises(hrana.CloudNetworkError):
        conn.cursor().execute("INSERT INTO t (name) VALUES ('a')")
    assert fake.sends == 1
    # l'écriture perdue interdit de valider la suite comme si de rien n'était
    with pytest.raises(hrana.DatabaseError):
        conn.cursor().execute("INSERT INTO t (name) VALUES ('b')")
    with pytest.raises(hrana.DatabaseError):
        conn.commit()
    conn.rollback()
    assert fake.sends == 1
    assert _names(db_path) == []


@pytest.mark.parametrize(
    "sql",
    [
        "WITH x AS (SELECT 'a' AS n) INSERT INTO t (name) SELECT n FROM x",
        "-- note\n/* autre */ INSERT INTO t (name) VALUES ('a')",
    ],
)
def test_disguised_write_is_transactional_and_not_retried(conn, fake, db_path, sql):
    fake.fail_next("drop_before")
    with pytest.raises(hrana.CloudNetworkError):
        conn.cursor().execute(sql)
    assert fake.sends == 1
    conn.rollback()
    conn.cursor().execute(sql)
    assert _names(db_path) == []
    conn.commit()
    assert _names(db_path) == ["a"]


def test_pragma_assignment_not_retried(conn, fake):
    fake.fail_next("drop_before")
    with pytest.raises(hrana.CloudNetworkError):
        conn.cursor().execute("PRAGMA user_version = 3")
    assert fake.sends == 1


def test_commented_with_select_is_a_read(conn, fake):
    assert conn.cursor().execute("/* a */ -- b\n WITH x AS (SELECT 1) SELECT * FROM x").fetchall() == [(1,)]
    assert "BEGIN" not in str(fake.requests)


def test_commit_never_retried(conn, fake, db_path):
    conn.cursor().execute("INSERT INTO t (name) VALUES ('a')")
    fake.fail_next("drop_after")
    with pytest.raises(hrana.CloudNetworkError):
        conn.commit()
    with pytest.raises(hrana.DatabaseError):
        conn.commit()
    conn.rollback()
    assert fake.statements().count("COMMIT") == 1
    assert _names(db_path) == ["a"]


def test_failed_commit_is_reported(conn, fake, db_path):
    """COMMIT refusé par le serveur : erreur, flux fermé, rien d'écrit."""
    conn.cursor().execute("INSERT INTO t (name) VALUES ('a')")
    with closing(sqlite3.connect(db_path, isolation_level=None)) as reader:
        reader.execute("BEGIN")
        reader.execute("SELECT * FROM t").fetchall()
        with pytest.raises(hrana.DatabaseError):  # SQLITE_BUSY
            conn.commit()
    assert fake.open_streams() == 0
    conn.rollback()
    assert _names(db_path) == []


def test_read_inside_transaction_not_retried(conn, fake):
    cur = conn.cursor()
    cur.execute("INSERT INTO t (name) VALUES ('a')")
    fake.fail_next("drop_before")
    with pytest.raises(hrana.CloudNetworkError):
        cur.execute("SELECT 1")
    assert fake.sends == 2
    with pytest.raises(hrana.DatabaseError):
        conn.commit()
    conn.rollback()
    assert fake.open_streams() == 0


def test_expired_stream_fails_transaction(conn, fake, db_path):
    cur = conn.cursor()
    cur.execute("INSERT INTO t (name) VALUES ('a')")
    fake.fail_next("expire_baton")
    with pytest.raises(hrana.CloudNetworkError):
        cur.execute("INSERT INTO t (name) VALUES ('b')")
    with pytest.raises(hrana.DatabaseError):
        conn.commit()
    conn.rollback()
    assert _names(db_path) == []


def test_expired_stream_fails_commit(conn, fake, db_path):
    conn.cursor().execute("INSERT INTO t (name) VALUES ('a')")
    fake.fail_next("expire_baton")
    with pytest.raises(hrana.CloudNetworkError):
        conn.commit()
    conn.rollback()
    assert _names(db_path) == []


OK_RESULT = {"cols": [], "rows": [], "affected_row_count": 1, "last_insert_rowid": "1"}
OK_BATCH = {"step_results": [OK_RESULT, OK_RESULT], "step_errors": [None, None]}
OK_FIRST_WRITE = {"type": "ok", "response": {"type": "batch", "result": OK_BATCH}}


@pytest.mark.parametrize("code", ["STREAM_EXPIRED", "TRANSACTION_TIMEOUT"])
def test_expiry_reported_in_results(code):
    """Le serveur peut aussi signaler l'expiration dans `results`, avec un statut 200."""
    replies = iter([OK_FIRST_WRITE, {"type": "error", "error": {"message": "expired", "code": code}}])
    conn = _served(lambda r: httpx.Response(200, json={"baton": "b", "base_url": None, "results": [next(replies)]}))
    conn.cursor().execute("DELETE FROM t")
    with pytest.raises(hrana.CloudNetworkError):
        conn.cursor().execute("DELETE FROM t")
    with pytest.raises(hrana.DatabaseError):
        conn.commit()


def test_stream_closed_by_server_blocks_transaction():
    """Sans jeton de flux après une écriture, la transaction est perdue : ne jamais la croire validée."""
    conn = _served(
        lambda r: httpx.Response(200, json={"baton": None, "base_url": None, "results": [OK_FIRST_WRITE]})
    )
    with pytest.raises(hrana.CloudNetworkError):
        conn.cursor().execute("INSERT INTO t (name) VALUES ('a')")
    with pytest.raises(hrana.DatabaseError):
        conn.commit()


@pytest.mark.parametrize("body", ["<html>portail</html>", "{}", '{"results": []}', '{"results": [{"type": "ok"}]}'])
def test_unreadable_response_is_network_error(body):
    conn = _served(lambda r: httpx.Response(200, text=body))
    with pytest.raises(hrana.CloudNetworkError):
        conn.cursor().execute("SELECT 1")
    with pytest.raises(hrana.CloudNetworkError):
        conn.cursor().execute("DELETE FROM t")


def test_http_error_is_network_error(conn, fake):
    fake.fail_next("http_500")
    with pytest.raises(hrana.CloudNetworkError, match="500"):
        conn.cursor().execute("SELECT 1")
    assert fake.sends == 1


def test_auth_error_hides_token(conn, fake, caplog):
    caplog.set_level(logging.DEBUG)
    fake.fail_next("http_401")
    with pytest.raises(hrana.CloudAuthError) as e:
        conn.cursor().execute("SELECT 1")
    assert caplog.records
    for text in (str(e.value), repr(e.value), repr(conn), caplog.text):
        assert TOKEN not in text


@pytest.mark.parametrize("token", ["secret-token\nx", "secret-tokené", "", "secret token"])
def test_unsendable_token_refused_without_leak(client, fake, token):
    """httpx citerait le jeton dans son erreur d'en-tête invalide : il est refusé avant l'envoi."""
    with pytest.raises(hrana.CloudAuthError) as e:
        hrana.connect(BASE, auth_token=token, client=client)
    assert "secret" not in str(e.value)
    assert fake.sends == 0


def test_network_error_does_not_chain_httpx_error(conn, fake):
    """L'erreur httpx porte la requête, donc le jeton."""
    fake.fail_next("drop_before")
    with pytest.raises(hrana.CloudNetworkError) as e:
        conn.cursor().execute("DELETE FROM t")
    assert e.value.__context__ is None
    assert e.value.__cause__ is None


class _DropSecond(BaseHTTPRequestHandler):
    """Vrai serveur : coupe la connexion gardée ouverte à la 2e requête, sans répondre."""

    protocol_version = "HTTP/1.1"

    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        self.server.received += 1
        if self.server.received == 2:
            self.close_connection = True
            return
        result = (
            b'{"baton":null,"base_url":null,"results":[{"type":"ok","response":{"type":"execute","result":'
            b'{"cols":[{"name":"1"}],"rows":[[{"type":"integer","value":"1"}]],"affected_row_count":0,'
            b'"last_insert_rowid":null}}},{"type":"ok","response":{"type":"close"}}]}'
        )
        self.send_response(200)
        self.send_header("Content-Length", str(len(result)))
        self.end_headers()
        self.wfile.write(result)

    def log_message(self, *args):
        pass


def test_real_http_dead_keepalive_and_debug_logs(caplog):
    caplog.set_level(logging.DEBUG)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _DropSecond)
    server.received = 0
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        with hrana.make_client() as client:
            conn = hrana.connect(f"http://127.0.0.1:{server.server_port}", auth_token=TOKEN, client=client)
            assert conn.cursor().execute("SELECT 1").fetchall() == [(1,)]
            assert conn.cursor().execute("SELECT 1").fetchall() == [(1,)]
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    assert server.received == 3
    assert any(r.name.startswith("httpcore") for r in caplog.records)
    assert TOKEN not in caplog.text


def test_sql_error_is_not_operational(conn):
    with pytest.raises(hrana.DatabaseError) as e:
        conn.cursor().execute("SELECT * FROM absente")
    assert not isinstance(e.value, hrana.OperationalError)
    assert "absente" in str(e.value)


def test_prefetch_consumed(conn, fake):
    a, b = "SELECT 1", "SELECT 2"
    conn.prefetch([a, b])
    assert "condition" not in str(fake.requests)
    cur = conn.cursor()
    assert cur.execute(a).fetchall() == [(1,)]
    assert cur.execute(b, ()).fetchall() == [(2,)]
    assert fake.sends == 1
    assert fake.open_streams() == 0
    assert cur.execute(a).fetchall() == [(1,)]
    assert fake.sends == 2


def test_prefetch_retried_and_errors_deferred(conn, fake):
    fake.fail_next("drop_before")
    conn.prefetch(["SELECT * FROM absente", "SELECT 2"])
    assert fake.sends == 2
    assert conn.cursor().execute("SELECT 2").fetchall() == [(2,)]
    assert fake.sends == 2
    with pytest.raises(hrana.DatabaseError):
        conn.cursor().execute("SELECT * FROM absente")


def test_prefetch_inside_transaction_sees_own_writes(conn, fake):
    conn.cursor().execute("INSERT INTO t (name) VALUES ('a')")
    conn.prefetch(["SELECT name FROM t"])
    assert conn.cursor().execute("SELECT name FROM t").fetchall() == [("a",)]
    assert fake.sends == 2
    conn.rollback()


def test_prefetch_refuses_writes(conn, fake):
    with pytest.raises(hrana.ProgrammingError):
        conn.prefetch(["SELECT 1", "DELETE FROM t"])
    conn.prefetch([])
    assert fake.sends == 0


def test_write_drops_prefetched(conn):
    sql = "SELECT count(*) FROM t"
    conn.prefetch([sql])
    conn.cursor().execute("INSERT INTO t (name) VALUES ('a')")
    assert conn.cursor().execute(sql).fetchall() == [(1,)]
    conn.rollback()


@pytest.mark.parametrize("end", ["commit", "rollback"])
def test_transaction_end_drops_prefetched(conn, db_path, end):
    """Une connexion rendue au pool ne garde pas de lecture périmée."""
    sql = "SELECT count(*) FROM t"
    conn.prefetch([sql])
    getattr(conn, end)()
    _local(db_path, "INSERT INTO t (name) VALUES ('a')")
    assert conn.cursor().execute(sql).fetchall() == [(1,)]


def test_concurrent_reads_do_not_block(client, fake):
    fake.delay_s = 0.3
    results = []

    def read():
        c = hrana.connect(BASE, auth_token=TOKEN, client=client)
        results.append(c.cursor().execute("SELECT 1").fetchone())

    threads = [threading.Thread(target=read) for _ in range(5)]
    start = time.monotonic()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert time.monotonic() - start < 0.9
    assert results == [(1,)] * 5
