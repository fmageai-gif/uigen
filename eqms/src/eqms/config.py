"""Static configuration, filesystem paths and immutable defaults.

This module deliberately contains **no business rules**. The only hardcoded
business value permitted by the specification is the bootstrap Super
Administrator account (:data:`SUPER_ADMIN_EMAIL`). Everything else — audit
reasons, validation rules, dashboard widgets, SharePoint paths, email
recipients, themes, backups and update settings — lives in ``Settings.xlsx``
and is editable at runtime through the Admin Center.

Paths follow the Windows convention of storing per-user application data under
``%LOCALAPPDATA%`` so the packaged ``.exe`` never needs write access to its own
install directory (which is typically ``C:\\Program Files`` and read-only).
"""

from __future__ import annotations

import os
from pathlib import Path

from . import APP_SHORT_NAME, __version__

# ---------------------------------------------------------------------------
# Bootstrap administrator (the ONLY hardcoded business rule, per spec)
# ---------------------------------------------------------------------------

#: The single Super Administrator for v1.0. Only this Microsoft 365 account may
#: access the Admin Center. Compared case-insensitively after trimming.
SUPER_ADMIN_EMAIL = "sundeep.bhardwaj@concentrix.com"


# ---------------------------------------------------------------------------
# Local filesystem layout
# ---------------------------------------------------------------------------

def _base_data_dir() -> Path:
    """Return the writable per-user data directory for the application.

    Uses ``%LOCALAPPDATA%`` on Windows and falls back to ``~/.local/share`` on
    other platforms so the package remains importable and testable on CI/Linux.
    """
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        base = Path(local_app_data)
    else:  # pragma: no cover - non-Windows fallback for development/CI
        base = Path.home() / ".local" / "share"
    return base / "HP-Mainstream-EQMS"


#: Root of all locally persisted state (cache, logs, backups, tokens, config).
DATA_DIR: Path = _base_data_dir()

#: Local SQLite cache database. Excel on SharePoint remains the system of
#: record; this is purely an offline/performance cache.
CACHE_DB_PATH: Path = DATA_DIR / "cache" / "eqms_cache.sqlite"

#: Rotating application log files (separate from the SharePoint SystemLogs.xlsx
#: audit trail, which records *business* events).
LOG_DIR: Path = DATA_DIR / "logs"

#: Local copies of downloaded workbooks and automatic backups.
BACKUP_DIR: Path = DATA_DIR / "backups"

#: MSAL token cache (encrypted at rest by the OS user profile).
TOKEN_CACHE_PATH: Path = DATA_DIR / "auth" / "token_cache.bin"

#: Local bootstrap settings (M365 client id/tenant, SharePoint site URL). This
#: is connection configuration only — never business rules.
LOCAL_CONFIG_PATH: Path = DATA_DIR / "config" / "local_config.json"

#: Directory used when the application runs in local/offline mode, standing in
#: for the SharePoint document library so the app is fully runnable without a
#: tenant (development, demos and automated tests).
LOCAL_STORE_DIR: Path = DATA_DIR / "local_store"


def ensure_directories() -> None:
    """Create every required local directory if it does not already exist."""
    for path in (
        DATA_DIR,
        CACHE_DB_PATH.parent,
        LOG_DIR,
        BACKUP_DIR,
        TOKEN_CACHE_PATH.parent,
        LOCAL_CONFIG_PATH.parent,
        LOCAL_STORE_DIR,
    ):
        path.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Local connection config (storage location). Kept in a small JSON file rather
# than Settings.xlsx so it can be read *before* the store exists (Settings is
# itself stored in the store), avoiding a chicken-and-egg dependency.
# ---------------------------------------------------------------------------

def read_local_config() -> dict:
    """Return the bootstrap local config dict (``{}`` if absent/invalid)."""
    import json

    try:
        if LOCAL_CONFIG_PATH.exists():
            return json.loads(LOCAL_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):  # pragma: no cover - corrupt file
        pass
    return {}


def write_local_config(values: dict) -> None:
    """Merge ``values`` into the local config JSON file."""
    import json

    ensure_directories()
    current = read_local_config()
    current.update(values)
    LOCAL_CONFIG_PATH.write_text(
        json.dumps(current, indent=2), encoding="utf-8"
    )


def get_storage_path() -> Path:
    """Return the folder that holds the Excel database (the system of record).

    Defaults to the per-user local store, but the administrator can point this
    at a shared network folder so a whole QA team uses one database. The value
    is read from ``local_config.json`` (key ``storage_path``).
    """
    configured = read_local_config().get("storage_path", "").strip()
    if configured:
        path = Path(configured)
        path.mkdir(parents=True, exist_ok=True)
        return path
    return LOCAL_STORE_DIR


def set_storage_path(path: str) -> None:
    """Persist the database folder location to local config."""
    write_local_config({"storage_path": (path or "").strip()})


# ---------------------------------------------------------------------------
# Workbook names (the system of record — Excel files in the storage folder)
# ---------------------------------------------------------------------------

WORKBOOK_AUDIT_DB = "AuditDatabase.xlsx"
WORKBOOK_MASTERLIST = "Masterlist.xlsx"
WORKBOOK_ARCHIVE = "Archive.xlsx"
WORKBOOK_SETTINGS = "Settings.xlsx"
WORKBOOK_LOGS = "SystemLogs.xlsx"

#: All workbooks the application manages, in canonical order.
ALL_WORKBOOKS = (
    WORKBOOK_SETTINGS,
    WORKBOOK_MASTERLIST,
    WORKBOOK_AUDIT_DB,
    WORKBOOK_ARCHIVE,
    WORKBOOK_LOGS,
)


# ---------------------------------------------------------------------------
# Microsoft 365 / Graph defaults (overridable via local_config.json or env)
# ---------------------------------------------------------------------------

#: Azure AD application (client) id. Override per-deployment. The well-known
#: value below is the public Microsoft Office client id which supports the
#: device-code and interactive public-client flows out of the box for
#: development; production deployments should register their own app.
DEFAULT_CLIENT_ID = os.environ.get(
    "EQMS_CLIENT_ID", "d3590ed6-52b3-4102-aeff-aad2292ab01c"
)

#: Azure AD tenant. ``organizations`` allows any work/school account; pin to a
#: specific tenant id in production via local config or the EQMS_TENANT env var.
DEFAULT_TENANT = os.environ.get("EQMS_TENANT", "organizations")

#: Delegated Graph scopes requested at sign-in.
GRAPH_SCOPES = (
    "User.Read",
    "Mail.Send",
    "Files.ReadWrite.All",
    "Sites.ReadWrite.All",
)

GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"


# ---------------------------------------------------------------------------
# Operational constants
# ---------------------------------------------------------------------------

#: Number of attempts and base back-off (seconds) for SharePoint/Excel calls
#: that may transiently fail due to file locking or throttling.
RETRY_ATTEMPTS = int(os.environ.get("EQMS_RETRY_ATTEMPTS", "5"))
RETRY_BASE_DELAY = float(os.environ.get("EQMS_RETRY_BASE_DELAY", "1.5"))
RETRY_MAX_DELAY = float(os.environ.get("EQMS_RETRY_MAX_DELAY", "30"))

#: How often (seconds) the background sync worker refreshes data from
#: SharePoint. Overridable through Settings.xlsx at runtime.
DEFAULT_SYNC_INTERVAL = 60

#: Window title used everywhere.
WINDOW_TITLE = f"{APP_SHORT_NAME}  v{__version__}"


def app_version() -> str:
    """Return the running application version string."""
    return __version__
