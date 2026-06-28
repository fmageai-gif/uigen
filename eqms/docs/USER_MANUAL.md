# EQMS User Manual (QA Analysts)

This guide is for QA Analysts using the HP Mainstream EQMS to record Short Call
Audits.

## 1. Signing in

1. Launch **HP-Mainstream-EQMS.exe**.
2. Click **Sign in with Microsoft 365**.
3. A code and a link appear — open the link in your browser, enter the code and
   complete sign-in with your `@concentrix.com` account.
4. The app remembers you; next time it signs you in silently.

> No tenant configured yet? Use **Continue offline** with your work email to
> explore the app against a local data store.

Your name and role (**QA Analyst**) appear at the bottom of the sidebar.

## 2. The dashboard

The **Dashboard** is your landing page. It shows:

- **KPI cards** — Today, This Week, This Month, Total, Valid %, Invalid %, Top
  QA/Agent/TL/OM, Most Common Invalid Reason, Last Submission and System Status.
- **Charts** — audits per day (last 14 days), Valid vs Invalid, and the top
  invalid reasons.
- A **live, searchable audit table**. Type in the search box to filter.

Click **⟳ Refresh** to pull the latest data from SharePoint. The status pill
shows **● Online** or **● Offline (cached)**.

## 3. Creating an audit

Open **New Audit** and complete the form:

| Field | Notes |
|-------|-------|
| **Agent** | Start typing the name or EID and pick from the dropdown. |
| Agent EID, Team Leader, Operations Manager, Queue, LOB, TL/OM Email | **Auto-filled** from the masterlist when you select an agent. |
| **Date** | Defaults to today; editable. |
| **Case Number** | Required. |
| **Genesys Transaction ID** | Required. |
| **Validation** | Choose **Valid** or **Invalid**. |
| **Reason** | The list changes to match your Validation choice. |
| **Remarks** | **Mandatory.** |

Rules enforced for you:

- **Case Number + Genesys Transaction ID must be unique** — duplicates are
  blocked.
- A **Valid** audit only accepts **valid** reasons; **Invalid** only accepts
  **invalid** reasons.
- **Remarks cannot be empty.**

Click **Submit Audit**. A green toast confirms success. If the audit is
**Invalid**, a notification email is sent automatically to the agent's TL and OM
and the QA distribution list.

> **Audit ID** is generated automatically (e.g. `AUD-2026-000123`).

## 4. Finding and editing audits

Open **History**:

- **Search** by ID, agent, EID, case, Genesys ID, QA, reason or remarks.
- Filter by **All / Valid / Invalid**.
- Toggle **My audits only**.

Each row has an **Edit** button. You may edit **only your own** audits — the
button is disabled on audits owned by other QAs. Editing opens the audit in the
form; make your changes and click **Update Audit**.

## 5. Reports

Open **Reports** to generate a monthly Excel report:

1. Choose the **Month** and **Year**.
2. Click **Generate Report**.
3. The path to the saved `.xlsx` is shown. Use **Open Reports Folder** to find
   it.

Reports contain a summary sheet (KPIs and breakdowns, with a chart) and a detail
sheet of the audits in scope.

## 6. Themes

Use the **Light/Dark** button at the bottom of the sidebar to switch appearance
at any time. Your choice is remembered.

## 7. Tips & troubleshooting

| Situation | What to do |
|-----------|-----------|
| "An audit with this Case Number and Genesys Transaction ID already exists" | The combination was already audited — check History. |
| Agent fields don't auto-fill | The agent may not be in the masterlist; ask your administrator to update it. |
| Status shows **Offline (cached)** | SharePoint was unreachable; your data is from the last sync. Reconnect and **Refresh**. |
| Email didn't send while offline | It's saved as an `.eml` in your backups `outbox` folder and recorded in the logs. |

For configuration changes (reasons, recipients, masterlist, etc.) contact your
**Super Administrator**.
