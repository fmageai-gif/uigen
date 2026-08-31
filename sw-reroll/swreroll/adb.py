"""Thin wrapper around the `adb` binary.

Everything the reroll loop needs to drive an Android device or emulator
instance: taps, swipes, screenshots, and app lifecycle control. Talking to
adb rather than the host mouse means the emulator window can be minimised,
moved, or stacked with a dozen siblings and the automation still lands.
"""

from __future__ import annotations

import random
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import Sequence

import cv2
import numpy as np

_DEVICE_LINE = re.compile(r"^(\S+)\s+device\b")


class AdbError(RuntimeError):
    """An adb invocation failed, timed out, or returned something unusable."""


def resolve_adb(adb_path: str = "adb") -> str:
    found = shutil.which(adb_path)
    if not found:
        raise AdbError(
            f"Could not find {adb_path!r} on PATH. Install platform-tools, or point "
            f"--adb at the binary shipped with your emulator "
            f"(LDPlayer: ldplayer/adb.exe, MuMu: MuMuPlayer/shell/adb.exe)."
        )
    return found


def list_devices(adb_path: str = "adb") -> list[str]:
    """Serials of every device currently in the `device` state."""
    out = _run([resolve_adb(adb_path), "devices"], timeout=20)
    serials = []
    for line in out.splitlines()[1:]:
        m = _DEVICE_LINE.match(line.strip())
        if m:
            serials.append(m.group(1))
    return serials


def _run(argv: Sequence[str], timeout: float, binary: bool = False):
    try:
        proc = subprocess.run(
            list(argv),
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise AdbError(f"adb timed out after {timeout}s: {' '.join(argv)}") from exc
    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", "replace").strip()
        raise AdbError(f"adb exited {proc.returncode}: {' '.join(argv)}\n{stderr}")
    if binary:
        return proc.stdout
    return proc.stdout.decode("utf-8", "replace")


@dataclass
class AdbDevice:
    """A single adb target. One instance per emulator window."""

    serial: str
    adb_path: str = "adb"
    timeout: float = 30.0
    #  Taps are nudged by up to this many pixels and delayed by a few tens of
    #  milliseconds. Perfectly identical input at perfectly identical intervals
    #  is the single most obvious bot signature there is.
    jitter_px: int = 4
    jitter_ms: tuple[int, int] = (40, 140)
    dry_run: bool = False

    def __post_init__(self) -> None:
        self._adb = resolve_adb(self.adb_path)
        self._size: tuple[int, int] | None = None

    # ---- plumbing --------------------------------------------------------

    def _argv(self, *args: str) -> list[str]:
        return [self._adb, "-s", self.serial, *args]

    def shell(self, *args: str, timeout: float | None = None) -> str:
        if self.dry_run:
            return ""
        return _run(self._argv("shell", *args), timeout or self.timeout)

    def _sleep_jitter(self) -> None:
        lo, hi = self.jitter_ms
        time.sleep(random.uniform(lo, hi) / 1000.0)

    # ---- input -----------------------------------------------------------

    def tap(self, x: int, y: int) -> None:
        if self.jitter_px:
            x += random.randint(-self.jitter_px, self.jitter_px)
            y += random.randint(-self.jitter_px, self.jitter_px)
        x, y = max(0, int(x)), max(0, int(y))
        self.shell("input", "tap", str(x), str(y))
        self._sleep_jitter()

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        self.shell(
            "input", "swipe",
            str(int(x1)), str(int(y1)), str(int(x2)), str(int(y2)), str(int(duration_ms)),
        )
        self._sleep_jitter()

    def key(self, keycode: str | int) -> None:
        self.shell("input", "keyevent", str(keycode))
        self._sleep_jitter()

    def text(self, value: str) -> None:
        # `input text` treats space as an argument separator and chokes on it.
        self.shell("input", "text", value.replace(" ", "%s"))
        self._sleep_jitter()

    def back(self) -> None:
        self.key("KEYCODE_BACK")

    # ---- screen ----------------------------------------------------------

    def screen_size(self) -> tuple[int, int]:
        """(width, height) in pixels, cached after the first call."""
        if self._size is not None:
            return self._size
        out = self.shell("wm", "size")
        m = re.search(r"(\d+)x(\d+)", out)
        if not m:
            raise AdbError(f"Could not parse screen size from {out!r}")
        self._size = (int(m.group(1)), int(m.group(2)))
        return self._size

    def screencap(self) -> np.ndarray:
        """Grab the framebuffer as a BGR ndarray."""
        if self.dry_run:
            w, h = 1280, 720
            return np.zeros((h, w, 3), dtype=np.uint8)

        raw = _run(self._argv("exec-out", "screencap", "-p"), self.timeout, binary=True)
        img = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            # Some emulators (older LDPlayer, a few MuMu builds) have no working
            # exec-out and mangle \n into \r\n on the way through `shell`.
            raw = _run(self._argv("shell", "screencap", "-p"), self.timeout, binary=True)
            raw = raw.replace(b"\r\n", b"\n")
            img = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise AdbError(
                f"{self.serial}: screencap returned data OpenCV could not decode."
            )
        return img

    # ---- app lifecycle ---------------------------------------------------

    def start_app(self, package: str) -> None:
        self.shell("monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1")

    def stop_app(self, package: str) -> None:
        self.shell("am", "force-stop", package)

    def clear_app_data(self, package: str) -> None:
        """Wipe the app's data dir. This is what actually discards an account."""
        out = self.shell("pm", "clear", package, timeout=max(self.timeout, 60))
        if not self.dry_run and "Success" not in out:
            raise AdbError(f"{self.serial}: pm clear {package} failed: {out.strip()}")

    def is_installed(self, package: str) -> bool:
        return package in self.shell("pm", "list", "packages", package)

    def foreground_package(self) -> str:
        out = self.shell("dumpsys", "window", "displays")
        m = re.search(r"mCurrentFocus=.*\s([\w.]+)/", out)
        return m.group(1) if m else ""


# Default ADB endpoints per emulator. Ports step by a fixed stride for each
# extra instance, which is what makes multi-instance rerolling scriptable.
#   MuMu Player 12 : 16384, +32   (MuMu 6 / Nebula used 7555)
#   LDPlayer       : 5555,  +2
#   BlueStacks     : 5555,  +10
#   Nox            : 62001, +24
EMULATOR_PORTS: dict[str, tuple[int, int]] = {
    "mumu": (16384, 32),
    "mumu6": (7555, 1),
    "ldplayer": (5555, 2),
    "bluestacks": (5555, 10),
    "nox": (62001, 24),
}


def connect(host_port: str, adb_path: str = "adb") -> bool:
    """`adb connect`. True if the endpoint is now attached."""
    try:
        out = _run([resolve_adb(adb_path), "connect", host_port], timeout=20)
    except AdbError:
        return False
    lowered = out.lower()
    return "connected" in lowered and "cannot" not in lowered


def connect_instances(
    emulator: str, count: int = 1, adb_path: str = "adb", host: str = "127.0.0.1"
) -> list[str]:
    """Connect the first `count` instances of a known emulator. Returns serials."""
    if emulator not in EMULATOR_PORTS:
        raise AdbError(
            f"Unknown emulator {emulator!r}. Known: {', '.join(sorted(EMULATOR_PORTS))}"
        )
    base, stride = EMULATOR_PORTS[emulator]
    attached = []
    for i in range(count):
        endpoint = f"{host}:{base + i * stride}"
        if connect(endpoint, adb_path):
            attached.append(endpoint)
    return attached
