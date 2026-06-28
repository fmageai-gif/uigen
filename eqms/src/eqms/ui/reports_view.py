"""Reports view: generate monthly or custom-range Excel reports on demand."""

from __future__ import annotations

import threading
from datetime import date

import customtkinter as ctk

from ..core.logging_config import get_logger
from ..services.context import AppContext
from .theme import ThemeManager
from .widgets import Toast

_log = get_logger(__name__)

_MONTHS = ["January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December"]


class ReportsView(ctk.CTkFrame):
    """Generate and locate Excel reports."""

    def __init__(self, master, *, ctx: AppContext, theme: ThemeManager):
        palette = theme.palette
        super().__init__(master, fg_color=palette.surface_alt)
        self.ctx = ctx
        self.theme = theme
        self.palette = palette
        self._toast = Toast(self, palette=palette)

        self.grid_columnconfigure(0, weight=1)
        self._build()

    def _build(self) -> None:
        ctk.CTkLabel(self, text="Reports",
                     font=ctk.CTkFont(size=22, weight="bold"),
                     text_color=self.palette.text).grid(
            row=0, column=0, sticky="w", padx=20, pady=(16, 8))

        card = ctk.CTkFrame(self, corner_radius=12, fg_color=self.palette.card,
                            border_width=1, border_color=self.palette.border)
        card.grid(row=1, column=0, sticky="ew", padx=20, pady=8)
        card.grid_columnconfigure(3, weight=1)

        ctk.CTkLabel(card, text="Monthly Report",
                     font=ctk.CTkFont(size=15, weight="bold"),
                     text_color=self.palette.text).grid(
            row=0, column=0, columnspan=4, sticky="w", padx=14, pady=(12, 6))

        today = date.today()
        ctk.CTkLabel(card, text="Month", text_color=self.palette.text_muted).grid(
            row=1, column=0, padx=(14, 6), pady=10, sticky="w")
        self._month = ctk.CTkOptionMenu(card, values=_MONTHS,
                                        fg_color=self.palette.primary,
                                        button_color=self.palette.primary_hover)
        self._month.set(_MONTHS[today.month - 1])
        self._month.grid(row=1, column=1, padx=6, pady=10)

        ctk.CTkLabel(card, text="Year", text_color=self.palette.text_muted).grid(
            row=1, column=2, padx=6, pady=10, sticky="e")
        years = [str(y) for y in range(today.year - 3, today.year + 1)]
        self._year = ctk.CTkOptionMenu(card, values=years,
                                       fg_color=self.palette.primary,
                                       button_color=self.palette.primary_hover)
        self._year.set(str(today.year))
        self._year.grid(row=1, column=3, padx=6, pady=10, sticky="w")

        self._gen_btn = ctk.CTkButton(
            card, text="Generate Report", fg_color=self.palette.primary,
            hover_color=self.palette.primary_hover,
            font=ctk.CTkFont(weight="bold"), command=self._generate)
        self._gen_btn.grid(row=2, column=0, columnspan=4, padx=14, pady=(4, 14),
                           sticky="w")

        self._result = ctk.CTkLabel(self, text="", text_color=self.palette.text_muted,
                                    wraplength=700, justify="left")
        self._result.grid(row=2, column=0, sticky="w", padx=20, pady=8)

        ctk.CTkButton(self, text="Open Reports Folder", width=180,
                      fg_color="transparent", border_width=1,
                      border_color=self.palette.primary,
                      text_color=self.palette.primary,
                      command=self._open_folder).grid(
            row=3, column=0, sticky="w", padx=20, pady=8)

    def _generate(self) -> None:
        month = _MONTHS.index(self._month.get()) + 1
        year = int(self._year.get())
        self._gen_btn.configure(state="disabled", text="Generating…")
        threading.Thread(target=self._do_generate, args=(year, month),
                         daemon=True).start()

    def _do_generate(self, year: int, month: int) -> None:
        try:
            result = self.ctx.report_service.generate_monthly(year, month)
            msg = (f"Report for {result.period_label} generated "
                   f"({result.audit_count} audits):\n{result.path}")
            self.after(0, lambda: self._done(msg, "success"))
        except Exception as exc:  # noqa: BLE001
            _log.exception("Report generation failed")
            self.after(0, lambda: self._done(f"Failed: {exc}", "error"))

    def _done(self, message: str, kind: str) -> None:
        self._gen_btn.configure(state="normal", text="Generate Report")
        self._result.configure(text=message)
        self._toast.show("Report generated" if kind == "success" else "Failed", kind)

    def _open_folder(self) -> None:
        import subprocess
        import sys
        from .. import config

        folder = config.BACKUP_DIR / "reports"
        folder.mkdir(parents=True, exist_ok=True)
        try:
            if sys.platform.startswith("win"):
                import os
                os.startfile(folder)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(folder)])
            else:
                subprocess.Popen(["xdg-open", str(folder)])
        except Exception as exc:  # noqa: BLE001
            self._toast.show(f"Could not open folder: {exc}", "warning")
