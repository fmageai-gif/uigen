# Focus Audit transfer

Copies your daily audit rows out of **ADHOC.xlsx** and into the **Focus Audit**
SharePoint list, so you don't have to retype them.

- Source: `ADHOC.xlsx` → sheet `Audit Log`
  (*HP Mainstream LOB / Admin / Derp's File*)
- Target: [Focus Audit list](https://cnxmail.sharepoint.com/sites/ChangeManagementTeam/Lists/Focus%20Audit/AllItems.aspx)

It drives a real browser using your own signed-in session. Nothing is stored
anywhere except on your PC.

---

## Setup (once)

1. Install **Python 3.10+** from [python.org](https://www.python.org/downloads/).
   On the first screen, tick **"Add python.exe to PATH"**.
2. Double-click **`setup.bat`** and wait for it to finish.
3. Sync the workbook so the script can read it:
   open *Derp's File* in SharePoint → **Sync**. Then put the resulting local
   path into `excel_path` in `config.json`, for example:

   ```json
   "excel_path": "C:\\Users\\you\\Concentrix\\HP Mainstream LOB - Admin\\Derp's File\\ADHOC.xlsx"
   ```

   Leave `excel_path` as `""` to download a fresh copy each run instead.

## Capture the form layout (once)

Double-click **`inspect.bat`**. A browser opens — sign in to SharePoint if
asked. It writes **`form_schema.json`** listing every field and every dropdown
option on the New item form.

Send that file back so the dropdown mapping can be completed in `config.json`.
Until that's done, values that don't match an option will pause and ask you.

## Daily use

| Command | What it does |
|---|---|
| `run.bat --preview` | Prints what would be sent and what would be skipped. **No browser, nothing submitted** |
| `run.bat --dry-run` | Fills one entry and stops **before** Save so you can check it |
| `run.bat` | Lists the rows it will submit, asks you to confirm, then does them |
| `run.bat --date 08/01/2026` | Only rows with that audit date |
| `run.bat --last-days 14` | Widen the default 7-day window |
| `run.bat --limit 5` | Stop after 5 rows |
| `run.bat --all` | Ignore dates entirely |
| `run.bat --force` | Re-submit rows already recorded as done |
| `run.bat --include-unmatched` | Also attempt the skipped rows, pausing so you pick the criteria |

**Run `--preview` first**, then `--dry-run`. Preview costs nothing and shows the
whole day's mapping at a glance; dry run proves the form filling works.

---

## How rows are chosen

1. Column **U** (`auditorName`) must equal `auditor_name` in `config.json`
   — so you only ever get your own audits, never a colleague's.
2. Column **B** (`auditDate`) must fall in the date window (last 7 days by default).
3. Anything whose `auditId` is already in `submitted.json` is skipped.

4. Rows that cannot fill a **required dropdown** are set aside. Call/Chat
   Selection Criteria only offers `Remote Solution`, `Case Voided` and
   `Quick Case`, so a `Subscription Cancellation (SubCan)` row could never be
   saved. Those rows are listed before anything is submitted, so you always see
   what is being left out. `run.bat --preview` shows the same thing without
   opening a browser.

`submitted.json` is what stops double-entry. Don't delete it. It is written
only after a save actually succeeds, so a failed row will be retried next run.
Skipped rows are never recorded as submitted, so they reappear if the option
list later gains a match.

Nothing is ever written back to ADHOC.xlsx. The workbook is co-authored by the
team, so the script only ever reads it.

## Field mapping

| Form field | Excel column | Rule |
|---|---|---|
| LOB | M `LOB` | Print / Instant Ink / Instant Ink Chat |
| Call Listening Date | B `auditDate` | time set to 12:00 AM |
| Agent Name | F `agentEmail` | people picker — typed, then the suggestion is clicked |
| Call/Chat Selection Criteria | S `expectedResolutionCode` | |
| Suggested Resolution Code | **R if Invalid, S if Valid** | see below; `Quick Case` → `NA` |
| Call/Chat Date | C `Call Date` | time set to 12:00 AM |
| CaseID | N `caseNumber` | |
| Call/Chat ID | P `genesysTransactionId` | |
| Case Subject | O `caseSubject` | |
| What are the Opportunities | — | always `N/A` |
| Comments/Summary | T `remarks` | |
| Validation | Q `validation` | Valid / Invalid |

Unused: A `auditId` (used as the dedupe key), D `agentName`, U `auditorName`,
V `quickCase`, W `sendEmail`.

### The Suggested Resolution Code rule

- **Invalid** audit → column **R** (`caseResolution`), e.g. `Subscription Cancellation (Invalid)`
- **Valid** audit → column **S** (`expectedResolutionCode`), e.g. `Subscription Cancellation (SubCan)`

Only the literal `(Invalid)` and `(Pass)` markers are stripped. Parentheses in
column S are part of the official code name — `(SubCan)`, `(HW/SW Resolved
Remotely via Phone/Chat)`, `(Test Case / Duplicate / Created by Mistake)` — and
are always kept.

## When something goes wrong

**A value doesn't match any dropdown option.** The script prints the available
options and waits. Pick the right one in the browser, press Enter, and it moves
on. It also tells you the line to add to `choice_map` in `config.json` so it's
automatic next time.

**"Could not find the 'X' field".** The form's labels changed. Re-run
`inspect.bat` and send the new `form_schema.json`.

**"No directory match appeared for …".** The people picker couldn't resolve
that agent's email — usually a leaver, or a typo in column F.

**It asks you to sign in every run.** Delete the `.browser-profile` folder and
run `inspect.bat` again to re-establish the session.

**The browser won't start.** `config.json` uses `"browser_channel": "msedge"`.
Set it to `"chrome"`, or `""` to use the copy of Chromium that `setup.bat`
installed.

`last_run.log` holds a timestamped record of the most recent run, and
`screenshots/` gets a PNG plus the page HTML whenever a row fails — send those
along if you need something diagnosed.

---

## What has and hasn't been tested

Verified against a synthetic workbook and a mock form built from the real
form's captured markup: the column mapping, the auditor and date filters, the
dedupe log, the Valid/Invalid resolution-code rule with its suffix handling,
two-way dropdown matching, the people picker (including skipping the
"Search Directory" entry), setting both date fields to 12:00 AM independently,
and recovering when a dropdown is left open over the fields below it.

Field locators and the dropdown option lists come from the live form. What has
**not** been exercised is the real page itself — timing, the directory lookup,
and Save. `--preview` and `--dry-run` exist to close that gap safely.
