# EQMS Administrator Manual

This guide is for the **Super Administrator**
(`sundeep.bhardwaj@concentrix.com`). Only this account can open the **Admin
Center**; every administrative action is recorded in the system audit trail
(`SystemLogs.xlsx`).

## Signing in as administrator

Sign in with Microsoft 365 using the administrator account. An **Admin Center**
entry appears in the sidebar (it is hidden for QA users). The service layer
independently enforces the gate, so administrative actions cannot be performed
by anyone else even if the UI is bypassed.

## Where configuration lives

All configuration is stored in **`Settings.xlsx`** (on SharePoint, or in the
local store when offline). Nothing below requires a code change or a rebuild.
The only value hardcoded in the application is the administrator email itself.

`Settings.xlsx` sheets: `Settings` (key/value), `ValidReasons`,
`InvalidReasons`, `EmailRecipients`, `DashboardWidgets`.

## Admin Center tabs

### General
Organisation name, app title/subtitle, background **sync interval** and whether
automatic sync is on.

### Branding & Theme
Primary and accent **colours** (HP blue by default) and the **appearance mode**
(System/Light/Dark). Colour changes fully apply on restart.

### Audit Reasons
Edit the **Valid** and **Invalid** reason lists (one per line). These drive the
audit form's Reason dropdown. Saving updates the lists immediately for all QAs.

### Validation
Toggle the rules QAs are held to:
- Remarks mandatory
- Unique Case + Genesys ID
- Block duplicate submissions
- Agent must be selected from the masterlist

### Widgets
Enable/disable each **dashboard KPI card**. Reopen the dashboard to apply.

### Email
- Enable/disable email automation.
- **Send only on Invalid** (default on).
- **Subject template** — supports `{audit_id}` and `{agent}` placeholders.
- **QA distribution list** — extra recipients (comma/newline separated) added to
  every notification, alongside the agent's TL and OM.

### SharePoint
- **Use SharePoint storage** — when off, the app uses the local Excel store.
- **Site URL** — e.g. `https://org.sharepoint.com/sites/QA`.
- **Folder path** — e.g. `Shared Documents/EQMS`.

Changes take effect after sign-out/restart. The five workbooks
(`Settings.xlsx`, `Masterlist.xlsx`, `AuditDatabase.xlsx`, `Archive.xlsx`,
`SystemLogs.xlsx`) are created automatically in that folder on first use.

### Backups & Updates
- **Automatic backups**, interval (hours) and **retention** (how many to keep).
- **Back up now** to run an immediate backup.
- **Automatic monthly report** and the **day of month** it runs (covers the
  previous month).
- **Automatic update check** and the **manifest URL** (see Packaging guide).
- **Archive/delete password** — gates archiving/deleting audits.

Backups and reports are written under
`%LOCALAPPDATA%\HP-Mainstream-EQMS\backups`.

### Masterlist
Upload or replace **`Masterlist.xlsx`**. Click *Choose .xlsx and import…* and
select the file. The application reads these columns (header names are matched
case-insensitively):

```
Agent Name | Agent EID | Team Leader | Operations Manager | Queue | LOB | TL Email | OM Email
```

The roster is replaced and the agent count is shown. QAs immediately get the new
autocomplete data.

### Logs
View the **business audit trail** (most recent 500 entries): who did what and
when. **Refresh** to reload, **Clear logs** to truncate (itself logged).

### Archive
View **archived (soft-deleted) audits** and **Restore** any of them back into the
active database. Restoration is blocked if it would create a duplicate
Case + Genesys record.

> To **archive** an audit, go to **History** (as admin), click **Archive** on a
> row and enter the archive password if one is configured. Archived records are
> never lost — they move to `Archive.xlsx`.

### Export
**Export all data** copies every workbook to a folder you choose — useful for
backups, audits or migrations.

## Operational notes

- **File locking / retries** — writes to SharePoint Excel are retried with
  exponential back-off, so transient locks by other users are handled
  automatically.
- **Logs** — technical logs rotate under `…\logs\eqms.log`; business events go to
  `SystemLogs.xlsx`.
- **Offline** — if SharePoint is unreachable the app serves cached data and
  queues emails as `.eml` files; reconnect and refresh to resync.

## Security checklist

- Keep the administrator account protected (MFA via Microsoft 365).
- Set an **archive/delete password** so destructive actions need confirmation.
- Restrict the SharePoint folder's permissions to the QA team.
- Code-sign the distributed `.exe` (see [Packaging](PACKAGING.md)).
