"""Cross-platform build helper that produces the single-file executable.

Usage
-----
    python scripts/build.py [--clean]

Steps
-----
1. (optional) remove previous ``build/`` and ``dist/`` output;
2. verify PyInstaller is available;
3. run PyInstaller against ``eqms.spec``;
4. report the resulting artefact path.

On Windows the output is ``dist/HP-Mainstream-EQMS.exe`` — a portable
executable that does not require Python on the target machine.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "eqms.spec"


def _clean() -> None:
    for name in ("build", "dist"):
        target = ROOT / name
        if target.exists():
            print(f"Removing {target} …")
            shutil.rmtree(target, ignore_errors=True)


def _check_pyinstaller() -> None:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        sys.exit("PyInstaller is not installed. Run: pip install -r requirements.txt")


def main(argv: list[str]) -> int:
    if "--clean" in argv:
        _clean()
    _check_pyinstaller()

    print("Building HP Mainstream EQMS with PyInstaller …")
    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", str(SPEC), "--noconfirm"],
        cwd=ROOT,
    )
    if result.returncode != 0:
        return result.returncode

    exe = ROOT / "dist" / (
        "HP-Mainstream-EQMS.exe" if sys.platform.startswith("win")
        else "HP-Mainstream-EQMS"
    )
    if exe.exists():
        size_mb = exe.stat().st_size / (1024 * 1024)
        print(f"\nBuild complete: {exe}  ({size_mb:.1f} MB)")
    else:
        print("\nBuild finished but the expected artefact was not found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
