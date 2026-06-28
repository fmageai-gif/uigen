"""A frame embedding a matplotlib figure inside CustomTkinter.

Provides helper methods for the chart types the dashboard needs (bar, pie/donut
and line). Rendering is defensive: if matplotlib is unavailable the frame simply
shows a placeholder label so the rest of the dashboard still works.
"""

from __future__ import annotations

import customtkinter as ctk

from ..theme import Palette


class ChartFrame(ctk.CTkFrame):
    """Hosts a single matplotlib axes that can be redrawn on demand."""

    def __init__(self, master, *, palette: Palette, title: str = "",
                 height: int = 240, **kwargs):
        super().__init__(master, corner_radius=12, fg_color=palette.card,
                         border_width=1, border_color=palette.border, **kwargs)
        self._palette = palette
        self._title = title
        self._mpl_canvas = None
        self._fig = None
        self._ax = None
        self._placeholder: ctk.CTkLabel | None = None
        self._height = height
        self._init_figure()

    def _init_figure(self) -> None:
        try:
            import matplotlib
            matplotlib.use("TkAgg")
            from matplotlib.figure import Figure
            from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
        except Exception:  # noqa: BLE001 - degrade to placeholder
            self._placeholder = ctk.CTkLabel(
                self, text=f"{self._title}\n(charting unavailable)",
                text_color=self._palette.text_muted,
            )
            self._placeholder.pack(expand=True, fill="both", padx=10, pady=10)
            return

        self._fig = Figure(figsize=(4, self._height / 72), dpi=72)
        self._fig.patch.set_alpha(0)
        self._ax = self._fig.add_subplot(111)
        self._mpl_canvas = FigureCanvasTkAgg(self._fig, master=self)
        self._mpl_canvas.get_tk_widget().pack(expand=True, fill="both", padx=8, pady=8)

    # -- chart renderers ----------------------------------------------------

    def _prep(self):
        if self._ax is None:
            return None
        self._ax.clear()
        is_dark = ctk.get_appearance_mode() == "Dark"
        fg = "#F5F5F5" if is_dark else "#1A1A1A"
        self._ax.tick_params(colors=fg, labelsize=8)
        for spine in self._ax.spines.values():
            spine.set_color(fg)
        self._ax.set_facecolor("none")
        self._ax.title.set_color(fg)
        return fg

    def bar(self, labels: list[str], values: list[int], *,
            color: str | None = None, title: str = "") -> None:
        fg = self._prep()
        if fg is None:
            return
        self._ax.bar(labels, values, color=color or self._palette.primary)
        self._ax.set_title(title or self._title)
        for label in self._ax.get_xticklabels():
            label.set_rotation(30)
            label.set_ha("right")
        self._render_canvas()

    def line(self, labels: list[str], values: list[int], *, title: str = "") -> None:
        fg = self._prep()
        if fg is None:
            return
        self._ax.plot(labels, values, marker="o", color=self._palette.accent)
        self._ax.fill_between(range(len(values)), values, alpha=0.15,
                              color=self._palette.accent)
        self._ax.set_title(title or self._title)
        for label in self._ax.get_xticklabels():
            label.set_rotation(30)
            label.set_ha("right")
        self._render_canvas()

    def donut(self, data: dict[str, int], *, title: str = "") -> None:
        fg = self._prep()
        if fg is None:
            return
        labels = [k for k, v in data.items() if v]
        values = [v for v in data.values() if v]
        if not values:
            self._ax.text(0.5, 0.5, "No data", ha="center", va="center",
                          color=fg, transform=self._ax.transAxes)
        else:
            colors = [self._palette.success, self._palette.danger,
                      self._palette.accent, self._palette.warning]
            wedges, *_ = self._ax.pie(
                values, labels=labels, autopct="%1.0f%%",
                colors=colors[: len(values)],
                wedgeprops={"width": 0.42}, textprops={"color": fg, "fontsize": 8},
            )
        self._ax.set_title(title or self._title)
        self._render_canvas()

    def _render_canvas(self) -> None:
        if self._fig and self._mpl_canvas:
            self._fig.tight_layout()
            self._mpl_canvas.draw()
