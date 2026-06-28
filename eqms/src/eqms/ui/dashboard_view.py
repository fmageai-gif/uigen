"""Dashboard view: KPI cards, charts and a live searchable audit table.

KPI cards and chart datasets are computed by
:class:`~eqms.services.dashboard_service.DashboardService`. Data loads happen on
a worker thread; the UI is updated via ``after(0, …)``. Which KPI cards appear
(and their order) is driven by the editable widget configuration in settings.
"""

from __future__ import annotations

import threading

import customtkinter as ctk

from ..core.logging_config import get_logger
from ..core.utils import truncate
from ..services.context import AppContext
from .concurrency import ui_post
from .theme import ThemeManager
from .widgets import ChartFrame, KPICard

_log = get_logger(__name__)


class DashboardView(ctk.CTkFrame):
    """Top-level dashboard with KPIs, charts and a filterable audit list."""

    def __init__(self, master, *, ctx: AppContext, theme: ThemeManager):
        palette = theme.palette
        super().__init__(master, fg_color=palette.surface_alt)
        self.ctx = ctx
        self.theme = theme
        self.palette = palette
        self._cards: dict[str, KPICard] = {}
        self._audits: list = []

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        self._build_header()
        self._scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self._scroll.grid(row=1, column=0, rowspan=2, sticky="nsew", padx=16, pady=(0, 16))
        self._scroll.grid_columnconfigure(0, weight=1)

        self._build_kpi_grid()
        self._build_charts()
        self._build_table()
        self.refresh_async()

    # -- header -------------------------------------------------------------

    def _build_header(self) -> None:
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 8))
        bar.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(bar, text="Dashboard",
                     font=ctk.CTkFont(size=22, weight="bold"),
                     text_color=self.palette.text).grid(row=0, column=0, sticky="w")
        self._status_label = ctk.CTkLabel(bar, text="Loading…",
                                          text_color=self.palette.text_muted)
        self._status_label.grid(row=0, column=1, sticky="e", padx=(0, 8))
        ctk.CTkButton(bar, text="⟳ Refresh", width=90,
                      fg_color=self.palette.primary,
                      hover_color=self.palette.primary_hover,
                      command=self.refresh_async).grid(row=0, column=2, sticky="e")

    # -- KPI grid -----------------------------------------------------------

    def _build_kpi_grid(self) -> None:
        container = ctk.CTkFrame(self._scroll, fg_color="transparent")
        container.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        widgets = [w for w in self.ctx.settings.get_widgets()
                   if str(w.get("Enabled", "true")).lower() in ("1", "true", "yes")]
        cols = 4
        for i in range(cols):
            container.grid_columnconfigure(i, weight=1, uniform="kpi")
        for idx, widget in enumerate(widgets):
            key = widget.get("Key", "")
            label = widget.get("Label", key)
            card = KPICard(container, title=label, palette=self.palette,
                           accent=self._accent_for(key))
            card.grid(row=idx // cols, column=idx % cols, padx=6, pady=6, sticky="ew")
            self._cards[key] = card

    def _accent_for(self, key: str) -> str:
        if key in ("valid_pct",):
            return self.palette.success
        if key in ("invalid_pct", "common_invalid"):
            return self.palette.danger
        return self.palette.primary

    # -- charts -------------------------------------------------------------

    def _build_charts(self) -> None:
        row = ctk.CTkFrame(self._scroll, fg_color="transparent")
        row.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        for i in range(3):
            row.grid_columnconfigure(i, weight=1, uniform="chart")
        self._chart_trend = ChartFrame(row, palette=self.palette,
                                       title="Audits (last 14 days)")
        self._chart_trend.grid(row=0, column=0, padx=6, sticky="nsew")
        self._chart_validity = ChartFrame(row, palette=self.palette,
                                          title="Valid vs Invalid")
        self._chart_validity.grid(row=0, column=1, padx=6, sticky="nsew")
        self._chart_reasons = ChartFrame(row, palette=self.palette,
                                         title="Top Invalid Reasons")
        self._chart_reasons.grid(row=0, column=2, padx=6, sticky="nsew")

    # -- live table ---------------------------------------------------------

    def _build_table(self) -> None:
        panel = ctk.CTkFrame(self._scroll, corner_radius=12,
                             fg_color=self.palette.card,
                             border_width=1, border_color=self.palette.border)
        panel.grid(row=2, column=0, sticky="nsew")
        panel.grid_columnconfigure(0, weight=1)

        bar = ctk.CTkFrame(panel, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", padx=12, pady=10)
        bar.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(bar, text="Live Audit Database",
                     font=ctk.CTkFont(size=15, weight="bold"),
                     text_color=self.palette.text).grid(row=0, column=0, sticky="w")
        self._search_var = ctk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._render_rows())
        ctk.CTkEntry(bar, textvariable=self._search_var, width=260,
                     placeholder_text="Search audits…").grid(row=0, column=1, sticky="e")

        header = ctk.CTkFrame(panel, fg_color=self.palette.surface_alt)
        header.grid(row=1, column=0, sticky="ew", padx=12)
        cols = ("Audit ID", "Date", "Agent", "QA", "Validation", "Reason")
        weights = (2, 2, 3, 3, 2, 4)
        for i, (c, w) in enumerate(zip(cols, weights)):
            header.grid_columnconfigure(i, weight=w)
            ctk.CTkLabel(header, text=c, font=ctk.CTkFont(size=11, weight="bold"),
                         text_color=self.palette.text_muted,
                         anchor="w").grid(row=0, column=i, sticky="w", padx=6, pady=6)

        self._rows_frame = ctk.CTkScrollableFrame(panel, fg_color="transparent",
                                                  height=240)
        self._rows_frame.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 12))
        self._rows_frame.grid_columnconfigure(0, weight=1)

    # -- data load ----------------------------------------------------------

    def refresh_async(self) -> None:
        self._status_label.configure(text="Refreshing…")
        threading.Thread(target=self._load, daemon=True).start()

    def _load(self) -> None:
        audits, status = self.ctx.dashboard_service.load_audits(refresh=True)
        kpis = self.ctx.dashboard_service.compute_kpis(audits, status)
        ui_post(self, lambda: self._apply(audits, kpis, status))

    def _apply(self, audits, kpis, status) -> None:
        self._audits = audits
        values = kpis.as_map()
        for key, card in self._cards.items():
            card.set_value(values.get(key, "—"))
        self._status_label.configure(text=f"● {status}")

        ds = self.ctx.dashboard_service
        labels, counts = ds.audits_per_day(audits)
        self._chart_trend.line(labels, counts, title="Audits (last 14 days)")
        self._chart_validity.donut(ds.validity_breakdown(audits),
                                   title="Valid vs Invalid")
        r_labels, r_counts = ds.top_invalid_reasons(audits)
        self._chart_reasons.bar([truncate(x, 14) for x in r_labels], r_counts,
                                color=self.palette.danger,
                                title="Top Invalid Reasons")
        self._render_rows()

    def _render_rows(self) -> None:
        for child in self._rows_frame.winfo_children():
            child.destroy()
        query = self._search_var.get().strip().lower()
        shown = 0
        for a in sorted(self._audits, key=lambda x: x.created_at, reverse=True):
            if query and query not in (
                f"{a.audit_id} {a.agent} {a.qa_name} {a.reason} {a.case_number}"
                .lower()
            ):
                continue
            self._row_widget(a)
            shown += 1
            if shown >= 200:  # keep the UI responsive on large datasets
                break
        if shown == 0:
            ctk.CTkLabel(self._rows_frame, text="No matching audits.",
                         text_color=self.palette.text_muted).grid(
                row=0, column=0, pady=20)

    def _row_widget(self, a) -> None:
        row = ctk.CTkFrame(self._rows_frame, fg_color="transparent")
        row.grid(sticky="ew", pady=1)
        row.grid_columnconfigure(0, weight=1)
        inner = ctk.CTkFrame(row, fg_color=self.palette.surface)
        inner.grid(sticky="ew")
        cells = (a.audit_id, a.date, a.agent, a.qa_name, a.validation,
                 truncate(a.reason, 40))
        weights = (2, 2, 3, 3, 2, 4)
        color = (self.palette.danger if a.is_invalid
                 else self.palette.success if a.validation else self.palette.text)
        for i, (text, w) in enumerate(zip(cells, weights)):
            inner.grid_columnconfigure(i, weight=w)
            tc = color if i == 4 else self.palette.text
            ctk.CTkLabel(inner, text=text, anchor="w", text_color=tc,
                         font=ctk.CTkFont(size=11)).grid(
                row=0, column=i, sticky="w", padx=6, pady=4)
