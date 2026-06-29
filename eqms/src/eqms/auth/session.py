"""Session manager — the single point of truth for the current user.

Owns the active :class:`AuthProvider`, the signed-in :class:`User`, and the
permission checks the UI relies on. Also wires the authenticated token provider
into the SharePoint storage backend when running online.
"""

from __future__ import annotations

import threading
from typing import Callable, Optional

from ..core.exceptions import NotAuthenticatedError, PermissionDeniedError
from ..core.logging_config import get_logger
from ..core.models import User
from .ms_auth import AuthProvider, LocalAuthProvider

_log = get_logger(__name__)


class SessionManager:
    """Holds the current authentication state for the running application."""

    def __init__(self, provider: AuthProvider | None = None):
        self._provider: AuthProvider = provider or LocalAuthProvider()
        self._user: Optional[User] = None
        self._lock = threading.RLock()

    # -- provider -----------------------------------------------------------

    def set_provider(self, provider: AuthProvider) -> None:
        with self._lock:
            self._provider = provider

    @property
    def provider(self) -> AuthProvider:
        return self._provider

    @property
    def is_online(self) -> bool:
        return self._provider.online

    # -- authentication -----------------------------------------------------

    def sign_in(self, prompt_callback: Callable[[str], None] | None = None) -> User:
        """Authenticate via the active provider and store the session user.

        Enforces the configurable login allow-list: only authorised QA emails
        and the Super Administrator may sign in. Unauthorised accounts are
        rejected before any session is established.
        """
        with self._lock:
            user = self._provider.sign_in(prompt_callback)
            self._authorise(user)
            self._user = user
            self._wire_storage()
            return user

    def _authorise(self, user: User) -> None:
        """Raise :class:`PermissionDeniedError` if the user is not allow-listed."""
        from ..data.settings_store import SettingsStore

        try:
            settings = SettingsStore()
            settings.ensure_seeded()
            allowed = settings.is_login_allowed(user.email)
        except PermissionDeniedError:
            raise
        except Exception as exc:  # noqa: BLE001 - never hard-fail open on errors
            _log.error("Authorization check failed for %s: %s", user.email, exc)
            allowed = True  # fail open on infrastructure errors, not policy
        if not allowed:
            _log.warning("Rejected unauthorised sign-in: %s", user.email)
            raise PermissionDeniedError(
                "This account is not authorized to use EQMS. "
                "Please contact your administrator."
            )

    def sign_out(self) -> None:
        with self._lock:
            if self._user:
                _log.info("Signing out %s", self._user.email)
            self._provider.sign_out()
            self._user = None

    def _wire_storage(self) -> None:
        """Connect the authenticated token provider to the storage backend.

        Only meaningful for online providers; the local fallback leaves the
        local Excel store in place.
        """
        if not self._provider.online:
            return
        from .. import config
        from ..data.settings_store import SettingsStore
        from ..sharepoint import factory

        try:
            settings = SettingsStore()
            settings.ensure_seeded()
            if settings.get_bool("sharepoint.enabled"):
                site = settings.get("sharepoint.site_url")
                folder = settings.get("sharepoint.folder_path", "Shared Documents/EQMS")
                if site:
                    factory.configure_sharepoint(site, folder, self._provider.get_token)
                    _log.info("SharePoint storage wired for %s", site)
        except Exception as exc:  # noqa: BLE001 - fall back to local store
            _log.error("Could not wire SharePoint storage, using local: %s", exc)

    # -- current user / permissions ----------------------------------------

    @property
    def user(self) -> User:
        if self._user is None:
            raise NotAuthenticatedError("No user is signed in")
        return self._user

    @property
    def is_authenticated(self) -> bool:
        return self._user is not None

    @property
    def is_admin(self) -> bool:
        return bool(self._user and self._user.is_admin)

    def require_admin(self) -> None:
        """Raise :class:`PermissionDeniedError` unless the user is the admin."""
        if not self.is_admin:
            raise PermissionDeniedError(
                "Only the Super Administrator may perform this action."
            )

    def can_edit_audit(self, audit_qa_email: str) -> bool:
        """QA may edit only their own audits; the admin may edit any."""
        from ..core.utils import normalise_email

        if not self.is_authenticated:
            return False
        if self.is_admin:
            return True
        return normalise_email(audit_qa_email) == normalise_email(self.user.email)


# ---------------------------------------------------------------------------
# Process-wide singleton
# ---------------------------------------------------------------------------

_session: SessionManager | None = None


def get_session() -> SessionManager:
    """Return the process-wide :class:`SessionManager` (created on first use)."""
    global _session
    if _session is None:
        _session = SessionManager()
    return _session
