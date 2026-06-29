"""``Settings.xlsx`` repository — the single source of all runtime configuration.

Holds scalar key/value settings plus list-style configuration (valid/invalid
reasons, email recipients, dashboard widgets) across several sheets. On first
use the workbook is seeded from :mod:`eqms.data.defaults`; thereafter every
value is owned by the workbook and edited through the Admin Center.

A short-lived in-memory cache avoids re-downloading the workbook on every
``get`` during a UI render; call :meth:`refresh` after a write or when the
background sync detects a change.
"""

from __future__ import annotations

import threading
import time
from typing import Iterable

from ..core.logging_config import get_logger
from .. import config
from ..sharepoint import ExcelStore, get_store
from . import defaults as D

_log = get_logger(__name__)


class SettingsStore:
    """Read/write access to ``Settings.xlsx`` with seeding and caching."""

    def __init__(self, store: ExcelStore | None = None, cache_ttl: float = 15.0):
        self._store = store or get_store()
        self._cache_ttl = cache_ttl
        self._lock = threading.RLock()
        self._scalar: dict[str, str] = {}
        self._loaded_at = 0.0
        self._seeded = False

    # -- seeding ------------------------------------------------------------

    def ensure_seeded(self) -> None:
        """Create and seed ``Settings.xlsx`` if it does not yet exist."""
        with self._lock:
            if self._seeded or self._store.exists(config.WORKBOOK_SETTINGS):
                self._seeded = True
                return
            _log.info("Seeding %s with defaults", config.WORKBOOK_SETTINGS)
            self._store.write_rows(
                config.WORKBOOK_SETTINGS, D.SHEET_SETTINGS, D.SETTINGS_HEADERS,
                [[k, v] for k, v in D.DEFAULT_SETTINGS.items()],
            )
            self._store.write_rows(
                config.WORKBOOK_SETTINGS, D.SHEET_VALID_REASONS, D.REASON_HEADERS,
                [[r] for r in D.DEFAULT_VALID_REASONS],
            )
            self._store.write_rows(
                config.WORKBOOK_SETTINGS, D.SHEET_INVALID_REASONS, D.REASON_HEADERS,
                [[r] for r in D.DEFAULT_INVALID_REASONS],
            )
            self._store.write_rows(
                config.WORKBOOK_SETTINGS, D.SHEET_EMAIL_RECIPIENTS,
                D.RECIPIENT_HEADERS, [],
            )
            self._store.write_rows(
                config.WORKBOOK_SETTINGS, D.SHEET_WIDGETS, D.WIDGET_HEADERS,
                [list(w) for w in D.DEFAULT_DASHBOARD_WIDGETS],
            )
            self._store.write_rows(
                config.WORKBOOK_SETTINGS, D.SHEET_AUTH_USERS, D.AUTH_USER_HEADERS,
                [[e] for e in D.DEFAULT_AUTHORIZED_USERS],
            )
            self._seeded = True
            self.refresh()

    # -- scalar settings ----------------------------------------------------

    def _maybe_load(self) -> None:
        if time.time() - self._loaded_at <= self._cache_ttl and self._scalar:
            return
        self.refresh()

    def refresh(self) -> None:
        """Force a reload of scalar settings from the workbook."""
        with self._lock:
            rows = self._store.read_rows(
                config.WORKBOOK_SETTINGS, D.SHEET_SETTINGS
            )
            merged = dict(D.DEFAULT_SETTINGS)  # defaults fill any gaps
            for row in rows:
                key = row.get("Key", "").strip()
                if key:
                    merged[key] = row.get("Value", "")
            self._scalar = merged
            self._loaded_at = time.time()

    def get(self, key: str, default: str = "") -> str:
        self._maybe_load()
        return self._scalar.get(key, D.DEFAULT_SETTINGS.get(key, default))

    def get_bool(self, key: str, default: bool = False) -> bool:
        value = self.get(key, "true" if default else "false")
        return str(value).strip().lower() in ("1", "true", "yes", "on")

    def get_int(self, key: str, default: int = 0) -> int:
        try:
            return int(float(self.get(key, str(default))))
        except (ValueError, TypeError):
            return default

    def set(self, key: str, value: str) -> None:
        """Update a single scalar setting and persist immediately."""
        self.set_many({key: str(value)})

    def set_many(self, values: dict[str, str]) -> None:
        """Update several scalar settings in one workbook transaction."""
        with self._lock:
            self.refresh()
            current = dict(self._scalar)
            current.update({k: str(v) for k, v in values.items()})
            rows = [[k, v] for k, v in current.items()]
            self._store.write_rows(
                config.WORKBOOK_SETTINGS, D.SHEET_SETTINGS, D.SETTINGS_HEADERS, rows
            )
            self._scalar = current
            self._loaded_at = time.time()
        _log.info("Updated settings: %s", ", ".join(values))

    def all_scalars(self) -> dict[str, str]:
        self._maybe_load()
        return dict(self._scalar)

    # -- reasons ------------------------------------------------------------

    def get_valid_reasons(self) -> list[str]:
        return self._read_reasons(D.SHEET_VALID_REASONS)

    def get_invalid_reasons(self) -> list[str]:
        return self._read_reasons(D.SHEET_INVALID_REASONS)

    def reasons_for(self, validation: str) -> list[str]:
        """Return the reason list matching a validation outcome."""
        if validation.strip().lower() == "valid":
            return self.get_valid_reasons()
        if validation.strip().lower() == "invalid":
            return self.get_invalid_reasons()
        return []

    def _read_reasons(self, sheet: str) -> list[str]:
        rows = self._store.read_rows(config.WORKBOOK_SETTINGS, sheet)
        return [r.get("Reason", "").strip() for r in rows if r.get("Reason", "").strip()]

    def set_valid_reasons(self, reasons: Iterable[str]) -> None:
        self._write_reasons(D.SHEET_VALID_REASONS, reasons)

    def set_invalid_reasons(self, reasons: Iterable[str]) -> None:
        self._write_reasons(D.SHEET_INVALID_REASONS, reasons)

    def _write_reasons(self, sheet: str, reasons: Iterable[str]) -> None:
        clean = [r.strip() for r in reasons if r and r.strip()]
        self._store.write_rows(
            config.WORKBOOK_SETTINGS, sheet, D.REASON_HEADERS, [[r] for r in clean]
        )
        _log.info("Updated %s (%d entries)", sheet, len(clean))

    # -- email recipients ---------------------------------------------------

    def get_recipients(self) -> list[dict[str, str]]:
        """Return configured QA distribution recipients (name/email/role)."""
        return self._store.read_rows(
            config.WORKBOOK_SETTINGS, D.SHEET_EMAIL_RECIPIENTS
        )

    def set_recipients(self, recipients: Iterable[dict[str, str]]) -> None:
        rows = [
            [r.get("Name", ""), r.get("Email", ""), r.get("Role", "")]
            for r in recipients
            if r.get("Email", "").strip()
        ]
        self._store.write_rows(
            config.WORKBOOK_SETTINGS, D.SHEET_EMAIL_RECIPIENTS,
            D.RECIPIENT_HEADERS, rows,
        )

    # -- authorised users (login allow-list) --------------------------------

    def get_authorized_users(self) -> list[str]:
        """Return the lower-cased allow-list of QA emails permitted to sign in.

        Falls back to the seed defaults when the sheet is absent/empty so an
        upgrade never locks existing users out before the admin saves a list.
        """
        rows = self._store.read_rows(config.WORKBOOK_SETTINGS, D.SHEET_AUTH_USERS)
        emails = [
            r.get("Email", "").strip().lower()
            for r in rows if r.get("Email", "").strip()
        ]
        if emails:
            return emails
        return [e.lower() for e in D.DEFAULT_AUTHORIZED_USERS]

    def set_authorized_users(self, emails) -> None:
        """Replace the allow-list with ``emails`` (de-duplicated, trimmed)."""
        seen: set[str] = set()
        clean: list[str] = []
        for raw in emails:
            e = (raw or "").strip()
            key = e.lower()
            if e and key not in seen:
                seen.add(key)
                clean.append(e)
        self._store.write_rows(
            config.WORKBOOK_SETTINGS, D.SHEET_AUTH_USERS, D.AUTH_USER_HEADERS,
            [[e] for e in clean],
        )
        _log.info("Updated authorized users (%d entries)", len(clean))

    def add_authorized_user(self, email: str) -> bool:
        """Add ``email`` to the allow-list. Returns ``True`` if newly added."""
        email = (email or "").strip()
        if not email:
            return False
        current = self.get_authorized_users()
        if email.lower() in current:
            return False
        self.set_authorized_users(current + [email])
        return True

    def remove_authorized_user(self, email: str) -> bool:
        """Remove ``email`` from the allow-list. Returns ``True`` if removed."""
        target = (email or "").strip().lower()
        current = self.get_authorized_users()
        kept = [e for e in current if e.lower() != target]
        if len(kept) == len(current):
            return False
        self.set_authorized_users(kept)
        return True

    def is_login_allowed(self, email: str) -> bool:
        """Return ``True`` if ``email`` may sign in.

        The Super Administrator is always allowed. When ``security.restrict_login``
        is off, anyone may sign in. Otherwise only allow-listed emails pass.
        """
        from ..core.utils import normalise_email

        e = normalise_email(email)
        if not e:
            return False
        if e == normalise_email(config.SUPER_ADMIN_EMAIL):
            return True
        if not self.get_bool("security.restrict_login", True):
            return True
        return e in set(self.get_authorized_users())

    # -- dashboard widgets --------------------------------------------------

    def get_widgets(self) -> list[dict[str, str]]:
        rows = self._store.read_rows(config.WORKBOOK_SETTINGS, D.SHEET_WIDGETS)
        if not rows:
            return [
                {"Key": k, "Label": label, "Enabled": en}
                for k, label, en in D.DEFAULT_DASHBOARD_WIDGETS
            ]
        return rows

    def set_widgets(self, widgets: Iterable[dict[str, str]]) -> None:
        rows = [
            [w.get("Key", ""), w.get("Label", ""), w.get("Enabled", "true")]
            for w in widgets
            if w.get("Key", "").strip()
        ]
        self._store.write_rows(
            config.WORKBOOK_SETTINGS, D.SHEET_WIDGETS, D.WIDGET_HEADERS, rows
        )
