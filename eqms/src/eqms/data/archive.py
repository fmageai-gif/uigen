"""``Archive.xlsx`` repository — soft-deleted / archived audits.

Records are never permanently deleted from the active database without being
preserved here first, so the administrator can always restore them.
"""

from __future__ import annotations

import threading

from ..core.logging_config import get_logger
from ..core.models import Audit
from .. import config
from ..sharepoint import ExcelStore, get_store

_log = get_logger(__name__)

SHEET_ARCHIVE = "Archive"


class ArchiveRepository:
    """Append-and-restore access to the archive workbook."""

    def __init__(self, store: ExcelStore | None = None):
        self._store = store or get_store()
        self._lock = threading.RLock()

    def all(self) -> list[Audit]:
        rows = self._store.read_rows(config.WORKBOOK_ARCHIVE, SHEET_ARCHIVE)
        return [Audit.from_row(r) for r in rows]

    def get(self, audit_id: str) -> Audit | None:
        audit_id = (audit_id or "").strip()
        return next((a for a in self.all() if a.audit_id == audit_id), None)

    def add(self, audit: Audit) -> None:
        """Archive an audit (append to the archive workbook)."""
        with self._lock:
            self._store.append_row(
                config.WORKBOOK_ARCHIVE, SHEET_ARCHIVE, Audit.HEADERS, audit.to_row()
            )
        _log.info("Audit %s archived", audit.audit_id)

    def remove(self, audit_id: str) -> Audit | None:
        """Remove an audit from the archive (e.g. after restoring it)."""
        with self._lock:
            current = self.all()
            removed = next((a for a in current if a.audit_id == audit_id), None)
            if removed is None:
                return None
            kept = [a.to_row() for a in current if a.audit_id != audit_id]
            self._store.write_rows(
                config.WORKBOOK_ARCHIVE, SHEET_ARCHIVE, Audit.HEADERS, kept
            )
        _log.info("Audit %s removed from archive", audit_id)
        return removed
