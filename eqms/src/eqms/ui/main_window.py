"""Main application window: sidebar navigation hosting the feature views.

Built after a successful sign-in. Owns the :class:`AppContext`, starts the
background worker, and swaps the central content panel between the Dashboard,
New/Edit Audit, History, Reports and (for the admin) the Admin Center. The Admin
navigation entry is only created for the Super Administrator.
"""

from __future__ import annotations

import customtkinter as ctk

from .. import __version__
from ..core.logging_config import get_logger
from ..core.models import Audit
from ..services.context import AppContext
from .admin_view import AdminView
from .audit_form_view import AuditFormView
from .audit_history_view import AuditHistoryView
from .dashboard_view import DashboardView
from .reports_view import ReportsView
from .theme import ThemeManager
from .widgets import Toast

_log = get_logger(__name__)


class MainWindow(ctk.CTkFrame):
    """The signed-in application shell."""

    def __init__(self, master, *, ctx: AppContext, theme: ThemeManager,
                 on_sign_out):
        palette = theme.palette
        super().__init__(master, fg_color=palette.surface)
        self.ctx = ctx
        self.theme = theme
        self.palette = palette
        self._on_sign_out = on_sign_out
        self._views: dict[str, ctk.CTkFrame] = {}
        self._nav_buttons: dict[str, ctk.CTkButton] = {}
        self._current = ""
        self._toast = Toast(self, palette=palette)

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        self._build_sidebar()
        self._content = ctk.CTkFrame(self, fg_color=palette.surface_alt)
        self._content.grid(row=0, column=1, sticky="nsew")
        self._content.grid_rowconfigure(0, weight=1)
        self._content.grid_columnconfigure(0, weight=1)

        self.show("Dashboard")
        self.ctx.start_background_worker(on_event=self._on_bg_event)

    # -- sidebar ------------------------------------------------------------

    def _build_sidebar(self) -> None:
        bar = ctk.CTkFrame(self, width=220, corner_radius=0,
                           fg_color=self.palette.sidebar)
        bar.grid(row=0, column=0, sticky="nsw")
        bar.grid_rowconfigure(20, weight=1)
        bar.grid_propagate(False)

        ctk.CTkLabel(bar, text=self.ctx.settings.get("app.title", "HP Mainstream EQMS"),
                     font=ctk.CTkFont(size=17, weight="bold"),
                     text_color="#FFFFFF", wraplength=190).grid(
            row=0, column=0, padx=18, pady=(22, 2), sticky="w")
        ctk.CTkLabel(bar, text=self.ctx.settings.get("app.subtitle", ""),
                     font=ctk.CTkFont(size=10), text_color="#C9D6E5",
                     wraplength=190).grid(row=1, column=0, padx=18, pady=(0, 18),
                                          sticky="w")

        items = [("Dashboard", "📊"), ("New Audit", "➕"),
                 ("History", "🗂"), ("Reports", "📈")]
        if self.ctx.session.is_admin:
            items.append(("Admin Center", "⚙"))
        for i, (name, icon) in enumerate(items, start=2):
            btn = ctk.CTkButton(
                bar, text=f"  {icon}   {name}", anchor="w", height=42,
                corner_radius=8, fg_color="transparent", hover_color="#1A5A93",
                font=ctk.CTkFont(size=13), command=lambda n=name: self.show(n))
            btn.grid(row=i, column=0, padx=12, pady=3, sticky="ew")
            self._nav_buttons[name] = btn

        # User panel at the bottom.
        user = self.ctx.session.user
        footer = ctk.CTkFrame(bar, fg_color="transparent")
        footer.grid(row=21, column=0, sticky="ew", padx=12, pady=12)
        footer.grid_columnconfigure(0, weight=1)
        role = "Administrator" if self.ctx.session.is_admin else "QA Analyst"
        ctk.CTkLabel(footer, text=user.display_name, anchor="w",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color="#FFFFFF").grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(footer, text=role, anchor="w", font=ctk.CTkFont(size=10),
                     text_color="#C9D6E5").grid(row=1, column=0, sticky="w")
        mode = "🌙 Dark" if ctk.get_appearance_mode() == "Light" else "☀ Light"
        self._theme_btn = ctk.CTkButton(
            footer, text=mode, height=30, fg_color="#1A5A93",
            hover_color="#15436D", command=self._toggle_theme)
        self._theme_btn.grid(row=2, column=0, sticky="ew", pady=(10, 4))
        ctk.CTkButton(footer, text="Sign out", height=30, fg_color="transparent",
                      border_width=1, border_color="#C9D6E5", text_color="#FFFFFF",
                      hover_color="#1A5A93", command=self._on_sign_out).grid(
            row=3, column=0, sticky="ew", pady=2)
        ctk.CTkLabel(footer, text=f"v{__version__}", font=ctk.CTkFont(size=9),
                     text_color="#88A4C0").grid(row=4, column=0, sticky="w",
                                                pady=(6, 0))

    # -- navigation ---------------------------------------------------------

    def show(self, name: str) -> None:
        """Display the named view, creating it lazily on first use."""
        if name not in self._views:
            self._views[name] = self._create_view(name)
        for other in self._views.values():
            other.grid_forget()
        self._views[name].grid(row=0, column=0, sticky="nsew")
        self._current = name
        for n, btn in self._nav_buttons.items():
            btn.configure(fg_color=self.palette.primary_hover if n == name
                          else "transparent")

    def _create_view(self, name: str) -> ctk.CTkFrame:
        if name == "Dashboard":
            return DashboardView(self._content, ctx=self.ctx, theme=self.theme)
        if name == "New Audit":
            return AuditFormView(self._content, ctx=self.ctx, theme=self.theme,
                                 on_saved=self._on_audit_saved)
        if name == "History":
            return AuditHistoryView(self._content, ctx=self.ctx, theme=self.theme,
                                    on_edit=self._edit_audit)
        if name == "Reports":
            return ReportsView(self._content, ctx=self.ctx, theme=self.theme)
        if name == "Admin Center":
            return AdminView(self._content, ctx=self.ctx, theme=self.theme)
        raise ValueError(f"Unknown view: {name}")

    # -- cross-view actions -------------------------------------------------

    def _edit_audit(self, audit: Audit) -> None:
        self.show("New Audit")
        form = self._views["New Audit"]
        assert isinstance(form, AuditFormView)
        form.load_audit(audit)

    def _on_audit_saved(self, audit: Audit) -> None:
        # Invalidate dependent views so they reload fresh data next time.
        for name in ("Dashboard", "History"):
            view = self._views.pop(name, None)
            if view is not None:
                view.destroy()

    def _toggle_theme(self) -> None:
        new_mode = self.theme.toggle_mode()
        self._theme_btn.configure(text="🌙 Dark" if new_mode == "Light" else "☀ Light")

    # -- background events --------------------------------------------------

    def _on_bg_event(self, event: str) -> None:
        """Handle worker notifications on the UI thread."""
        def handle():
            if event.startswith("update-available:"):
                version = event.split(":", 1)[1]
                self._toast.show(f"Update available: v{version}", "info", 6000)
            elif event == "backup-complete":
                _log.info("Background backup complete")
        try:
            self.after(0, handle)
        except Exception:  # noqa: BLE001 - window may be closing
            pass
