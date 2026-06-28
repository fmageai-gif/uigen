# HP Mainstream EQMS — Architecture

## Overview

The EQMS is a modular Python desktop application packaged as a single Windows
`.exe`. It uses **Excel workbooks on SharePoint as the system of record** and a
local SQLite file purely as an offline/performance cache. No business rules are
hardcoded except the bootstrap Super Administrator account.

```
+---------------------------------------------------------------+
|                       UI  (CustomTkinter)                     |
|  login · dashboard · audit form · history · admin · reports   |
+-----------------------------+---------------------------------+
                              | calls
+-----------------------------v---------------------------------+
|                          Services                             |
|  audit · dashboard · email · report · backup · update         |
+-----------------------------+---------------------------------+
                              | uses
+-----------------------------v---------------------------------+
|                        Data layer                             |
|  settings · masterlist · audit_repo · archive · logs · cache  |
+-----------------------------+---------------------------------+
                              | reads/writes
+-----------------------------v---------------------------------+
|              SharePoint / Excel store abstraction             |
|   SharePointExcelStore  ·  LocalExcelStore (offline/dev)      |
+-----------------------------+---------------------------------+
                              | authenticates via
+-----------------------------v---------------------------------+
|                Microsoft 365 auth (MSAL + Graph)              |
+---------------------------------------------------------------+
```

## Layers

| Layer | Package | Responsibility |
|-------|---------|----------------|
| Configuration | `eqms.config` | Paths, defaults, the single hardcoded admin email. |
| Core | `eqms.core` | Logging, exceptions, dataclass models, retry, utilities. |
| Auth | `eqms.auth` | Microsoft 365 sign-in (MSAL), session/role resolution. |
| Storage | `eqms.sharepoint` | Excel read/write over SharePoint with a swappable backend. |
| Data | `eqms.data` | Per-workbook repositories that speak in domain models. |
| Services | `eqms.services` | Business logic, validation, charts, email, reports, backups, updates. |
| UI | `eqms.ui` | CustomTkinter views, widgets, theming. |

## Key design decisions

- **Excel is the system of record.** Every write goes to SharePoint; SQLite is
  a read-through cache that lets the dashboard render instantly and degrade
  gracefully when offline.
- **Swappable storage backend.** `LocalExcelStore` mirrors the SharePoint
  library on disk so the entire app runs, is demoable, and is unit-testable
  without a tenant. `SharePointExcelStore` is selected automatically once M365
  connection settings are present.
- **Retry everywhere it touches Excel.** Workbook locking and Graph throttling
  are treated as transient and retried with exponential back-off + jitter.
- **Configuration over code.** All audit reasons, validation rules, widgets,
  recipients, paths, themes, backup and update settings live in
  `Settings.xlsx` and are edited through the Admin Center at runtime.
- **Threaded I/O.** Network/Excel work runs on background threads; the UI
  thread only ever renders, keeping the window responsive.

## Workbooks (system of record)

| Workbook | Contents |
|----------|----------|
| `Settings.xlsx` | All runtime configuration (reasons, rules, recipients, paths, theme, backup/update, branding). |
| `Masterlist.xlsx` | Agent roster uploaded by the admin. |
| `AuditDatabase.xlsx` | All active audit submissions. |
| `Archive.xlsx` | Soft-deleted / archived audits. |
| `SystemLogs.xlsx` | Business audit trail of user/admin actions. |

See [`docs/USER_MANUAL.md`](USER_MANUAL.md) and
[`docs/ADMIN_MANUAL.md`](ADMIN_MANUAL.md) for usage, and
[`docs/PACKAGING.md`](PACKAGING.md) to build the `.exe`.
