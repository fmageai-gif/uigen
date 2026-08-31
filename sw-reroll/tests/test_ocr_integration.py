"""End-to-end OCR against the real tesseract binary.

Skipped automatically when tesseract is not installed, so the suite stays
runnable anywhere. When it does run it proves the thing the unit tests can
only approximate: that preprocessing plus the engine actually reads text off
a dark, busy, game-like panel.
"""

import shutil

import cv2
import numpy as np
import pytest

from swreroll.ocr import Ocr

pytestmark = pytest.mark.skipif(
    shutil.which("tesseract") is None, reason="tesseract not installed"
)

NAME_REGION = (0.28, 0.55, 0.45, 0.17)
WANTED = ["Ariel", "Jeanne", "Vigor", "Beelzebub", "Zeratu", "Woosa"]


def result_screen(name: str, seed: int = 3) -> np.ndarray:
    """A stand-in for the summon result: light text on a dark, noisy panel."""
    rng = np.random.default_rng(seed)
    screen = rng.integers(15, 45, (720, 1280, 3), dtype=np.uint8)
    cv2.rectangle(screen, (360, 400), (920, 520), (55, 45, 70), -1)
    cv2.putText(screen, name, (400, 480), cv2.FONT_HERSHEY_DUPLEX, 2.0, (245, 240, 255), 3)
    return screen


def test_reads_a_monster_name_off_a_dark_panel():
    assert Ocr().read(result_screen("Beelzebub"), NAME_REGION) == "Beelzebub"


def test_reads_a_counter_with_a_thousands_separator():
    screen = result_screen("Ariel")
    cv2.putText(screen, "1,250", (60, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (240, 240, 240), 2)
    assert Ocr().read_int(screen, (0.0, 0.03, 0.25, 0.07)) == 1250


def test_a_wanted_monster_is_banked():
    hit, raw, ratio = Ocr().match_any(result_screen("Beelzebub"), WANTED, NAME_REGION)
    assert hit == "Beelzebub"
    assert ratio >= 0.82


@pytest.mark.parametrize("name", ["Lapis", "Colleen", "Shannon"])
def test_an_unwanted_monster_is_not_a_false_positive(name):
    """A false positive here banks a junk account and stops the run."""
    hit, _, _ = Ocr().match_any(result_screen(name), WANTED, NAME_REGION)
    assert hit is None


def test_find_text_returns_a_tappable_box():
    word = Ocr().find_text(result_screen("Beelzebub"), "Beelzebub", NAME_REGION)
    assert word is not None
    cx, cy = word.center
    # The name sits inside the panel drawn at (360,400)-(920,520).
    assert 360 < cx < 920 and 400 < cy < 520
