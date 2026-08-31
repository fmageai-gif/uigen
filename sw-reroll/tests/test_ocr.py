"""OCR logic, with the tesseract subprocess stubbed out.

The parts worth testing here are ours: fuzzy name matching that survives the
glyph swaps stylised game fonts provoke, and the coordinate maths that turns a
TSV box back into a tappable device pixel.
"""

import numpy as np
import pytest

from swreroll.ocr import Ocr, OcrError, canonical, crop, preprocess, similar
from tests.conftest import make_screen


# ---- fuzzy matching ------------------------------------------------------

def test_canonical_folds_case_and_punctuation():
    assert canonical("Ariel!") == canonical("  ariel ") == "ariel"


@pytest.mark.parametrize("read,expected", [
    ("8eelzebub", "Beelzebub"),   # B -> 8
    ("Arie1", "Ariel"),           # l -> 1
    ("Zeratu", "Zeratu"),
    ("VIGOR", "Vigor"),
    ("Je4nne", "Jeanne"),         # one bad glyph, still closest
])
def test_common_ocr_slips_still_match_the_right_monster(read, expected):
    roster = ["Ariel", "Jeanne", "Vigor", "Beelzebub", "Zeratu", "Woosa"]
    best = max(roster, key=lambda name: similar(read, name))
    assert best == expected
    assert similar(read, expected) >= 0.8


def test_similar_does_not_confuse_different_monsters():
    assert similar("Ariel", "Beelzebub") < 0.5
    assert similar("", "Ariel") == 0.0


# ---- preprocessing -------------------------------------------------------

def test_preprocess_upscales_pads_and_binarises():
    src = make_screen(100, 40, color=(20, 20, 20))
    src[10:30, 10:90] = 240  # a light "text" bar on a dark panel
    out = preprocess(src, upscale=2.0, invert=True, binarize=True, pad=5)

    assert out.ndim == 2                              # greyscale
    assert out.shape == (40 * 2 + 10, 100 * 2 + 10)   # upscaled + padded
    assert set(np.unique(out)).issubset({0, 255})     # binarised
    assert out[0, 0] == 255                           # padding is white


def test_crop_uses_fractions_and_reports_the_offset():
    sub, x, y = crop(make_screen(1000, 500), (0.2, 0.4, 0.3, 0.2))
    assert sub.shape[:2] == (100, 300)
    assert (x, y) == (200, 200)


def test_crop_rejects_an_empty_region():
    with pytest.raises(OcrError, match="empty"):
        crop(make_screen(), (0.5, 0.5, 0.0, 0.0))


def test_whole_screen_when_no_region():
    screen = make_screen(800, 600)
    sub, x, y = crop(screen, None)
    assert sub.shape == screen.shape and (x, y) == (0, 0)


# ---- engine behaviour with a stubbed binary ------------------------------

class StubOcr(Ocr):
    """Captures the argv tesseract would have been called with."""

    def __init__(self, output="", **kw):
        super().__init__(**kw)
        self.output = output
        self.seen = []

    def _bin(self):
        return "/usr/bin/tesseract"

    def _run(self, img, psm, whitelist, tsv):
        self.seen.append({"psm": psm, "whitelist": whitelist, "tsv": tsv})
        return self.output


def test_read_collapses_whitespace():
    ocr = StubOcr(output="  Ariel \n\n")
    assert ocr.read(make_screen()) == "Ariel"


def test_read_int_strips_separators():
    ocr = StubOcr(output="1,250\n")
    assert ocr.read_int(make_screen()) == 1250
    assert ocr.seen[-1]["whitelist"] is not None  # digits are whitelisted


def test_read_int_returns_the_default_when_nothing_is_legible():
    assert StubOcr(output="~~~").read_int(make_screen(), default=0) == 0


def _tsv(rows):
    header = "level\tpage\tblock\tpar\tline\tword\tleft\ttop\twidth\theight\tconf\ttext"
    lines = [header]
    for text, conf, (l, t, w, h) in rows:
        lines.append(f"5\t1\t1\t1\t1\t1\t{l}\t{t}\t{w}\t{h}\t{conf}\t{text}")
    return "\n".join(lines)


def test_words_converts_boxes_back_to_device_pixels():
    #  Region starts 20% across a 1280px screen; upscale 2, pad 10.
    ocr = StubOcr(output=_tsv([("Summon", 92.0, (10 + 100, 10 + 60, 120, 40))]))
    words = ocr.words(make_screen(1280, 720), region=(0.2, 0.0, 0.5, 1.0), upscale=2.0, pad=10)

    assert len(words) == 1
    w = words[0]
    assert w.text == "Summon"
    # left: (110-10)/2 + 256 = 306 ; top: (70-10)/2 = 30
    assert w.rect[0] == pytest.approx(306, abs=2)
    assert w.rect[1] == pytest.approx(30, abs=2)
    assert w.rect[2] == pytest.approx(60, abs=2)   # 120 / upscale
    assert w.center[0] == pytest.approx(336, abs=3)


def test_words_drops_low_confidence_noise():
    ocr = StubOcr(output=_tsv([
        ("Summon", 90.0, (10, 10, 80, 30)),
        ("~4x", 12.0, (10, 60, 40, 20)),
    ]))
    assert [w.text for w in ocr.words(make_screen(), min_conf=45)] == ["Summon"]


def test_find_text_spans_multiple_word_boxes():
    ocr = StubOcr(output=_tsv([
        ("Summon", 90.0, (110, 110, 100, 30)),
        ("Again", 88.0, (220, 110, 90, 30)),
    ]))
    hit = ocr.find_text(make_screen(), "Summon Again", upscale=1.0, pad=10)
    assert hit is not None
    assert hit.text == "Summon Again"
    # The box must span both words.
    assert hit.rect[2] >= 190


def test_find_text_returns_none_below_the_ratio():
    ocr = StubOcr(output=_tsv([("Inventory", 90.0, (10, 10, 100, 30))]))
    assert ocr.find_text(make_screen(), "Summon", min_ratio=0.8) is None


def test_match_any_picks_the_wanted_monster():
    ocr = StubOcr(output="8eelzebub")
    hit, raw, ratio = ocr.match_any(make_screen(), ["Ariel", "Beelzebub", "Vigor"])
    assert hit == "Beelzebub"
    assert raw == "8eelzebub"
    assert ratio >= 0.82


def test_match_any_matches_a_name_embedded_in_a_longer_read():
    ocr = StubOcr(output="Dark Beelzebub 5*")
    hit, _, _ = ocr.match_any(make_screen(), ["Beelzebub"])
    assert hit == "Beelzebub"


def test_match_any_rejects_an_unwanted_monster():
    """The whole loop hinges on this: a miss must not read as a keep."""
    ocr = StubOcr(output="Lapis")
    hit, raw, _ = ocr.match_any(make_screen(), ["Ariel", "Beelzebub", "Zeratu"])
    assert hit is None
    assert raw == "Lapis"


def test_match_any_on_an_unreadable_screen_is_a_miss():
    hit, raw, ratio = StubOcr(output="").match_any(make_screen(), ["Ariel"])
    assert (hit, raw, ratio) == (None, "", 0.0)


def test_missing_tesseract_binary_explains_how_to_install_it():
    with pytest.raises(OcrError, match="brew install tesseract"):
        Ocr(binary="definitely-not-a-real-binary").read(make_screen())


def test_dictionary_is_disabled_for_game_text():
    """Monster names are not English words; the language model only hurts."""
    ocr = Ocr()
    ocr._resolved = "/usr/bin/tesseract"
    argv = ocr._argv(psm=7, whitelist=None, tsv=False)
    assert "load_system_dawg=0" in argv
    assert "load_freq_dawg=0" in argv


def test_tessdata_dir_is_forwarded():
    ocr = Ocr(tessdata_dir="/opt/tessdata")
    ocr._resolved = "/usr/bin/tesseract"
    argv = ocr._argv(psm=7, whitelist=None, tsv=False)
    assert "--tessdata-dir" in argv and "/opt/tessdata" in argv
