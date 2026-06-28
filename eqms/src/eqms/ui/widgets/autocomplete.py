"""Autocomplete entry with a dropdown suggestion list.

Used by the audit form for agent search-as-you-type. The suggestion source is
an injected callable returning ``(label, payload)`` pairs, so the same widget
can serve agents, reasons or any other lookup.
"""

from __future__ import annotations

from typing import Callable

import customtkinter as ctk

from ..theme import Palette


class AutocompleteEntry(ctk.CTkFrame):
    """A text entry that shows a filtered dropdown of suggestions."""

    def __init__(
        self,
        master,
        *,
        palette: Palette,
        suggest: Callable[[str], list[tuple[str, object]]],
        on_select: Callable[[str, object], None] | None = None,
        placeholder: str = "",
        width: int = 240,
        max_results: int = 8,
        **kwargs,
    ):
        super().__init__(master, fg_color="transparent", **kwargs)
        self._palette = palette
        self._suggest = suggest
        self._on_select = on_select
        self._max_results = max_results
        self._results: list[tuple[str, object]] = []

        self.var = ctk.StringVar()
        self.entry = ctk.CTkEntry(
            self, textvariable=self.var, placeholder_text=placeholder, width=width
        )
        self.entry.grid(row=0, column=0, sticky="ew")
        self.grid_columnconfigure(0, weight=1)

        self._listbox = ctk.CTkScrollableFrame(
            self, fg_color=palette.surface_alt, height=0, corner_radius=6
        )
        self._list_visible = False

        self.var.trace_add("write", self._on_change)
        self.entry.bind("<FocusOut>", lambda e: self.after(150, self._hide))
        self.entry.bind("<Escape>", lambda e: self._hide())

    # -- value access -------------------------------------------------------

    def get(self) -> str:
        return self.var.get()

    def set(self, value: str) -> None:
        self.var.set(value)

    def configure_state(self, state: str) -> None:
        self.entry.configure(state=state)

    # -- suggestion handling ------------------------------------------------

    def _on_change(self, *_args) -> None:
        term = self.var.get().strip()
        self._results = self._suggest(term)[: self._max_results] if term else []
        self._render()

    def _render(self) -> None:
        for child in self._listbox.winfo_children():
            child.destroy()
        if not self._results:
            self._hide()
            return
        for label, payload in self._results:
            btn = ctk.CTkButton(
                self._listbox, text=label, anchor="w", height=28,
                fg_color="transparent", text_color=self._palette.text,
                hover_color=self._palette.primary,
                command=lambda l=label, p=payload: self._choose(l, p),
            )
            btn.pack(fill="x", padx=2, pady=1)
        self._show()

    def _choose(self, label: str, payload: object) -> None:
        self.var.set(label)
        self._hide()
        if self._on_select:
            self._on_select(label, payload)

    def _show(self) -> None:
        if not self._list_visible:
            rows = min(len(self._results), self._max_results)
            self._listbox.configure(height=max(30, rows * 30))
            self._listbox.grid(row=1, column=0, sticky="ew", pady=(2, 0))
            self._list_visible = True

    def _hide(self) -> None:
        if self._list_visible:
            self._listbox.grid_forget()
            self._list_visible = False
