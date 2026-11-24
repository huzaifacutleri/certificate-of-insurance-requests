"""SQLite persistence (standard library only).

Design notes
------------
* Every row carries ``agency_id`` and ``Repository`` is constructed *for one agency*, so a
  query can never cross tenants by accident. Moving to Postgres later keeps this shape.
* Records are stored as JSON documents (``data``) next to the few columns we query on
  (status, message id). That keeps schema churn low while the product is still changing.
* ``audit_log`` is append-only: who did what to which request, and when.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from .models import Client, CoiRequest, RequestStatus

SCHEMA = """
CREATE TABLE IF NOT EXISTS clients (
    agency_id TEXT NOT NULL,
    id        TEXT NOT NULL,
    name      TEXT NOT NULL,
    data      TEXT NOT NULL,
    PRIMARY KEY (agency_id, id)
);
CREATE TABLE IF NOT EXISTS requests (
    id         TEXT PRIMARY KEY,
    agency_id  TEXT NOT NULL,
    message_id TEXT NOT NULL,
    status     TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    data       TEXT NOT NULL,
    UNIQUE (agency_id, message_id)
);
CREATE INDEX IF NOT EXISTS idx_requests_status ON requests (agency_id, status, created_at);
CREATE TABLE IF NOT EXISTS audit_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    agency_id  TEXT NOT NULL,
    request_id TEXT NOT NULL,
    at         TEXT NOT NULL,
    actor      TEXT NOT NULL,
    action     TEXT NOT NULL,
    detail     TEXT NOT NULL DEFAULT ''
);
"""


def connect(path: str) -> sqlite3.Connection:
    """Open (and initialise) the database. ``:memory:`` works for tests."""
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


class RequestNotFound(KeyError):
    pass


class Repository:
    """Data access for one agency."""

    def __init__(self, conn: sqlite3.Connection, agency_id: str) -> None:
        self._conn = conn
        self.agency_id = agency_id

    # ---- clients -----------------------------------------------------------------

    def upsert_clients(self, clients: list[Client]) -> None:
        with self._conn:
            self._conn.executemany(
                "INSERT INTO clients (agency_id, id, name, data) VALUES (?, ?, ?, ?) "
                "ON CONFLICT (agency_id, id) DO UPDATE SET name = excluded.name, data = excluded.data",
                [(self.agency_id, c.id, c.name, c.model_dump_json()) for c in clients],
            )

    def list_clients(self) -> list[Client]:
        rows = self._conn.execute(
            "SELECT data FROM clients WHERE agency_id = ? ORDER BY name", (self.agency_id,)
        )
        return [Client.model_validate_json(r["data"]) for r in rows]

    def get_client(self, client_id: str) -> Client | None:
        row = self._conn.execute(
            "SELECT data FROM clients WHERE agency_id = ? AND id = ?", (self.agency_id, client_id)
        ).fetchone()
        return Client.model_validate_json(row["data"]) if row else None

    # ---- requests ----------------------------------------------------------------

    def find_by_message_id(self, message_id: str) -> CoiRequest | None:
        """Used to de-duplicate: the same email delivered twice must create one request."""
        row = self._conn.execute(
            "SELECT data FROM requests WHERE agency_id = ? AND message_id = ?",
            (self.agency_id, message_id),
        ).fetchone()
        return CoiRequest.model_validate_json(row["data"]) if row else None

    def save_request(self, request: CoiRequest) -> None:
        """Insert or update a request (keyed by id)."""
        with self._conn:
            self._conn.execute(
                "INSERT INTO requests (id, agency_id, message_id, status, created_at, updated_at, data) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (id) DO UPDATE SET status = excluded.status, "
                "updated_at = excluded.updated_at, data = excluded.data",
                (
                    request.id,
                    self.agency_id,
                    request.email.message_id,
                    request.status.value,
                    request.created_at.isoformat(),
                    request.updated_at.isoformat(),
                    request.model_dump_json(),
                ),
            )

    def get_request(self, request_id: str) -> CoiRequest:
        row = self._conn.execute(
            "SELECT data FROM requests WHERE agency_id = ? AND id = ?",
            (self.agency_id, request_id),
        ).fetchone()
        if row is None:
            raise RequestNotFound(request_id)
        return CoiRequest.model_validate_json(row["data"])

    def list_requests(self, status: RequestStatus | None = None) -> list[CoiRequest]:
        sql = "SELECT data FROM requests WHERE agency_id = ?"
        params: list[str] = [self.agency_id]
        if status is not None:
            sql += " AND status = ?"
            params.append(status.value)
        rows = self._conn.execute(sql + " ORDER BY created_at DESC", params)
        return [CoiRequest.model_validate_json(r["data"]) for r in rows]

    # ---- audit log ---------------------------------------------------------------

    def add_audit(self, request_id: str, actor: str, action: str, detail: str = "") -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO audit_log (agency_id, request_id, at, actor, action, detail) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    self.agency_id,
                    request_id,
                    datetime.now(UTC).isoformat(),
                    actor,
                    action,
                    detail,
                ),
            )

    def list_audit(self, request_id: str) -> list[dict[str, str]]:
        rows = self._conn.execute(
            "SELECT at, actor, action, detail FROM audit_log "
            "WHERE agency_id = ? AND request_id = ? ORDER BY id",
            (self.agency_id, request_id),
        )
        return [dict(r) for r in rows]
