# Dynamics 365 → ADHOC.xlsx ConnID automation

Captures a repetitive audit workflow in code: open a Dynamics 365 case, find the
agent's **incoming** phone call, pull the **ConnID** (Genesys interaction id) out
of the Tenfold Call Details section, and log a row into the SharePoint-hosted
`ADHOC.xlsx` workbook in Excel for the web.

```
python automate.py "<case_url>" --dry-run     # extract + print, write nothing
python automate.py "<case_url>"               # extract + write the audit row
```

---

## What it does

| Step | Action |
| ---- | ------ |
| 1 | Opens the case in Customer Service Workspace and reads `owner` **first** (it is the filter for everything after), then `caseNumber`, `caseSubject`, `resolutionCode`. |
| 2 | Clicks the **Customer Interactions** tab. |
| 3 | Reads the **Phone Calls** grid and applies the filters strictly, in order: inbound-only, then owner-only, then the queue subject pattern. |
| 4 | Opens the single matching call, expands **Tenfold Call Details**, extracts **ConnID**. |
| 5–6 | Opens `ADHOC.xlsx` in Excel for the web, maps columns by header name, finds the first empty row, and fills it. |
| 7 | Waits for the autosave indicator. |

### The two hard filters

These are requirements, not preferences, and the script fails loudly rather than
working around them:

* **Inbound only.** Only rows whose Direction reads `Incoming` / `Inbound` are
  considered. Outgoing rows are skipped without ever being opened or read.
* **Owner only.** Of those, only calls belonging to the case owner captured in
  step 1 count. Matching is case-insensitive and whitespace-normalized, and also
  accepts an identical *token set* so `Dela Cruz, Juan` matches `Juan Dela Cruz`.
  It is deliberately **not** fuzzy — a near-miss never routes another agent's
  call into your audit row.

If nothing satisfies both filters, the script logs which filter failed (inbound,
owner, or both), exits with code `2`, and **writes nothing to the workbook**.

The subject pattern `voice - CS_AM_CV_US_HQ_PostSales_CONS_CE_ENG + <phone>` is
applied as a third, softer narrowing step: when at least one candidate matches
it, only those are considered; when none do, the script logs a warning and falls
back to the inbound + owner candidates. If several rows still qualify, it warns
and takes the most recent by Start Time.

### Before writing

* **Duplicate guard.** The `genesysTransactionId` column is scanned first; if the
  ConnID is already logged, the write is skipped.
* **Dropdown cells.** `agentName` and `expectedResolutionCode` are validated
  fields. The script opens the validation list (`Alt+↓`), falls back to
  type-ahead suggestions, and picks the closest option. Below a similarity of
  `0.72` it logs a warning and leaves the cell **blank for manual review**
  instead of guessing.
  `agentName` is stricter still: it accepts only an exact or reordered-token
  match, never a fuzzy one. Character similarity rates `Juana Dela Cruz` a 0.97
  match for `Juan Dela Cruz`, which would log the wrong agent — so if the owner
  is not in the list verbatim, the cell is left blank.

---

## Install

Python 3.11 or newer.

```bash
cd dynamics-connid-automation
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

## Authentication setup

No credentials live in the code, the environment, or the arguments. You sign in
once by hand, and Playwright saves the resulting session (`storage_state`) to a
file the automation reuses.

```bash
cp .env.example .env
# fill in DYNAMICS_CASE_URL (and DYNAMICS_LOGIN_URL if different)

python save_auth.py
```

A real browser window opens and walks you through **both** sign-ins — Dynamics
and SharePoint issue separate cookies and the automation needs both. Complete
each one (MFA included), press Enter at the prompt, and the session is written
to `auth_state.json`.

> The session file grants access to your Microsoft account for as long as its
> tokens stay valid. It is gitignored and chmod-600'd on creation. Keep it off
> shared drives. When `automate.py` reports an expired session, just re-run
> `save_auth.py`.

## Configuration

All URLs and tuning live in `.env` (see `.env.example`):

| Variable | Purpose |
| -------- | ------- |
| `PLAYWRIGHT_STORAGE_STATE` | Path to the saved session. **Required.** |
| `DYNAMICS_CASE_URL` | Default case URL when none is passed on the CLI. |
| `DYNAMICS_LOGIN_URL` | Sign-in target for `save_auth.py`; defaults to the case URL. |
| `EXCEL_WORKBOOK_URL` | The `ADHOC.xlsx` Excel-for-the-web URL. **Required.** |
| `EXCEL_HEADER_ROW` | 1-based header row in the sheet (default `1`). |
| `HEADLESS` | `false` to watch the run. |
| `SLOW_MO` | Per-action delay in ms, for debugging. |
| `DEFAULT_TIMEOUT_MS` | Element wait budget (default `45000`). |
| `LOG_LEVEL` | `DEBUG` prints every grid row it read. |
| `SCREENSHOT_DIR` | Where to drop failure screenshots; blank disables them. |
| `PLAYWRIGHT_EXECUTABLE_PATH` | Path to an existing Chromium/Chrome, for locked-down machines that can't run `playwright install`. Blank uses Playwright's bundled browser. |

Columns are matched **by header name**, so reordering the sheet is fine:
`auditDate`, `Call Date`, `agentName`, `caseNumber`, `caseSubject`,
`genesysTransactionId`, `expectedResolutionCode`. Dates are written as
`MM/DD/YYYY` (the `DATE_FORMAT` constant at the top of `automate.py`).

## Usage

Dry run first — it does everything except touch the workbook, and prints which
phone-call row matched and why:

```bash
python automate.py "https://<org>.crm.dynamics.com/main.aspx?...&id=<case-guid>" --dry-run
```

```
========================================================================
DRY RUN — nothing was written to ADHOC.xlsx
========================================================================
Collected from Dynamics:
  owner                = 'Juan Dela Cruz'
  caseNumber           = '5123456789'
  caseSubject          = 'Printer offline after firmware update'
  resolutionCode       = 'Resolved - Technical'
  connId               = 'e1b24457-c74c-427c-83ea-7c79821bfb05'

Matched phone-call row:
  row #2 | direction=Incoming | callFrom=Juan Dela Cruz | start=08/19/2026 9:41 AM | ...
  reason: Direction='Incoming' (inbound), Call From='Juan Dela Cruz' matches owner ...
```

Real run:

```bash
python automate.py "https://<org>.crm.dynamics.com/main.aspx?...&id=<case-guid>"
```

With the case URL in `.env`, the argument can be omitted entirely:

```bash
python automate.py --dry-run
```

### Options

| Flag | Effect |
| ---- | ------ |
| `--dry-run` | Extract and print everything; never open or modify the workbook. |
| `--headed` | Show the browser window. |
| `--slow-mo N` | Delay each action by N ms. |
| `--timeout N` | Override the element wait budget (ms). |
| `--excel-url` / `--storage-state` / `--header-row` | Override the matching `.env` values. |
| `--screenshot-dir DIR` | Save screenshots, including on failure. |
| `--executable-path PATH` | Use an existing browser binary instead of Playwright's. |
| `--log-level DEBUG` | Log every row read from the Phone Calls grid. |

### Exit codes

| Code | Meaning |
| ---- | ------- |
| `0` | Row written, or duplicate skipped, or dry run finished. |
| `1` | Configuration problem (missing URL, missing session file). |
| `2` | No phone-call row satisfied the filters — nothing was written. |
| `3` | A field or page never loaded (timeout). |
| `4` | Browser / Excel-for-the-web error. |

---

## How it stays robust

* **Role, label and text selectors** — `get_by_role`, `get_by_label` and
  `aria-label` first. Dynamics' generated element ids are volatile and are never
  used; `data-id` (derived from the schema name, far more stable) appears only as
  a last-resort fallback.
* **Frame-agnostic lookups.** Customer Service Workspace nests forms in iframes
  and Excel for the web runs in its own; `find_in_frames()` polls every frame, so
  no step depends on knowing the frame layout.
* **Explicit waits everywhere** — each step polls for the element that proves the
  step succeeded, rather than sleeping.
* **Excel via the Name Box and formula bar.** The web grid is canvas-rendered, so
  cells are addressed through the labelled Name Box (`A1` style navigation) and
  read back from the formula bar. Selector lists cover several generations of the
  Excel web chrome.
* **Virtualised grids.** The Phone Calls grid is scrolled until no new rows load
  (bounded at 200 rows).
* **Everything is logged** — each step, each extracted value, each row read and
  the verdict for it, and every skipped or blanked cell.

## Troubleshooting

| Symptom | Fix |
| ------- | --- |
| `the Dynamics case form never became ready` | Session expired — re-run `save_auth.py`. Or the URL points at a record you can't open. |
| `the Excel for the web grid never loaded` | The link opened the desktop app or a sign-in page. Re-run `save_auth.py` and confirm the workbook opens in the browser. |
| `no phone-call row satisfies the required filters` | Working as designed. The log lists every row with its verdict — check the Direction column and whether the call belongs to the case owner. |
| `could not locate the 'resolutionCode' field` | The field is labelled differently in your org; add the label to `CASE_FIELDS` in `automate.py`. |
| A dropdown cell is left blank | No option cleared the `0.72` similarity threshold. The log names the best candidate; fill it in by hand or adjust `DROPDOWN_MATCH_THRESHOLD`. |
| Nothing matches and you want to see why | `--headed --slow-mo 250 --log-level DEBUG`. |
