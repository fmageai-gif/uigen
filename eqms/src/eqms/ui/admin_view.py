"""Admin Center: runtime configuration of (almost) every aspect of the app.

Accessible only to the Super Administrator (the view is not mounted for QA
users; the service layer enforces the gate independently). Every change is
written to ``Settings.xlsx`` and recorded in the system audit trail — nothing
here requires a code change or rebuild.

Tabs mirror the admin capabilities in the specification: General, Branding &
Theme, Audit Reasons, Validation Rules, Dashboard Widgets, Email Recipients,
SharePoint, Backups & Updates, Masterlist, Logs, Archive/Restore and Export.
"""

from __future__ import annotations

import threading
from tkinter import filedialog

import customtkinter as ctk

from ..core.exceptions import EQMSError
from ..core.logging_config import get_logger
from ..services.context import AppContext
from .theme import ThemeManager
from .widgets import Toast

_log = get_logger(__name__)


class AdminView(ctk.CTkFrame):
    """Tabbed administration console."""

    def __init__(self, master, *, ctx: AppContext, theme: ThemeManager):
        palette = theme.palette
        super().__init__(master, fg_color=palette.surface_alt)
        self.ctx = ctx
        self.theme = theme
        self.palette = palette
        self.settings = ctx.settings
        self._toast = Toast(self, palette=palette)
        self._scalar_vars: dict[str, ctk.StringVar] = {}

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(self, text="Admin Center",
                     font=ctk.CTkFont(size=22, weight="bold"),
                     text_color=palette.text).grid(
            row=0, column=0, sticky="w", padx=20, pady=(16, 8))

        self.tabs = ctk.CTkTabview(self, fg_color=palette.card,
                                   segmented_button_selected_color=palette.primary)
        self.tabs.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 16))

        for name in ("General", "Branding & Theme", "Audit Reasons",
                     "Validation", "Widgets", "Email", "SharePoint",
                     "Backups & Updates", "Masterlist", "Logs",
                     "Archive", "Export"):
            self.tabs.add(name)

        self._build_general(self.tabs.tab("General"))
        self._build_branding(self.tabs.tab("Branding & Theme"))
        self._build_reasons(self.tabs.tab("Audit Reasons"))
        self._build_validation(self.tabs.tab("Validation"))
        self._build_widgets(self.tabs.tab("Widgets"))
        self._build_email(self.tabs.tab("Email"))
        self._build_sharepoint(self.tabs.tab("SharePoint"))
        self._build_backups_updates(self.tabs.tab("Backups & Updates"))
        self._build_masterlist(self.tabs.tab("Masterlist"))
        self._build_logs(self.tabs.tab("Logs"))
        self._build_archive(self.tabs.tab("Archive"))
        self._build_export(self.tabs.tab("Export"))

    # -- reusable builders --------------------------------------------------

    def _scalar_row(self, master, label: str, key: str, row: int, *,
                    secret: bool = False, hint: str = "") -> None:
        ctk.CTkLabel(master, text=label, anchor="w",
                     text_color=self.palette.text).grid(
            row=row, column=0, sticky="w", padx=10, pady=6)
        var = ctk.StringVar(value=self.settings.get(key, ""))
        self._scalar_vars[key] = var
        entry = ctk.CTkEntry(master, textvariable=var, width=320,
                             show="•" if secret else "")
        entry.grid(row=row, column=1, sticky="w", padx=10, pady=6)
        if hint:
            ctk.CTkLabel(master, text=hint, text_color=self.palette.text_muted,
                         font=ctk.CTkFont(size=10)).grid(
                row=row, column=2, sticky="w", padx=6)

    def _bool_row(self, master, label: str, key: str, row: int) -> None:
        var = ctk.StringVar(value="true" if self.settings.get_bool(key) else "false")
        self._scalar_vars[key] = var
        ctk.CTkLabel(master, text=label, anchor="w",
                     text_color=self.palette.text).grid(
            row=row, column=0, sticky="w", padx=10, pady=6)
        switch = ctk.CTkSwitch(
            master, text="", variable=var, onvalue="true", offvalue="false")
        switch.grid(row=row, column=1, sticky="w", padx=10, pady=6)

    def _save_button(self, master, row: int, keys: list[str],
                     after=None) -> None:
        def _save():
            updates = {k: self._scalar_vars[k].get() for k in keys
                       if k in self._scalar_vars}
            try:
                self.settings.set_many(updates)
                self.ctx.logs.record("SETTINGS_UPDATED",
                                     user=self.ctx.session.user.email,
                                     details=", ".join(updates))
                self._toast.show("Settings saved", "success")
                if after:
                    after()
            except EQMSError as exc:
                self._toast.show(str(exc), "error")

        ctk.CTkButton(master, text="Save", width=120, fg_color=self.palette.primary,
                      hover_color=self.palette.primary_hover, command=_save).grid(
            row=row, column=0, sticky="w", padx=10, pady=12)

    # -- tabs ---------------------------------------------------------------

    def _build_general(self, tab) -> None:
        self._scalar_row(tab, "Organisation", "app.organisation", 0)
        self._scalar_row(tab, "App title", "app.title", 1)
        self._scalar_row(tab, "App subtitle", "app.subtitle", 2)
        self._scalar_row(tab, "Sync interval (s)", "sync.interval_seconds", 3)
        self._bool_row(tab, "Automatic sync", "sync.auto", 4)
        self._save_button(tab, 5, ["app.organisation", "app.title", "app.subtitle",
                                   "sync.interval_seconds", "sync.auto"])

    def _build_branding(self, tab) -> None:
        self._scalar_row(tab, "Primary colour", "app.primary_color", 0,
                         hint="#0F4C81")
        self._scalar_row(tab, "Accent colour", "app.accent_color", 1, hint="#1C7ED6")
        ctk.CTkLabel(tab, text="Appearance mode", text_color=self.palette.text).grid(
            row=2, column=0, sticky="w", padx=10, pady=6)
        self._mode_menu = ctk.CTkOptionMenu(
            tab, values=["System", "Light", "Dark"],
            command=lambda m: self.theme.set_mode(m),
            fg_color=self.palette.primary, button_color=self.palette.primary_hover)
        self._mode_menu.set(self.settings.get("theme.mode", "System"))
        self._mode_menu.grid(row=2, column=1, sticky="w", padx=10, pady=6)

        def after():
            self.settings.set("theme.mode", self._mode_menu.get())
            self.theme.refresh_palette()
            self._toast.show("Branding saved — restart to fully apply", "info")

        self._save_button(tab, 3, ["app.primary_color", "app.accent_color"], after)

    def _build_reasons(self, tab) -> None:
        tab.grid_columnconfigure((0, 1), weight=1)
        self._valid_box = self._reason_editor(
            tab, "Valid Reasons", self.settings.get_valid_reasons(), 0)
        self._invalid_box = self._reason_editor(
            tab, "Invalid Reasons", self.settings.get_invalid_reasons(), 1)

        def save():
            valid = [l for l in self._valid_box.get("1.0", "end").splitlines() if l.strip()]
            invalid = [l for l in self._invalid_box.get("1.0", "end").splitlines() if l.strip()]
            self.settings.set_valid_reasons(valid)
            self.settings.set_invalid_reasons(invalid)
            self.ctx.logs.record("REASONS_UPDATED", user=self.ctx.session.user.email,
                                 details=f"valid={len(valid)} invalid={len(invalid)}")
            self._toast.show("Reasons saved", "success")

        ctk.CTkButton(tab, text="Save Reasons", fg_color=self.palette.primary,
                      hover_color=self.palette.primary_hover, command=save).grid(
            row=2, column=0, sticky="w", padx=10, pady=12)

    def _reason_editor(self, master, title: str, items: list[str], col: int):
        ctk.CTkLabel(master, text=f"{title} (one per line)",
                     font=ctk.CTkFont(weight="bold"),
                     text_color=self.palette.text).grid(
            row=0, column=col, sticky="w", padx=10, pady=(6, 2))
        box = ctk.CTkTextbox(master, height=320)
        box.grid(row=1, column=col, sticky="nsew", padx=10, pady=6)
        box.insert("1.0", "\n".join(items))
        return box

    def _build_validation(self, tab) -> None:
        self._bool_row(tab, "Remarks mandatory", "validation.remarks_required", 0)
        self._bool_row(tab, "Unique Case + Genesys ID",
                       "validation.unique_case_genesys", 1)
        self._bool_row(tab, "Block duplicate submissions",
                       "validation.block_duplicate_submissions", 2)
        self._bool_row(tab, "Agent must be in masterlist",
                       "validation.require_agent_from_masterlist", 3)
        self._save_button(tab, 4, [
            "validation.remarks_required", "validation.unique_case_genesys",
            "validation.block_duplicate_submissions",
            "validation.require_agent_from_masterlist"])

    def _build_widgets(self, tab) -> None:
        ctk.CTkLabel(tab, text="Enable/disable dashboard KPI cards",
                     font=ctk.CTkFont(weight="bold"),
                     text_color=self.palette.text).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=10, pady=8)
        self._widget_vars: dict[str, ctk.StringVar] = {}
        widgets = self.settings.get_widgets()
        for i, w in enumerate(widgets):
            key = w.get("Key", "")
            var = ctk.StringVar(
                value="true" if str(w.get("Enabled", "true")).lower()
                in ("1", "true", "yes") else "false")
            self._widget_vars[key] = var
            ctk.CTkSwitch(tab, text=w.get("Label", key), variable=var,
                          onvalue="true", offvalue="false").grid(
                row=1 + i // 2, column=i % 2, sticky="w", padx=14, pady=4)

        def save():
            updated = [{"Key": w.get("Key", ""), "Label": w.get("Label", ""),
                        "Enabled": self._widget_vars[w.get("Key", "")].get()}
                       for w in widgets]
            self.settings.set_widgets(updated)
            self._toast.show("Widgets saved — reopen dashboard to apply", "success")

        ctk.CTkButton(tab, text="Save Widgets", fg_color=self.palette.primary,
                      hover_color=self.palette.primary_hover, command=save).grid(
            row=2 + len(widgets) // 2, column=0, sticky="w", padx=10, pady=12)

    def _build_email(self, tab) -> None:
        self._bool_row(tab, "Email automation enabled", "email.enabled", 0)
        self._bool_row(tab, "Send only on Invalid", "email.send_on_invalid_only", 1)
        self._scalar_row(tab, "Subject template", "email.subject_template", 2,
                         hint="{audit_id} {agent}")
        ctk.CTkLabel(tab, text="QA distribution list (comma/newline separated)",
                     text_color=self.palette.text).grid(
            row=3, column=0, sticky="w", padx=10, pady=(10, 2))
        self._dist_box = ctk.CTkTextbox(tab, height=120, width=420)
        self._dist_box.grid(row=4, column=0, columnspan=2, sticky="w", padx=10, pady=6)
        self._dist_box.insert("1.0", self.settings.get("email.qa_distribution_list", ""))

        def save():
            updates = {
                "email.enabled": self._scalar_vars["email.enabled"].get(),
                "email.send_on_invalid_only":
                    self._scalar_vars["email.send_on_invalid_only"].get(),
                "email.subject_template":
                    self._scalar_vars["email.subject_template"].get(),
                "email.qa_distribution_list":
                    self._dist_box.get("1.0", "end").strip(),
            }
            self.settings.set_many(updates)
            self._toast.show("Email settings saved", "success")

        ctk.CTkButton(tab, text="Save", fg_color=self.palette.primary,
                      hover_color=self.palette.primary_hover, command=save).grid(
            row=5, column=0, sticky="w", padx=10, pady=12)

    def _build_sharepoint(self, tab) -> None:
        self._bool_row(tab, "Use SharePoint storage", "sharepoint.enabled", 0)
        self._scalar_row(tab, "Site URL", "sharepoint.site_url", 1,
                         hint="https://org.sharepoint.com/sites/QA")
        self._scalar_row(tab, "Folder path", "sharepoint.folder_path", 2,
                         hint="Shared Documents/EQMS")
        ctk.CTkLabel(
            tab, text="Changes take effect after sign-out / restart.",
            text_color=self.palette.text_muted,
            font=ctk.CTkFont(size=11)).grid(row=3, column=0, columnspan=2,
                                            sticky="w", padx=10, pady=6)
        self._save_button(tab, 4, ["sharepoint.enabled", "sharepoint.site_url",
                                   "sharepoint.folder_path"])

    def _build_backups_updates(self, tab) -> None:
        self._bool_row(tab, "Automatic backups", "backup.enabled", 0)
        self._scalar_row(tab, "Backup interval (hours)", "backup.interval_hours", 1)
        self._scalar_row(tab, "Backups to retain", "backup.retention", 2)
        self._bool_row(tab, "Automatic monthly report", "report.auto_monthly", 3)
        self._scalar_row(tab, "Report day of month", "report.day_of_month", 4)
        self._bool_row(tab, "Automatic update check", "update.auto_check", 5)
        self._scalar_row(tab, "Update manifest URL", "update.manifest_url", 6)
        self._scalar_row(tab, "Archive/delete password", "security.archive_password",
                         7, secret=True)
        self._save_button(tab, 8, [
            "backup.enabled", "backup.interval_hours", "backup.retention",
            "report.auto_monthly", "report.day_of_month", "update.auto_check",
            "update.manifest_url", "security.archive_password"])
        ctk.CTkButton(tab, text="Back up now", fg_color=self.palette.accent,
                      command=self._backup_now).grid(
            row=8, column=1, sticky="w", padx=10, pady=12)

    def _backup_now(self) -> None:
        def run():
            try:
                res = self.ctx.backup_service.backup_now(
                    user=self.ctx.session.user.email)
                self.after(0, lambda: self._toast.show(
                    f"Backed up {len(res.files)} workbooks", "success"))
            except Exception as exc:  # noqa: BLE001
                self.after(0, lambda: self._toast.show(f"Backup failed: {exc}",
                                                       "error"))
        threading.Thread(target=run, daemon=True).start()

    def _build_masterlist(self, tab) -> None:
        ctk.CTkLabel(tab, text="Upload or replace Masterlist.xlsx",
                     font=ctk.CTkFont(weight="bold"),
                     text_color=self.palette.text).grid(
            row=0, column=0, sticky="w", padx=10, pady=(10, 4))
        self._ml_status = ctk.CTkLabel(
            tab, text=f"Current agents: {self.ctx.masterlist.count()}",
            text_color=self.palette.text_muted)
        self._ml_status.grid(row=1, column=0, sticky="w", padx=10, pady=4)
        ctk.CTkButton(tab, text="Choose .xlsx and import…",
                      fg_color=self.palette.primary,
                      hover_color=self.palette.primary_hover,
                      command=self._upload_masterlist).grid(
            row=2, column=0, sticky="w", padx=10, pady=10)

    def _upload_masterlist(self) -> None:
        path = filedialog.askopenfilename(
            title="Select Masterlist.xlsx",
            filetypes=[("Excel workbook", "*.xlsx")])
        if not path:
            return

        def run():
            try:
                count = self.ctx.masterlist.replace_from_file(path)
                self.ctx.logs.record("MASTERLIST_UPLOADED",
                                     user=self.ctx.session.user.email,
                                     details=f"{count} agents")
                self.after(0, lambda: self._ml_status.configure(
                    text=f"Current agents: {count}"))
                self.after(0, lambda: self._toast.show(
                    f"Imported {count} agents", "success"))
            except Exception as exc:  # noqa: BLE001
                self.after(0, lambda: self._toast.show(
                    f"Import failed: {exc}", "error", duration=5000))
        threading.Thread(target=run, daemon=True).start()

    def _build_logs(self, tab) -> None:
        tab.grid_rowconfigure(1, weight=1)
        tab.grid_columnconfigure(0, weight=1)
        bar = ctk.CTkFrame(tab, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", padx=6, pady=6)
        bar.grid_columnconfigure(0, weight=1)
        ctk.CTkButton(bar, text="⟳ Refresh", width=90, fg_color=self.palette.primary,
                      command=self._refresh_logs).grid(row=0, column=1, padx=4)
        ctk.CTkButton(bar, text="Clear logs", width=90, fg_color=self.palette.danger,
                      command=self._clear_logs).grid(row=0, column=2, padx=4)
        self._logs_box = ctk.CTkTextbox(tab, font=ctk.CTkFont(family="Consolas",
                                                              size=11))
        self._logs_box.grid(row=1, column=0, sticky="nsew", padx=6, pady=6)
        self._refresh_logs()

    def _refresh_logs(self) -> None:
        def run():
            entries = self.ctx.logs.all(limit=500)
            text = "\n".join(
                f"{e.timestamp} | {e.level:<7} | {e.user} | {e.action} | {e.details}"
                for e in entries) or "No log entries."
            self.after(0, lambda: self._set_logs(text))
        threading.Thread(target=run, daemon=True).start()

    def _set_logs(self, text: str) -> None:
        self._logs_box.delete("1.0", "end")
        self._logs_box.insert("1.0", text)

    def _clear_logs(self) -> None:
        self.ctx.logs.clear()
        self.ctx.logs.record("LOGS_CLEARED", user=self.ctx.session.user.email)
        self._refresh_logs()
        self._toast.show("Logs cleared", "warning")

    def _build_archive(self, tab) -> None:
        tab.grid_rowconfigure(1, weight=1)
        tab.grid_columnconfigure(0, weight=1)
        ctk.CTkButton(tab, text="⟳ Refresh archive", width=140,
                      fg_color=self.palette.primary, command=self._refresh_archive).grid(
            row=0, column=0, sticky="w", padx=10, pady=8)
        self._archive_list = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        self._archive_list.grid(row=1, column=0, sticky="nsew", padx=10, pady=6)
        self._archive_list.grid_columnconfigure(0, weight=1)
        self._refresh_archive()

    def _refresh_archive(self) -> None:
        def run():
            items = self.ctx.archive.all()
            self.after(0, lambda: self._render_archive(items))
        threading.Thread(target=run, daemon=True).start()

    def _render_archive(self, items) -> None:
        for child in self._archive_list.winfo_children():
            child.destroy()
        if not items:
            ctk.CTkLabel(self._archive_list, text="Archive is empty.",
                         text_color=self.palette.text_muted).grid(pady=20)
            return
        for a in items:
            row = ctk.CTkFrame(self._archive_list, fg_color=self.palette.surface)
            row.grid(sticky="ew", pady=2)
            row.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(row, anchor="w", text_color=self.palette.text,
                         text=f"{a.audit_id} · {a.agent} · {a.validation} · {a.date}"
                         ).grid(row=0, column=0, sticky="w", padx=8, pady=6)
            ctk.CTkButton(row, text="Restore", width=80,
                          fg_color=self.palette.success,
                          command=lambda x=a: self._restore(x.audit_id)).grid(
                row=0, column=1, padx=8)

    def _restore(self, audit_id: str) -> None:
        try:
            self.ctx.audit_service.restore_audit(audit_id)
            self._toast.show(f"Restored {audit_id}", "success")
            self._refresh_archive()
        except EQMSError as exc:
            self._toast.show(str(exc), "error", duration=5000)

    def _build_export(self, tab) -> None:
        ctk.CTkLabel(tab, text="Export all workbooks to a folder",
                     font=ctk.CTkFont(weight="bold"),
                     text_color=self.palette.text).grid(
            row=0, column=0, sticky="w", padx=10, pady=10)
        ctk.CTkButton(tab, text="Export all data…", fg_color=self.palette.primary,
                      hover_color=self.palette.primary_hover,
                      command=self._export_all).grid(
            row=1, column=0, sticky="w", padx=10, pady=8)
        self._export_status = ctk.CTkLabel(tab, text="",
                                          text_color=self.palette.text_muted)
        self._export_status.grid(row=2, column=0, sticky="w", padx=10, pady=6)

    def _export_all(self) -> None:
        folder = filedialog.askdirectory(title="Select export destination")
        if not folder:
            return

        def run():
            from pathlib import Path
            from .. import config

            dest = Path(folder)
            saved = []
            for wb in config.ALL_WORKBOOKS:
                try:
                    if self.ctx.store.exists(wb):
                        self.ctx.store.download(wb, dest / wb)
                        saved.append(wb)
                except Exception as exc:  # noqa: BLE001
                    _log.error("Export of %s failed: %s", wb, exc)
            self.ctx.logs.record("DATA_EXPORTED", user=self.ctx.session.user.email,
                                 details=f"{len(saved)} workbooks -> {dest}")
            self.after(0, lambda: self._export_status.configure(
                text=f"Exported {len(saved)} workbooks to {dest}"))
            self.after(0, lambda: self._toast.show("Export complete", "success"))
        threading.Thread(target=run, daemon=True).start()
