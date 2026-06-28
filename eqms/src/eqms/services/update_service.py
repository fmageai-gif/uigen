"""Automatic update checking.

Fetches a small JSON manifest (URL configured in the Admin Center) describing
the latest released version and compares it against the running version using
semantic-version ordering. Network and parsing errors are swallowed so a failed
check never disrupts the application.

Expected manifest shape::

    {
      "version": "1.1.0",
      "url": "https://.../EQMS-Setup-1.1.0.exe",
      "notes": "What changed",
      "mandatory": false
    }
"""

from __future__ import annotations

from dataclasses import dataclass

import requests

from ..core.logging_config import get_logger
from ..core.utils import now_iso
from ..data.settings_store import SettingsStore
from .. import config

_log = get_logger(__name__)


@dataclass(slots=True)
class UpdateInfo:
    available: bool
    current_version: str
    latest_version: str = ""
    url: str = ""
    notes: str = ""
    mandatory: bool = False
    checked_at: str = ""
    error: str = ""


def parse_version(value: str) -> tuple[int, ...]:
    """Parse a dotted version string into a comparable integer tuple."""
    parts: list[int] = []
    for chunk in str(value).strip().lstrip("v").split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) or (0,)


class UpdateService:
    """Check a remote manifest for a newer application version."""

    def __init__(self, settings: SettingsStore | None = None):
        self.settings = settings or SettingsStore()

    def is_enabled(self) -> bool:
        return self.settings.get_bool("update.auto_check", True)

    def check(self, *, timeout: int = 15) -> UpdateInfo:
        current = config.app_version()
        info = UpdateInfo(available=False, current_version=current,
                          checked_at=now_iso())

        manifest_url = self.settings.get("update.manifest_url", "").strip()
        if not manifest_url:
            info.error = "No update manifest URL configured"
            return info

        try:
            resp = requests.get(manifest_url, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:  # noqa: BLE001 - never disrupt the app
            _log.warning("Update check failed: %s", exc)
            info.error = str(exc)
            return info

        latest = str(data.get("version", "")).strip()
        info.latest_version = latest
        info.url = str(data.get("url", ""))
        info.notes = str(data.get("notes", ""))
        info.mandatory = bool(data.get("mandatory", False))
        info.available = bool(latest) and parse_version(latest) > parse_version(current)
        if info.available:
            _log.info("Update available: %s -> %s", current, latest)
        return info
