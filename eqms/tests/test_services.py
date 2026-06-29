"""Tests for the service layer: validation, permissions, KPIs, email, reports."""

from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest

from eqms.core.exceptions import (
    DuplicateAuditError,
    PermissionDeniedError,
    ValidationError,
)
from eqms.data.settings_store import SettingsStore
from eqms.services.audit_service import AuditService
from eqms.services.dashboard_service import DashboardService
from eqms.services.email_service import EmailService
from eqms.services.report_service import ReportService


@pytest.fixture
def audit_service(store, qa_session, seeded_masterlist):
    s = SettingsStore(store)
    s.ensure_seeded()
    return AuditService(settings=s, session=qa_session)


def _valid_audit(svc):
    a = svc.new_blank_audit()
    a = svc.apply_agent(a, "John Smith")
    return replace(a, auditor_name="QA Auditor", case_number="C1",
                   genesys_id="G1", validation="Valid", reason="RESOLVED",
                   remarks="looks good")


def test_create_valid_audit(audit_service):
    saved = audit_service.create(_valid_audit(audit_service))
    assert saved.agent == "John Smith"
    assert saved.agent_eid == "E100"  # auto-filled from masterlist
    assert saved.qa_email == "qa.user@concentrix.com"


def test_remarks_mandatory(audit_service):
    a = replace(_valid_audit(audit_service), remarks="")
    with pytest.raises(ValidationError) as exc:
        audit_service.create(a)
    assert exc.value.field == "remarks"


def test_reason_must_match_validation(audit_service):
    # An invalid-list reason on a Valid audit must be rejected.
    a = replace(_valid_audit(audit_service), validation="Valid",
                reason="AGENT UNRESPONSIVE")
    with pytest.raises(ValidationError):
        audit_service.create(a)


def test_duplicate_blocked(audit_service):
    audit_service.create(_valid_audit(audit_service))
    dup = replace(_valid_audit(audit_service), case_number="C1", genesys_id="G1")
    with pytest.raises(DuplicateAuditError):
        audit_service.create(dup)


def test_qa_cannot_edit_others_audit(store, qa_session, seeded_masterlist):
    s = SettingsStore(store); s.ensure_seeded()
    svc = AuditService(settings=s, session=qa_session)
    saved = svc.create(_valid_audit(svc))
    # Simulate a record owned by someone else.
    foreign = replace(saved, qa_email="other@concentrix.com")
    svc.audits.update(foreign)
    with pytest.raises(PermissionDeniedError):
        svc.update(replace(foreign, remarks="changed"))


def test_archive_requires_admin(store, qa_session, seeded_masterlist):
    s = SettingsStore(store); s.ensure_seeded()
    svc = AuditService(settings=s, session=qa_session)
    saved = svc.create(_valid_audit(svc))
    with pytest.raises(PermissionDeniedError):
        svc.archive_audit(saved.audit_id)


def test_admin_archive_and_restore(store, admin_session, seeded_masterlist):
    s = SettingsStore(store); s.ensure_seeded()
    svc = AuditService(settings=s, session=admin_session)
    saved = svc.create(_valid_audit(svc))
    svc.archive_audit(saved.audit_id)
    assert svc.audits.get(saved.audit_id) is None
    svc.restore_audit(saved.audit_id)
    assert svc.audits.get(saved.audit_id) is not None


def test_archive_password_enforced(store, admin_session, seeded_masterlist):
    s = SettingsStore(store); s.ensure_seeded()
    s.set("security.archive_password", "secret")
    svc = AuditService(settings=s, session=admin_session)
    saved = svc.create(_valid_audit(svc))
    with pytest.raises(PermissionDeniedError):
        svc.archive_audit(saved.audit_id, password="wrong")
    svc.archive_audit(saved.audit_id, password="secret")  # correct -> ok


def test_dashboard_kpis(store, qa_session, seeded_masterlist, make_audit):
    svc = AuditService(settings=SettingsStore(store), session=qa_session)
    svc.settings.ensure_seeded()
    svc.create(replace(_valid_audit(svc), case_number="A", genesys_id="1"))
    inv = replace(_valid_audit(svc), case_number="B", genesys_id="2",
                  validation="Invalid", reason="UNRESOLVED")
    svc.create(inv)
    ds = DashboardService(svc.audits)
    kpis = ds.compute_kpis()
    assert kpis.total == 2
    assert kpis.valid_pct == 50.0
    assert kpis.invalid_pct == 50.0
    assert kpis.common_invalid_reason == "UNRESOLVED"


def test_email_recipients_and_invalid_only(store, qa_session):
    s = SettingsStore(store); s.ensure_seeded()
    s.set("email.qa_distribution_list", "dist@x.com")
    svc = EmailService(settings=s, session=qa_session)
    from eqms.core.models import Audit

    valid = Audit(validation="Valid")
    assert not svc.should_send(valid)
    invalid = Audit(validation="Invalid", agent_email="agent@x.com",
                    tl_email="tl@x.com", om_email="om@x.com")
    assert svc.should_send(invalid)
    recipients = svc.resolve_recipients(invalid)
    # Agent, TL and OM all receive the notification, plus the distribution list.
    assert set(recipients) == {"agent@x.com", "tl@x.com", "om@x.com", "dist@x.com"}


def test_report_generation(store, qa_session, seeded_masterlist, tmp_path):
    s = SettingsStore(store); s.ensure_seeded()
    svc = AuditService(settings=s, session=qa_session)
    svc.create(_valid_audit(svc))
    report = ReportService(audits=svc.audits, settings=s)
    today = date.today()
    result = report.generate_monthly(today.year, today.month, output_dir=tmp_path)
    assert result.path.exists()
    assert result.audit_count == 1
