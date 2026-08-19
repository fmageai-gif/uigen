#!/usr/bin/env python3
"""Extract a ConnID from a Dynamics 365 case's phone-call record and log a row
into the SharePoint-hosted ADHOC.xlsx workbook (Excel for the web).

Run `python automate.py --help` for usage. See README.md for setup.

Hard requirements enforced by this script:
  * Only *incoming* (inbound) phone-call rows are ever opened or read.
  * Only phone calls belonging to the *case owner* are ever opened or read.
If the intended record cannot be found the script fails loudly and writes
nothing to the spreadsheet.
"""

from __future__ import annotations

import argparse
import asyncio
import difflib
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Callable, Iterable, Sequence

from dotenv import load_dotenv
from playwright.async_api import (
    Error as PlaywrightError,
    TimeoutError as PlaywrightTimeoutError,
    Frame,
    Locator,
    Page,
    async_playwright,
)

# --------------------------------------------------------------------------- #
# Module-level constants
# --------------------------------------------------------------------------- #

#: Every date written to the workbook uses this format.
DATE_FORMAT = "%m/%d/%Y"

#: The subject the target phone-call row is expected to carry, e.g.
#: ``voice - CS_AM_CV_US_HQ_PostSales_CONS_CE_ENG + 18005551234``
SUBJECT_QUEUE_TOKEN = "CS_AM_CV_US_HQ_PostSales_CONS_CE_ENG"
SUBJECT_PATTERN = re.compile(
    r"voice\s*-\s*" + re.escape(SUBJECT_QUEUE_TOKEN) + r"\s*\+?\s*(?P<phone>\+?[\d][\d\s().-]{4,})?",
    re.IGNORECASE,
)

#: Values that count as inbound / outbound in the grid's Direction column.
INBOUND_VALUES = {"incoming", "inbound", "in"}
OUTBOUND_VALUES = {"outgoing", "outbound", "out"}

#: A ConnID / Genesys interaction id looks like a UUID.
UUID_PATTERN = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE
)

#: Case number is a 10-character identifier (digits, possibly dash-separated).
CASE_NUMBER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{4,}$")

#: Minimum similarity before a dropdown suggestion is accepted as "the closest
#: matching option". Below this the cell is left blank for manual review.
DROPDOWN_MATCH_THRESHOLD = 0.72

#: Grid / workbook scanning bounds.
MAX_GRID_ROWS = 200
MAX_HEADER_COLUMNS = 40
MAX_WORKBOOK_SCAN_ROWS = 2000

#: Waits (milliseconds).
DEFAULT_TIMEOUT_MS = 45_000
SHORT_TIMEOUT_MS = 8_000
POLL_INTERVAL_MS = 250
AUTOSAVE_TIMEOUT_MS = 60_000

#: Columns written to ADHOC.xlsx, keyed by the header text in the sheet.
COLUMN_AUDIT_DATE = "auditDate"
COLUMN_CALL_DATE = "Call Date"
COLUMN_AGENT_NAME = "agentName"
COLUMN_CASE_NUMBER = "caseNumber"
COLUMN_CASE_SUBJECT = "caseSubject"
COLUMN_GENESYS_ID = "genesysTransactionId"
COLUMN_RESOLUTION_CODE = "expectedResolutionCode"

#: Header cells that are dropdown / data-validation driven.
VALIDATED_COLUMNS = {COLUMN_AGENT_NAME, COLUMN_RESOLUTION_CODE}

#: Exit codes.
EXIT_OK = 0
EXIT_CONFIG_ERROR = 1
EXIT_NO_MATCH = 2
EXIT_EXTRACT_ERROR = 3
EXIT_EXCEL_ERROR = 4

LOG = logging.getLogger("automate")


# --------------------------------------------------------------------------- #
# Selector vocabularies (role / label / text first, data-id only as fallback)
# --------------------------------------------------------------------------- #

#: Dynamics field label synonyms. ``data_ids`` are last-resort fallbacks: the
#: ``data-id`` attribute is derived from the schema name and is far more stable
#: than the generated element ids, but labels are always tried first.
CASE_FIELDS: dict[str, dict[str, Sequence[str]]] = {
    "owner": {
        "labels": ("Owner", "Owner Name", "Assigned To"),
        "data_ids": ("ownerid.fieldControl-Lookup_ownerid", "ownerid"),
    },
    "caseNumber": {
        "labels": ("Case Number", "Ticket Number"),
        "data_ids": ("ticketnumber",),
    },
    "caseSubject": {
        "labels": ("Case Subject", "Subject", "Case Title", "Title"),
        "data_ids": ("subjectid.fieldControl-Lookup_subjectid", "subjectid", "title"),
    },
    "resolutionCode": {
        "labels": (
            "Case Resolution Code",
            "Resolution Code",
            "Case Resolution",
            "Resolution",
        ),
        "data_ids": ("caseresolutioncode", "resolutioncode", "cnx_resolutioncode"),
    },
}

CONNID_LABELS = ("ConnID", "Conn ID", "Connection ID", "Interaction ID", "Genesys ID")
TENFOLD_SECTION_LABELS = ("Tenfold Call Details", "Tenfold Call Detail", "Tenfold")

#: Excel for the web chrome. Selector lists are tried in order; Microsoft ships
#: several generations of the web grid and the ids differ between them.
EXCEL_NAME_BOX_SELECTORS = (
    "#FormulaBar-NameBox-input",
    'input[aria-label="Name Box"]',
    'input[aria-label*="Name Box" i]',
    "#m_excelWebRenderer_ewaCtl_NameBox",
)
EXCEL_FORMULA_BAR_SELECTORS = (
    "#FormulaBar-Input",
    '[aria-label="formula bar"]',
    '[aria-label*="formula bar" i]',
    "#m_excelWebRenderer_ewaCtl_editableFormulaBar",
)
EXCEL_OPTION_SELECTORS = (
    '[role="listbox"] [role="option"]',
    '[role="menu"] [role="menuitem"]',
    ".ewa-dv-listbox [role='option']",
    "[class*='listbox'] [role='option']",
)


# --------------------------------------------------------------------------- #
# Pure helpers (no browser involved)
# --------------------------------------------------------------------------- #


def normalize(value: str | None) -> str:
    """Collapse whitespace and lowercase, for case-insensitive comparison."""
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip().lower()


def name_tokens(value: str | None) -> frozenset[str]:
    """Tokenise a person's name, dropping punctuation and single initials.

    Lets ``"Dela Cruz, Juan"`` match ``"Juan Dela Cruz"`` without resorting to
    fuzzy matching: the token *sets* have to be identical.
    """
    cleaned = re.sub(r"[^\w\s]", " ", normalize(value))
    return frozenset(tok for tok in cleaned.split() if len(tok) > 1)


def names_match(left: str | None, right: str | None) -> bool:
    """True when two display names refer to the same person.

    Accepts an exact normalized match or an identical token set (handles
    ``Last, First`` vs ``First Last``). Deliberately *not* fuzzy — a partial
    match must never route another agent's call into the audit row.
    """
    if not left or not right:
        return False
    if normalize(left) == normalize(right):
        return True
    left_tokens, right_tokens = name_tokens(left), name_tokens(right)
    return bool(left_tokens) and left_tokens == right_tokens


def classify_direction(value: str | None) -> str:
    """Return ``"inbound"``, ``"outbound"`` or ``"unknown"``."""
    text = normalize(value)
    if not text:
        return "unknown"
    for token in INBOUND_VALUES:
        if token == text or re.search(rf"\b{token}\b", text):
            return "inbound"
    for token in OUTBOUND_VALUES:
        if token == text or re.search(rf"\b{token}\b", text):
            return "outbound"
    return "unknown"


_DATETIME_FORMATS = (
    "%m/%d/%Y %I:%M %p",
    "%m/%d/%Y %H:%M",
    "%m/%d/%Y",
    "%d/%m/%Y %I:%M %p",
    "%d/%m/%Y %H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%b %d, %Y %I:%M %p",
    "%d %b %Y %H:%M",
)


def parse_datetime(value: str | None) -> datetime | None:
    """Best-effort parse of a Dynamics grid date/time string."""
    text = re.sub(r"\s+", " ", (value or "")).strip()
    if not text:
        return None
    for fmt in _DATETIME_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    try:  # e.g. "2026-08-11T13:04:00Z"
        return datetime.fromisoformat(text.replace("Z", "+00:00").replace("T", " ")[:19])
    except ValueError:
        return None


def best_option(target: str, options: Sequence[str]) -> tuple[str | None, float]:
    """Pick the option closest to ``target``; returns ``(option, score)``.

    An exact hit scores 1.0. Reordered words (``Dela Cruz, Juan`` for
    ``Juan Dela Cruz``) and substring hits score just below that, since
    character-level similarity badly underrates both. Everything else falls back
    to difflib.
    """
    if not options:
        return None, 0.0
    wanted = normalize(target)
    wanted_tokens = name_tokens(target)
    scored: list[tuple[float, str]] = []
    for option in options:
        candidate = normalize(option)
        if not candidate:
            continue
        if candidate == wanted:
            return option, 1.0
        score = difflib.SequenceMatcher(None, wanted, candidate).ratio()
        if wanted_tokens and wanted_tokens == name_tokens(option):
            score = max(score, 0.95)
        if wanted and (wanted in candidate or candidate in wanted):
            score = max(score, 0.9)
        scored.append((score, option))
    if not scored:
        return None, 0.0
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return scored[0][1], scored[0][0]


def column_letter(index: int) -> str:
    """1-based column index → spreadsheet column letters (1 → ``A``)."""
    if index < 1:
        raise ValueError(f"column index must be >= 1, got {index}")
    letters = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters


# --------------------------------------------------------------------------- #
# Data holders
# --------------------------------------------------------------------------- #


@dataclass
class CaseData:
    owner: str = ""
    caseNumber: str = ""
    caseSubject: str = ""
    resolutionCode: str = ""
    connId: str = ""

    def as_log_lines(self) -> list[str]:
        return [
            f"owner                = {self.owner!r}",
            f"caseNumber           = {self.caseNumber!r}",
            f"caseSubject          = {self.caseSubject!r}",
            f"resolutionCode       = {self.resolutionCode!r}",
            f"connId               = {self.connId!r}",
        ]


@dataclass
class PhoneCallRow:
    """One row of the Phone Calls sub-grid."""

    index: int
    cells: dict[str, str]
    locator: Locator

    @property
    def subject(self) -> str:
        for key in ("phone activity", "subject", "regarding"):
            value = self.cells.get(key)
            if value:
                return value
        return ""

    @property
    def direction_text(self) -> str:
        return self.cells.get("direction", "")

    @property
    def direction(self) -> str:
        return classify_direction(self.direction_text)

    @property
    def call_from(self) -> str:
        return self.cells.get("call from", "")

    @property
    def start_time_text(self) -> str:
        return self.cells.get("start time", "")

    @property
    def start_time(self) -> datetime | None:
        return parse_datetime(self.start_time_text)

    def describe(self) -> str:
        parts = [
            f"row #{self.index}",
            f"direction={self.direction_text or '?'}",
            f"callFrom={self.call_from or '?'}",
            f"start={self.start_time_text or '?'}",
            f"subject={self.subject[:80] or '?'}",
        ]
        return " | ".join(parts)


@dataclass
class RowVerdict:
    row: PhoneCallRow
    passes_inbound: bool
    passes_owner: bool
    passes_subject: bool

    @property
    def is_candidate(self) -> bool:
        """Only the inbound + owner filters are hard requirements."""
        return self.passes_inbound and self.passes_owner

    def reason(self) -> str:
        failures = []
        if not self.passes_inbound:
            failures.append(
                f"direction is {self.row.direction!r} (need inbound/Incoming)"
            )
        if not self.passes_owner:
            failures.append(
                f"call owner {self.row.call_from!r} is not the case owner"
            )
        if not failures:
            note = "inbound + owner filters passed"
            note += (
                "; subject matches the expected queue pattern"
                if self.passes_subject
                else "; subject does NOT match the expected queue pattern"
            )
            return note
        return "; ".join(failures)


@dataclass
class Settings:
    case_url: str
    excel_url: str
    storage_state: str
    headless: bool = True
    slow_mo: int = 0
    timeout_ms: int = DEFAULT_TIMEOUT_MS
    header_row: int = 1
    dry_run: bool = False
    screenshot_dir: str | None = None
    executable_path: str | None = None
    extra: dict[str, str] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Frame-aware locator helpers
# --------------------------------------------------------------------------- #

LocatorBuilder = Callable[[Frame], Locator]


async def _visible_count(locator: Locator) -> int:
    try:
        return await locator.count()
    except PlaywrightError:
        return 0


async def find_in_frames(
    page: Page,
    builders: Iterable[LocatorBuilder],
    *,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    require_visible: bool = True,
) -> Locator | None:
    """Return the first matching element across every frame of the page.

    Dynamics Customer Service Workspace nests the form in one or more iframes,
    and Excel for the web lives in its own; searching every frame keeps the
    caller free of frame bookkeeping.
    """
    builders = list(builders)
    deadline = time.monotonic() + timeout_ms / 1000
    while True:
        for frame in list(page.frames):
            for build in builders:
                try:
                    locator = build(frame)
                except PlaywrightError:
                    continue
                count = await _visible_count(locator)
                for i in range(min(count, 5)):
                    candidate = locator.nth(i)
                    try:
                        if not require_visible or await candidate.is_visible():
                            return candidate
                    except PlaywrightError:
                        continue
        if time.monotonic() >= deadline:
            return None
        await page.wait_for_timeout(POLL_INTERVAL_MS)


async def element_text(locator: Locator) -> str:
    """Read a value out of an input, contenteditable, link or plain element."""
    try:
        tag = (await locator.evaluate("el => el.tagName.toLowerCase()")) or ""
    except PlaywrightError:
        tag = ""
    try:
        if tag in {"input", "textarea", "select"}:
            value = await locator.input_value()
            if value:
                return value.strip()
        text = (await locator.inner_text()) or ""
        if text.strip():
            return re.sub(r"\s+", " ", text).strip()
        for attribute in ("value", "title", "aria-valuetext", "data-value"):
            attr = await locator.get_attribute(attribute)
            if attr and attr.strip():
                return attr.strip()
        # Lookup / read-only fields sometimes only expose the value nested in a
        # descendant that is itself not the labelled element.
        nested = await locator.evaluate(
            "el => (el.querySelector('input,textarea,a,span,div')?.value)"
            " || (el.querySelector('a,span,div')?.textContent) || ''"
        )
        if nested and nested.strip():
            return re.sub(r"\s+", " ", nested).strip()
    except PlaywrightError:
        pass
    return ""


def field_builders(labels: Sequence[str], data_ids: Sequence[str]) -> list[LocatorBuilder]:
    """Role → label → aria-label → data-id, in decreasing preference."""
    builders: list[LocatorBuilder] = []
    for label in labels:
        pattern = re.compile(rf"^\s*{re.escape(label)}\s*$", re.IGNORECASE)
        loose = re.compile(re.escape(label), re.IGNORECASE)
        builders.extend(
            [
                lambda frame, p=pattern: frame.get_by_role("textbox", name=p),
                lambda frame, p=pattern: frame.get_by_label(p),
                lambda frame, p=pattern: frame.get_by_role("combobox", name=p),
                lambda frame, lbl=label: frame.locator(f'[aria-label="{lbl}" i]'),
                lambda frame, lbl=label: frame.locator(f'[aria-label^="{lbl}" i]'),
                lambda frame, p=loose: frame.get_by_role("link", name=p),
            ]
        )
    for data_id in data_ids:
        builders.append(
            lambda frame, did=data_id: frame.locator(
                f'[data-id="{did}"] input, [data-id="{did}"] a, [data-id="{did}"]'
            )
        )
    return builders


async def read_case_field(
    page: Page, name: str, *, timeout_ms: int, required: bool = True
) -> str:
    spec = CASE_FIELDS[name]
    locator = await find_in_frames(
        page,
        field_builders(spec["labels"], spec["data_ids"]),
        timeout_ms=timeout_ms,
        require_visible=False,
    )
    if locator is None:
        message = f"could not locate the {name!r} field on the case form"
        if required:
            raise LookupError(message)
        LOG.warning("%s", message)
        return ""
    value = await element_text(locator)
    if not value and required:
        raise LookupError(f"the {name!r} field was found but is empty")
    return value


# --------------------------------------------------------------------------- #
# Step 1 — case header
# --------------------------------------------------------------------------- #


async def wait_for_dynamics_ready(page: Page, timeout_ms: int) -> None:
    LOG.info("Waiting for the Dynamics form to finish loading…")
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
    except PlaywrightError:
        pass
    # The form is ready once a labelled case field is addressable in some frame.
    ready = await find_in_frames(
        page,
        [
            lambda frame: frame.get_by_role("tab", name=re.compile("Summary", re.I)),
            lambda frame: frame.locator('[aria-label^="Case Number" i]'),
            lambda frame: frame.locator('[data-id*="ticketnumber"]'),
            lambda frame: frame.get_by_role(
                "link", name=re.compile("Customer Interactions", re.I)
            ),
        ],
        timeout_ms=timeout_ms,
        require_visible=False,
    )
    if ready is None:
        raise TimeoutError(
            "the Dynamics case form never became ready — the saved session may "
            "have expired (re-run save_auth.py) or the URL may be wrong"
        )
    try:
        await page.wait_for_load_state("networkidle", timeout=SHORT_TIMEOUT_MS)
    except PlaywrightError:
        pass
    LOG.info("Dynamics form is ready.")


async def collect_case_header(page: Page, settings: Settings) -> CaseData:
    LOG.info("STEP 1 — reading the case header")
    data = CaseData()

    # Owner first: it is the filter for the phone-call grid.
    data.owner = (await read_case_field(page, "owner", timeout_ms=settings.timeout_ms)).strip()
    LOG.info("owner = %r (normalized: %r)", data.owner, normalize(data.owner))

    data.caseNumber = await read_case_field(
        page, "caseNumber", timeout_ms=SHORT_TIMEOUT_MS
    )
    LOG.info("caseNumber = %r", data.caseNumber)
    if not CASE_NUMBER_PATTERN.match(data.caseNumber.strip()):
        LOG.warning(
            "caseNumber %r does not look like the expected XXXXXXXXXX format",
            data.caseNumber,
        )

    data.caseSubject = await read_case_field(
        page, "caseSubject", timeout_ms=SHORT_TIMEOUT_MS
    )
    LOG.info("caseSubject = %r", data.caseSubject)

    data.resolutionCode = await read_case_field(
        page, "resolutionCode", timeout_ms=SHORT_TIMEOUT_MS, required=False
    )
    LOG.info("resolutionCode = %r", data.resolutionCode)
    if not data.resolutionCode:
        LOG.warning(
            "resolutionCode is empty — the expectedResolutionCode cell will be "
            "left for manual review"
        )
    return data


# --------------------------------------------------------------------------- #
# Step 2 — Customer Interactions tab
# --------------------------------------------------------------------------- #


async def open_customer_interactions(page: Page, settings: Settings) -> None:
    LOG.info("STEP 2 — opening the 'Customer Interactions' tab")
    pattern = re.compile(r"Customer\s+Interactions", re.IGNORECASE)
    tab = await find_in_frames(
        page,
        [
            lambda frame: frame.get_by_role("tab", name=pattern),
            lambda frame: frame.get_by_role("link", name=pattern),
            lambda frame: frame.get_by_role("button", name=pattern),
            lambda frame: frame.locator('[aria-label*="Customer Interactions" i]'),
            lambda frame: frame.get_by_text(pattern),
        ],
        timeout_ms=settings.timeout_ms,
    )
    if tab is None:
        raise LookupError(
            "the 'Customer Interactions' tab was not found in the horizontal "
            "navigation menu"
        )
    await tab.scroll_into_view_if_needed()
    await tab.click()
    LOG.info("Clicked 'Customer Interactions'; waiting for the Phone Calls grid…")
    try:
        await page.wait_for_load_state("networkidle", timeout=SHORT_TIMEOUT_MS)
    except PlaywrightError:
        pass


# --------------------------------------------------------------------------- #
# Step 3 — Phone Calls grid: read, filter, pick
# --------------------------------------------------------------------------- #


async def find_phone_calls_grid(page: Page, timeout_ms: int) -> tuple[Locator, list[str]]:
    """Locate the Phone Calls sub-grid and return it with its header texts."""
    deadline = time.monotonic() + timeout_ms / 1000
    while True:
        for frame in list(page.frames):
            for role in ("grid", "table", "treegrid"):
                try:
                    grids = frame.get_by_role(role)
                    count = await grids.count()
                except PlaywrightError:
                    continue
                for i in range(min(count, 10)):
                    grid = grids.nth(i)
                    try:
                        headers = [
                            re.sub(r"\s+", " ", text).strip()
                            for text in await grid.get_by_role(
                                "columnheader"
                            ).all_inner_texts()
                        ]
                    except PlaywrightError:
                        continue
                    lowered = [normalize(h) for h in headers]
                    has_direction = any("direction" in h for h in lowered)
                    has_call = any(
                        "phone activity" in h or "call from" in h for h in lowered
                    )
                    if has_direction and has_call:
                        LOG.info("Found the Phone Calls grid; headers: %s", headers)
                        return grid, headers
        if time.monotonic() >= deadline:
            raise LookupError(
                "the 'Phone Calls' table (with Direction / Call From columns) was "
                "not found on the Customer Interactions tab"
            )
        await page.wait_for_timeout(POLL_INTERVAL_MS)


async def read_grid_rows(
    page: Page, grid: Locator, headers: Sequence[str]
) -> list[PhoneCallRow]:
    """Read every data row, scrolling to page in virtualised rows."""
    header_keys = [normalize(h) for h in headers]
    seen: dict[str, PhoneCallRow] = {}
    rows: list[PhoneCallRow] = []
    previous_total = -1

    for _ in range(12):  # bounded scroll attempts
        try:
            row_locators = grid.get_by_role("row")
            total = await row_locators.count()
        except PlaywrightError:
            break

        for i in range(min(total, MAX_GRID_ROWS)):
            row = row_locators.nth(i)
            try:
                cell_locator = row.locator('[role="gridcell"], [role="rowheader"], td')
                cell_texts = [
                    re.sub(r"\s+", " ", text).strip()
                    for text in await cell_locator.all_inner_texts()
                ]
            except PlaywrightError:
                continue
            if not cell_texts:
                continue  # header row or a spacer
            # A header row re-read as data: its cells equal the header texts.
            if [normalize(t) for t in cell_texts[: len(header_keys)]] == header_keys:
                continue
            cells: dict[str, str] = {}
            for key, value in zip(header_keys, cell_texts):
                if key:
                    cells[key] = value
            fingerprint = "|".join(cell_texts)
            if fingerprint in seen:
                continue
            entry = PhoneCallRow(index=len(rows) + 1, cells=cells, locator=row)
            seen[fingerprint] = entry
            rows.append(entry)

        if len(rows) == previous_total or len(rows) >= MAX_GRID_ROWS:
            break
        previous_total = len(rows)
        try:  # page in more virtualised rows
            await grid.get_by_role("row").last.scroll_into_view_if_needed(
                timeout=SHORT_TIMEOUT_MS
            )
            await page.wait_for_timeout(POLL_INTERVAL_MS * 2)
        except PlaywrightError:
            break

    LOG.info("Read %d phone-call row(s) from the grid.", len(rows))
    for row in rows:
        LOG.debug("  %s", row.describe())
    return rows


def evaluate_rows(rows: Sequence[PhoneCallRow], owner: str) -> list[RowVerdict]:
    verdicts: list[RowVerdict] = []
    for row in rows:
        inbound = row.direction == "inbound"
        # "Call From" holds the agent on an incoming queue call; some orgs
        # surface the agent in Call To instead, so both are consulted — but only
        # ever compared against the *case owner*, never loosened.
        owner_match = names_match(row.call_from, owner) or names_match(
            row.cells.get("call to"), owner
        )
        subject_match = bool(SUBJECT_PATTERN.search(row.subject or ""))
        verdicts.append(
            RowVerdict(
                row=row,
                passes_inbound=inbound,
                passes_owner=owner_match,
                passes_subject=subject_match,
            )
        )
    return verdicts


def select_target_row(
    verdicts: Sequence[RowVerdict], owner: str
) -> tuple[RowVerdict, str]:
    """Apply the filters strictly and return the single target row.

    Raises ``LookupError`` (never falls back to an outbound call or another
    agent's call) when nothing qualifies.
    """
    LOG.info("STEP 3 — filtering rows: inbound only, then owner %r only", owner)
    for verdict in verdicts:
        LOG.info(
            "  %s → %s",
            verdict.row.describe(),
            "CANDIDATE" if verdict.is_candidate else f"SKIP ({verdict.reason()})",
        )
        if verdict.row.direction == "outbound":
            LOG.debug(
                "    outbound row ignored without inspection, as required: %s",
                verdict.row.describe(),
            )

    candidates = [v for v in verdicts if v.is_candidate]
    if not candidates:
        any_inbound = any(v.passes_inbound for v in verdicts)
        any_owner = any(v.passes_owner for v in verdicts)
        if not any_inbound and not any_owner:
            failed = "both the inbound filter and the owner filter"
        elif not any_inbound:
            failed = "the inbound filter (no row has Direction = Incoming)"
        else:
            failed = f"the owner filter (no incoming row belongs to {owner!r})"
        raise LookupError(
            f"no phone-call row satisfies the required filters: failed {failed}. "
            f"Scanned {len(verdicts)} row(s). Nothing was written to the workbook."
        )

    # The queue-subject pattern narrows further when it is present, but is not
    # a hard requirement on its own.
    subject_matches = [v for v in candidates if v.passes_subject]
    if subject_matches:
        pool, note = subject_matches, "matched the expected queue subject pattern"
    else:
        pool = candidates
        note = "no candidate matched the queue subject pattern, so it was not used"
        LOG.warning(
            "No inbound owner-owned row matched %r; falling back to the inbound "
            "+ owner filters alone.",
            SUBJECT_QUEUE_TOKEN,
        )

    if len(pool) > 1:
        LOG.warning(
            "%d rows satisfy the filters — picking the most recent by Start Time.",
            len(pool),
        )
        pool = sorted(
            pool,
            key=lambda v: (
                v.row.start_time is not None,
                v.row.start_time or datetime.min,
                -v.row.index,
            ),
            reverse=True,
        )
        if pool[0].row.start_time is None:
            LOG.warning(
                "Start Time could not be parsed for the tied rows; falling back "
                "to the grid's own ordering (topmost row)."
            )

    chosen = pool[0]
    reason = (
        f"Direction={chosen.row.direction_text!r} (inbound), "
        f"Call From={chosen.row.call_from!r} matches owner {owner!r}, "
        f"Start Time={chosen.row.start_time_text!r}; {note}"
    )
    LOG.info("Selected %s", chosen.row.describe())
    LOG.info("Selection reason: %s", reason)
    return chosen, reason


async def open_phone_call_record(page: Page, verdict: RowVerdict, timeout_ms: int) -> None:
    LOG.info("Opening the matched phone-call record…")
    row = verdict.row
    opened = False
    try:
        link = row.locator.get_by_role("link").first
        if await link.count():
            await link.scroll_into_view_if_needed()
            await link.click()
            opened = True
    except PlaywrightError:
        opened = False
    if not opened:
        try:
            await row.locator.click()
            await row.locator.press("Enter")
            opened = True
        except PlaywrightError as exc:  # pragma: no cover - environment specific
            raise LookupError(f"could not open the matched phone-call row: {exc}") from exc

    ready = await find_in_frames(
        page,
        [
            lambda frame: frame.get_by_text(
                re.compile(r"Tenfold\s+Call\s+Detail", re.I)
            ),
            lambda frame: frame.locator('[aria-label*="ConnID" i]'),
            lambda frame: frame.get_by_role(
                "tab", name=re.compile(r"General|Summary", re.I)
            ),
        ],
        timeout_ms=timeout_ms,
        require_visible=False,
    )
    if ready is None:
        raise TimeoutError("the phone-call record did not finish loading")
    LOG.info("Phone-call record is open.")


# --------------------------------------------------------------------------- #
# Step 4 — ConnID from the Tenfold Call Details section
# --------------------------------------------------------------------------- #


async def extract_conn_id(page: Page, timeout_ms: int) -> str:
    LOG.info("STEP 4 — extracting ConnID from 'Tenfold Call Details'")

    section = await find_in_frames(
        page,
        [
            lambda frame, lbl=label: frame.get_by_role(
                "tab", name=re.compile(re.escape(lbl), re.I)
            )
            for label in TENFOLD_SECTION_LABELS
        ]
        + [
            lambda frame, lbl=label: frame.get_by_role(
                "button", name=re.compile(re.escape(lbl), re.I)
            )
            for label in TENFOLD_SECTION_LABELS
        ]
        + [
            lambda frame, lbl=label: frame.get_by_text(
                re.compile(re.escape(lbl), re.I)
            )
            for label in TENFOLD_SECTION_LABELS
        ],
        timeout_ms=SHORT_TIMEOUT_MS,
        require_visible=False,
    )
    if section is not None:
        try:
            await section.scroll_into_view_if_needed()
            expanded = await section.get_attribute("aria-expanded")
            role = await section.get_attribute("role")
            if expanded == "false" or role in {"tab", "button"}:
                await section.click()
                LOG.info("Expanded / activated the 'Tenfold Call Details' section.")
            await page.wait_for_timeout(POLL_INTERVAL_MS * 2)
        except PlaywrightError:
            LOG.debug("Could not interact with the Tenfold section header.")
    else:
        LOG.warning(
            "'Tenfold Call Details' section header not found; searching the whole "
            "record for the ConnID field."
        )

    locator = await find_in_frames(
        page,
        field_builders(CONNID_LABELS, ("connid", "conn_id", "tenfold")),
        timeout_ms=timeout_ms,
        require_visible=False,
    )
    conn_id = (await element_text(locator)).strip() if locator is not None else ""

    if not UUID_PATTERN.fullmatch(conn_id):
        match = UUID_PATTERN.search(conn_id)
        if match:
            conn_id = match.group(0)
        else:
            conn_id = await _conn_id_from_page_text(page, conn_id)

    if not conn_id:
        raise LookupError(
            "the ConnID field was not found (or was empty) in the 'Tenfold Call "
            "Details' section"
        )
    LOG.info("connId = %r", conn_id)
    if not UUID_PATTERN.fullmatch(conn_id):
        LOG.warning("connId %r is not a UUID-shaped value — verify manually.", conn_id)
    return conn_id


async def _conn_id_from_page_text(page: Page, current: str) -> str:
    """Fallback: scrape a UUID out of the record's text near a ConnID label."""
    for frame in list(page.frames):
        try:
            text = await frame.locator("body").inner_text(timeout=SHORT_TIMEOUT_MS)
        except PlaywrightError:
            continue
        for label in CONNID_LABELS:
            match = re.search(
                re.escape(label) + r"[^\w]{0,40}(" + UUID_PATTERN.pattern + ")",
                text,
                re.IGNORECASE | re.DOTALL,
            )
            if match:
                LOG.info("Recovered ConnID from the record text near %r.", label)
                return match.group(1)
    return current


# --------------------------------------------------------------------------- #
# Steps 5-7 — Excel for the web
# --------------------------------------------------------------------------- #


class ExcelWebSheet:
    """Thin driver over Excel for the web's grid.

    Cell access goes through the Name Box (navigate) and the formula bar
    (read), which are stable, labelled controls — unlike the canvas-rendered
    grid itself.
    """

    def __init__(self, page: Page, frame: Frame, header_row: int) -> None:
        self.page = page
        self.frame = frame
        self.header_row = header_row
        self._name_box_selector: str | None = None
        self._formula_bar_selector: str | None = None

    # -- infrastructure ---------------------------------------------------- #

    @classmethod
    async def open(cls, page: Page, settings: Settings) -> "ExcelWebSheet":
        LOG.info("STEP 5 — opening the SharePoint workbook (Excel for the web)")
        await page.goto(settings.excel_url, wait_until="domcontentloaded",
                        timeout=settings.timeout_ms)
        LOG.info("STEP 6 — waiting for the Excel web grid iframe…")
        frame = await cls._wait_for_grid_frame(page, settings.timeout_ms)
        sheet = cls(page, frame, settings.header_row)
        await sheet._resolve_controls()
        await sheet._ensure_editing()
        LOG.info("Excel web grid is ready (frame url: %s).", frame.url[:120])
        return sheet

    @staticmethod
    async def _wait_for_grid_frame(page: Page, timeout_ms: int) -> Frame:
        deadline = time.monotonic() + timeout_ms / 1000
        while True:
            for frame in list(page.frames):
                for selector in EXCEL_NAME_BOX_SELECTORS:
                    try:
                        if await frame.locator(selector).count():
                            return frame
                    except PlaywrightError:
                        continue
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    "the Excel for the web grid never loaded — the workbook may "
                    "be opening in the desktop app, or the saved session may have "
                    "expired for SharePoint (re-run save_auth.py)"
                )
            await page.wait_for_timeout(POLL_INTERVAL_MS * 2)

    async def _resolve_controls(self) -> None:
        for selector in EXCEL_NAME_BOX_SELECTORS:
            if await self.frame.locator(selector).count():
                self._name_box_selector = selector
                break
        for selector in EXCEL_FORMULA_BAR_SELECTORS:
            if await self.frame.locator(selector).count():
                self._formula_bar_selector = selector
                break
        if not self._name_box_selector:
            raise TimeoutError("Excel's Name Box control was not found")
        if not self._formula_bar_selector:
            LOG.warning(
                "Excel's formula bar was not found; cell reads will fall back to "
                "the active cell's accessible name."
            )

    async def _ensure_editing(self) -> None:
        """Switch out of view-only mode when the workbook opens read-only."""
        for scope in (self.page, self.frame):
            try:
                banner = scope.get_by_text(re.compile(r"View.?only", re.I))
                if not await banner.count():
                    continue
            except PlaywrightError:
                continue
            for name in (r"^Editing$", r"Edit in browser", r"^Edit$", r"Enable Editing"):
                try:
                    button = scope.get_by_role("button", name=re.compile(name, re.I))
                    if await button.count() and await button.first.is_visible():
                        await button.first.click()
                        LOG.info("Switched the workbook into editing mode.")
                        await self.page.wait_for_timeout(POLL_INTERVAL_MS * 4)
                        return
                except PlaywrightError:
                    continue

    # -- primitive cell operations ----------------------------------------- #

    async def goto_cell(self, reference: str) -> None:
        name_box = self.frame.locator(self._name_box_selector).first
        await name_box.click()
        await name_box.fill(reference)
        await name_box.press("Enter")
        await self.page.wait_for_timeout(POLL_INTERVAL_MS)

    async def read_cell(self, reference: str) -> str:
        await self.goto_cell(reference)
        if self._formula_bar_selector:
            bar = self.frame.locator(self._formula_bar_selector).first
            try:
                tag = await bar.evaluate("el => el.tagName.toLowerCase()")
                value = (
                    await bar.input_value()
                    if tag in {"input", "textarea"}
                    else await bar.inner_text()
                )
                return re.sub(r"\s+", " ", value or "").strip()
            except PlaywrightError:
                pass
        try:  # fallback: the active cell exposes its content as its a11y name
            active = self.frame.locator('[aria-selected="true"], [class*="cell-active"]').first
            return re.sub(r"\s+", " ", (await active.inner_text()) or "").strip()
        except PlaywrightError:
            return ""

    async def write_cell(self, reference: str, value: str) -> None:
        await self.goto_cell(reference)
        await self.page.keyboard.type(value, delay=25)
        await self.page.keyboard.press("Enter")
        await self.page.wait_for_timeout(POLL_INTERVAL_MS)

    # -- structure --------------------------------------------------------- #

    async def read_headers(self) -> dict[str, int]:
        """Map header text → 1-based column index (resilient to reordering)."""
        headers: dict[str, int] = {}
        blanks = 0
        for index in range(1, MAX_HEADER_COLUMNS + 1):
            reference = f"{column_letter(index)}{self.header_row}"
            text = await self.read_cell(reference)
            if not text:
                blanks += 1
                if blanks >= 3:  # tolerate a gap, stop at the end of the table
                    break
                continue
            blanks = 0
            headers[text] = index
            LOG.debug("  header %s = %r", reference, text)
        LOG.info("Workbook headers: %s", headers)
        return headers

    async def last_used_row(self) -> int:
        """Row number of the last used cell (via Ctrl+End)."""
        await self.goto_cell(f"A{self.header_row}")
        await self.page.keyboard.press("Control+End")
        await self.page.wait_for_timeout(POLL_INTERVAL_MS * 2)
        name_box = self.frame.locator(self._name_box_selector).first
        try:
            reference = await name_box.input_value()
        except PlaywrightError:
            reference = ""
        match = re.search(r"([A-Z]+)(\d+)", (reference or "").upper())
        row = int(match.group(2)) if match else self.header_row
        LOG.info("Last used row according to Ctrl+End: %d (name box: %r)", row, reference)
        return max(row, self.header_row)

    async def column_values(self, column: int, first_row: int, last_row: int) -> list[str]:
        letter = column_letter(column)
        values: list[str] = []
        for row in range(first_row, min(last_row, first_row + MAX_WORKBOOK_SCAN_ROWS) + 1):
            values.append(await self.read_cell(f"{letter}{row}"))
        return values

    async def first_empty_row(self, headers: dict[str, int]) -> int:
        """First row with no value in any of the columns we populate."""
        last = await self.last_used_row()
        key_columns = [
            headers[name]
            for name in (COLUMN_GENESYS_ID, COLUMN_CASE_NUMBER, COLUMN_AUDIT_DATE)
            if name in headers
        ] or [1]
        for row in range(self.header_row + 1, last + 2):
            empty = True
            for col in key_columns:
                if await self.read_cell(f"{column_letter(col)}{row}"):
                    empty = False
                    break
            if empty:
                LOG.info("First empty row: %d", row)
                return row
        row = last + 1
        LOG.info("First empty row (after the last used row): %d", row)
        return row

    # -- dropdown / validated cells ---------------------------------------- #

    async def _collect_options(self) -> list[tuple[str, Locator]]:
        options: list[tuple[str, Locator]] = []
        for selector in EXCEL_OPTION_SELECTORS:
            try:
                locator = self.frame.locator(selector)
                count = await locator.count()
            except PlaywrightError:
                continue
            for i in range(min(count, 200)):
                item = locator.nth(i)
                try:
                    if not await item.is_visible():
                        continue
                    text = re.sub(r"\s+", " ", (await item.inner_text()) or "").strip()
                except PlaywrightError:
                    continue
                if text:
                    options.append((text, item))
            if options:
                break
        return options

    async def write_validated_cell(
        self, reference: str, value: str, label: str, *, is_name: bool = False
    ) -> bool:
        """Type into a dropdown-backed cell and select the closest option.

        Returns ``True`` when a value was committed. When nothing matches well
        enough the cell is left empty for manual review and ``False`` is
        returned.

        ``is_name`` switches to exact / token-set matching: fuzzy similarity
        rates ``Juana Dela Cruz`` a 0.97 match for ``Juan Dela Cruz``, which
        would log the wrong agent.
        """
        if not value:
            LOG.warning("%s: no source value to write — left blank for manual review.", label)
            return False

        await self.goto_cell(reference)
        # Open the data-validation list first: it enumerates the allowed values.
        await self.page.keyboard.press("Alt+ArrowDown")
        await self.page.wait_for_timeout(POLL_INTERVAL_MS * 2)
        options = await self._collect_options()

        if not options:  # no validation list: try type-ahead autocomplete
            await self.page.keyboard.type(value, delay=40)
            await self.page.wait_for_timeout(POLL_INTERVAL_MS * 3)
            options = await self._collect_options()

        if options:
            texts = [text for text, _ in options]
            LOG.debug("%s: %d suggestion(s): %s", label, len(texts), texts[:20])
            if is_name:
                exact = [text for text in texts if names_match(text, value)]
                choice, score = (exact[0], 1.0) if exact else (None, 0.0)
                if not exact:
                    near, near_score = best_option(value, texts)
                    LOG.warning(
                        "%s: no option is the same person as %r (closest: %r, "
                        "similarity %.2f) — names are matched exactly, never "
                        "fuzzily.",
                        label, value, near, near_score,
                    )
            else:
                choice, score = best_option(value, texts)
            if choice and score >= DROPDOWN_MATCH_THRESHOLD:
                item = next(loc for text, loc in options if text == choice)
                await item.click()
                await self.page.wait_for_timeout(POLL_INTERVAL_MS)
                await self.page.keyboard.press("Enter")
                LOG.info(
                    "%s: selected %r for %r (similarity %.2f).", label, choice, value, score
                )
                return True
            if is_name:
                LOG.warning("%s: leaving %s blank for manual review.", label, reference)
            else:
                LOG.warning(
                    "%s: no reasonable match for %r (best: %r, similarity %.2f, "
                    "threshold %.2f) — leaving %s blank for manual review.",
                    label, value, choice, score, DROPDOWN_MATCH_THRESHOLD, reference,
                )
            await self.page.keyboard.press("Escape")
            await self.goto_cell(reference)
            await self.page.keyboard.press("Delete")
            return False

        LOG.warning(
            "%s: no suggestion list appeared; writing %r as plain text.", label, value
        )
        await self.page.keyboard.press("Escape")
        await self.write_cell(reference, value)
        return True

    # -- autosave ---------------------------------------------------------- #

    async def wait_for_autosave(self) -> bool:
        LOG.info("STEP 7 — waiting for Excel for the web to autosave…")
        deadline = time.monotonic() + AUTOSAVE_TIMEOUT_MS / 1000
        saved_pattern = re.compile(r"\bSaved\b|AutoSave is on|All changes saved", re.I)
        pending_pattern = re.compile(r"Saving|Uploading|Working on it", re.I)
        while time.monotonic() < deadline:
            for scope in (self.frame, self.page):
                try:
                    if await scope.get_by_text(saved_pattern).count():
                        pending = await scope.get_by_text(pending_pattern).count()
                        if not pending:
                            LOG.info("Excel reports the workbook is saved.")
                            return True
                except PlaywrightError:
                    continue
            await self.page.wait_for_timeout(POLL_INTERVAL_MS * 4)
        LOG.warning(
            "Did not observe an explicit 'Saved' indicator within %ds — verify the "
            "workbook manually.",
            AUTOSAVE_TIMEOUT_MS // 1000,
        )
        return False


async def write_row(sheet: ExcelWebSheet, data: CaseData) -> None:
    headers = await sheet.read_headers()
    if not headers:
        raise LookupError("no header row could be read from the workbook")

    today = date.today().strftime(DATE_FORMAT)
    values = {
        COLUMN_AUDIT_DATE: today,
        COLUMN_CALL_DATE: today,
        COLUMN_AGENT_NAME: data.owner,
        COLUMN_CASE_NUMBER: data.caseNumber,
        COLUMN_CASE_SUBJECT: data.caseSubject,
        COLUMN_GENESYS_ID: data.connId,
        COLUMN_RESOLUTION_CODE: data.resolutionCode,
    }

    resolved: dict[str, int] = {}
    for name in values:
        choice, score = best_option(name, list(headers))
        if choice and score >= 0.9:
            resolved[name] = headers[choice]
            if normalize(choice) != normalize(name):
                LOG.info("Header %r resolved to workbook column %r.", name, choice)
        else:
            LOG.warning(
                "Column %r is not present in the workbook header row — that value "
                "will not be written.",
                name,
            )

    # Duplicate guard.
    if COLUMN_GENESYS_ID in resolved:
        last = await sheet.last_used_row()
        existing = await sheet.column_values(
            resolved[COLUMN_GENESYS_ID], sheet.header_row + 1, last
        )
        if any(normalize(value) == normalize(data.connId) for value in existing):
            LOG.warning(
                "genesysTransactionId %r already exists in the workbook — skipping "
                "the write to avoid a duplicate row.",
                data.connId,
            )
            return
        LOG.info(
            "No existing row carries genesysTransactionId %r (checked %d row(s)).",
            data.connId,
            len(existing),
        )
    else:
        LOG.warning(
            "Cannot run the duplicate check: the %r column is missing.",
            COLUMN_GENESYS_ID,
        )

    target_row = await sheet.first_empty_row(headers)
    LOG.info("Writing the audit row into row %d.", target_row)

    manual_review: list[str] = []
    for name, value in values.items():
        if name not in resolved:
            continue
        reference = f"{column_letter(resolved[name])}{target_row}"
        if name in VALIDATED_COLUMNS:
            ok = await sheet.write_validated_cell(
                reference, value, name, is_name=(name == COLUMN_AGENT_NAME)
            )
            if not ok:
                manual_review.append(f"{name} ({reference})")
            continue
        if not value:
            LOG.warning("%s: empty value — leaving %s blank.", name, reference)
            manual_review.append(f"{name} ({reference})")
            continue
        await sheet.write_cell(reference, value)
        LOG.info("Wrote %s = %r to %s", name, value, reference)

    await sheet.wait_for_autosave()
    if manual_review:
        LOG.warning("Cells left for manual review: %s", ", ".join(manual_review))
    LOG.info("Row %d complete.", target_row)


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #


async def screenshot(page: Page, settings: Settings, name: str) -> None:
    if not settings.screenshot_dir:
        return
    os.makedirs(settings.screenshot_dir, exist_ok=True)
    path = os.path.join(
        settings.screenshot_dir, f"{datetime.now():%Y%m%d-%H%M%S}-{name}.png"
    )
    try:
        await page.screenshot(path=path, full_page=True)
        LOG.info("Saved screenshot: %s", path)
    except PlaywrightError as exc:  # pragma: no cover
        LOG.debug("Screenshot failed: %s", exc)


async def run(settings: Settings) -> int:
    async with async_playwright() as playwright:
        launch_args: dict[str, object] = {
            "headless": settings.headless,
            "slow_mo": settings.slow_mo,
        }
        if settings.executable_path:
            # Managed machines often cannot download Playwright's own build.
            launch_args["executable_path"] = settings.executable_path
            LOG.info("Using the browser at %s", settings.executable_path)
        browser = await playwright.chromium.launch(**launch_args)
        context = await browser.new_context(
            storage_state=settings.storage_state,
            viewport={"width": 1600, "height": 1000},
        )
        context.set_default_timeout(settings.timeout_ms)
        page = await context.new_page()
        data = CaseData()
        try:
            LOG.info("Opening the Dynamics case: %s", settings.case_url)
            await page.goto(
                settings.case_url, wait_until="domcontentloaded",
                timeout=settings.timeout_ms,
            )
            await wait_for_dynamics_ready(page, settings.timeout_ms)

            data = await collect_case_header(page, settings)
            await open_customer_interactions(page, settings)

            grid, headers = await find_phone_calls_grid(page, settings.timeout_ms)
            rows = await read_grid_rows(page, grid, headers)
            if not rows:
                raise LookupError(
                    "the Phone Calls table is empty — nothing was written to the "
                    "workbook"
                )
            verdicts = evaluate_rows(rows, data.owner)
            chosen, reason = select_target_row(verdicts, data.owner)

            await open_phone_call_record(page, chosen, settings.timeout_ms)
            data.connId = await extract_conn_id(page, settings.timeout_ms)

            LOG.info("Collected values:")
            for line in data.as_log_lines():
                LOG.info("  %s", line)
            LOG.info("Matched phone-call row: %s", chosen.row.describe())
            LOG.info("Why it matched: %s", reason)

            if settings.dry_run:
                print_dry_run(data, chosen, reason)
                LOG.info("--dry-run: the workbook was not opened or modified.")
                return EXIT_OK

            sheet = await ExcelWebSheet.open(page, settings)
            await write_row(sheet, data)
            await screenshot(page, settings, "workbook")
            return EXIT_OK

        except LookupError as exc:
            LOG.error("%s", exc)
            await screenshot(page, settings, "lookup-error")
            return EXIT_NO_MATCH
        except (TimeoutError, PlaywrightTimeoutError) as exc:
            LOG.error("Timed out: %s", exc)
            await screenshot(page, settings, "timeout")
            return EXIT_EXTRACT_ERROR
        except PlaywrightError as exc:
            LOG.error("Browser error: %s", exc)
            await screenshot(page, settings, "browser-error")
            return EXIT_EXCEL_ERROR
        finally:
            await context.close()
            await browser.close()


def print_dry_run(data: CaseData, chosen: RowVerdict, reason: str) -> None:
    today = date.today().strftime(DATE_FORMAT)
    lines = [
        "",
        "=" * 72,
        "DRY RUN — nothing was written to ADHOC.xlsx",
        "=" * 72,
        "Collected from Dynamics:",
        *(f"  {line}" for line in data.as_log_lines()),
        "",
        "Matched phone-call row:",
        f"  {chosen.row.describe()}",
        f"  reason: {reason}",
        "",
        "Would write:",
        f"  {COLUMN_AUDIT_DATE:<24}= {today}",
        f"  {COLUMN_CALL_DATE:<24}= {today}",
        f"  {COLUMN_AGENT_NAME:<24}= {data.owner}   (dropdown)",
        f"  {COLUMN_CASE_NUMBER:<24}= {data.caseNumber}",
        f"  {COLUMN_CASE_SUBJECT:<24}= {data.caseSubject}",
        f"  {COLUMN_GENESYS_ID:<24}= {data.connId}",
        f"  {COLUMN_RESOLUTION_CODE:<24}= {data.resolutionCode}   (dropdown)",
        "=" * 72,
        "",
    ]
    print("\n".join(lines))


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Extract a ConnID from a Dynamics 365 case's incoming phone-call "
            "record and log an audit row into ADHOC.xlsx on SharePoint."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "case_url",
        nargs="?",
        help="Dynamics 365 case record URL (falls back to DYNAMICS_CASE_URL in .env)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="extract and print everything, but do not touch the workbook",
    )
    parser.add_argument("--excel-url", help="override EXCEL_WORKBOOK_URL")
    parser.add_argument("--storage-state", help="override PLAYWRIGHT_STORAGE_STATE")
    parser.add_argument(
        "--headed",
        action="store_true",
        help="run with a visible browser window (useful for debugging)",
    )
    parser.add_argument("--slow-mo", type=int, help="delay each action by N ms")
    parser.add_argument("--timeout", type=int, help="default timeout in ms")
    parser.add_argument(
        "--header-row", type=int, help="1-based row number of the workbook header row"
    )
    parser.add_argument("--screenshot-dir", help="save screenshots here")
    parser.add_argument(
        "--executable-path",
        help="path to an existing Chromium/Chrome binary (overrides "
        "PLAYWRIGHT_EXECUTABLE_PATH)",
    )
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        help="logging verbosity",
    )
    return parser


def env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    try:
        return int(raw) if raw else default
    except ValueError:
        LOG.warning("%s=%r is not an integer; using %d.", name, raw, default)
        return default


def load_settings(argv: Sequence[str] | None = None) -> Settings:
    args = build_parser().parse_args(argv)
    load_dotenv()

    logging.basicConfig(
        level=args.log_level or os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s  %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )

    case_url = args.case_url or os.getenv("DYNAMICS_CASE_URL", "")
    excel_url = args.excel_url or os.getenv("EXCEL_WORKBOOK_URL", "")
    storage_state = args.storage_state or os.getenv("PLAYWRIGHT_STORAGE_STATE", "")

    missing = [
        name
        for name, value in (
            ("case_url / DYNAMICS_CASE_URL", case_url),
            ("EXCEL_WORKBOOK_URL", excel_url),
            ("PLAYWRIGHT_STORAGE_STATE", storage_state),
        )
        if not value
    ]
    if missing:
        raise SystemExit(
            "Missing configuration: "
            + ", ".join(missing)
            + ".\nCopy .env.example to .env and fill it in (see README.md)."
        )
    if not os.path.exists(storage_state):
        raise SystemExit(
            f"Auth session file not found: {storage_state}\n"
            "Run `python save_auth.py` first to sign in once and save the session."
        )

    headless = not args.headed and env_flag("HEADLESS", True)
    return Settings(
        case_url=case_url,
        excel_url=excel_url,
        storage_state=storage_state,
        headless=headless,
        slow_mo=args.slow_mo if args.slow_mo is not None else env_int("SLOW_MO", 0),
        timeout_ms=args.timeout or env_int("DEFAULT_TIMEOUT_MS", DEFAULT_TIMEOUT_MS),
        header_row=args.header_row or env_int("EXCEL_HEADER_ROW", 1),
        dry_run=args.dry_run,
        screenshot_dir=args.screenshot_dir or os.getenv("SCREENSHOT_DIR") or None,
        executable_path=(
            args.executable_path or os.getenv("PLAYWRIGHT_EXECUTABLE_PATH") or None
        ),
    )


def main(argv: Sequence[str] | None = None) -> int:
    try:
        settings = load_settings(argv)
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        return EXIT_CONFIG_ERROR
    LOG.info(
        "Configuration: headless=%s dry_run=%s timeout=%dms storage_state=%s",
        settings.headless, settings.dry_run, settings.timeout_ms, settings.storage_state,
    )
    return asyncio.run(run(settings))


if __name__ == "__main__":
    sys.exit(main())
