import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from swreroll.flow import Context          # noqa: E402
from swreroll.vision import TemplateStore  # noqa: E402


class FakeDevice:
    """Stands in for AdbDevice. Records input, serves canned screens."""

    def __init__(self, screens=None, size=(1280, 720)):
        self.serial = "fake:5555"
        self.taps = []
        self.swipes = []
        self.keys = []
        self.texts = []
        self.calls = []
        self._size = size
        # A list is consumed one screen per capture, then the last repeats.
        self._screens = list(screens or [np.zeros((size[1], size[0], 3), np.uint8)])
        self._i = 0

    def screencap(self):
        img = self._screens[min(self._i, len(self._screens) - 1)]
        self._i += 1
        return img

    def screen_size(self):
        return self._size

    def tap(self, x, y):
        self.taps.append((x, y))

    def swipe(self, x1, y1, x2, y2, duration_ms=300):
        self.swipes.append((x1, y1, x2, y2))

    def key(self, code):
        self.keys.append(str(code))

    def back(self):
        self.keys.append("KEYCODE_BACK")

    def text(self, value):
        self.texts.append(value)

    def start_app(self, pkg):
        self.calls.append(("start", pkg))

    def stop_app(self, pkg):
        self.calls.append(("stop", pkg))

    def clear_app_data(self, pkg):
        self.calls.append(("clear", pkg))

    def is_installed(self, pkg):
        return True


def make_screen(w=1280, h=720, color=(30, 30, 30)):
    img = np.zeros((h, w, 3), np.uint8)
    img[:] = color
    return img


def stamp(screen, patch, x, y):
    """Paste a patch into a screen at (x, y) and return the screen."""
    ph, pw = patch.shape[:2]
    screen[y : y + ph, x : x + pw] = patch
    return screen


@pytest.fixture
def badge():
    """A distinctive patch that template matching can lock onto."""
    rng = np.random.default_rng(1234)
    return rng.integers(0, 255, (60, 90, 3), dtype=np.uint8)


@pytest.fixture
def store(tmp_path, badge):
    import cv2
    (tmp_path / "ui").mkdir()
    (tmp_path / "keepers").mkdir()
    cv2.imwrite(str(tmp_path / "ui" / "badge.png"), badge)
    return TemplateStore(tmp_path)


@pytest.fixture
def ctx_factory(store, tmp_path):
    from swreroll.config import Flow, Phase

    def build(device, flow=None, **kw):
        flow = flow or Flow(package="com.example.game", phases={}, order=[])
        kw.setdefault("out_dir", tmp_path / "out")
        kw.setdefault("save_shots", False)
        kw.setdefault("poll_interval", 0.01)
        kw.setdefault("step_timeout", 1.0)
        return Context(device=device, store=store, flow=flow, **kw)

    return build
