"""Automatic backups of the system-of-record workbooks.

Downloads each managed workbook from the active store into a timestamped local
folder, applies a retention policy (keep the N most recent backups), and is
safe to run on a schedule from the background worker.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .. import config
from ..core.logging_config import get_logger
from ..data.logs_store import LogsRepository
from ..data.settings_store import SettingsStore
from ..sharepoint import ExcelStore, get_store

_log = get_logger(__name__)


@dataclass(slots=True)
class BackupResult:
    folder: Path
    files: list[str]
    timestamp: str


class BackupService:
    """Create and prune local backups of all managed workbooks."""

    def __init__(
        self,
        *,
        store: ExcelStore | None = None,
        settings: SettingsStore | None = None,
        logs: LogsRepository | None = None,
    ):
        self.store = store or get_store()
        self.settings = settings or SettingsStore()
        self.logs = logs or LogsRepository()

    def backup_now(self, *, user: str = "system") -> BackupResult:
        """Back up every existing managed workbook into a timestamped folder."""
        config.ensure_directories()
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        folder = config.BACKUP_DIR / stamp
        folder.mkdir(parents=True, exist_ok=True)

        saved: list[str] = []
        for workbook in config.ALL_WORKBOOKS:
            try:
                if self.store.exists(workbook):
                    self.store.download(workbook, folder / workbook)
                    saved.append(workbook)
            except Exception as exc:  # noqa: BLE001 - one bad file shouldn't abort
                _log.error("Backup of %s failed: %s", workbook, exc)

        self._prune()
        self.logs.record(
            "BACKUP_CREATED", user=user,
            details=f"{stamp}: {', '.join(saved) or 'no workbooks'}",
        )
        _log.info("Backup complete: %s (%d files)", folder, len(saved))
        return BackupResult(folder=folder, files=saved, timestamp=stamp)

    def _prune(self) -> None:
        """Delete the oldest backup folders beyond the retention count."""
        retention = self.settings.get_int("backup.retention", 30)
        folders = sorted(
            (p for p in config.BACKUP_DIR.iterdir()
             if p.is_dir() and p.name[0].isdigit()),
            key=lambda p: p.name,
        )
        excess = len(folders) - retention
        for old in folders[:max(0, excess)]:
            shutil.rmtree(old, ignore_errors=True)
            _log.info("Pruned old backup %s", old.name)

    def due(self, last_run: datetime | None) -> bool:
        """Return ``True`` if a scheduled backup is due given ``last_run``."""
        if not self.settings.get_bool("backup.enabled", True):
            return False
        if last_run is None:
            return True
        interval_hours = self.settings.get_int("backup.interval_hours", 24)
        elapsed = (datetime.now() - last_run).total_seconds() / 3600
        return elapsed >= interval_hours

    def list_backups(self) -> list[Path]:
        if not config.BACKUP_DIR.exists():
            return []
        return sorted(
            (p for p in config.BACKUP_DIR.iterdir()
             if p.is_dir() and p.name[0].isdigit()),
            key=lambda p: p.name, reverse=True,
        )
