"""Microsoft 365 authentication and session management.

The UI talks only to :class:`~eqms.auth.session.SessionManager`, which wraps an
:class:`~eqms.auth.ms_auth.AuthProvider`. Two providers exist: a real MSAL/Graph
provider and a local provider for offline/development use.
"""

from .session import SessionManager, get_session
from .ms_auth import AuthProvider, GraphAuthProvider, LocalAuthProvider

__all__ = [
    "SessionManager",
    "get_session",
    "AuthProvider",
    "GraphAuthProvider",
    "LocalAuthProvider",
]
