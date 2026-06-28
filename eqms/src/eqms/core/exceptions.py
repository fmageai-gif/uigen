"""Application-specific exception hierarchy.

A single rooted hierarchy lets the UI layer distinguish *expected* business
failures (which become friendly dialogs) from *unexpected* programming errors
(which are logged with a full traceback and reported as "an unexpected error
occurred").
"""

from __future__ import annotations


class EQMSError(Exception):
    """Base class for every error raised intentionally by the application."""


# -- Authentication ---------------------------------------------------------


class AuthError(EQMSError):
    """Raised when Microsoft 365 authentication fails or is cancelled."""


class NotAuthenticatedError(AuthError):
    """Raised when an operation requires a signed-in user but none is present."""


class PermissionDeniedError(EQMSError):
    """Raised when the current user lacks permission for an action."""


# -- Storage / SharePoint ---------------------------------------------------


class StorageError(EQMSError):
    """Base class for failures in the SharePoint/Excel storage layer."""


class WorkbookLockedError(StorageError):
    """Raised when a workbook is locked by another user and retries exhausted."""


class WorkbookNotFoundError(StorageError):
    """Raised when an expected workbook does not exist on SharePoint."""


class ConnectivityError(StorageError):
    """Raised when SharePoint/Graph cannot be reached after retries."""


# -- Domain / validation ----------------------------------------------------


class ValidationError(EQMSError):
    """Raised when user-supplied data fails a validation rule.

    Parameters
    ----------
    message:
        Human-readable description shown to the user.
    field:
        Optional name of the offending form field, so the UI can highlight it.
    """

    def __init__(self, message: str, field: str | None = None) -> None:
        super().__init__(message)
        self.field = field


class DuplicateAuditError(ValidationError):
    """Raised when an audit violates the Case Number + Genesys ID uniqueness."""


class ConfigurationError(EQMSError):
    """Raised when required configuration is missing or invalid."""
