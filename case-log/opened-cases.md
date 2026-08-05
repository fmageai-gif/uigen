# Opened Case Ledger

Running record of case IDs pulled from the **HP_ADHOC_ Derp\*** view
(Dynamics 365 → Customer Service Workspace). **No case ID may be opened twice.**

Source view total: 87 rows. Only the first 16 are visible in the shared screenshot;
the remaining 71 need to be captured before the pool is exhausted.

## Opened

| # | Case ID | Subject | Created On | Opened (session) | Status |
|---|---------|---------|------------|------------------|--------|
| 1 | 5163090341 | Printer not eligible for Insta… | 8/6/2026 1:13 AM | 2026-08-05 | OPEN |

## Available pool (not yet opened)

| Case ID | Subject | Created On | Modified By | Resolution | QuickCase |
|---------|---------|------------|-------------|------------|-----------|
| 5163090187 | AIP - Misroute | 8/6/2026 1:09 AM | SYSTEM | — | Yes |
| 5163088476 | Troubleshooting Printing Is… | 8/6/2026 12:27 AM | SYSTEM | — | Yes |
| 5163085740 | Printer issue | 8/5/2026 11:29 PM | SYSTEM | — | Yes |
| 5163084695 | ii- offline | 8/5/2026 11:08 PM | Jayson Cerace | Remote Solution | No |
| 5163084403 | AIP Printer issue | 8/5/2026 11:01 PM | Jayson Cerace | — | Yes |
| 5163084243 | Troubleshooting Printing Is… | 8/5/2026 10:58 PM | SYSTEM | — | Yes |
| 5163083811 | HW UNABLE TO PRINT | 8/5/2026 10:49 PM | Jinky Malate | Remote Solution | No |
| 5163082775 | Troubleshooting Printing Is… | 8/5/2026 10:28 PM | SYSTEM | — | Yes |
| 5163082705 | AIP issue | 8/5/2026 10:27 PM | SYSTEM | — | Yes |
| 5163082135 | Troubleshooting Printing Is… | 8/5/2026 10:15 PM | SYSTEM | — | Yes |
| 5163081581 | ii billing update | 8/5/2026 10:03 PM | Irene Juson | Case Voided | No |
| 5163080451 | Laptop issue/offline | 8/5/2026 9:41 PM | SYSTEM | — | Yes |
| 5163078937 | II - cancel instant ink subscr… | 8/5/2026 9:05 PM | Percival Magante | Subscription c… | No |
| 5163077290 | ghost call | 8/5/2026 8:24 PM | SYSTEM | — | Yes |
| 5163047938 | no info | 8/5/2026 9:24 AM | SYSTEM | — | Yes |

## Rules

1. Pick from **Available pool** only — top of the list first (newest Created On).
2. On pick: move the row to **Opened**, stamp the date, never return it to the pool.
3. Before every pick, re-read this file. If an ID already appears under Opened, skip it.

## Superseded by the app

The `Case` table is now the source of truth — see `/cases`. The
`openedAt` column enforces rule 3 in the database rather than by hand:
`openCase()` claims a row only `WHERE openedAt IS NULL`, so a second
open of the same ID cannot succeed. This file stays as the origin record.
