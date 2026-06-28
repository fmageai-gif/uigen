"""Console/GUI entry point: ``python -m eqms`` (and the packaged .exe target)."""

from __future__ import annotations


def main() -> None:
    from .ui.app import run

    run()


if __name__ == "__main__":
    main()
