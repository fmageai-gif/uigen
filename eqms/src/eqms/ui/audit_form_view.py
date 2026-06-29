"""Audit form view: create a new audit or edit an existing one.

Selecting an agent auto-fills EID, TL, OM, Queue, LOB and the TL/OM emails from
the masterlist. Choosing Valid/Invalid swaps the Reason dropdown to the matching
configurable list. Submission runs on a worker thread (it may send an email) and
reports success/failure through a toast.
"""

from __future__ import annotations

import threading
from dataclasses import replace
from typing import Callable

import customtkinter as ctk

from ..core.exceptions import EQMSError
from ..core.logging_config import get_logger
from ..core.models import Audit
from ..services.context import AppContext
from .theme import ThemeManager
from .widgets import AutocompleteEntry, Toast

_log = get_logger(__name__)


class AuditFormView(ctk.CTkFrame):
    """Create/edit audit form bound to :class:`AuditService`."""

    def __init__(
        self,
        master,
        *,
        ctx: AppContext,
        theme: ThemeManager,
        on_saved: Callable[[Audit], None] | None = None,
    ):
        palette = theme.palette
        super().__init__(master, fg_color=palette.surface_alt)
        self.ctx = ctx
        self.theme = theme
        self.palette = palette
        self.on_saved = on_saved
        self._audit = ctx.audit_service.new_blank_audit()
        self._editing = False
        self._readonly_fields: dict[str, ctk.CTkEntry] = {}

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self._toast = Toast(self, palette=palette)

        self._build_header()
        self._build_form()
        self._load_into_form()

    # -- header -------------------------------------------------------------

    def _build_header(self) -> None:
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", padx=20, pady=(16, 4))
        bar.grid_columnconfigure(0, weight=1)
        self._title = ctk.CTkLabel(bar, text="New Audit",
                                   font=ctk.CTkFont(size=22, weight="bold"),
                                   text_color=self.palette.text)
        self._title.grid(row=0, column=0, sticky="w")
        self._id_label = ctk.CTkLabel(bar, text="", text_color=self.palette.text_muted)
        self._id_label.grid(row=0, column=1, sticky="e")

    # -- form body ----------------------------------------------------------

    def _build_form(self) -> None:
        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        scroll.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 12))
        scroll.grid_columnconfigure((0, 1), weight=1, uniform="form")

        card = ctk.CTkFrame(scroll, corner_radius=12, fg_color=self.palette.card,
                            border_width=1, border_color=self.palette.border)
        card.grid(row=0, column=0, columnspan=2, sticky="ew", pady=4)
        card.grid_columnconfigure((1, 3), weight=1)

        r = 0
        # Agent autocomplete (drives the auto-fill).
        self._field_label(card, "Agent *", r, 0)
        self._agent_entry = AutocompleteEntry(
            card, palette=self.palette, placeholder="Type agent name or EID…",
            suggest=self._suggest_agents, on_select=self._on_agent_selected,
        )
        self._agent_entry.grid(row=r, column=1, columnspan=3, sticky="ew",
                               padx=10, pady=8)
        r += 1

        # Auto-filled read-only fields.
        self._readonly_fields["agent_eid"] = self._ro_field(card, "Agent EID", r, 0)
        self._readonly_fields["region"] = self._ro_field(card, "Region", r, 2)
        r += 1
        self._readonly_fields["agent_email"] = self._ro_field(card, "Agent Email", r, 0)
        self._readonly_fields["team_leader"] = self._ro_field(card, "Team Leader", r, 2)
        r += 1
        self._readonly_fields["operations_manager"] = self._ro_field(
            card, "Operations Manager", r, 0)
        self._readonly_fields["lob"] = self._ro_field(card, "LOB", r, 2)
        r += 1
        self._readonly_fields["tl_email"] = self._ro_field(card, "TL Email", r, 0)
        self._readonly_fields["om_email"] = self._ro_field(card, "OM Email", r, 2)
        r += 1

        # Auditor Name (editable; defaults to the signed-in user) + Date.
        self._field_label(card, "Auditor Name *", r, 0)
        self._auditor_entry = ctk.CTkEntry(card, placeholder_text="Auditor name")
        self._auditor_entry.grid(row=r, column=1, sticky="ew", padx=10, pady=8)
        self._field_label(card, "Date", r, 2)
        self._date_entry = ctk.CTkEntry(card)
        self._date_entry.grid(row=r, column=3, sticky="ew", padx=10, pady=8)
        r += 1

        # Case number + Genesys id.
        self._field_label(card, "Case Number *", r, 0)
        self._case_entry = ctk.CTkEntry(card, placeholder_text="Case number")
        self._case_entry.grid(row=r, column=1, sticky="ew", padx=10, pady=8)
        self._field_label(card, "Genesys Transaction ID *", r, 2)
        self._genesys_entry = ctk.CTkEntry(card, placeholder_text="Genesys ID")
        self._genesys_entry.grid(row=r, column=3, sticky="ew", padx=10, pady=8)
        r += 1

        # Validation + reason (cascading).
        self._field_label(card, "Validation *", r, 0)
        self._validation_menu = ctk.CTkOptionMenu(
            card, values=["Valid", "Invalid"], command=self._on_validation_changed,
            fg_color=self.palette.primary, button_color=self.palette.primary_hover,
        )
        self._validation_menu.set("Valid")
        self._validation_menu.grid(row=r, column=1, sticky="ew", padx=10, pady=8)
        self._field_label(card, "Reason *", r, 2)
        self._reason_menu = ctk.CTkOptionMenu(card, values=["—"],
                                              dynamic_resizing=False)
        self._reason_menu.grid(row=r, column=3, sticky="ew", padx=10, pady=8)
        r += 1

        # Remarks (mandatory).
        self._field_label(card, "Remarks *", r, 0)
        self._remarks_box = ctk.CTkTextbox(card, height=90)
        self._remarks_box.grid(row=r, column=1, columnspan=3, sticky="ew",
                               padx=10, pady=8)
        r += 1

        # Actions.
        actions = ctk.CTkFrame(scroll, fg_color="transparent")
        actions.grid(row=1, column=0, columnspan=2, sticky="ew", pady=10)
        actions.grid_columnconfigure(0, weight=1)
        ctk.CTkButton(actions, text="Clear", width=120, fg_color="transparent",
                      border_width=1, border_color=self.palette.border,
                      text_color=self.palette.text,
                      command=self.reset).grid(row=0, column=1, padx=6)
        self._submit_btn = ctk.CTkButton(
            actions, text="Submit Audit", width=160,
            fg_color=self.palette.primary, hover_color=self.palette.primary_hover,
            font=ctk.CTkFont(size=14, weight="bold"), command=self._submit)
        self._submit_btn.grid(row=0, column=2, padx=6)

        self._on_validation_changed("Valid")

    # -- field helpers ------------------------------------------------------

    def _field_label(self, master, text: str, row: int, col: int) -> None:
        ctk.CTkLabel(master, text=text, anchor="w",
                     text_color=self.palette.text_muted,
                     font=ctk.CTkFont(size=12)).grid(
            row=row, column=col, sticky="w", padx=(12, 4), pady=8)

    def _ro_field(self, master, text: str, row: int, col: int) -> ctk.CTkEntry:
        self._field_label(master, text, row, col)
        entry = ctk.CTkEntry(master, state="disabled",
                             fg_color=self.palette.surface_alt)
        entry.grid(row=row, column=col + 1, sticky="ew", padx=10, pady=8)
        return entry

    def _set_ro(self, entry: ctk.CTkEntry, value: str) -> None:
        entry.configure(state="normal")
        entry.delete(0, "end")
        entry.insert(0, value or "")
        entry.configure(state="disabled")

    # -- agent autocomplete -------------------------------------------------

    def _suggest_agents(self, term: str) -> list[tuple[str, object]]:
        return [
            (f"{a.agent_name}  ·  {a.agent_eid}", a)
            for a in self.ctx.masterlist.search(term)
        ]

    def _on_agent_selected(self, label: str, agent) -> None:
        self._audit = self.ctx.audit_service.apply_agent(self._audit, agent.agent_name)
        self._agent_entry.set(agent.agent_name)
        # Read-only field keys match Agent attribute names, so populate generically.
        for key, entry in self._readonly_fields.items():
            self._set_ro(entry, getattr(agent, key, ""))

    # -- validation/reason cascade -----------------------------------------

    def _on_validation_changed(self, value: str) -> None:
        reasons = self.ctx.audit_service.reasons_for(value) or ["—"]
        self._reason_menu.configure(values=reasons)
        self._reason_menu.set(reasons[0])

    # -- load / reset -------------------------------------------------------

    def load_audit(self, audit: Audit) -> None:
        """Switch the form into edit mode for an existing audit."""
        self._audit = audit
        self._editing = True
        self._title.configure(text="Edit Audit")
        self._load_into_form()

    def reset(self) -> None:
        self._audit = self.ctx.audit_service.new_blank_audit()
        self._editing = False
        self._title.configure(text="New Audit")
        self._load_into_form()

    def _load_into_form(self) -> None:
        a = self._audit
        self._id_label.configure(text=f"ID: {a.audit_id}")
        self._agent_entry.set(a.agent)
        for key, entry in self._readonly_fields.items():
            self._set_ro(entry, getattr(a, key, ""))
        self._auditor_entry.delete(0, "end")
        self._auditor_entry.insert(0, a.auditor_name or a.qa_name)
        self._date_entry.delete(0, "end"); self._date_entry.insert(0, a.date)
        self._case_entry.delete(0, "end"); self._case_entry.insert(0, a.case_number)
        self._genesys_entry.delete(0, "end"); self._genesys_entry.insert(0, a.genesys_id)
        if a.validation in ("Valid", "Invalid"):
            self._validation_menu.set(a.validation)
            self._on_validation_changed(a.validation)
            if a.reason:
                self._reason_menu.set(a.reason)
        self._remarks_box.delete("1.0", "end")
        self._remarks_box.insert("1.0", a.remarks)

    # -- collect & submit ---------------------------------------------------

    def _collect(self) -> Audit:
        return replace(
            self._audit,
            agent=self._agent_entry.get().strip(),
            auditor_name=self._auditor_entry.get().strip(),
            date=self._date_entry.get().strip(),
            case_number=self._case_entry.get().strip(),
            genesys_id=self._genesys_entry.get().strip(),
            validation=self._validation_menu.get(),
            reason=self._reason_menu.get(),
            remarks=self._remarks_box.get("1.0", "end").strip(),
        )

    def _submit(self) -> None:
        audit = self._collect()
        self._submit_btn.configure(state="disabled", text="Saving…")
        threading.Thread(target=self._do_submit, args=(audit,), daemon=True).start()

    def _do_submit(self, audit: Audit) -> None:
        try:
            if self._editing:
                saved = self.ctx.audit_service.update(audit)
                detail = "Audit updated."
            else:
                saved, detail = self.ctx.submit_audit(audit)
                detail = "Audit submitted." + (f" {detail}" if detail else "")
            self.after(0, lambda: self._on_success(saved, detail))
        except EQMSError as exc:
            self.after(0, lambda: self._on_error(str(exc)))
        except Exception as exc:  # noqa: BLE001
            _log.exception("Unexpected error saving audit")
            self.after(0, lambda: self._on_error(f"Unexpected error: {exc}"))

    def _on_success(self, saved: Audit, detail: str) -> None:
        self._submit_btn.configure(state="normal", text="Submit Audit")
        self._toast.show(detail, "success")
        if self.on_saved:
            self.on_saved(saved)
        if not self._editing:
            self.reset()

    def _on_error(self, message: str) -> None:
        self._submit_btn.configure(
            state="normal",
            text="Update Audit" if self._editing else "Submit Audit")
        self._toast.show(message, "error", duration=5000)
