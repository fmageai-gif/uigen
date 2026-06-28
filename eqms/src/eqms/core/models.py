"""Domain models.

These are plain ``dataclasses`` that map 1:1 to rows in the Excel workbooks.
Keeping them framework-agnostic means the data layer, services and UI all speak
the same vocabulary without coupling to openpyxl or CustomTkinter.

Every model provides ``to_row`` / ``from_row`` helpers so the storage layer can
serialise to and from the ordered column layout of its workbook. ``HEADERS``
defines the canonical column order for each sheet.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import datetime, date
from typing import Any, Mapping


def _to_str(value: Any) -> str:
    """Normalise a cell value to a trimmed string ("" for None)."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    return str(value).strip()


# ---------------------------------------------------------------------------
# Agent (a row of Masterlist.xlsx)
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class Agent:
    """An agent record sourced from the administrator-uploaded Masterlist."""

    agent_name: str = ""
    agent_eid: str = ""
    team_leader: str = ""
    operations_manager: str = ""
    queue: str = ""
    lob: str = ""
    tl_email: str = ""
    om_email: str = ""

    HEADERS = (
        "Agent Name",
        "Agent EID",
        "Team Leader",
        "Operations Manager",
        "Queue",
        "LOB",
        "TL Email",
        "OM Email",
    )

    def to_row(self) -> list[str]:
        return [
            self.agent_name,
            self.agent_eid,
            self.team_leader,
            self.operations_manager,
            self.queue,
            self.lob,
            self.tl_email,
            self.om_email,
        ]

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "Agent":
        """Build an :class:`Agent` from a header→value mapping (case-tolerant)."""
        get = _row_getter(row)
        return cls(
            agent_name=get("Agent Name"),
            agent_eid=get("Agent EID"),
            team_leader=get("Team Leader"),
            operations_manager=get("Operations Manager"),
            queue=get("Queue"),
            lob=get("LOB"),
            tl_email=get("TL Email"),
            om_email=get("OM Email"),
        )

    @property
    def search_key(self) -> str:
        """Lower-cased text used for autocomplete matching."""
        return f"{self.agent_name} {self.agent_eid}".lower()


# ---------------------------------------------------------------------------
# Audit (a row of AuditDatabase.xlsx / Archive.xlsx)
# ---------------------------------------------------------------------------

VALIDATION_VALID = "Valid"
VALIDATION_INVALID = "Invalid"


@dataclass(slots=True)
class Audit:
    """A single Short Call Audit submission."""

    audit_id: str = ""
    date: str = ""           # ISO date the audit covers / was created
    qa_name: str = ""        # auto-filled from the signed-in user
    qa_email: str = ""       # owner; used to enforce "edit only your own"
    auditor_name: str = ""   # name of the auditor performing the audit
    agent: str = ""
    agent_eid: str = ""
    team_leader: str = ""
    operations_manager: str = ""
    tl_email: str = ""
    om_email: str = ""
    queue: str = ""
    lob: str = ""
    case_number: str = ""
    genesys_id: str = ""
    validation: str = ""     # "Valid" | "Invalid"
    reason: str = ""
    remarks: str = ""
    email_sent: str = ""     # "Yes" / "No" / "" for invalid-audit notifications
    created_at: str = ""     # ISO timestamp of submission
    updated_at: str = ""     # ISO timestamp of last edit

    HEADERS = (
        "Audit ID",
        "Date",
        "QA Name",
        "QA Email",
        "Auditor Name",
        "Agent",
        "Agent EID",
        "TL",
        "OM",
        "TL Email",
        "OM Email",
        "Queue",
        "LOB",
        "Case Number",
        "Genesys Transaction ID",
        "Validation",
        "Reason",
        "Remarks",
        "Email Sent",
        "Created At",
        "Updated At",
    )

    def to_row(self) -> list[str]:
        return [
            self.audit_id,
            self.date,
            self.qa_name,
            self.qa_email,
            self.auditor_name,
            self.agent,
            self.agent_eid,
            self.team_leader,
            self.operations_manager,
            self.tl_email,
            self.om_email,
            self.queue,
            self.lob,
            self.case_number,
            self.genesys_id,
            self.validation,
            self.reason,
            self.remarks,
            self.email_sent,
            self.created_at,
            self.updated_at,
        ]

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "Audit":
        get = _row_getter(row)
        return cls(
            audit_id=get("Audit ID"),
            date=get("Date"),
            qa_name=get("QA Name"),
            qa_email=get("QA Email"),
            auditor_name=get("Auditor Name"),
            agent=get("Agent"),
            agent_eid=get("Agent EID"),
            team_leader=get("TL"),
            operations_manager=get("OM"),
            tl_email=get("TL Email"),
            om_email=get("OM Email"),
            queue=get("Queue"),
            lob=get("LOB"),
            case_number=get("Case Number"),
            genesys_id=get("Genesys Transaction ID"),
            validation=get("Validation"),
            reason=get("Reason"),
            remarks=get("Remarks"),
            email_sent=get("Email Sent"),
            created_at=get("Created At"),
            updated_at=get("Updated At"),
        )

    @property
    def is_invalid(self) -> bool:
        return self.validation.strip().lower() == VALIDATION_INVALID.lower()

    @property
    def dedupe_key(self) -> str:
        """Composite uniqueness key: Case Number + Genesys Transaction ID."""
        return f"{self.case_number.strip().lower()}|{self.genesys_id.strip().lower()}"


# ---------------------------------------------------------------------------
# User session
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class User:
    """The authenticated Microsoft 365 user for the current session."""

    email: str = ""
    display_name: str = ""
    is_admin: bool = False

    @property
    def first_name(self) -> str:
        return self.display_name.split(" ")[0] if self.display_name else self.email


# ---------------------------------------------------------------------------
# System log entry (a row of SystemLogs.xlsx)
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class LogEntry:
    """A structured business audit-trail event."""

    timestamp: str = ""
    level: str = "INFO"
    user: str = ""
    action: str = ""
    details: str = ""

    HEADERS = ("Timestamp", "Level", "User", "Action", "Details")

    def to_row(self) -> list[str]:
        return [self.timestamp, self.level, self.user, self.action, self.details]

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "LogEntry":
        get = _row_getter(row)
        return cls(
            timestamp=get("Timestamp"),
            level=get("Level"),
            user=get("User"),
            action=get("Action"),
            details=get("Details"),
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row_getter(row: Mapping[str, Any]):
    """Return a case/space-insensitive accessor for a header→value mapping."""
    normalised = {str(k).strip().lower(): v for k, v in row.items()}

    def get(header: str) -> str:
        return _to_str(normalised.get(header.strip().lower()))

    return get


def model_field_names(model_cls) -> list[str]:
    """Return the dataclass field names of a model in declaration order."""
    return [f.name for f in fields(model_cls)]
