"""Application context — the composition root wiring everything together.

A single :class:`AppContext` instance owns the session, settings, repositories
and services, plus a background worker thread that performs periodic sync,
backups, monthly reports and update checks without blocking the UI thread.

The UI receives one ``AppContext`` and reaches services through it, keeping
construction and dependency wiring in one place.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import Callable

from ..auth.session import SessionManager, get_session
from ..core.logging_config import get_logger
from ..data.archive import ArchiveRepository
from ..data.audit_repository import AuditRepository
from ..data.local_cache import LocalCache
from ..data.logs_store import LogsRepository
from ..data.masterlist import MasterlistRepository
from ..data.settings_store import SettingsStore
from ..sharepoint import get_store
from .audit_service import AuditService
from .backup_service import BackupService
from .dashboard_service import DashboardService
from .email_service import EmailService
from .report_service import ReportService
from .update_service import UpdateService

_log = get_logger(__name__)


class AppContext:
    """Owns and exposes every service the UI needs."""

    def __init__(self, session: SessionManager | None = None):
        self.session = session or get_session()
        self.store = get_store()

        # Repositories (shared instances so caches are coherent).
        self.settings = SettingsStore(self.store)
        self.cache = LocalCache()
        self.logs = LogsRepository(self.store)
        self.masterlist = MasterlistRepository(self.store)
        self.audits = AuditRepository(self.store)
        self.archive = ArchiveRepository(self.store)

        # Services.
        self.audit_service = AuditService(
            audits=self.audits, archive=self.archive, masterlist=self.masterlist,
            settings=self.settings, logs=self.logs, session=self.session,
        )
        self.dashboard_service = DashboardService(self.audits, self.cache)
        self.email_service = EmailService(
            settings=self.settings, logs=self.logs, session=self.session,
        )
        self.report_service = ReportService(
            audits=self.audits, settings=self.settings,
            dashboard=self.dashboard_service,
        )
        self.backup_service = BackupService(
            store=self.store, settings=self.settings, logs=self.logs,
        )
        self.update_service = UpdateService(self.settings)

        self._worker: BackgroundWorker | None = None

    # -- lifecycle ----------------------------------------------------------

    def initialise(self) -> None:
        """Seed configuration and warm caches. Safe to call once at start-up."""
        self.settings.ensure_seeded()
        _log.info("AppContext initialised (backend=%s)", self.store.backend_name)

    def start_background_worker(
        self, on_event: Callable[[str], None] | None = None
    ) -> None:
        """Launch the periodic background worker (idempotent)."""
        if self._worker and self._worker.is_alive():
            return
        self._worker = BackgroundWorker(self, on_event=on_event)
        self._worker.start()

    def stop_background_worker(self) -> None:
        if self._worker:
            self._worker.stop()
            self._worker = None

    # -- convenience --------------------------------------------------------

    def submit_audit(self, audit, *, send_email: bool = True):
        """Create an audit and dispatch its notification email if applicable.

        Returns ``(saved_audit, email_detail)``. Email failures never block the
        save; the audit's ``email_sent`` flag records the outcome.
        """
        saved = self.audit_service.create(audit)
        detail = ""
        if send_email and self.email_service.should_send(saved):
            sent, detail = self.email_service.send_audit_email(saved)
            from dataclasses import replace

            saved = replace(saved, email_sent="Yes" if sent else "Queued")
            self.audits.update(saved)
        return saved, detail


class BackgroundWorker(threading.Thread):
    """Daemon thread running periodic maintenance tasks."""

    def __init__(self, ctx: AppContext, on_event: Callable[[str], None] | None = None):
        super().__init__(name="eqms-bg", daemon=True)
        self.ctx = ctx
        self._on_event = on_event
        self._stop = threading.Event()
        self._last_backup: datetime | None = None
        self._last_report_check: str = ""
        self._last_update_check = 0.0

    def stop(self) -> None:
        self._stop.set()

    def _emit(self, message: str) -> None:
        if self._on_event:
            try:
                self._on_event(message)
            except Exception:  # noqa: BLE001 - UI callback must not kill worker
                pass

    def run(self) -> None:  # pragma: no cover - timing/loop behaviour
        _log.info("Background worker started")
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as exc:  # noqa: BLE001 - keep the loop alive
                _log.error("Background tick error: %s", exc)
            interval = self.ctx.settings.get_int(
                "sync.interval_seconds", 60
            )
            self._stop.wait(max(15, interval))
        _log.info("Background worker stopped")

    def _tick(self) -> None:
        # 1) Refresh data so the dashboard stays current.
        if self.ctx.settings.get_bool("sync.auto", True):
            self.ctx.dashboard_service.load_audits(refresh=True)
            self._emit("data-refreshed")

        # 2) Automatic backups.
        if self.ctx.backup_service.due(self._last_backup):
            self.ctx.backup_service.backup_now()
            self._last_backup = datetime.now()
            self._emit("backup-complete")

        # 3) Automatic monthly report.
        due = self.ctx.report_service.auto_monthly_due()
        token = datetime.now().strftime("%Y-%m")
        if due and self._last_report_check != token:
            self.ctx.report_service.generate_monthly(*due)
            self._last_report_check = token
            self._emit("report-generated")

        # 4) Update check (at most hourly).
        now = time.time()
        if (self.ctx.update_service.is_enabled()
                and now - self._last_update_check > 3600):
            info = self.ctx.update_service.check()
            self._last_update_check = now
            if info.available:
                self._emit(f"update-available:{info.latest_version}")
