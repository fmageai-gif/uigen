"""Audit business logic: create, edit, search, archive and restore.

All validation rules are read from ``Settings.xlsx`` (so the administrator can
toggle them) rather than being hardcoded. Permissions are enforced through the
:class:`~eqms.auth.session.SessionManager` ("edit only your own audits"; archive
/delete gated behind the admin and the configured archive password).
"""

from __future__ import annotations

from dataclasses import replace

from ..auth.session import SessionManager, get_session
from ..core.exceptions import (
    DuplicateAuditError,
    PermissionDeniedError,
    ValidationError,
)
from ..core.logging_config import get_logger
from ..core.models import Audit, VALIDATION_INVALID, VALIDATION_VALID
from ..core.utils import now_iso, today_iso
from ..data.audit_repository import AuditRepository
from ..data.archive import ArchiveRepository
from ..data.logs_store import LogsRepository
from ..data.masterlist import MasterlistRepository
from ..data.settings_store import SettingsStore

_log = get_logger(__name__)


class AuditService:
    """Coordinates audit creation/editing with validation and permissions."""

    def __init__(
        self,
        *,
        audits: AuditRepository | None = None,
        archive: ArchiveRepository | None = None,
        masterlist: MasterlistRepository | None = None,
        settings: SettingsStore | None = None,
        logs: LogsRepository | None = None,
        session: SessionManager | None = None,
    ):
        self.audits = audits or AuditRepository()
        self.archive = archive or ArchiveRepository()
        self.masterlist = masterlist or MasterlistRepository()
        self.settings = settings or SettingsStore()
        self.logs = logs or LogsRepository()
        self.session = session or get_session()

    # -- helpers ------------------------------------------------------------

    def new_blank_audit(self) -> Audit:
        """Return a pre-populated draft audit for the current user."""
        user = self.session.user
        return Audit(
            audit_id=self.audits.next_audit_id(),
            date=today_iso(),
            qa_name=user.display_name,
            qa_email=user.email,
        )

    def reasons_for(self, validation: str) -> list[str]:
        """Return the valid/invalid reason list matching the validation."""
        return self.settings.reasons_for(validation)

    def apply_agent(self, audit: Audit, agent_term: str) -> Audit:
        """Populate agent-derived fields from the masterlist selection."""
        agent = self.masterlist.resolve(agent_term)
        if agent is None:
            return replace(audit, agent=agent_term)
        return replace(
            audit,
            agent=agent.agent_name,
            agent_eid=agent.agent_eid,
            team_leader=agent.team_leader,
            operations_manager=agent.operations_manager,
            tl_email=agent.tl_email,
            om_email=agent.om_email,
            queue=agent.queue,
            lob=agent.lob,
        )

    # -- validation ---------------------------------------------------------

    def validate(self, audit: Audit, *, is_update: bool = False) -> None:
        """Validate an audit against the configurable rule set. Raises on error."""
        if not audit.auditor_name.strip():
            raise ValidationError("Auditor Name is required.", field="auditor_name")
        if not audit.agent.strip():
            raise ValidationError("Agent is required.", field="agent")
        if not audit.case_number.strip():
            raise ValidationError("Case Number is required.", field="case_number")
        if not audit.genesys_id.strip():
            raise ValidationError(
                "Genesys Transaction ID is required.", field="genesys_id"
            )

        validation = audit.validation.strip()
        if validation not in (VALIDATION_VALID, VALIDATION_INVALID):
            raise ValidationError(
                "Validation must be 'Valid' or 'Invalid'.", field="validation"
            )

        if not audit.reason.strip():
            raise ValidationError("A reason must be selected.", field="reason")
        allowed = self.reasons_for(validation)
        if allowed and audit.reason.strip() not in allowed:
            raise ValidationError(
                f"'{audit.reason}' is not a valid reason for a "
                f"{validation} audit.",
                field="reason",
            )

        if self.settings.get_bool("validation.remarks_required", True):
            if not audit.remarks.strip():
                raise ValidationError("Remarks are mandatory.", field="remarks")

        if self.settings.get_bool("validation.require_agent_from_masterlist", False):
            if self.masterlist.resolve(audit.agent) is None:
                raise ValidationError(
                    "Agent must be selected from the masterlist.", field="agent"
                )

        if self.settings.get_bool("validation.unique_case_genesys", True):
            exclude = audit.audit_id if is_update else ""
            if self.audits.exists_dedupe(
                audit.case_number, audit.genesys_id, exclude_id=exclude
            ):
                raise DuplicateAuditError(
                    "An audit with this Case Number and Genesys Transaction ID "
                    "already exists. Duplicate submissions are blocked.",
                    field="case_number",
                )

    # -- create / update ----------------------------------------------------

    def create(self, audit: Audit) -> Audit:
        """Validate and persist a new audit, stamping ownership and timestamps."""
        user = self.session.user
        audit = replace(
            audit,
            qa_name=user.display_name,
            qa_email=user.email,
            date=audit.date or today_iso(),
            created_at=now_iso(),
            updated_at=now_iso(),
        )
        if not audit.audit_id:
            audit = replace(audit, audit_id=self.audits.next_audit_id())

        self.validate(audit, is_update=False)
        saved = self.audits.add(audit)
        self.logs.record(
            "AUDIT_CREATED", user=user.email,
            details=f"{saved.audit_id} | {saved.agent} | {saved.validation}",
        )
        return saved

    def update(self, audit: Audit) -> Audit:
        """Validate and persist an edit, enforcing ownership."""
        existing = self.audits.get(audit.audit_id)
        if existing is None:
            raise ValidationError("Audit no longer exists.", field="audit_id")
        if not self.session.can_edit_audit(existing.qa_email):
            raise PermissionDeniedError("You may only edit your own audits.")

        audit = replace(
            audit,
            qa_name=existing.qa_name,
            qa_email=existing.qa_email,  # ownership is immutable
            created_at=existing.created_at,
            updated_at=now_iso(),
        )
        self.validate(audit, is_update=True)
        saved = self.audits.update(audit)
        self.logs.record(
            "AUDIT_UPDATED", user=self.session.user.email,
            details=f"{saved.audit_id}",
        )
        return saved

    # -- search -------------------------------------------------------------

    def search(self, query: str = "", *, validation: str = "",
               mine_only: bool = False) -> list[Audit]:
        """Filter audits by free-text query, validation and ownership."""
        audits = self.audits.all()
        if mine_only:
            email = self.session.user.email.lower()
            audits = [a for a in audits if a.qa_email.lower() == email]
        if validation:
            audits = [a for a in audits if a.validation.lower() == validation.lower()]
        query = query.strip().lower()
        if query:
            def matches(a: Audit) -> bool:
                haystack = " ".join([
                    a.audit_id, a.agent, a.agent_eid, a.case_number,
                    a.genesys_id, a.team_leader, a.operations_manager,
                    a.qa_name, a.reason, a.remarks, a.queue, a.lob,
                ]).lower()
                return query in haystack
            audits = [a for a in audits if matches(a)]
        # Most recent first.
        audits.sort(key=lambda a: a.created_at, reverse=True)
        return audits

    # -- archive / restore (admin + password gated) -------------------------

    def _check_archive_password(self, password: str) -> None:
        configured = self.settings.get("security.archive_password", "")
        if configured and password != configured:
            raise PermissionDeniedError("Incorrect archive/delete password.")

    def archive_audit(self, audit_id: str, *, password: str = "") -> Audit:
        """Move an audit to the archive (admin-only, soft delete)."""
        self.session.require_admin()
        self._check_archive_password(password)
        audit = self.audits.get(audit_id)
        if audit is None:
            raise ValidationError("Audit not found.")
        self.archive.add(audit)
        self.audits.remove(audit_id)
        self.logs.record(
            "AUDIT_ARCHIVED", user=self.session.user.email, details=audit_id,
            level="WARNING",
        )
        return audit

    def restore_audit(self, audit_id: str) -> Audit:
        """Restore an archived audit back into the active database."""
        self.session.require_admin()
        audit = self.archive.get(audit_id)
        if audit is None:
            raise ValidationError("Archived audit not found.")
        # Avoid resurrecting a duplicate.
        if self.audits.exists_dedupe(audit.case_number, audit.genesys_id):
            raise DuplicateAuditError(
                "Cannot restore: an active audit already uses this "
                "Case Number + Genesys Transaction ID."
            )
        self.audits.add(audit)
        self.archive.remove(audit_id)
        self.logs.record(
            "AUDIT_RESTORED", user=self.session.user.email, details=audit_id,
        )
        return audit
