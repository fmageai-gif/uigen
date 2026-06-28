"""Sign-in view: Microsoft 365 authentication (or offline email entry).

Authentication runs on a worker thread so the device-code prompt and Graph
profile lookup never freeze the UI. On success the supplied ``on_success``
callback is invoked on the UI thread with the resolved :class:`User`.
"""

from __future__ import annotations

import threading
from typing import Callable

import customtkinter as ctk

from .. import APP_NAME, __version__
from ..auth.ms_auth import GraphAuthProvider, LocalAuthProvider
from ..auth.session import SessionManager
from ..core.logging_config import get_logger
from ..core.models import User
from .theme import ThemeManager

_log = get_logger(__name__)


class LoginView(ctk.CTkFrame):
    """Full-window sign-in panel."""

    def __init__(
        self,
        master,
        *,
        session: SessionManager,
        theme: ThemeManager,
        on_success: Callable[[User], None],
    ):
        palette = theme.palette
        super().__init__(master, fg_color=palette.surface)
        self.session = session
        self.theme = theme
        self.palette = palette
        self.on_success = on_success

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        card = ctk.CTkFrame(self, corner_radius=16, fg_color=palette.card,
                            border_width=1, border_color=palette.border)
        card.grid(row=0, column=0, padx=40, pady=40)

        ctk.CTkLabel(
            card, text="HP Mainstream EQMS",
            font=ctk.CTkFont(size=26, weight="bold"),
            text_color=palette.primary,
        ).pack(padx=48, pady=(36, 4))
        ctk.CTkLabel(
            card, text=APP_NAME, text_color=palette.text_muted,
            font=ctk.CTkFont(size=12),
        ).pack(padx=48, pady=(0, 24))

        # Microsoft 365 sign-in button.
        self.ms_button = ctk.CTkButton(
            card, text="Sign in with Microsoft 365", height=44, width=320,
            fg_color=palette.primary, hover_color=palette.primary_hover,
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self._sign_in_m365,
        )
        self.ms_button.pack(padx=48, pady=(0, 16))

        # Offline / local sign-in (development & no-tenant environments).
        ctk.CTkLabel(card, text="— or work offline —",
                     text_color=palette.text_muted,
                     font=ctk.CTkFont(size=11)).pack(pady=(0, 8))
        self.email_entry = ctk.CTkEntry(
            card, placeholder_text="your.name@concentrix.com", width=320, height=38
        )
        self.email_entry.pack(padx=48, pady=(0, 8))
        self.local_button = ctk.CTkButton(
            card, text="Continue offline", height=38, width=320,
            fg_color="transparent", border_width=1, border_color=palette.primary,
            text_color=palette.primary, hover_color=palette.surface_alt,
            command=self._sign_in_local,
        )
        self.local_button.pack(padx=48, pady=(0, 16))

        self.status = ctk.CTkLabel(card, text="", text_color=palette.text_muted,
                                   wraplength=320, justify="center",
                                   font=ctk.CTkFont(size=11))
        self.status.pack(padx=48, pady=(0, 12))

        ctk.CTkLabel(card, text=f"Version {__version__}",
                     text_color=palette.text_muted,
                     font=ctk.CTkFont(size=10)).pack(pady=(0, 24))

    # -- actions ------------------------------------------------------------

    def _set_busy(self, busy: bool, message: str = "") -> None:
        state = "disabled" if busy else "normal"
        self.ms_button.configure(state=state)
        self.local_button.configure(state=state)
        self.status.configure(text=message)

    def _sign_in_m365(self) -> None:
        self.session.set_provider(GraphAuthProvider())
        self._set_busy(True, "Starting Microsoft 365 sign-in…")
        threading.Thread(target=self._do_sign_in, daemon=True).start()

    def _sign_in_local(self) -> None:
        email = self.email_entry.get().strip()
        if not email:
            self.status.configure(text="Please enter your work email.",
                                  text_color=self.palette.danger)
            return
        self.session.set_provider(LocalAuthProvider(email))
        self._set_busy(True, "Signing in…")
        threading.Thread(target=self._do_sign_in, daemon=True).start()

    def _do_sign_in(self) -> None:
        try:
            user = self.session.sign_in(prompt_callback=self._show_prompt)
            self.after(0, lambda: self.on_success(user))
        except Exception as exc:  # noqa: BLE001 - report to the user
            _log.error("Sign-in failed: %s", exc)
            msg = str(exc)
            self.after(0, lambda: self._set_busy(False, ""))
            self.after(0, lambda: self.status.configure(
                text=f"Sign-in failed: {msg}", text_color=self.palette.danger))

    def _show_prompt(self, message: str) -> None:
        """Surface the device-code instruction on the UI thread."""
        self.after(0, lambda: self.status.configure(
            text=message, text_color=self.palette.text))
