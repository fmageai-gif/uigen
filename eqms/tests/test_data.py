"""Tests for the storage abstraction and per-workbook repositories."""

from __future__ import annotations

import pytest

from eqms.core.exceptions import DuplicateAuditError, WorkbookNotFoundError
from eqms.data.archive import ArchiveRepository
from eqms.data.audit_repository import AuditRepository
from eqms.data.masterlist import MasterlistRepository
from eqms.data.settings_store import SettingsStore


def test_store_write_read_append_roundtrip(store, make_audit):
    repo = AuditRepository(store)
    a = make_audit()
    repo.add(a)
    assert len(repo.all(refresh=True)) == 1
    repo.add(make_audit())
    assert len(repo.all(refresh=True)) == 2


def test_download_missing_workbook_raises(store):
    with pytest.raises(WorkbookNotFoundError):
        store.download("DoesNotExist.xlsx", store.root / "x.xlsx")


def test_settings_seed_and_reasons(store):
    s = SettingsStore(store)
    s.ensure_seeded()
    assert len(s.get_valid_reasons()) == 11
    assert len(s.get_invalid_reasons()) == 10
    assert "AGENT UNRESPONSIVE" in s.reasons_for("Invalid")
    assert s.reasons_for("Valid") == s.get_valid_reasons()


def test_settings_scalar_set_get(store):
    s = SettingsStore(store)
    s.ensure_seeded()
    assert s.get("theme.mode") == "System"
    s.set("theme.mode", "Dark")
    assert SettingsStore(store).get("theme.mode") == "Dark"


def test_masterlist_search_and_resolve(seeded_masterlist):
    m = MasterlistRepository(seeded_masterlist)
    assert m.count() == 2
    assert [a.agent_name for a in m.search("jo")] == ["John Smith"]
    assert m.get_by_eid("E200").agent_name == "Jane Doe"
    assert m.resolve("John Smith").agent_eid == "E100"


def test_audit_dedupe_enforced_at_repo(store, make_audit):
    repo = AuditRepository(store)
    repo.add(make_audit(case_number="X", genesys_id="Y"))
    with pytest.raises(DuplicateAuditError):
        repo.add(make_audit(case_number="X", genesys_id="Y"))


def test_audit_sequential_ids(store, make_audit):
    repo = AuditRepository(store)
    assert repo.next_audit_id().endswith("000001")
    repo.add(make_audit(audit_id="AUD-2026-000007"))
    assert repo.next_audit_id().endswith("000008")


def test_archive_and_restore_cycle(store, make_audit):
    audits = AuditRepository(store)
    archive = ArchiveRepository(store)
    a = make_audit()
    audits.add(a)
    removed = audits.remove(a.audit_id)
    archive.add(removed)
    assert audits.get(a.audit_id) is None
    assert archive.get(a.audit_id) is not None
    back = archive.remove(a.audit_id)
    assert back.audit_id == a.audit_id
    assert archive.get(a.audit_id) is None
