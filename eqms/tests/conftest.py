"""Shared pytest fixtures.

Every test runs against an isolated, temporary :class:`LocalExcelStore` so no
SharePoint tenant or network is required and tests cannot interfere with real
user data. The storage factory is reset between tests.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from eqms.auth.ms_auth import LocalAuthProvider  # noqa: E402
from eqms.auth.session import SessionManager  # noqa: E402
from eqms.core.models import Agent, Audit  # noqa: E402
from eqms.core.utils import now_iso, today_iso  # noqa: E402
from eqms.sharepoint import factory  # noqa: E402
from eqms.sharepoint.local_store import LocalExcelStore  # noqa: E402


@pytest.fixture
def store(tmp_path):
    """An isolated local Excel store wired as the active backend."""
    s = LocalExcelStore(tmp_path / "store")
    factory._store = s
    yield s
    factory.reset_store()


@pytest.fixture
def admin_session():
    sm = SessionManager(LocalAuthProvider("sundeep.bhardwaj@concentrix.com"))
    sm.sign_in()
    return sm


@pytest.fixture
def qa_session():
    sm = SessionManager(LocalAuthProvider("qa.user@concentrix.com"))
    sm.sign_in()
    return sm


@pytest.fixture
def seeded_masterlist(store):
    store.write_rows("Masterlist.xlsx", "Masterlist", Agent.HEADERS, [
        Agent("John Smith", "E100", "Lead A", "OM A", "Q1", "LOB1",
              "tl@x.com", "om@x.com").to_row(),
        Agent("Jane Doe", "E200", "Lead B", "OM B", "Q2", "LOB2",
              "tl2@x.com", "om2@x.com").to_row(),
    ])
    return store


@pytest.fixture
def make_audit():
    """Factory for valid Audit objects with sensible defaults."""
    counter = {"n": 0}

    def _make(**overrides) -> Audit:
        counter["n"] += 1
        n = counter["n"]
        base = dict(
            audit_id=f"AUD-2026-{n:06d}",
            date=today_iso(),
            qa_name="QA User",
            qa_email="qa.user@concentrix.com",
            auditor_name="QA User",
            agent="John Smith",
            agent_eid="E100",
            team_leader="Lead A",
            operations_manager="OM A",
            tl_email="tl@x.com",
            om_email="om@x.com",
            queue="Q1",
            lob="LOB1",
            case_number=f"C{n}",
            genesys_id=f"G{n}",
            validation="Valid",
            reason="RESOLVED",
            remarks="ok",
            created_at=now_iso(),
        )
        base.update(overrides)
        return Audit(**base)

    return _make
