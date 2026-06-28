"""Transient toast notifications (success / error / info)."""

from __future__ import annotations

import customtkinter as ctk

from ..theme import Palette

_KINDS = {
    "success": ("✓", "success"),
    "error": ("✕", "danger"),
    "warning": ("!", "warning"),
    "info": ("i", "accent"),
}


class Toast(ctk.CTkFrame):
    """A small, auto-dismissing banner shown at the top of a parent view."""

    def __init__(self, master, *, palette: Palette, **kwargs):
        super().__init__(master, corner_radius=8, **kwargs)
        self._palette = palette
        self._label = ctk.CTkLabel(self, text="", anchor="w",
                                   text_color="#FFFFFF",
                                   font=ctk.CTkFont(size=13, weight="bold"))
        self._label.pack(fill="x", padx=14, pady=8)
        self._job = None

    def show(self, message: str, kind: str = "info", duration: int = 3500) -> None:
        """Display ``message`` styled by ``kind`` for ``duration`` ms."""
        icon, color_attr = _KINDS.get(kind, _KINDS["info"])
        color = getattr(self._palette, color_attr, self._palette.accent)
        self.configure(fg_color=color)
        self._label.configure(text=f"  {icon}   {message}")
        self.place(relx=0.5, rely=0.02, anchor="n")
        self.lift()
        if self._job is not None:
            self.after_cancel(self._job)
        self._job = self.after(duration, self.hide)

    def hide(self) -> None:
        self.place_forget()
        self._job = None
