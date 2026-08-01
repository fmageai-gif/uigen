#!/usr/bin/env python3
"""Copy daily audit rows from ADHOC.xlsx into the Focus Audit SharePoint list.

Typical use on Windows:

    inspect.bat          once, to capture the form's fields and dropdown options
    run.bat --dry-run    fills one entry and stops before Save so you can check it
    run.bat              does the real thing

The browser profile lives in .browser-profile/ next to this script, so you sign
in to SharePoint once and stay signed in on later runs.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.utils import column_index_from_string
from playwright.sync_api import Page, TimeoutError as PWTimeout, sync_playwright

HERE = Path(__file__).resolve().parent
CONFIG_PATH = HERE / "config.json"
PROFILE_DIR = HERE / ".browser-profile"
SUBMITTED_LOG = HERE / "submitted.json"
SCHEMA_OUT = HERE / "form_schema.json"
RUN_LOG = HERE / "last_run.log"

# Form field label -> how we fill it. Labels must match the SharePoint form exactly.
TEXT_FIELDS = ("CaseID", "Call/Chat ID", "Case Subject", "What are the Opportunities", "Comments/Summary")
CHOICE_FIELDS = ("LOB", "Call/Chat Selection Criteria", "Suggested Resolution Code", "Validation")
DATE_FIELDS = ("Call Listening Date", "Call/Chat Date")
PERSON_FIELD = "Agent Name"

# Only these two markers are validity tags. Parentheses in expectedResolutionCode
# (e.g. "Subscription Cancellation (SubCan)") are part of the real code name and
# must never be stripped.
VALIDITY_SUFFIX = re.compile(r"\s*\((?:Pass|Invalid)\)\s*$", re.IGNORECASE)


# --------------------------------------------------------------------------- #
# Config + logging
# --------------------------------------------------------------------------- #

def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        sys.exit(f"Missing {CONFIG_PATH.name} - it must sit next to transfer.py")
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


_log_lines: list[str] = []


def log(msg: str) -> None:
    print(msg, flush=True)
    _log_lines.append(f"{datetime.now():%H:%M:%S}  {msg}")


def flush_log() -> None:
    RUN_LOG.write_text("\n".join(_log_lines), encoding="utf-8")


# --------------------------------------------------------------------------- #
# Excel
# --------------------------------------------------------------------------- #

@dataclass
class Row:
    excel_row: int
    audit_id: str = ""
    audit_date: str = ""
    call_date: str = ""
    agent_name: str = ""
    agent_email: str = ""
    lob: str = ""
    case_number: str = ""
    case_subject: str = ""
    genesys_id: str = ""
    validation: str = ""
    case_resolution: str = ""
    expected_resolution: str = ""
    remarks: str = ""
    auditor_name: str = ""
    quick_case: str = ""

    @property
    def is_invalid(self) -> bool:
        return self.validation.strip().lower() == "invalid"

    @property
    def suggested_resolution_code(self) -> str:
        """Invalid audits take the tagged code (col R); valid ones take the expected code (col S).

        The trailing "(Invalid)" / "(Pass)" marker is dropped, because it labels the
        audit outcome rather than forming part of the resolution code itself.
        """
        source = self.case_resolution if self.is_invalid else self.expected_resolution
        return VALIDITY_SUFFIX.sub("", source).strip()


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return f"{value.month}/{value.day}/{value.year}"
    if isinstance(value, date):
        return f"{value.month}/{value.day}/{value.year}"
    return str(value).strip()


def _as_date(text: str) -> date | None:
    text = text.strip()
    if not text:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def read_rows(cfg: dict[str, Any], xlsx: Path) -> list[Row]:
    wb = load_workbook(xlsx, data_only=True, read_only=True)
    sheet = cfg["sheet_name"]
    if sheet not in wb.sheetnames:
        sys.exit(f"Sheet '{sheet}' not found. Sheets present: {', '.join(wb.sheetnames)}")
    ws = wb[sheet]

    idx = {name: column_index_from_string(letter) - 1 for name, letter in cfg["columns"].items()}
    widest = max(idx.values()) + 1

    rows: list[Row] = []
    for n, values in enumerate(ws.iter_rows(min_row=cfg["header_row"] + 1, values_only=True),
                               start=cfg["header_row"] + 1):
        if values is None or all(v is None or str(v).strip() == "" for v in values):
            continue
        padded = list(values) + [None] * (widest - len(values))
        row = Row(excel_row=n, **{name: _cell_text(padded[i]) for name, i in idx.items()})
        if row.audit_id or row.case_number:
            rows.append(row)
    wb.close()
    return rows


def select_rows(cfg: dict[str, Any], rows: list[Row], args: argparse.Namespace) -> list[Row]:
    """Narrow to this auditor's rows, within the requested dates, minus anything already sent."""
    auditor = cfg["auditor_name"].strip().lower()
    picked = [r for r in rows if r.auditor_name.strip().lower() == auditor]
    log(f"{len(picked)} of {len(rows)} rows belong to {cfg['auditor_name']}")

    if args.date:
        target = _as_date(args.date) or date.fromisoformat(args.date)
        picked = [r for r in picked if _as_date(r.audit_date) == target]
        log(f"{len(picked)} with auditDate {target:%m/%d/%Y}")
    elif not args.all:
        cutoff = date.today().toordinal() - args.last_days
        picked = [r for r in picked
                  if (d := _as_date(r.audit_date)) and d.toordinal() >= cutoff]
        log(f"{len(picked)} within the last {args.last_days} days")

    if not args.force:
        done = set(load_submitted())
        before = len(picked)
        picked = [r for r in picked if r.audit_id not in done]
        if before != len(picked):
            log(f"{before - len(picked)} already submitted on an earlier run - skipping")

    return picked[: args.limit] if args.limit else picked


def load_submitted() -> list[str]:
    if not SUBMITTED_LOG.exists():
        return []
    try:
        return json.loads(SUBMITTED_LOG.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []


def mark_submitted(audit_id: str) -> None:
    done = load_submitted()
    if audit_id and audit_id not in done:
        done.append(audit_id)
        SUBMITTED_LOG.write_text(json.dumps(done, indent=2), encoding="utf-8")


# --------------------------------------------------------------------------- #
# SharePoint form
# --------------------------------------------------------------------------- #

class FormError(RuntimeError):
    pass


@dataclass
class Form:
    """Thin wrapper over the modern SharePoint 'New item' panel."""

    page: Page
    choice_map: dict[str, dict[str, str]] = field(default_factory=dict)

    # -- locating ---------------------------------------------------------- #

    def _control(self, label: str, roles: tuple[str, ...]):
        """Find a control by its field label, trying the ways SharePoint exposes it."""
        for role in roles:
            candidate = self.page.get_by_role(role, name=label, exact=False)
            if candidate.count():
                return candidate.first
        candidate = self.page.get_by_label(label, exact=False)
        if candidate.count():
            return candidate.first
        # Fall back to the input nearest the visible label text.
        xpath = (
            f"xpath=//*[normalize-space(text())={label!r}]"
            f"/ancestor::*[self::div][1]//*[self::input or self::textarea or @role='combobox']"
        )
        candidate = self.page.locator(xpath)
        if candidate.count():
            return candidate.first
        raise FormError(f"Could not find the '{label}' field on the form")

    # -- filling ----------------------------------------------------------- #

    def set_text(self, label: str, value: str) -> None:
        control = self._control(label, ("textbox",))
        control.click()
        control.fill(value)

    def set_date(self, label: str, value: str, time_of_day: str) -> None:
        control = self._control(label, ("textbox", "combobox"))
        control.click()
        control.fill(value)
        control.press("Enter")
        self._set_time_beside(label, time_of_day)

    def _set_time_beside(self, label: str, time_of_day: str) -> None:
        """Date fields with time enabled render a separate time dropdown next to the date box."""
        combos = self.page.get_by_role("combobox", name=re.compile("time", re.IGNORECASE))
        if not combos.count():
            return
        combo = combos.first
        try:
            combo.click()
            option = self.page.get_by_role("option", name=time_of_day, exact=False)
            if option.count():
                option.first.click()
                log(f"    {label}: time set to {time_of_day}")
            else:
                combo.press("Escape")
                log(f"    ! '{time_of_day}' not offered for {label} - left as-is")
        except PWTimeout:
            log(f"    ! timed out setting the time for {label}")

    def set_person(self, label: str, email: str) -> None:
        control = self._control(label, ("textbox", "combobox", "searchbox"))
        control.click()
        control.fill(email)
        # The picker needs a moment to resolve the address against the directory.
        suggestion = self.page.locator("[role='listbox'] [role='option'], .ms-Suggestions-item")
        try:
            suggestion.first.wait_for(state="visible", timeout=12_000)
            suggestion.first.click()
            log(f"    {label}: matched {email}")
        except PWTimeout:
            raise FormError(f"No directory match appeared for {email}")

    def set_choice(self, label: str, value: str, interactive: bool) -> None:
        wanted = self.choice_map.get(label, {}).get(value, value).strip()
        control = self._control(label, ("combobox", "button"))
        control.click()

        options = self.page.get_by_role("option")
        try:
            options.first.wait_for(state="visible", timeout=8_000)
        except PWTimeout:
            raise FormError(f"The '{label}' dropdown did not open")

        texts = [t.strip() for t in options.all_inner_texts()]
        match = _best_option(wanted, texts)
        if match is None:
            control.press("Escape")
            self._resolve_manually(label, value, wanted, texts, interactive)
            return

        options.nth(texts.index(match)).click()
        if match != wanted:
            log(f"    {label}: '{value}' -> '{match}'")

    def _resolve_manually(self, label: str, excel_value: str, wanted: str,
                          options: list[str], interactive: bool) -> None:
        log(f"    ! No '{label}' option matches Excel value '{excel_value}'")
        log(f"      Available: {', '.join(options) or '(none found)'}")
        if not interactive:
            raise FormError(f"Unmatched {label} value '{excel_value}'")
        log(f"      Pick the right option in the browser yourself, then press Enter here.")
        input("      Press Enter once you've set it... ")
        log(f"      Tip: add \"{wanted}\": \"<the option you picked>\" under "
            f"choice_map -> {label} in config.json so it's automatic next time.")

    # -- submitting -------------------------------------------------------- #

    def save(self) -> None:
        self.page.get_by_role("button", name="Save", exact=True).click()
        self.page.wait_for_timeout(2500)


def _best_option(wanted: str, options: list[str]) -> str | None:
    """Exact, then case-insensitive, then unambiguous prefix match."""
    if wanted in options:
        return wanted
    lowered = wanted.lower()
    for opt in options:
        if opt.lower() == lowered:
            return opt
    starts = [o for o in options if o.lower().startswith(lowered[:25])]
    return starts[0] if len(starts) == 1 else None


def open_new_item(page: Page, cfg: dict[str, Any]) -> Form:
    page.goto(cfg["list_url"], wait_until="domcontentloaded")
    page.get_by_role("button", name=cfg["new_item_button"], exact=False).first.click()
    page.get_by_text("New item", exact=False).first.wait_for(state="visible", timeout=20_000)
    return Form(page=page, choice_map=cfg.get("choice_map", {}))


def fill_row(form: Form, row: Row, cfg: dict[str, Any], interactive: bool) -> None:
    time_of_day = cfg.get("time_of_day", "12:00 AM")
    form.set_choice("LOB", row.lob, interactive)
    form.set_date("Call Listening Date", row.audit_date, time_of_day)
    form.set_person(PERSON_FIELD, row.agent_email)
    form.set_choice("Call/Chat Selection Criteria", row.expected_resolution, interactive)
    form.set_choice("Suggested Resolution Code", row.suggested_resolution_code, interactive)
    form.set_date("Call/Chat Date", row.call_date, time_of_day)
    form.set_text("CaseID", row.case_number)
    form.set_text("Call/Chat ID", row.genesys_id)
    form.set_text("Case Subject", row.case_subject)
    form.set_text("What are the Opportunities", cfg.get("opportunities_text", "N/A"))
    form.set_text("Comments/Summary", row.remarks)
    form.set_choice("Validation", row.validation, interactive)


# --------------------------------------------------------------------------- #
# Inspect mode
# --------------------------------------------------------------------------- #

def inspect_form(page: Page, cfg: dict[str, Any]) -> None:
    """Dump every field and every dropdown option so the mapping can be finalised."""
    open_new_item(page, cfg)
    schema: dict[str, Any] = {"captured_at": datetime.now().isoformat(), "fields": []}

    controls = page.locator("input, textarea, [role='combobox'], [role='button'][aria-haspopup]")
    for i in range(controls.count()):
        el = controls.nth(i)
        try:
            schema["fields"].append({
                "tag": el.evaluate("e => e.tagName.toLowerCase()"),
                "role": el.get_attribute("role"),
                "type": el.get_attribute("type"),
                "aria_label": el.get_attribute("aria-label"),
                "placeholder": el.get_attribute("placeholder"),
                "id": el.get_attribute("id"),
                "class": (el.get_attribute("class") or "")[:120],
            })
        except Exception as exc:  # a control can detach while the panel settles
            schema["fields"].append({"error": str(exc)})

    schema["choices"] = {}
    for label in CHOICE_FIELDS:
        try:
            form = Form(page=page)
            control = form._control(label, ("combobox", "button"))
            control.click()
            page.get_by_role("option").first.wait_for(state="visible", timeout=8_000)
            schema["choices"][label] = [t.strip() for t in page.get_by_role("option").all_inner_texts()]
            control.press("Escape")
            log(f"  {label}: {len(schema['choices'][label])} options")
        except Exception as exc:
            schema["choices"][label] = {"error": str(exc)}
            log(f"  ! {label}: {exc}")

    SCHEMA_OUT.write_text(json.dumps(schema, indent=2), encoding="utf-8")
    log(f"\nWrote {SCHEMA_OUT.name} - send this file back to finish the mapping.")


# --------------------------------------------------------------------------- #
# Excel retrieval
# --------------------------------------------------------------------------- #

def resolve_workbook(cfg: dict[str, Any], page: Page | None) -> Path:
    configured = cfg.get("excel_path", "").strip()
    if configured:
        path = Path(configured)
        if not path.exists():
            sys.exit(f"excel_path points at {path}, which does not exist")
        log(f"Reading {path}")
        return path

    if page is None:
        sys.exit("excel_path is empty and no browser is available to download the workbook")

    log("excel_path is empty - downloading the workbook from SharePoint")
    target = HERE / "ADHOC.xlsx"
    with page.expect_download(timeout=120_000) as dl:
        page.goto(cfg["excel_download_url"])
    dl.value.save_as(target)
    log(f"Downloaded to {target}")
    return target


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Transfer audit rows into the Focus Audit list.")
    p.add_argument("--inspect", action="store_true",
                   help="capture the form's fields and dropdown options, then exit")
    p.add_argument("--dry-run", action="store_true",
                   help="fill the first row but stop before saving")
    p.add_argument("--date", help="only rows whose auditDate matches (e.g. 08/01/2026)")
    p.add_argument("--last-days", type=int, default=7,
                   help="how far back to look when --date is not given (default 7)")
    p.add_argument("--all", action="store_true", help="ignore the date window entirely")
    p.add_argument("--limit", type=int, help="stop after this many rows")
    p.add_argument("--force", action="store_true",
                   help="include rows already recorded as submitted")
    p.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    cfg = load_config()
    PROFILE_DIR.mkdir(exist_ok=True)

    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            channel="msedge",
            args=["--start-maximized"],
            no_viewport=True,
            accept_downloads=True,
        )
        page = context.pages[0] if context.pages else context.new_page()

        try:
            if args.inspect:
                log("Inspecting the Focus Audit form...")
                inspect_form(page, cfg)
                return 0

            workbook = resolve_workbook(cfg, page)
            rows = select_rows(cfg, read_rows(cfg, workbook), args)

            if not rows:
                log("Nothing to submit.")
                return 0

            log(f"\n{len(rows)} row(s) queued:")
            for r in rows:
                log(f"  {r.audit_id}  {r.audit_date}  {r.case_number}  "
                    f"{r.agent_email}  [{r.validation}]")

            if args.dry_run:
                rows = rows[:1]
                log("\nDry run - filling one entry and stopping before Save.")
            elif not args.yes:
                if input("\nProceed? [y/N] ").strip().lower() not in ("y", "yes"):
                    log("Cancelled.")
                    return 0

            ok = failed = 0
            for n, row in enumerate(rows, 1):
                log(f"\n[{n}/{len(rows)}] {row.audit_id} (Excel row {row.excel_row})")
                try:
                    form = open_new_item(page, cfg)
                    fill_row(form, row, cfg, interactive=True)
                    if args.dry_run:
                        log("  Filled. Check every field, then close the panel yourself.")
                        input("  Press Enter to finish the dry run... ")
                    else:
                        form.save()
                        mark_submitted(row.audit_id)
                        log("  Saved.")
                    ok += 1
                except (FormError, PWTimeout) as exc:
                    failed += 1
                    log(f"  FAILED: {exc}")
                    if input("  Continue with the next row? [Y/n] ").strip().lower() in ("n", "no"):
                        break

            log(f"\nDone. {ok} succeeded, {failed} failed.")
            return 1 if failed else 0
        finally:
            flush_log()
            context.close()


if __name__ == "__main__":
    sys.exit(main())
