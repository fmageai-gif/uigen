"""KPI card widget: a labelled metric tile used on the dashboard."""

from __future__ import annotations

import customtkinter as ctk

from ..theme import Palette


class KPICard(ctk.CTkFrame):
    """A rounded card showing a title, a large value and an optional accent bar."""

    def __init__(self, master, *, title: str, value: str = "—",
                 palette: Palette, accent: str | None = None, **kwargs):
        super().__init__(
            master, corner_radius=12, fg_color=palette.card,
            border_width=1, border_color=palette.border, **kwargs,
        )
        self._palette = palette
        accent_color = accent or palette.primary

        # Left accent bar for visual hierarchy.
        bar = ctk.CTkFrame(self, width=5, corner_radius=6, fg_color=accent_color)
        bar.grid(row=0, column=0, rowspan=2, sticky="ns", padx=(8, 6), pady=10)

        self._title = ctk.CTkLabel(
            self, text=title, anchor="w",
            font=ctk.CTkFont(size=12, weight="normal"),
            text_color=palette.text_muted,
        )
        self._title.grid(row=0, column=1, sticky="w", padx=(0, 12), pady=(12, 0))

        self._value = ctk.CTkLabel(
            self, text=value, anchor="w",
            font=ctk.CTkFont(size=24, weight="bold"),
            text_color=palette.text,
        )
        self._value.grid(row=1, column=1, sticky="w", padx=(0, 12), pady=(0, 12))

        self.grid_columnconfigure(1, weight=1)

    def set_value(self, value: str) -> None:
        """Update the displayed metric value."""
        self._value.configure(text=value)

    def set_title(self, title: str) -> None:
        self._title.configure(text=title)
