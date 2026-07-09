# HP Mainstream EQMS — Single-File Web Edition

`EQMS.html` is the entire application: dashboards, audit form, team database,
history, analytics and admin center in **one HTML file** with zero
dependencies, zero installs and zero network calls. It runs from a local
folder or a OneDrive-synced folder in Chrome or Edge — nothing to approve
with IT.

## Quick start

1. Copy `EQMS.html` anywhere (Desktop, Downloads, a synced team folder).
2. Double-click it → sign in with your name and Concentrix email.
3. `sundeep.bhardwaj@concentrix.com` signs in as the Administrator and sees
   the **Admin Center**; everyone else signs in as a Quality Auditor.
4. Admin Center → **Agent Masterlist** → upload your masterlist as CSV
   (save your Excel masterlist with *File → Save As → CSV UTF-8*).
   Recognized columns: `Agent Name, Agent EID, Agent Email, Team Leader,
   Operations Manager, Region, LOB, TL Email, OM Email` (order/extra columns
   don't matter; common synonyms like `EID`, `Supervisor`, `Account` work too).

## Live team sync (14+ auditors, no server)

The team database is a single `EQMS_TeamDB.json` file living in a
SharePoint / OneDrive folder that every auditor has synced in File Explorer.

**Admin (once):**
1. Admin Center → *Team Live Sync* → **Create team DB file…** and save it
   inside the team's synced SharePoint folder.
2. Share that folder with all auditors (normal SharePoint/OneDrive sharing).

**Each auditor (once):**
1. In File Explorer, make sure the shared folder is synced (OneDrive ✔ icon).
2. Open EQMS → click the **“Local Only”** pill (top right) → **Connect
   existing file…** → pick `EQMS_TeamDB.json`.

From then on every copy of the app re-reads and merges the shared file every
10 seconds and after every submission — audits, the masterlist, and admin
settings all propagate to the whole team. Conflict handling is automatic
(newest edit per audit wins; deletions propagate via tombstones).

> Browser note: live file sync requires Chrome or Edge (File System Access
> API). On first open after a restart the pill shows *“Click to re-connect
> Team Sync”* — one click re-authorizes it (a browser security rule).

## Invalid-audit email notifications

Submitting an **Invalid** audit opens a fully pre-written Outlook draft
addressed to the agent's TL + OM (Cc: the QA distribution list configured in
Admin Center) containing the complete audit summary and a 48-hour coaching
acknowledgement request — the auditor just presses **Send**. The audit's
*Email Sent* flag is tracked in the database. Subject template, Cc list and
the auto-open toggle live in Admin Center → *Email Notifications*.

## Roles & disputes

- **Administrator** (configurable, default `sundeep.bhardwaj@concentrix.com`):
  full Admin Center, can edit/delete *any* audit (dispute resolution).
- **Auditors**: submit audits; edit/delete only their *own* audits.
- Audit History is the dispute workbench: search/filter, 👁 view, ✏️ edit
  (banner shows whose audit is being amended), every edit updates
  `Updated At` and syncs to the team.
- Optional: Admin Center → *Users & Access* → restrict sign-in to the
  authorized auditor email list.

## Data & exports

- Excel-ready CSV exports (UTF-8 BOM): all audits, invalid only, quick case
  only, filtered history, agent masterlist.
- Full JSON backup / restore-merge in Admin Center.
- "Wipe this device" clears only the local browser copy — reconnecting to
  the team DB restores everything.

## Quick Case logic

An audit appears on the **Quick Case Dashboard** when the tagged Case
Resolution *or* the Expected Resolution Code contains “Quick Case” — covering
both valid and invalid quick cases automatically, no extra field to fill.
