"""Faux serveur Hrana v2 (HTTP) pour les tests : exécute les requêtes sur un fichier SQLite.

Comme le vrai serveur : une connexion SQLite par flux, un jeton de flux (`baton`) à usage unique,
une pipeline qui continue après une erreur, et un flux fermé annule sa transaction.
"""

import base64
import json
import sqlite3
import threading
import time
from collections import deque
from typing import Literal

import httpx

Failure = Literal["drop_before", "drop_after", "http_401", "http_500", "expire_baton"]


class FakeHrana:
    def __init__(self, path) -> None:
        self._path = str(path)
        self.transport = httpx.MockTransport(self._handle)
        self.sends = 0
        self.requests: list[dict] = []
        self.urls: list[str] = []
        self.headers: list[httpx.Headers] = []
        self.delay_s = 0.0
        # Adresse collante renvoyée aux clients, comme le fait Turso (None : aucune).
        self.base_url: str | None = None
        self._failures: deque[str] = deque()
        self._streams: dict[str, sqlite3.Connection] = {}
        self._next_baton = 0
        self._lock = threading.Lock()

    def fail_next(self, kind: Failure) -> None:
        """Programme une panne pour le prochain envoi (les appels successifs s'empilent)."""
        self._failures.append(kind)

    def statements(self) -> list[str]:
        """Toutes les requêtes SQL reçues, dans l'ordre."""
        found = []
        for body in self.requests:
            for req in body["requests"]:
                if req["type"] == "execute":
                    found.append(req["stmt"]["sql"])
                elif req["type"] == "batch":
                    found += [step["stmt"]["sql"] for step in req["batch"]["steps"]]
        return found

    def open_streams(self) -> int:
        return len(self._streams)

    def expire_streams(self) -> None:
        """Ferme tous les flux : leurs transactions sont annulées."""
        with self._lock:
            streams, self._streams = self._streams, {}
        for db in streams.values():
            db.close()

    def _handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        with self._lock:
            self.sends += 1
            self.requests.append(body)
            self.urls.append(str(request.url))
            self.headers.append(request.headers)
            failure = self._failures.popleft() if self._failures else None
        if self.delay_s:
            time.sleep(self.delay_s)
        if failure == "drop_before":
            raise httpx.RemoteProtocolError("Server disconnected without sending a response.")
        if failure == "http_401":
            return httpx.Response(401, json={"error": "unauthorized"})
        if failure == "http_500":
            return httpx.Response(500, text="boom")
        if failure == "expire_baton":
            self.expire_streams()
        response = self._pipeline(body)
        if failure == "drop_after":
            raise httpx.ReadError("connection reset")
        return response

    def _pipeline(self, body: dict) -> httpx.Response:
        baton = body.get("baton")
        if baton is None:
            db = sqlite3.connect(self._path, isolation_level=None, check_same_thread=False, timeout=0.2)
        else:
            with self._lock:
                db = self._streams.pop(baton, None)
            if db is None:
                return httpx.Response(
                    400, json={"message": "The stream has expired due to inactivity", "code": "STREAM_EXPIRED"}
                )
        results, closed = [], False
        for req in body["requests"]:
            if req["type"] == "close":
                db.close()
                closed = True
                results.append({"type": "ok", "response": {"type": "close"}})
                continue
            try:
                result = _execute(db, req["stmt"]) if req["type"] == "execute" else _batch(db, req["batch"])
                results.append({"type": "ok", "response": {"type": req["type"], "result": result}})
            except sqlite3.Error as e:
                results.append({"type": "error", "error": _error(e)})
        next_baton = None
        if not closed:
            with self._lock:
                self._next_baton += 1
                next_baton = f"baton-{self._next_baton}"
                self._streams[next_baton] = db
        return httpx.Response(200, json={"baton": next_baton, "base_url": self.base_url, "results": results})


def _error(e: sqlite3.Error) -> dict:
    return {"message": str(e), "code": getattr(e, "sqlite_errorname", "SQL_INPUT_ERROR")}


def _batch(db: sqlite3.Connection, batch: dict) -> dict:
    results, errors = [], []
    for step in batch["steps"]:
        result = error = None
        if _condition(step.get("condition"), results):
            try:
                result = _execute(db, step["stmt"])
            except sqlite3.Error as e:
                error = _error(e)
        results.append(result)
        errors.append(error)
    return {"step_results": results, "step_errors": errors}


def _condition(cond: dict | None, results: list) -> bool:
    if cond is None:
        return True
    assert cond["type"] == "ok", "seule condition utilisée par le pilote"
    return results[cond["step"]] is not None


def _execute(db: sqlite3.Connection, stmt: dict) -> dict:
    cur = db.execute(stmt["sql"], [_decode(v) for v in stmt.get("args", [])])
    rows = cur.fetchall() if cur.description else []
    return {
        "cols": [{"name": c[0], "decltype": None} for c in cur.description or []],
        "rows": [[_encode(v) for v in row] for row in rows],
        "affected_row_count": max(cur.rowcount, 0),
        "last_insert_rowid": None if cur.lastrowid is None else str(cur.lastrowid),
    }


def _decode(value: dict):
    kind = value["type"]
    if kind == "null":
        return None
    if kind == "integer":
        assert isinstance(value["value"], str), "Hrana : un entier voyage en chaîne"
        return int(value["value"])
    if kind == "float":
        assert isinstance(value["value"], float)
        return value["value"]
    if kind == "text":
        return value["value"]
    assert kind == "blob"
    return base64.b64decode(value["base64"])


def _encode(value) -> dict:
    if value is None:
        return {"type": "null"}
    if isinstance(value, int):
        return {"type": "integer", "value": str(value)}
    if isinstance(value, float):
        return {"type": "float", "value": value}
    if isinstance(value, str):
        return {"type": "text", "value": value}
    # le vrai serveur n'envoie pas le remplissage « = »
    return {"type": "blob", "base64": base64.b64encode(value).decode().rstrip("=")}
