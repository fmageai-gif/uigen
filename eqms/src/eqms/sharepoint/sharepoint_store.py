"""SharePoint implementation of :class:`ExcelStore` using Office365-REST.

Workbooks live in a SharePoint document library folder (configured in
``Settings.xlsx`` / local config). Each mutating transaction:

1. downloads the workbook to a temp file,
2. applies the openpyxl mutation locally,
3. uploads the file back, overwriting the server copy.

Every network operation is wrapped in :func:`eqms.core.retry.retry_call` so
transient locking/throttling is retried with back-off. Authentication uses the
delegated access token obtained by :mod:`eqms.auth`.

This module imports ``office365`` lazily so the package remains importable (and
the local backend remains usable) on machines without that dependency.
"""

from __future__ import annotations

import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator, Sequence

from ..core.exceptions import (
    ConnectivityError,
    StorageError,
    WorkbookLockedError,
    WorkbookNotFoundError,
)
from ..core.logging_config import get_logger
from ..core.retry import retry_call
from . import excel_io
from .base import ExcelStore, WorkbookSession

_log = get_logger(__name__)


class SharePointExcelStore(ExcelStore):
    """Read/write Excel workbooks stored in a SharePoint document library.

    Parameters
    ----------
    site_url:
        Full SharePoint site URL, e.g. ``https://contoso.sharepoint.com/sites/QA``.
    folder_path:
        Server-relative folder holding the workbooks, e.g.
        ``/sites/QA/Shared Documents/EQMS``.
    token_provider:
        Zero-argument callable returning a valid Graph/SharePoint bearer token.
        Injected from the auth layer so this class never owns credentials.
    """

    backend_name = "SharePoint"

    def __init__(
        self,
        site_url: str,
        folder_path: str,
        token_provider: Callable[[], str],
    ):
        self.site_url = site_url.rstrip("/")
        self.folder_path = "/" + folder_path.strip("/")
        self._token_provider = token_provider
        self._ctx = None  # lazily created ClientContext

    # -- client context -----------------------------------------------------

    def _client(self):
        """Return an authenticated Office365 ``ClientContext`` (cached)."""
        if self._ctx is not None:
            return self._ctx
        try:
            from office365.runtime.auth.token_response import TokenResponse
            from office365.sharepoint.client_context import ClientContext
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise StorageError(
                "Office365-REST-Python-Client is not installed"
            ) from exc

        def _with_token(request):
            token = self._token_provider()
            request.ensure_header("Authorization", f"Bearer {token}")

        ctx = ClientContext(self.site_url)
        ctx.with_access_token(
            lambda: TokenResponse(self._token_provider(), "Bearer")
        )
        self._ctx = ctx
        return ctx

    def _server_relative_url(self, workbook: str) -> str:
        return f"{self.folder_path}/{workbook}"

    # -- ExcelStore API -----------------------------------------------------

    def exists(self, workbook: str) -> bool:
        def _check() -> bool:
            ctx = self._client()
            try:
                f = ctx.web.get_file_by_server_relative_url(
                    self._server_relative_url(workbook)
                )
                ctx.load(f)
                ctx.execute_query()
                return True
            except Exception as exc:  # noqa: BLE001 - office365 raises broadly
                if _is_not_found(exc):
                    return False
                raise _translate(exc)

        return retry_call(_check, description=f"exists({workbook})")

    def read_rows(
        self, workbook: str, sheet: str | None = None
    ) -> list[dict[str, str]]:
        with tempfile.TemporaryDirectory() as tmp:
            local = Path(tmp) / workbook
            self.download(workbook, local)
            return excel_io.read_rows(local, sheet)

    def download(self, workbook: str, destination: Path) -> Path:
        def _download() -> Path:
            ctx = self._client()
            destination.parent.mkdir(parents=True, exist_ok=True)
            url = self._server_relative_url(workbook)
            try:
                with open(destination, "wb") as handle:
                    f = ctx.web.get_file_by_server_relative_url(url)
                    f.download(handle)
                    ctx.execute_query()
            except Exception as exc:  # noqa: BLE001
                raise _translate(exc, workbook)
            return destination

        return retry_call(_download, description=f"download({workbook})")

    def upload(self, workbook: str, source: Path) -> None:
        def _upload() -> None:
            ctx = self._client()
            try:
                target = ctx.web.get_folder_by_server_relative_url(self.folder_path)
                with open(source, "rb") as handle:
                    content = handle.read()
                target.upload_file(workbook, content)
                ctx.execute_query()
            except Exception as exc:  # noqa: BLE001
                raise _translate(exc, workbook)

        retry_call(_upload, description=f"upload({workbook})")

    @contextmanager
    def open_workbook(
        self, workbook: str, headers: Sequence[str], sheet: str
    ) -> Iterator[WorkbookSession]:
        """Download → mutate locally → upload, with retry on the round-trip.

        The whole transaction is retried as a unit so a lock encountered during
        upload re-downloads the latest copy and re-applies the change, avoiding
        lost updates.
        """
        tmpdir = tempfile.mkdtemp(prefix="eqms_sp_")
        local = Path(tmpdir) / workbook
        try:
            if self.exists(workbook):
                self.download(workbook, local)
            excel_io.ensure_sheet(local, sheet, headers)
            session = WorkbookSession(workbook, local)
            yield session
            if session.dirty:
                self.upload(workbook, local)
                _log.debug("Flushed %s to SharePoint", workbook)
        finally:
            import shutil

            shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Error translation
# ---------------------------------------------------------------------------

def _is_not_found(exc: Exception) -> bool:
    text = str(exc).lower()
    return "404" in text or "not found" in text or "does not exist" in text


def _is_locked(exc: Exception) -> bool:
    text = str(exc).lower()
    return "423" in text or "locked" in text or "checked out" in text


def _translate(exc: Exception, workbook: str | None = None) -> StorageError:
    """Map an office365/requests exception onto the app's exception types."""
    label = workbook or "workbook"
    if _is_not_found(exc):
        return WorkbookNotFoundError(f"{label} not found on SharePoint")
    if _is_locked(exc):
        return WorkbookLockedError(f"{label} is locked on SharePoint: {exc}")
    return ConnectivityError(f"SharePoint error for {label}: {exc}")
