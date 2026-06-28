"""Top-level launch script and PyInstaller entry point.

Kept at the project root (rather than inside the package) so PyInstaller has a
simple, importable script to analyse. It adjusts ``sys.path`` to include ``src``
when run from a source checkout, then delegates to :func:`eqms.ui.app.run`.
"""

from __future__ import annotations

import os
import sys


def _ensure_src_on_path() -> None:
    """Add the bundled/local ``src`` directory to ``sys.path`` if present."""
    here = os.path.dirname(os.path.abspath(__file__))
    src = os.path.join(here, "src")
    if os.path.isdir(src) and src not in sys.path:
        sys.path.insert(0, src)


def main() -> None:
    _ensure_src_on_path()
    from eqms.ui.app import run

    run()


if __name__ == "__main__":
    main()
