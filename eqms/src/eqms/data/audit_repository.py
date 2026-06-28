"""``AuditDatabase.xlsx`` repository — CRUD over audit submissions.

Handles persistence only; business validation (mandatory remarks, reason↔
validation matching, permissions) lives in the service layer. The repository
does enforce the *storage-level* uniqueness of the Case Number + Genesys
Transaction ID composite key, since that guarantee is intrinsic to the data.
"""

from __future__ import annotations

import threading
import time

from ..core.exceptions import DuplicateAuditError
from ..core.logging_config import get_logger
from ..core.models import Audit
from .. import config
from ..sharepoint import ExcelStore, get_store

_log = get_logger(__name__)

SHEET_AUDITS = "Audits"


class AuditRepository:
    """Read/write access to the active audit database."""

    def __init__(self, store: ExcelStore | None = None, cache_ttl: float = 30.0):
        self._store = store or get_store()
        self._cache_ttl = cache_ttl
        self._lock = threading.RLock()
        self._cache: list[Audit] = []
        self._loaded_at = 0.0

    # -- loading ------------------------------------------------------------

    def _maybe_load(self) -> None:
        if self._cache and time.time() - self._loaded_at <= self._cache_ttl:
            return
        self.refresh()

    def refresh(self) -> None:
        with self._lock:
            rows = self._store.read_rows(config.WORKBOOK_AUDIT_DB, SHEET_AUDITS)
            self._cache = [Audit.from_row(r) for r in rows]
            self._loaded_at = time.time()

    # -- reads --------------------------------------------------------------

    def all(self, *, refresh: bool = False) -> list[Audit]:
        if refresh:
            self.refresh()
        else:
            self._maybe_load()
        return list(self._cache)

    def get(self, audit_id: str) -> Audit | None:
        self._maybe_load()
        audit_id = (audit_id or "").strip()
        return next((a for a in self._cache if a.audit_id == audit_id), None)

    def for_user(self, qa_email: str) -> list[Audit]:
        from ..core.utils import normalise_email

        target = normalise_email(qa_email)
        return [a for a in self.all() if normalise_email(a.qa_email) == target]

    def exists_dedupe(self, case_number: str, genesys_id: str,
                      *, exclude_id: str = "") -> bool:
        """Return ``True`` if another audit shares the Case+Genesys key."""
        key = f"{case_number.strip().lower()}|{genesys_id.strip().lower()}"
        self._maybe_load()
        for a in self._cache:
            if a.audit_id == exclude_id:
                continue
            if a.dedupe_key == key:
                return True
        return False

    def next_audit_id(self) -> str:
        """Generate the next sequential audit id, e.g. ``AUD-2026-000123``.

        The numeric portion is monotonic across years to guarantee global
        uniqueness even if the year prefix differs.
        """
        from datetime import date

        self._maybe_load()
        max_seq = 0
        for a in self._cache:
            tail = a.audit_id.rsplit("-", 1)[-1]
            if tail.isdigit():
                max_seq = max(max_seq, int(tail))
        return f"AUD-{date.today().year}-{max_seq + 1:06d}"

    # -- writes -------------------------------------------------------------

    def add(self, audit: Audit) -> Audit:
        """Append a new audit, enforcing the composite uniqueness key."""
        with self._lock:
            self.refresh()  # re-read to catch concurrent inserts before checking
            if self.exists_dedupe(audit.case_number, audit.genesys_id):
                raise DuplicateAuditError(
                    "An audit with this Case Number and Genesys Transaction ID "
                    "already exists.",
                    field="case_number",
                )
            self._store.append_row(
                config.WORKBOOK_AUDIT_DB, SHEET_AUDITS, Audit.HEADERS, audit.to_row()
            )
            self._cache.append(audit)
        _log.info("Audit %s added by %s", audit.audit_id, audit.qa_email)
        return audit

    def update(self, audit: Audit) -> Audit:
        """Rewrite the sheet with ``audit`` replacing the row of equal id."""
        with self._lock:
            self.refresh()
            found = False
            new_rows: list[list[str]] = []
            for existing in self._cache:
                if existing.audit_id == audit.audit_id:
                    new_rows.append(audit.to_row())
                    found = True
                else:
                    new_rows.append(existing.to_row())
            if not found:
                new_rows.append(audit.to_row())
            self._store.write_rows(
                config.WORKBOOK_AUDIT_DB, SHEET_AUDITS, Audit.HEADERS, new_rows
            )
            self.refresh()
        _log.info("Audit %s updated", audit.audit_id)
        return audit

    def remove(self, audit_id: str) -> Audit | None:
        """Delete an audit row from the active database, returning it.

        Callers (the service layer) are expected to write the removed audit to
        the Archive workbook first — this method only detaches it from the
        active set.
        """
        with self._lock:
            self.refresh()
            removed: Audit | None = None
            kept_rows: list[list[str]] = []
            for existing in self._cache:
                if existing.audit_id == audit_id:
                    removed = existing
                else:
                    kept_rows.append(existing.to_row())
            if removed is None:
                return None
            self._store.write_rows(
                config.WORKBOOK_AUDIT_DB, SHEET_AUDITS, Audit.HEADERS, kept_rows
            )
            self.refresh()
        _log.info("Audit %s removed from active database", audit_id)
        return removed
