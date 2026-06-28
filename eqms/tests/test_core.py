"""Tests for core models, utils and retry behaviour."""

from __future__ import annotations

import pytest

from eqms.core import utils
from eqms.core.exceptions import WorkbookLockedError
from eqms.core.models import Agent, Audit
from eqms.core.retry import retry_call


def test_audit_roundtrip_row():
    a = Audit(audit_id="A1", case_number="C1", genesys_id="G1",
              validation="Invalid", remarks="x")
    restored = Audit.from_row(dict(zip(Audit.HEADERS, a.to_row())))
    assert restored.audit_id == "A1"
    assert restored.is_invalid
    assert restored.dedupe_key == "c1|g1"


def test_agent_from_row_is_case_insensitive():
    row = {"agent name": "John", "AGENT EID": "E1", "TL Email": "t@x.com"}
    agent = Agent.from_row(row)
    assert agent.agent_name == "John"
    assert agent.agent_eid == "E1"
    assert agent.tl_email == "t@x.com"


@pytest.mark.parametrize("part,whole,expected", [(1, 4, 25.0), (0, 0, 0.0), (3, 3, 100.0)])
def test_percentage(part, whole, expected):
    assert utils.percentage(part, whole) == expected


def test_split_recipients_dedupes_and_trims():
    assert utils.split_recipients("a@x.com, b@x.com; a@x.com\n c@x.com") == [
        "a@x.com", "b@x.com", "c@x.com"]


def test_is_valid_email():
    assert utils.is_valid_email("a.b@x.com")
    assert not utils.is_valid_email("nope")


def test_retry_succeeds_after_transient_failures():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise WorkbookLockedError("locked")
        return "ok"

    result = retry_call(flaky, attempts=5, description="test", sleep=lambda _: None)
    assert result == "ok"
    assert calls["n"] == 3


def test_retry_reraises_after_exhaustion():
    def always_locked():
        raise WorkbookLockedError("locked")

    with pytest.raises(WorkbookLockedError):
        retry_call(always_locked, attempts=3, description="test",
                   sleep=lambda _: None)
