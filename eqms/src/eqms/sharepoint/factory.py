"""Selects and caches the active :class:`ExcelStore` backend.

Selection rules:

* If a SharePoint site URL + folder are configured **and** an authenticated
  token provider is supplied, use :class:`SharePointExcelStore`.
* Otherwise fall back to :class:`LocalExcelStore` rooted at
  :data:`config.LOCAL_STORE_DIR` — the offline/development mode.

The active store is process-global and cached; call :func:`reset_store` after
changing connection settings (e.g. from the Admin Center) to force re-creation.
"""

from __future__ import annotations

from typing import Callable, Optional

from .. import config
from ..core.logging_config import get_logger
from .base import ExcelStore
from .local_store import LocalExcelStore
from .sharepoint_store import SharePointExcelStore

_log = get_logger(__name__)

_store: Optional[ExcelStore] = None


def configure_sharepoint(
    site_url: str,
    folder_path: str,
    token_provider: Callable[[], str],
) -> ExcelStore:
    """Create and cache a SharePoint-backed store, returning it."""
    global _store
    _store = SharePointExcelStore(site_url, folder_path, token_provider)
    _log.info("Storage backend: SharePoint (%s)", site_url)
    return _store


def get_store() -> ExcelStore:
    """Return the active store, creating a local fallback if none is set."""
    global _store
    if _store is None:
        config.ensure_directories()
        _store = LocalExcelStore(config.LOCAL_STORE_DIR)
        _log.info("Storage backend: Local fallback (%s)", config.LOCAL_STORE_DIR)
    return _store


def reset_store() -> None:
    """Clear the cached store so the next :func:`get_store` re-selects."""
    global _store
    _store = None
