"""Helpers for safely marshalling work back onto the Tk UI thread.

Background workers update the UI by scheduling a callable with ``widget.after``.
If the window is being torn down at that moment Tk raises ``TclError`` /
``RuntimeError``; :func:`ui_post` swallows those so a shutdown race never crashes
a worker thread.
"""

from __future__ import annotations

from typing import Callable


def ui_post(widget, func: Callable[[], None]) -> None:
    """Schedule ``func`` on ``widget``'s UI thread, ignoring teardown races."""
    try:
        widget.after(0, func)
    except Exception:  # noqa: BLE001 - window closing; safe to drop the update
        pass
