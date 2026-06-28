"""Authentication providers.

:class:`GraphAuthProvider` performs real Microsoft 365 sign-in using MSAL's
public-client **device code flow** (well suited to desktop apps: no embedded
browser, no client secret) with a persistent encrypted token cache so users are
not prompted on every launch. It exposes a ``get_token`` callable that the
SharePoint storage backend uses to authorise its requests, and resolves the
signed-in user's profile from Microsoft Graph.

:class:`LocalAuthProvider` is an offline stand-in used when M365 is not
configured: the user simply confirms their work email. It enables the entire
application — including admin gating against
:data:`eqms.config.SUPER_ADMIN_EMAIL` — to run and be tested without a tenant.

``msal`` and ``requests`` are imported lazily so the package stays importable
without those optional dependencies.
"""

from __future__ import annotations

import abc
import atexit
from typing import Callable

import requests

from .. import config
from ..core.exceptions import AuthError
from ..core.logging_config import get_logger
from ..core.models import User
from ..core.utils import normalise_email

_log = get_logger(__name__)


def is_admin_email(email: str) -> bool:
    """Return ``True`` if ``email`` is the configured Super Administrator."""
    return normalise_email(email) == normalise_email(config.SUPER_ADMIN_EMAIL)


class AuthProvider(abc.ABC):
    """Abstract authentication provider."""

    #: True when this provider can authorise SharePoint/Graph calls.
    online: bool = False

    @abc.abstractmethod
    def sign_in(self, prompt_callback: Callable[[str], None] | None = None) -> User:
        """Authenticate and return the signed-in :class:`User`.

        ``prompt_callback`` receives a human-readable instruction (e.g. the
        device-code message) to surface in the UI during interactive flows.
        """

    @abc.abstractmethod
    def sign_out(self) -> None:
        """Forget the current account and clear cached tokens."""

    def get_token(self) -> str:  # pragma: no cover - overridden where meaningful
        """Return a bearer token for Graph/SharePoint. Raises if unavailable."""
        raise AuthError("This provider cannot issue access tokens")


# ---------------------------------------------------------------------------
# Microsoft 365 (MSAL device-code) provider
# ---------------------------------------------------------------------------

class GraphAuthProvider(AuthProvider):
    """Real Microsoft 365 authentication via MSAL device code flow."""

    online = True

    def __init__(self, client_id: str | None = None, tenant: str | None = None):
        self.client_id = client_id or config.DEFAULT_CLIENT_ID
        self.tenant = tenant or config.DEFAULT_TENANT
        self.authority = f"https://login.microsoftonline.com/{self.tenant}"
        self._app = None
        self._account = None

    def _build_app(self):
        if self._app is not None:
            return self._app
        try:
            import msal
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise AuthError("The 'msal' package is required for M365 sign-in") from exc

        config.ensure_directories()
        cache = msal.SerializableTokenCache()
        if config.TOKEN_CACHE_PATH.exists():
            try:
                cache.deserialize(config.TOKEN_CACHE_PATH.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001 - corrupt cache => start fresh
                _log.warning("Token cache unreadable, ignoring: %s", exc)

        def _persist():
            if cache.has_state_changed:
                config.TOKEN_CACHE_PATH.write_text(cache.serialize(), encoding="utf-8")

        atexit.register(_persist)
        self._persist = _persist

        self._app = msal.PublicClientApplication(
            self.client_id, authority=self.authority, token_cache=cache
        )
        return self._app

    def sign_in(self, prompt_callback: Callable[[str], None] | None = None) -> User:
        app = self._build_app()
        scopes = list(config.GRAPH_SCOPES)

        # Try silent acquisition from the cache first.
        accounts = app.get_accounts()
        result = None
        if accounts:
            result = app.acquire_token_silent(scopes, account=accounts[0])

        if not result:
            flow = app.initiate_device_flow(scopes=scopes)
            if "user_code" not in flow:
                raise AuthError(f"Failed to start device flow: {flow.get('error_description')}")
            message = flow.get(
                "message",
                f"To sign in, visit {flow.get('verification_uri')} and enter "
                f"code {flow.get('user_code')}",
            )
            _log.info("Device code sign-in initiated")
            if prompt_callback:
                prompt_callback(message)
            result = app.acquire_token_by_device_flow(flow)

        if "access_token" not in result:
            raise AuthError(result.get("error_description", "Authentication failed"))

        self._persist()
        self._account = app.get_accounts()[0] if app.get_accounts() else None
        user = self._resolve_profile(result["access_token"])
        _log.info("Signed in as %s (admin=%s)", user.email, user.is_admin)
        return user

    def _resolve_profile(self, token: str) -> User:
        try:
            resp = requests.get(
                f"{config.GRAPH_BASE_URL}/me",
                headers={"Authorization": f"Bearer {token}"},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            raise AuthError(f"Could not read user profile from Graph: {exc}") from exc

        email = (data.get("mail") or data.get("userPrincipalName") or "").strip()
        name = (data.get("displayName") or email).strip()
        return User(email=email, display_name=name, is_admin=is_admin_email(email))

    def get_token(self) -> str:
        app = self._build_app()
        accounts = app.get_accounts()
        if not accounts:
            raise AuthError("Not signed in")
        result = app.acquire_token_silent(list(config.GRAPH_SCOPES), account=accounts[0])
        if not result or "access_token" not in result:
            raise AuthError("Session expired; please sign in again")
        return result["access_token"]

    def sign_out(self) -> None:
        try:
            if config.TOKEN_CACHE_PATH.exists():
                config.TOKEN_CACHE_PATH.unlink()
        except OSError as exc:  # pragma: no cover
            _log.warning("Could not delete token cache: %s", exc)
        self._app = None
        self._account = None


# ---------------------------------------------------------------------------
# Local / offline provider
# ---------------------------------------------------------------------------

class LocalAuthProvider(AuthProvider):
    """Offline provider: trusts a confirmed work email. No tokens issued.

    Intended for development, demos and environments where SharePoint is not yet
    configured. Admin gating still applies, so the offline experience mirrors
    production roles exactly.
    """

    online = False

    def __init__(self, email: str = ""):
        self._email = email

    def sign_in(self, prompt_callback: Callable[[str], None] | None = None) -> User:
        email = self._email.strip()
        if not email:
            raise AuthError("An email address is required for local sign-in")
        name = email.split("@")[0].replace(".", " ").title()
        return User(email=email, display_name=name, is_admin=is_admin_email(email))

    def with_email(self, email: str) -> "LocalAuthProvider":
        self._email = email
        return self

    def sign_out(self) -> None:
        self._email = ""
