# HP Mainstream EQMS — Single-File Web Edition

`EQMS.html` is the entire application: dashboards, audit form, team database,
history, analytics and admin center in **one HTML file** with zero
dependencies, zero installs and zero network calls. It runs in Chrome or Edge
— nothing to approve with IT.

## Quick start

1. Copy `EQMS.html` anywhere (Desktop, Downloads, a synced team folder).
2. Double-click it → sign in with your name and Concentrix email.
3. `sundeep.bhardwaj@concentrix.com` is the **one and only Administrator**
   (hardcoded); everyone else signs in as a Quality Auditor.
4. At first sign-in the app walks you through connecting the **Team
   Database** (below) — this is required for live team sharing.
5. Admin Center → **Agent Masterlist Roster** → upload your roster CSV.
   Expected headers: `EmployeeNumber, FullName, Email, ImmediateSupervisor,
   ImmediateSupervisorEmail, Manager, ManagerEmail, SOM, SOMEmail, CHANNEL,
   Internal LOB` (order flexible, common synonyms accepted). You can also
   add/edit agents manually one at a time.

## Team Database — Microsoft 365 live sync

The team database is a single `EQMS_TeamDB.json` file living in a
SharePoint / OneDrive folder that every auditor has synced in File Explorer.
Microsoft 365 replicates the file to every PC; each copy of the app
auto-merges it **every 5 seconds** and immediately after every submission,
edit, roster or settings change — so everyone sees everyone's uploads live
without doing anything.

**Admin (once):**
1. Admin Center → *Team Database* → **Create team DB file…** and save it
   inside the team's synced SharePoint folder.
2. Share that folder with all auditors (normal SharePoint/OneDrive sharing).

**Each auditor (once per PC):**
1. In File Explorer, make sure the shared folder is synced (OneDrive ✔).
2. The app prompts at sign-in → **Connect EQMS_TeamDB.json** → pick the file.

Conflict handling is automatic (newest edit per audit wins; deletions
propagate via tombstones). After a browser restart Chrome may ask once to
re-authorize file access — one click on the status pill.

> Note: a locally opened HTML file cannot call Microsoft Graph / SharePoint
> APIs directly (that needs an IT-approved Azure app registration). The
> synced-file approach is the M365-backed design that works with zero IT
> involvement.

## Invalid-audit email notifications

Submitting an **Invalid** audit opens a fully pre-written Outlook draft
addressed to the agent's TL + OM (Cc: the QA distribution list configured in
Admin Center) containing the complete audit summary and a 48-hour coaching
acknowledgement request — the auditor just presses **Send**. The audit's
*Email Sent* flag is tracked in the database.

## Roles & disputes

- **Administrator** (fixed: `sundeep.bhardwaj@concentrix.com`): full Admin
  Center, can edit/delete *any* audit (dispute resolution).
- **Auditors**: submit audits; edit/delete only their *own* audits.
- Audit History is the dispute workbench: search/filter, view, edit,
  every change stamps `updatedAt` and syncs to the team.
- Admin Center → *User & Auditor Access Control*: authorized auditor list +
  optional sign-in restriction.

## Analytics & exports

- **Export CSV columns** (Excel/PowerBI-ready, UTF-8 BOM): `auditId,
  auditDate, agentName, agentEid, agentEmail, teamLeader, tlEmail,
  operationsManager, omEmail, caseNumber, genesysTransactionId, queue, lob,
  validation, reason, remarks, auditorName, createdAt` plus traceability
  extras (`expectedResolutionCode, quickCase, emailSent, auditorEmail,
  updatedAt`). `reason` is the valid case reason for Valid audits and the
  invalid defect reason for Invalid ones.
- **Defective Case Resolution Code Distribution** — every invalid defect
  reason with its defect count and percentage.
- Exports: all audits, invalid only, quick case only, filtered history,
  roster CSV, full JSON backup.

## Reason repositories

Admin Center manages two live lists that drive the form dropdowns for the
whole team:
- 📋 **Invalid Defect Reasons Repository** → "Validation Result / Case
  Resolution" options (choosing any of them marks the audit Invalid).
- ✔️ **Valid Case Reasons Repository** → "Expected Resolution Code" options.

## Quick Case logic

An audit appears on the **Quick Case Dashboard** when the tagged Case
Resolution *or* the Expected Resolution Code contains “Quick Case” — covering
both valid and invalid quick cases automatically.
