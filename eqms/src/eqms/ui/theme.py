"""Centralised theming: HP-inspired enterprise blue, light/dark modes.

A single palette object exposes the colours every view uses, derived from the
branding settings (so the administrator can re-brand without code changes).
Appearance mode (System/Light/Dark) and the CustomTkinter base colour theme are
applied here too.
"""

from __future__ import annotations

from dataclasses import dataclass

import customtkinter as ctk

from ..core.logging_config import get_logger
from ..data.settings_store import SettingsStore

_log = get_logger(__name__)


@dataclass(frozen=True)
class Palette:
    """Resolved colour palette. Tuples are ``(light, dark)`` CustomTkinter pairs."""

    primary: str = "#0F4C81"        # HP-inspired enterprise blue
    primary_hover: str = "#0C3D68"
    accent: str = "#1C7ED6"
    success: str = "#2F9E44"
    danger: str = "#E03131"
    warning: str = "#F08C00"
    sidebar: tuple[str, str] = ("#0F4C81", "#0A2E4D")
    surface: tuple[str, str] = ("#FFFFFF", "#1E1E1E")
    surface_alt: tuple[str, str] = ("#F4F7FB", "#262626")
    text: tuple[str, str] = ("#1A1A1A", "#F5F5F5")
    text_muted: tuple[str, str] = ("#667085", "#A0A0A0")
    card: tuple[str, str] = ("#FFFFFF", "#2A2A2A")
    border: tuple[str, str] = ("#E0E6ED", "#3A3A3A")


class ThemeManager:
    """Applies appearance settings and exposes the active palette."""

    def __init__(self, settings: SettingsStore):
        self.settings = settings
        self.palette = self._build_palette()

    def _build_palette(self) -> Palette:
        primary = self.settings.get("app.primary_color", "#0F4C81")
        accent = self.settings.get("app.accent_color", "#1C7ED6")
        return Palette(primary=primary, accent=accent,
                       primary_hover=_darken(primary, 0.15),
                       sidebar=(primary, _darken(primary, 0.35)))

    def apply(self) -> None:
        """Apply appearance mode and base colour theme from settings."""
        mode = self.settings.get("theme.mode", "System")
        if mode not in ("System", "Light", "Dark"):
            mode = "System"
        ctk.set_appearance_mode(mode)
        color_theme = self.settings.get("theme.color_theme", "blue")
        try:
            ctk.set_default_color_theme(color_theme)
        except Exception:  # noqa: BLE001 - unknown theme name => keep default
            ctk.set_default_color_theme("blue")
        _log.info("Applied theme: mode=%s colour=%s", mode, color_theme)

    def set_mode(self, mode: str) -> None:
        """Persist and apply a new appearance mode at runtime."""
        self.settings.set("theme.mode", mode)
        ctk.set_appearance_mode(mode)

    def toggle_mode(self) -> str:
        """Switch between Light and Dark, returning the new mode."""
        current = ctk.get_appearance_mode()  # "Light" or "Dark"
        new_mode = "Light" if current == "Dark" else "Dark"
        self.set_mode(new_mode)
        return new_mode

    def refresh_palette(self) -> Palette:
        """Rebuild the palette after a branding change."""
        self.palette = self._build_palette()
        return self.palette


# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------

def _clamp(value: int) -> int:
    return max(0, min(255, value))


def _darken(hex_color: str, factor: float) -> str:
    """Return ``hex_color`` darkened by ``factor`` (0..1)."""
    try:
        h = hex_color.lstrip("#")
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    except (ValueError, IndexError):
        return hex_color
    r = _clamp(int(r * (1 - factor)))
    g = _clamp(int(g * (1 - factor)))
    b = _clamp(int(b * (1 - factor)))
    return f"#{r:02X}{g:02X}{b:02X}"
