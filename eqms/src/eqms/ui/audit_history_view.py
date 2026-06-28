"""Audit history view: search, filter and drill into past audits.

QA users may edit only their own audits (enforced by the service layer and
reflected here by enabling/disabling the Edit action). The admin may also
archive audits, gated behind the configured archive/delete password.
"""

from __future__ import annotations

import threading
from typing import Callable

import customtkinter as ctk

from ..core.exceptions import EQMSError
from ..core.logging_config import get_logger
from ..core.models import Audit
from ..core.utils import truncate
from ..services.context import AppContext
from .theme import ThemeManager
from .widgets import Toast

_log = get_logger(__name__)


class AuditHistoryView(ctk.CTkFrame):
    """Searchable, filterable list of audits with drill-down detail."""

    def __init__(self, master, *, ctx: AppContext, theme: ThemeManager,
                 on_edit: Callable[[Audit], None] | None = None):
        palette = theme.palette
        super().__init__(master, fg_color=palette.surface_alt)
        self.ctx = ctx
        self.theme = theme
        self.palette = palette
        self.on_edit = on_edit
        self._audits: list[Audit] = []
        self._toast = Toast(self, palette=palette)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        self._build_header()
        self._build_filters()
        self._build_list()
        self.refresh_async()

    def _build_header(self) -> None:
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", padx=20, pady=(16, 4))
        bar.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(bar, text="Audit History",
                     font=ctk.CTkFont(size=22, weight="bold"),
                     text_color=self.palette.text).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(bar, text="⟳ Refresh", width=90,
                      fg_color=self.palette.primary,
                      hover_color=self.palette.primary_hover,
                      command=self.refresh_async).grid(row=0, column=1, sticky="e")

    def _build_filters(self) -> None:
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=1, column=0, sticky="ew", padx=20, pady=4)
        bar.grid_columnconfigure(0, weight=1)
        self._search_var = ctk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._render())
        ctk.CTkEntry(bar, textvariable=self._search_var,
                     placeholder_text="Search by ID, agent, case, reason…",
                     width=320).grid(row=0, column=0, sticky="w")
        self._validation_filter = ctk.CTkOptionMenu(
            bar, values=["All", "Valid", "Invalid"],
            command=lambda *_: self._render(), width=120,
            fg_color=self.palette.primary, button_color=self.palette.primary_hover)
        self._validation_filter.grid(row=0, column=1, padx=8)
        self._mine_var = ctk.BooleanVar(value=False)
        ctk.CTkSwitch(bar, text="My audits only", variable=self._mine_var,
                      command=self._render).grid(row=0, column=2, padx=8)

    def _build_list(self) -> None:
        self._list = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self._list.grid(row=2, column=0, sticky="nsew", padx=20, pady=(4, 16))
        self._list.grid_columnconfigure(0, weight=1)

    # -- data ---------------------------------------------------------------

    def refresh_async(self) -> None:
        threading.Thread(target=self._load, daemon=True).start()

    def _load(self) -> None:
        try:
            audits = self.ctx.audits.all(refresh=True)
        except Exception as exc:  # noqa: BLE001
            audits = self.ctx.audits.all()
            _log.warning("History load fell back to cache: %s", exc)
        self.after(0, lambda: self._apply(audits))

    def _apply(self, audits) -> None:
        self._audits = audits
        self._render()

    def _render(self) -> None:
        for child in self._list.winfo_children():
            child.destroy()
        query = self._search_var.get().strip().lower()
        vfilter = self._validation_filter.get()
        mine = self._mine_var.get()
        me = self.ctx.session.user.email.lower()

        rows = sorted(self._audits, key=lambda a: a.created_at, reverse=True)
        shown = 0
        for a in rows:
            if mine and a.qa_email.lower() != me:
                continue
            if vfilter != "All" and a.validation.lower() != vfilter.lower():
                continue
            if query and query not in (
                f"{a.audit_id} {a.agent} {a.agent_eid} {a.case_number} "
                f"{a.genesys_id} {a.qa_name} {a.reason} {a.remarks}".lower()
            ):
                continue
            self._row(a)
            shown += 1
        if shown == 0:
            ctk.CTkLabel(self._list, text="No audits match your filters.",
                         text_color=self.palette.text_muted).grid(pady=24)

    def _row(self, a: Audit) -> None:
        card = ctk.CTkFrame(self._list, corner_radius=10, fg_color=self.palette.card,
                            border_width=1, border_color=self.palette.border)
        card.grid(sticky="ew", pady=4)
        card.grid_columnconfigure(1, weight=1)

        badge_color = self.palette.danger if a.is_invalid else self.palette.success
        ctk.CTkLabel(card, text=a.validation or "—", width=70, corner_radius=6,
                     fg_color=badge_color, text_color="#FFFFFF",
                     font=ctk.CTkFont(size=11, weight="bold")).grid(
            row=0, column=0, rowspan=2, padx=10, pady=10)

        ctk.CTkLabel(card, text=f"{a.audit_id}  ·  {a.agent}  ({a.agent_eid})",
                     anchor="w", font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=self.palette.text).grid(
            row=0, column=1, sticky="w", pady=(8, 0))
        ctk.CTkLabel(
            card, anchor="w", text_color=self.palette.text_muted,
            font=ctk.CTkFont(size=11),
            text=(f"QA: {a.qa_name}  ·  Case: {a.case_number}  ·  "
                  f"Reason: {truncate(a.reason, 36)}  ·  {a.date}"),
        ).grid(row=1, column=1, sticky="w", pady=(0, 8))

        can_edit = self.ctx.session.can_edit_audit(a.qa_email)
        edit_btn = ctk.CTkButton(
            card, text="Edit", width=70, state="normal" if can_edit else "disabled",
            fg_color=self.palette.primary, hover_color=self.palette.primary_hover,
            command=lambda x=a: self.on_edit and self.on_edit(x))
        edit_btn.grid(row=0, column=2, rowspan=2, padx=(4, 6))

        if self.ctx.session.is_admin:
            ctk.CTkButton(card, text="Archive", width=80,
                          fg_color=self.palette.warning, hover_color="#C97A00",
                          command=lambda x=a: self._archive(x)).grid(
                row=0, column=3, rowspan=2, padx=(0, 10))

    # -- archive (admin) ----------------------------------------------------

    def _archive(self, audit: Audit) -> None:
        dialog = ctk.CTkInputDialog(
            text=f"Enter archive password to archive {audit.audit_id}:",
            title="Confirm Archive")
        password = dialog.get_input()
        if password is None:
            return
        try:
            self.ctx.audit_service.archive_audit(audit.audit_id, password=password)
            self._toast.show(f"Archived {audit.audit_id}", "success")
            self.refresh_async()
        except EQMSError as exc:
            self._toast.show(str(exc), "error", duration=5000)
