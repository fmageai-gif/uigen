"""``Masterlist.xlsx`` repository — the administrator-uploaded agent roster.

Provides fast in-memory autocomplete lookup so the audit form can resolve an
agent's EID, Team Leader, Operations Manager, Queue, LOB and the TL/OM emails
the instant a QA selects an agent.
"""

from __future__ import annotations

import threading
import time

from ..core.logging_config import get_logger
from ..core.models import Agent
from .. import config
from ..sharepoint import ExcelStore, get_store

_log = get_logger(__name__)

SHEET_MASTERLIST = "Masterlist"


class MasterlistRepository:
    """Read access plus autocomplete over the agent masterlist."""

    def __init__(self, store: ExcelStore | None = None, cache_ttl: float = 300.0):
        self._store = store or get_store()
        self._cache_ttl = cache_ttl
        self._lock = threading.RLock()
        self._agents: list[Agent] = []
        self._by_eid: dict[str, Agent] = {}
        self._by_name: dict[str, Agent] = {}
        self._loaded_at = 0.0

    # -- loading ------------------------------------------------------------

    def _maybe_load(self) -> None:
        if self._agents and time.time() - self._loaded_at <= self._cache_ttl:
            return
        self.refresh()

    def refresh(self) -> None:
        """Reload the roster from the workbook into the in-memory indexes."""
        with self._lock:
            rows = self._store.read_rows(config.WORKBOOK_MASTERLIST, SHEET_MASTERLIST)
            if not rows:
                # Tolerate workbooks whose first sheet is not named "Masterlist".
                rows = self._store.read_rows(config.WORKBOOK_MASTERLIST)
            agents = [Agent.from_row(r) for r in rows]
            agents = [a for a in agents if a.agent_name or a.agent_eid]
            self._agents = agents
            self._by_eid = {a.agent_eid.strip().lower(): a for a in agents if a.agent_eid}
            self._by_name = {a.agent_name.strip().lower(): a for a in agents if a.agent_name}
            self._loaded_at = time.time()
        _log.info("Loaded %d agents from masterlist", len(self._agents))

    # -- lookup -------------------------------------------------------------

    def count(self) -> int:
        self._maybe_load()
        return len(self._agents)

    def all_agents(self) -> list[Agent]:
        self._maybe_load()
        return list(self._agents)

    def get_by_eid(self, eid: str) -> Agent | None:
        self._maybe_load()
        return self._by_eid.get((eid or "").strip().lower())

    def get_by_name(self, name: str) -> Agent | None:
        self._maybe_load()
        return self._by_name.get((name or "").strip().lower())

    def resolve(self, term: str) -> Agent | None:
        """Resolve an exact agent by name or EID (used on form selection)."""
        return self.get_by_name(term) or self.get_by_eid(term)

    def search(self, term: str, limit: int = 15) -> list[Agent]:
        """Return agents whose name or EID contains ``term`` (autocomplete)."""
        self._maybe_load()
        term = (term or "").strip().lower()
        if not term:
            return self._agents[:limit]
        matches = [a for a in self._agents if term in a.search_key]
        # Prefer prefix matches, then substring matches.
        matches.sort(key=lambda a: (not a.search_key.startswith(term), a.agent_name))
        return matches[:limit]

    # -- admin upload -------------------------------------------------------

    def replace_from_file(self, local_xlsx) -> int:
        """Replace the masterlist with an admin-uploaded ``.xlsx`` file.

        Reads the uploaded workbook, normalises it onto the canonical
        :class:`Agent` columns, and writes it back to the store. Returns the
        number of agent rows imported.
        """
        from ..sharepoint import excel_io
        from pathlib import Path

        path = Path(local_xlsx)
        raw_rows = excel_io.read_rows(path)
        agents = [Agent.from_row(r) for r in raw_rows]
        agents = [a for a in agents if a.agent_name or a.agent_eid]
        self._store.write_rows(
            config.WORKBOOK_MASTERLIST, SHEET_MASTERLIST, Agent.HEADERS,
            [a.to_row() for a in agents],
        )
        self.refresh()
        _log.info("Replaced masterlist with %d agents from %s", len(agents), path.name)
        return len(agents)
