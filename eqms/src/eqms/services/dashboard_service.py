"""Dashboard analytics: KPI computation and chart datasets.

Reads the audit set (preferring the live repository, falling back to the local
cache snapshot when offline) and derives the KPI cards and chart series the
dashboard renders. Returns plain data structures so the UI layer stays free of
analytics logic.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable

from ..core.logging_config import get_logger
from ..core.models import Audit
from ..core.utils import parse_date, percentage
from ..data.audit_repository import AuditRepository
from ..data.local_cache import LocalCache

_log = get_logger(__name__)


@dataclass(slots=True)
class KPISet:
    """All computed KPI values for the dashboard cards."""

    today: int = 0
    week: int = 0
    month: int = 0
    total: int = 0
    valid_pct: float = 0.0
    invalid_pct: float = 0.0
    top_qa: str = "—"
    top_agent: str = "—"
    top_tl: str = "—"
    top_om: str = "—"
    common_invalid_reason: str = "—"
    last_submission: str = "—"
    system_status: str = "Unknown"

    def as_map(self) -> dict[str, str]:
        """Map widget keys → display strings (matches DEFAULT_DASHBOARD_WIDGETS)."""
        return {
            "today": str(self.today),
            "week": str(self.week),
            "month": str(self.month),
            "total": str(self.total),
            "valid_pct": f"{self.valid_pct:.1f}%",
            "invalid_pct": f"{self.invalid_pct:.1f}%",
            "top_qa": self.top_qa,
            "top_agent": self.top_agent,
            "top_tl": self.top_tl,
            "top_om": self.top_om,
            "common_invalid": self.common_invalid_reason,
            "last_submission": self.last_submission,
            "system_status": self.system_status,
        }


class DashboardService:
    """Compute KPIs and chart series from the audit dataset."""

    CACHE_KEY = "dashboard.audits"

    def __init__(
        self,
        audits: AuditRepository | None = None,
        cache: LocalCache | None = None,
    ):
        self.audits = audits or AuditRepository()
        self.cache = cache or LocalCache()

    # -- data acquisition ---------------------------------------------------

    def load_audits(self, *, refresh: bool = True) -> tuple[list[Audit], str]:
        """Return ``(audits, status)`` where status is the system state string.

        On success the dataset is snapshotted to the local cache. On failure the
        last cached snapshot is returned so the dashboard still renders offline.
        """
        try:
            data = self.audits.all(refresh=refresh)
            self.cache.put(self.CACHE_KEY, [a.to_row() for a in data])
            return data, "Online"
        except Exception as exc:  # noqa: BLE001 - degrade gracefully
            _log.warning("Live audit load failed, using cache: %s", exc)
            cached = self.cache.get(self.CACHE_KEY, default=[])
            restored = [Audit.from_row(_row_to_map(r)) for r in cached]
            return restored, "Offline (cached)"

    # -- KPIs ---------------------------------------------------------------

    def compute_kpis(self, audits: Iterable[Audit] | None = None,
                     status: str = "Online") -> KPISet:
        if audits is None:
            audits, status = self.load_audits()
        audits = list(audits)

        today = date.today()
        start_week = today - timedelta(days=today.weekday())
        start_month = today.replace(day=1)

        def in_range(a: Audit, since: date) -> bool:
            d = parse_date(a.created_at) or parse_date(a.date)
            return d is not None and d >= since

        total = len(audits)
        valid = sum(1 for a in audits if not a.is_invalid and a.validation)
        invalid = sum(1 for a in audits if a.is_invalid)
        graded = valid + invalid

        kpis = KPISet(
            today=sum(1 for a in audits if in_range(a, today)),
            week=sum(1 for a in audits if in_range(a, start_week)),
            month=sum(1 for a in audits if in_range(a, start_month)),
            total=total,
            valid_pct=percentage(valid, graded),
            invalid_pct=percentage(invalid, graded),
            top_qa=_top([a.qa_name for a in audits]),
            top_agent=_top([a.agent for a in audits]),
            top_tl=_top([a.team_leader for a in audits]),
            top_om=_top([a.operations_manager for a in audits]),
            common_invalid_reason=_top(
                [a.reason for a in audits if a.is_invalid]
            ),
            last_submission=_latest(audits),
            system_status=status,
        )
        return kpis

    # -- chart datasets -----------------------------------------------------

    def validity_breakdown(self, audits: Iterable[Audit]) -> dict[str, int]:
        """Counts for a Valid vs Invalid pie/donut chart."""
        audits = list(audits)
        return {
            "Valid": sum(1 for a in audits if not a.is_invalid and a.validation),
            "Invalid": sum(1 for a in audits if a.is_invalid),
        }

    def audits_per_day(self, audits: Iterable[Audit], days: int = 14
                       ) -> tuple[list[str], list[int]]:
        """Return (labels, counts) of audits per day over the last ``days``."""
        today = date.today()
        window = [today - timedelta(days=i) for i in range(days - 1, -1, -1)]
        counts = {d: 0 for d in window}
        for a in audits:
            d = parse_date(a.created_at) or parse_date(a.date)
            if d in counts:
                counts[d] += 1
        labels = [d.strftime("%d %b") for d in window]
        return labels, [counts[d] for d in window]

    def top_invalid_reasons(self, audits: Iterable[Audit], limit: int = 6
                            ) -> tuple[list[str], list[int]]:
        """Return (reasons, counts) for the most common invalid reasons."""
        counter = Counter(
            a.reason.strip() for a in audits if a.is_invalid and a.reason.strip()
        )
        items = counter.most_common(limit)
        return [r for r, _ in items], [c for _, c in items]

    def top_entities(self, audits: Iterable[Audit], field: str, limit: int = 6
                     ) -> tuple[list[str], list[int]]:
        """Generic top-N by an Audit attribute (e.g. 'agent', 'qa_name')."""
        counter = Counter(
            getattr(a, field).strip() for a in audits if getattr(a, field).strip()
        )
        items = counter.most_common(limit)
        return [k for k, _ in items], [c for _, c in items]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _top(values: list[str]) -> str:
    clean = [v.strip() for v in values if v and v.strip()]
    if not clean:
        return "—"
    return Counter(clean).most_common(1)[0][0]


def _latest(audits: list[Audit]) -> str:
    if not audits:
        return "—"
    latest = max(audits, key=lambda a: a.created_at or a.date or "")
    return latest.created_at or latest.date or "—"


def _row_to_map(row: list[str]) -> dict[str, str]:
    """Rebuild a header→value map from a cached positional row."""
    return {h: (row[i] if i < len(row) else "") for i, h in enumerate(Audit.HEADERS)}
