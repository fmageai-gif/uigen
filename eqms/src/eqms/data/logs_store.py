"""``SystemLogs.xlsx`` repository — the business audit trail.

Distinct from the technical application log (rotating text files): this records
*who did what, when* — every administrator action and significant QA event —
and is persisted to SharePoint so it survives reinstalls and is auditable.

Writes are best-effort and non-blocking from the caller's perspective: a
failure to record a log entry must never abort the user action that triggered
it, so exceptions are swallowed (after being written to the technical log).
"""

from __future__ import annotations

import threading

from ..core.logging_config import get_logger
from ..core.models import LogEntry
from ..core.utils import now_iso
from .. import config
from ..sharepoint import ExcelStore, get_store

_log = get_logger(__name__)

SHEET_LOGS = "Logs"


class LogsRepository:
    """Append-only access to the system audit-trail workbook."""

    def __init__(self, store: ExcelStore | None = None):
        self._store = store or get_store()
        self._lock = threading.RLock()

    def record(self, action: str, *, user: str = "system",
               details: str = "", level: str = "INFO") -> None:
        """Append an audit-trail entry. Never raises."""
        entry = LogEntry(
            timestamp=now_iso(), level=level, user=user,
            action=action, details=details,
        )
        try:
            with self._lock:
                self._store.append_row(
                    config.WORKBOOK_LOGS, SHEET_LOGS, LogEntry.HEADERS, entry.to_row()
                )
        except Exception as exc:  # noqa: BLE001 - logging must never break flow
            _log.error("Failed to write system log entry '%s': %s", action, exc)

    def all(self, limit: int | None = None) -> list[LogEntry]:
        """Return audit-trail entries, most recent first."""
        rows = self._store.read_rows(config.WORKBOOK_LOGS, SHEET_LOGS)
        entries = [LogEntry.from_row(r) for r in rows]
        entries.reverse()
        return entries[:limit] if limit else entries

    def clear(self) -> None:
        """Truncate the audit trail (admin-only, itself logged by the caller)."""
        with self._lock:
            self._store.write_rows(
                config.WORKBOOK_LOGS, SHEET_LOGS, LogEntry.HEADERS, []
            )
