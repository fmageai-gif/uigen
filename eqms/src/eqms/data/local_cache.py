"""Optional local SQLite cache (Excel on SharePoint remains the system of record).

Purpose is strictly performance and offline resilience: the dashboard can render
instantly from the last cached snapshot while a fresh copy is fetched in the
background, and the app degrades gracefully when SharePoint is unreachable.

The cache stores opaque JSON snapshots keyed by workbook name; it never becomes
authoritative and is safe to delete at any time.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from typing import Any

from ..core.logging_config import get_logger
from ..core.utils import now_iso
from .. import config

_log = get_logger(__name__)


class LocalCache:
    """Thread-safe key/value snapshot cache backed by SQLite."""

    def __init__(self, db_path=None):
        config.ensure_directories()
        self._path = str(db_path or config.CACHE_DB_PATH)
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS snapshots (
                    key        TEXT PRIMARY KEY,
                    payload    TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def put(self, key: str, value: Any) -> None:
        """Store a JSON-serialisable snapshot under ``key``."""
        payload = json.dumps(value, ensure_ascii=False)
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO snapshots(key, payload, updated_at) VALUES(?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET payload=excluded.payload, "
                "updated_at=excluded.updated_at",
                (key, payload, now_iso()),
            )

    def get(self, key: str, default: Any = None) -> Any:
        """Return the cached snapshot for ``key`` or ``default`` if absent."""
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM snapshots WHERE key=?", (key,)
            ).fetchone()
        if not row:
            return default
        try:
            return json.loads(row[0])
        except json.JSONDecodeError:  # pragma: no cover - corrupt cache
            return default

    def updated_at(self, key: str) -> str | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT updated_at FROM snapshots WHERE key=?", (key,)
            ).fetchone()
        return row[0] if row else None

    def clear(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM snapshots")
        _log.info("Local cache cleared")
