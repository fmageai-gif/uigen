import cv2
import numpy as np
import pytest

from swreroll.vision import (
    REFERENCE_WIDTH,
    TemplateError,
    TemplateStore,
    find_all,
    find_template,
    normalise,
)
from tests.conftest import make_screen, stamp


def test_finds_a_template_and_reports_its_centre(badge):
    screen = stamp(make_screen(), badge, 400, 300)
    m = find_template(screen, badge, threshold=0.9)
    assert m.found
    assert m.score > 0.95
    assert m.center == pytest.approx((400 + 45, 300 + 30), abs=3)


def test_reports_a_miss_when_absent(badge):
    m = find_template(make_screen(), badge, threshold=0.85)
    assert not m.found
    assert not m  # __bool__


def test_coordinates_come_back_in_device_pixels_on_a_bigger_screen(badge):
    """A template cut on a 1280-wide instance must work on a 1920-wide one."""
    big = make_screen(1920, 1080)
    scale = 1920 / REFERENCE_WIDTH
    scaled = cv2.resize(badge, None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)
    stamp(big, scaled, int(400 * scale), int(300 * scale))

    m = find_template(big, badge, threshold=0.8)
    assert m.found
    # The badge sits at (400, 300) in *reference* space and is 90x60 there,
    # so its centre is (445, 330) reference -> x1.5 in this screen's pixels.
    assert m.center == pytest.approx((int(445 * scale), int(330 * scale)), abs=25)


def test_region_restricts_the_search(badge):
    screen = stamp(make_screen(), badge, 900, 500)
    assert find_template(screen, badge, 0.9, region=(0.0, 0.0, 0.3, 0.3)).found is False
    assert find_template(screen, badge, 0.9, region=(0.6, 0.5, 0.4, 0.5)).found is True


def test_normalise_leaves_reference_width_alone():
    img, factor = normalise(make_screen(REFERENCE_WIDTH, 720))
    assert factor == 1.0
    assert img.shape[1] == REFERENCE_WIDTH


def test_store_missing_template_says_how_to_capture_one(store):
    with pytest.raises(TemplateError, match="swreroll shot"):
        store.get("ui/does_not_exist")


def test_store_groups_and_caches(store, badge, tmp_path):
    cv2.imwrite(str(tmp_path / "keepers" / "ariel.png"), badge)
    cv2.imwrite(str(tmp_path / "keepers" / "jeanne.png"), badge)
    assert store.group("keepers") == ["keepers/ariel", "keepers/jeanne"]
    assert store.group("nothing_here") == []
    first = store.get("ui/badge")
    assert store.get("ui/badge") is first  # cached, not re-read


def test_find_any_returns_the_matching_name(store, badge, tmp_path):
    rng = np.random.default_rng(99)
    other = rng.integers(0, 255, (40, 40, 3), dtype=np.uint8)
    cv2.imwrite(str(tmp_path / "ui" / "other.png"), other)
    screen = stamp(make_screen(), badge, 200, 100)

    name, match = store.find_any(screen, ["ui/other", "ui/badge"], threshold=0.9)
    assert name == "ui/badge"
    assert match.found

    name, match = store.find_any(make_screen(), ["ui/other", "ui/badge"], threshold=0.9)
    assert name is None
    assert not match.found


# ---- multi-match ---------------------------------------------------------

def test_find_all_counts_repeated_icons(badge):
    """Counting star glyphs is how grade is read without knowing the name."""
    screen = make_screen()
    for i in range(5):
        stamp(screen, badge, 300 + i * 100, 400)

    hits = find_all(screen, badge, threshold=0.9)
    assert len(hits) == 5
    # Returned left-to-right.
    assert [h.rect[0] for h in hits] == sorted(h.rect[0] for h in hits)


def test_find_all_suppresses_overlapping_detections(badge):
    """One icon must never be counted twice."""
    screen = stamp(make_screen(), badge, 500, 300)
    assert len(find_all(screen, badge, threshold=0.9)) == 1


def test_find_all_respects_a_region(badge):
    screen = make_screen()
    stamp(screen, badge, 100, 100)   # outside
    stamp(screen, badge, 700, 500)   # inside
    hits = find_all(screen, badge, threshold=0.9, region=(0.5, 0.5, 0.5, 0.5))
    assert len(hits) == 1


def test_find_all_returns_nothing_when_absent(badge):
    assert find_all(make_screen(), badge, threshold=0.9) == []


def test_find_all_honours_max_hits(badge):
    screen = make_screen()
    for i in range(6):
        stamp(screen, badge, 100 + i * 100, 300)
    assert len(find_all(screen, badge, threshold=0.9, max_hits=3)) == 3


# ---- colour matching -----------------------------------------------------
#
# The element icons differ mainly by hue: light is a silver crest, dark a
# purple disc. Greyscale throws that away, and confusing the two means either
# wiping an LD5 or banking a dud.

def _disc(color, size=44):
    """A solid coloured disc on a dark panel -- shaped like an element icon."""
    img = np.zeros((size, size, 3), np.uint8)
    img[:] = (40, 30, 50)
    cv2.circle(img, (size // 2, size // 2), size // 2 - 4, color, -1)
    return img


def test_greyscale_confuses_two_icons_of_equal_luminance():
    """The defect that colour matching exists to fix."""
    #  Purple and a grey-green chosen to share a luminance, differ in hue.
    dark = _disc((150, 40, 140))
    other = _disc((95, 95, 95))
    screen = stamp(make_screen(), other, 600, 300)

    grey = find_template(screen, dark, threshold=0.85, color=False)
    colour = find_template(screen, dark, threshold=0.85, color=True)
    # Greyscale scores the wrong icon far higher than colour does.
    assert colour.score < grey.score


def test_colour_matching_finds_the_right_icon(badge):
    dark = _disc((150, 40, 140))
    screen = stamp(make_screen(), dark, 600, 300)
    m = find_template(screen, dark, threshold=0.9, color=True)
    assert m.found
    assert m.center == pytest.approx((622, 322), abs=4)


def test_colour_matching_rejects_a_different_hue():
    """A silver crest must not match where a purple disc is, and vice versa."""
    dark = _disc((150, 40, 140))
    light = _disc((225, 225, 230))
    screen = stamp(make_screen(), light, 600, 300)
    assert find_template(screen, dark, threshold=0.9, color=True).found is False
    assert find_template(screen, light, threshold=0.9, color=True).found is True


def test_find_all_supports_colour(badge):
    gold = _disc((60, 200, 240), size=30)
    screen = make_screen()
    for i in range(5):
        stamp(screen, gold, 300 + i * 60, 400)
    assert len(find_all(screen, gold, threshold=0.9, color=True)) == 5


def test_a_greyscale_template_still_works_in_colour_mode():
    """A crop saved as greyscale must not blow up when color=True."""
    gold = _disc((60, 200, 240), size=30)
    screen = stamp(make_screen(), gold, 400, 400)
    grey_template = cv2.cvtColor(gold, cv2.COLOR_BGR2GRAY)
    m = find_template(screen, grey_template, threshold=0.5, color=True)
    assert m.score >= 0.0  # converted, matched, did not raise
