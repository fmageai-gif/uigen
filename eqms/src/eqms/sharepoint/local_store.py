"""Local filesystem implementation of :class:`ExcelStore`.

Mirrors the SharePoint document library as a folder on disk. This backend lets
the entire application run, be demonstrated and be unit-tested without a
Microsoft 365 tenant. It also serves as the offline cache target.

A lightweight advisory lock file per workbook simulates SharePoint's
single-writer behaviour so the retry machinery has something realistic to react
to under concurrent access (e.g. two app instances on the same machine).
"""

from __future__ import annotations

import os
import shutil
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Sequence

from ..core.exceptions import WorkbookLockedError, WorkbookNotFoundError
from ..core.logging_config import get_logger
from . import excel_io
from .base import ExcelStore, WorkbookSession

_log = get_logger(__name__)


class LocalExcelStore(ExcelStore):
    """Store workbooks in a local directory tree."""

    backend_name = "Local"

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        _log.info("LocalExcelStore rooted at %s", self.root)

    # -- path helpers -------------------------------------------------------

    def _path(self, workbook: str) -> Path:
        return self.root / workbook

    def _lock_path(self, workbook: str) -> Path:
        return self.root / f".{workbook}.lock"

    # -- ExcelStore API -----------------------------------------------------

    def exists(self, workbook: str) -> bool:
        return self._path(workbook).exists()

    def read_rows(
        self, workbook: str, sheet: str | None = None
    ) -> list[dict[str, str]]:
        return excel_io.read_rows(self._path(workbook), sheet)

    def download(self, workbook: str, destination: Path) -> Path:
        src = self._path(workbook)
        if not src.exists():
            raise WorkbookNotFoundError(f"{workbook} not found in local store")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, destination)
        return destination

    def upload(self, workbook: str, source: Path) -> None:
        dst = self._path(workbook)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dst)

    @contextmanager
    def open_workbook(
        self, workbook: str, headers: Sequence[str], sheet: str
    ) -> Iterator[WorkbookSession]:
        path = self._path(workbook)
        with self._advisory_lock(workbook):
            excel_io.ensure_sheet(path, sheet, headers)
            session = WorkbookSession(workbook, path)
            yield session
            # Local store writes in place, so a dirty flag needs no flush; the
            # file is already the source of truth. We keep the flag for parity.

    # -- advisory locking ---------------------------------------------------

    @contextmanager
    def _advisory_lock(self, workbook: str, timeout: float = 5.0):
        """Acquire an exclusive lock file, raising if it cannot be obtained.

        Raising :class:`WorkbookLockedError` lets the retry layer back off and
        try again, mirroring SharePoint's behaviour when a file is checked out.
        """
        lock = self._lock_path(workbook)
        deadline = time.time() + timeout
        fd = None
        while True:
            try:
                fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                break
            except FileExistsError:
                if time.time() >= deadline:
                    raise WorkbookLockedError(
                        f"{workbook} is locked by another process"
                    )
                time.sleep(0.1)
        try:
            yield
        finally:
            if fd is not None:
                os.close(fd)
            try:
                lock.unlink()
            except FileNotFoundError:  # pragma: no cover
                pass
