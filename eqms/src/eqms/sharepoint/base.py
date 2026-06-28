"""Abstract Excel storage backend.

Defines the contract the data layer relies on. Two concrete implementations
exist: :class:`~eqms.sharepoint.local_store.LocalExcelStore` (offline/dev) and
:class:`~eqms.sharepoint.sharepoint_store.SharePointExcelStore` (production).

Workbooks are addressed by *name* (e.g. ``"AuditDatabase.xlsx"``); the backend
maps the name to its physical location (a local folder or a SharePoint document
library path). Sheet-level read/modify/write is mediated through a context
manager (:meth:`open_workbook`) so the SharePoint backend can download once,
apply several mutations, and upload once — minimising lock contention.
"""

from __future__ import annotations

import abc
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Sequence

from ..core.logging_config import get_logger

_log = get_logger(__name__)


class WorkbookSession:
    """A mutable handle to a locally-materialised workbook within a transaction.

    Instances are yielded by :meth:`ExcelStore.open_workbook`. Mutations are
    buffered on the local file and flushed back to the underlying store when the
    context exits successfully.
    """

    def __init__(self, name: str, local_path: Path):
        self.name = name
        self.local_path = local_path
        self.dirty = False

    def mark_dirty(self) -> None:
        self.dirty = True


class ExcelStore(abc.ABC):
    """Transport-agnostic interface for reading/writing Excel workbooks."""

    #: Human-readable backend label used in logs and the System Status widget.
    backend_name: str = "abstract"

    # -- read paths (cheap, no upload) --------------------------------------

    @abc.abstractmethod
    def read_rows(
        self, workbook: str, sheet: str | None = None
    ) -> list[dict[str, str]]:
        """Return all data rows of ``sheet`` as header→value dicts."""

    @abc.abstractmethod
    def exists(self, workbook: str) -> bool:
        """Return ``True`` if ``workbook`` exists in the store."""

    # -- whole-workbook transfer --------------------------------------------

    @abc.abstractmethod
    def download(self, workbook: str, destination: Path) -> Path:
        """Copy ``workbook`` from the store to ``destination`` locally."""

    @abc.abstractmethod
    def upload(self, workbook: str, source: Path) -> None:
        """Replace ``workbook`` in the store with the file at ``source``."""

    # -- transactional mutation ---------------------------------------------

    @abc.abstractmethod
    def open_workbook(
        self, workbook: str, headers: Sequence[str], sheet: str
    ) -> AbstractContextManager[WorkbookSession]:  # pragma: no cover - abstract
        """Return a context manager yielding a :class:`WorkbookSession`.

        On a clean ``with`` exit, if the session was marked dirty the local file
        is flushed back to the store. On exception nothing is flushed.
        Concrete backends implement this with ``@contextlib.contextmanager``.
        """
        raise NotImplementedError

    # -- convenience built on the primitives --------------------------------

    def write_rows(
        self,
        workbook: str,
        sheet: str,
        headers: Sequence[str],
        rows: Sequence[Sequence[str]],
    ) -> None:
        """Replace the contents of a sheet in one transaction."""
        from . import excel_io

        with self.open_workbook(workbook, headers, sheet) as session:
            excel_io.write_rows(session.local_path, sheet, headers, rows)
            session.mark_dirty()

    def append_row(
        self,
        workbook: str,
        sheet: str,
        headers: Sequence[str],
        row: Sequence[str],
    ) -> None:
        """Append a single row in one transaction."""
        from . import excel_io

        with self.open_workbook(workbook, headers, sheet) as session:
            excel_io.append_row(session.local_path, sheet, headers, row)
            session.mark_dirty()
