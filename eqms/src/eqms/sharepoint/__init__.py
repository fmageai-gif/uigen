"""SharePoint-backed Excel storage with a swappable local backend.

The rest of the application depends only on the :class:`~eqms.sharepoint.base.ExcelStore`
interface. Use :func:`~eqms.sharepoint.factory.get_store` to obtain the
appropriate concrete backend for the current configuration.
"""

from .base import ExcelStore
from .factory import get_store, reset_store

__all__ = ["ExcelStore", "get_store", "reset_store"]
