import cv2
import numpy as np
import pytest

from swreroll.vision import (
    REFERENCE_WIDTH,
    TemplateError,
    TemplateStore,
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
