"""First-run seed values for ``Settings.xlsx``.

IMPORTANT: nothing here is a *hardcoded business rule*. These are one-time
**seed defaults** written into ``Settings.xlsx`` the first time the application
runs against an empty store. From that moment on every value is owned by the
workbook and is fully editable by the Super Administrator through the Admin
Center — changing a reason or a recipient never requires a code change or a
rebuild. The only genuinely hardcoded business value lives in
:data:`eqms.config.SUPER_ADMIN_EMAIL`.
"""

from __future__ import annotations

from .. import config

# ---------------------------------------------------------------------------
# Audit reasons (seed lists — editable in the Admin Center afterwards)
# ---------------------------------------------------------------------------

DEFAULT_VALID_REASONS = [
    "BCP - CANNOT ASSIST",
    "DISC CB MET - IN-SCOPE ISSUE, NON-T/S CALL",
    "DISC CB MET - IN-SCOPE, STARTED TO PERFORM T/S",
    "DISC CB NOT REQ - GHOST CALL WITH OR WITHOUT ACCT (CDAX PROFILE/AST ACCOUNT)",
    "DISC CB NOT REQ - IN-SCOPE ISSUE, NO T/S DONE YET",
    "DISCONNECTED CALL - UNKNOWN ISSUE",
    "NO INTERACTION",
    "OOS - TRANSFERRED/REFERRED",
    "OTHER",
    "RESOLVED",
    "UNKNOWN ISSUE - AGENT DC [TRACKING]",
]

DEFAULT_INVALID_REASONS = [
    "AGENT UNRESPONSIVE",
    "BCP - CAN ASSIST",
    "DISC CB NOT MET - IN-SCOPE ISSUE",
    "NON-T/S CALL",
    "DISC CB NOT MET - IN-SCOPE, STARTED TO PERFORM T/S",
    "DISCONNECTED CALL - UNKNOWN ISSUE",
    "IN SCOPE - TRANSFERRED/REFERRED",
    "UNPROFESSIONAL",
    "UNRESOLVED",
    "OTHERS",
]

# ---------------------------------------------------------------------------
# Scalar configuration (key/value) seeds
# ---------------------------------------------------------------------------

DEFAULT_SETTINGS: dict[str, str] = {
    # --- Branding ---
    "app.title": config.APP_SHORT_NAME if hasattr(config, "APP_SHORT_NAME") else "HP Mainstream EQMS",
    "app.subtitle": "Enterprise Quality Management System",
    "app.primary_color": "#0F4C81",      # HP-inspired enterprise blue
    "app.accent_color": "#1C7ED6",
    "app.organisation": "HP Mainstream Quality Assurance",
    # --- Theme ---
    "theme.mode": "System",              # System | Light | Dark
    "theme.color_theme": "blue",         # CustomTkinter base theme
    # --- SharePoint connection ---
    "sharepoint.site_url": "",
    "sharepoint.folder_path": "Shared Documents/EQMS",
    "sharepoint.enabled": "false",       # false => local offline store
    # --- Sync / cache ---
    "sync.interval_seconds": str(config.DEFAULT_SYNC_INTERVAL),
    "sync.auto": "true",
    # --- Backups ---
    "backup.enabled": "true",
    "backup.interval_hours": "24",
    "backup.retention": "30",            # keep N most recent backups
    # --- Reports ---
    "report.auto_monthly": "true",
    "report.day_of_month": "1",          # generate on the Nth day
    "report.recipients": "",             # who receives monthly reports
    # --- Updates ---
    "update.auto_check": "true",
    "update.manifest_url": "",           # JSON manifest with latest version
    "update.channel": "stable",
    # --- Email ---
    "email.enabled": "true",
    "email.send_on_invalid_only": "true",
    "email.qa_distribution_list": "",    # extra recipients on every invalid audit
    "email.subject_template": "[EQMS] Invalid Audit {audit_id} - {agent}",
    # --- Security ---
    "security.archive_password": "",     # set by admin; gates archive/delete
    # --- Validation rules (editable toggles) ---
    "validation.remarks_required": "true",
    "validation.unique_case_genesys": "true",
    "validation.block_duplicate_submissions": "true",
    "validation.require_agent_from_masterlist": "false",
}

# ---------------------------------------------------------------------------
# Default dashboard widgets (KPI cards) — order and visibility are editable.
# Each entry: key | label | enabled
# ---------------------------------------------------------------------------

DEFAULT_DASHBOARD_WIDGETS = [
    ("today", "Today's Audits", "true"),
    ("week", "This Week", "true"),
    ("month", "This Month", "true"),
    ("total", "Total Audits", "true"),
    ("valid_pct", "Valid %", "true"),
    ("invalid_pct", "Invalid %", "true"),
    ("top_qa", "Top QA", "true"),
    ("top_agent", "Top Agent", "true"),
    ("top_tl", "Top TL", "true"),
    ("top_om", "Top OM", "true"),
    ("common_invalid", "Most Common Invalid Reason", "true"),
    ("last_submission", "Last Submission", "true"),
    ("system_status", "System Status", "true"),
]

# ---------------------------------------------------------------------------
# Sheet names within Settings.xlsx
# ---------------------------------------------------------------------------

SHEET_SETTINGS = "Settings"
SHEET_VALID_REASONS = "ValidReasons"
SHEET_INVALID_REASONS = "InvalidReasons"
SHEET_EMAIL_RECIPIENTS = "EmailRecipients"
SHEET_WIDGETS = "DashboardWidgets"

SETTINGS_HEADERS = ("Key", "Value")
REASON_HEADERS = ("Reason",)
RECIPIENT_HEADERS = ("Name", "Email", "Role")
WIDGET_HEADERS = ("Key", "Label", "Enabled")
