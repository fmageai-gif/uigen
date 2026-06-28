"""Small, dependency-free helper functions shared across the application."""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from typing import Iterable


def now_iso() -> str:
    """Return the current local time as ``YYYY-MM-DD HH:MM:SS``."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today_iso() -> str:
    """Return today's local date as ``YYYY-MM-DD``."""
    return date.today().strftime("%Y-%m-%d")


def parse_date(value: str | datetime | date | None) -> date | None:
    """Best-effort parse of a date from common string formats or datetimes."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def is_valid_email(value: str) -> bool:
    """Return ``True`` if ``value`` looks like a syntactically valid address."""
    return bool(_EMAIL_RE.match((value or "").strip()))


def normalise_email(value: str) -> str:
    """Lower-case and trim an email address for comparison."""
    return (value or "").strip().lower()


def split_recipients(value: str) -> list[str]:
    """Split a delimited recipients string into a clean list of addresses.

    Accepts comma, semicolon or newline separated values; ignores blanks and
    de-duplicates while preserving order.
    """
    parts = re.split(r"[;,\n]+", value or "")
    seen: set[str] = set()
    result: list[str] = []
    for part in parts:
        addr = part.strip()
        key = addr.lower()
        if addr and key not in seen:
            seen.add(key)
            result.append(addr)
    return result


def slugify(text: str) -> str:
    """Return a filesystem/identifier-safe slug derived from ``text``."""
    normalised = unicodedata.normalize("NFKD", text)
    ascii_text = normalised.encode("ascii", "ignore").decode("ascii")
    ascii_text = re.sub(r"[^\w\s-]", "", ascii_text).strip().lower()
    return re.sub(r"[\s_-]+", "-", ascii_text) or "item"


def truncate(text: str, length: int = 80) -> str:
    """Truncate ``text`` to ``length`` characters with an ellipsis."""
    text = text or ""
    return text if len(text) <= length else text[: length - 1] + "…"


def coalesce(*values: object, default: str = "") -> str:
    """Return the first non-empty stringified value, else ``default``."""
    for value in values:
        if value not in (None, ""):
            return str(value)
    return default


def percentage(part: int, whole: int) -> float:
    """Return ``part / whole`` as a percentage, guarding against zero."""
    return round((part / whole) * 100, 1) if whole else 0.0


def chunked(items: Iterable, size: int) -> Iterable[list]:
    """Yield successive ``size``-length chunks from ``items``."""
    batch: list = []
    for item in items:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch
