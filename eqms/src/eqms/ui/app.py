"""Application bootstrap: the CustomTkinter root window and top-level flow.

Wires logging, configuration, theming and the session, then shows the login
view and, on success, swaps in the main window. Handles clean shutdown of the
background worker.
"""

from __future__ import annotations

import customtkinter as ctk

from .. import APP_SHORT_NAME, __version__, config
from ..auth.session import SessionManager, get_session
from ..core.logging_config import configure_logging, get_logger
from ..core.models import User
from ..services.context import AppContext
from .login_view import LoginView
from .main_window import MainWindow
from .theme import ThemeManager

_log = get_logger(__name__)


class EQMSApp(ctk.CTk):
    """Root application window."""

    def __init__(self):
        super().__init__()
        config.ensure_directories()
        self.title(config.WINDOW_TITLE)
        self.geometry("1280x820")
        self.minsize(1100, 700)

        self.session: SessionManager = get_session()
        self.settings_bootstrap()
        self.theme = ThemeManager(self._settings)
        self.theme.apply()

        self._container = ctk.CTkFrame(self, fg_color="transparent")
        self._container.pack(expand=True, fill="both")

        self._ctx: AppContext | None = None
        self._main: MainWindow | None = None
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._show_login()

    def settings_bootstrap(self) -> None:
        """Seed settings early so theming has values to read."""
        from ..data.settings_store import SettingsStore

        self._settings = SettingsStore()
        try:
            self._settings.ensure_seeded()
        except Exception as exc:  # noqa: BLE001 - continue with defaults
            _log.warning("Settings seed deferred: %s", exc)

    # -- screens ------------------------------------------------------------

    def _clear_container(self) -> None:
        for child in self._container.winfo_children():
            child.destroy()

    def _show_login(self) -> None:
        self._clear_container()
        login = LoginView(self._container, session=self.session, theme=self.theme,
                          on_success=self._on_signed_in)
        login.pack(expand=True, fill="both")

    def _on_signed_in(self, user: User) -> None:
        _log.info("Building main window for %s", user.email)
        self._ctx = AppContext(self.session)
        self._ctx.initialise()
        self.theme.refresh_palette()
        self._clear_container()
        self._main = MainWindow(self._container, ctx=self._ctx, theme=self.theme,
                                on_sign_out=self._sign_out)
        self._main.pack(expand=True, fill="both")

    def _sign_out(self) -> None:
        if self._ctx:
            self._ctx.stop_background_worker()
            self._ctx = None
        self.session.sign_out()
        self._show_login()

    # -- shutdown -----------------------------------------------------------

    def _on_close(self) -> None:
        _log.info("Shutting down")
        if self._ctx:
            self._ctx.stop_background_worker()
        self.destroy()


def run() -> None:
    """Entry point: configure logging and launch the application."""
    configure_logging()
    _log.info("Starting %s v%s", APP_SHORT_NAME, __version__)
    app = EQMSApp()
    app.mainloop()
