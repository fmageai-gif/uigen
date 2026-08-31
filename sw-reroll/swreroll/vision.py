"""Screen recognition.

The reroll loop never blind-taps on a timer if it can help it. It taps, then
waits until it can *see* the next screen. Template matching against small
reference crops is what makes that possible, and it is what keeps the loop
alive when a server hiccup adds four seconds to a loading screen.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

# Templates are captured at whatever resolution the author's emulator ran at.
# Everything is matched against a screen normalised to this width so a crop
# taken on a 1600x900 instance still works on a 1280x720 one.
REFERENCE_WIDTH = 1280

# Multi-scale search handles the residual few-percent difference between
# emulator aspect ratios and UI scaling settings.
DEFAULT_SCALES = (1.0, 0.95, 1.05, 0.9, 1.1)


@dataclass
class Match:
    found: bool
    score: float
    center: tuple[int, int] = (0, 0)
    rect: tuple[int, int, int, int] = (0, 0, 0, 0)  # x, y, w, h
    scale: float = 1.0

    def __bool__(self) -> bool:
        return self.found


class TemplateError(RuntimeError):
    pass


def normalise(screen: np.ndarray, reference_width: int = REFERENCE_WIDTH) -> tuple[np.ndarray, float]:
    """Scale a screenshot to the reference width. Returns (image, factor).

    `factor` converts reference-space coordinates back to device pixels.
    """
    h, w = screen.shape[:2]
    if w == reference_width:
        return screen, 1.0
    factor = w / reference_width
    resized = cv2.resize(
        screen,
        (reference_width, max(1, int(round(h / factor)))),
        interpolation=cv2.INTER_AREA if factor > 1 else cv2.INTER_LINEAR,
    )
    return resized, factor


def _to_gray(img: np.ndarray) -> np.ndarray:
    if img.ndim == 2:
        return img
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def _crop_region(img: np.ndarray, region: tuple[float, float, float, float] | None):
    """Region is (x, y, w, h) in 0..1 fractions of the frame."""
    if not region:
        return img, (0, 0)
    h, w = img.shape[:2]
    rx, ry, rw, rh = region
    x0 = max(0, min(w - 1, int(rx * w)))
    y0 = max(0, min(h - 1, int(ry * h)))
    x1 = max(x0 + 1, min(w, int((rx + rw) * w)))
    y1 = max(y0 + 1, min(h, int((ry + rh) * h)))
    return img[y0:y1, x0:x1], (x0, y0)


def find_template(
    screen: np.ndarray,
    template: np.ndarray,
    threshold: float = 0.85,
    region: tuple[float, float, float, float] | None = None,
    scales: tuple[float, ...] = DEFAULT_SCALES,
) -> Match:
    """Locate `template` inside `screen`. Coordinates come back in *device* pixels."""
    norm, factor = normalise(screen)
    haystack_full = _to_gray(norm)
    haystack, (off_x, off_y) = _crop_region(haystack_full, region)
    needle_base = _to_gray(template)

    best = Match(found=False, score=0.0)
    for scale in scales:
        if scale == 1.0:
            needle = needle_base
        else:
            nh, nw = needle_base.shape[:2]
            nw, nh = int(round(nw * scale)), int(round(nh * scale))
            if nw < 4 or nh < 4:
                continue
            needle = cv2.resize(needle_base, (nw, nh), interpolation=cv2.INTER_AREA)

        th, tw = needle.shape[:2]
        if th > haystack.shape[0] or tw > haystack.shape[1]:
            continue

        result = cv2.matchTemplate(haystack, needle, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        if max_val <= best.score:
            continue

        x = (max_loc[0] + off_x) * factor
        y = (max_loc[1] + off_y) * factor
        best = Match(
            found=max_val >= threshold,
            score=float(max_val),
            center=(int(x + tw * factor / 2), int(y + th * factor / 2)),
            rect=(int(x), int(y), int(tw * factor), int(th * factor)),
            scale=scale,
        )
        # A near-perfect hit is not going to be beaten by another scale.
        if max_val >= 0.98:
            break

    return best


@dataclass
class TemplateStore:
    """Lazily loads and caches reference crops from a directory tree.

    Names are paths relative to the root without the extension, so
    `templates/keepers/ariel.png` is addressed as `keepers/ariel`.
    """

    root: Path
    _cache: dict[str, np.ndarray] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self.root = Path(self.root)

    def path_for(self, name: str) -> Path:
        return self.root / f"{name}.png"

    def has(self, name: str) -> bool:
        return name in self._cache or self.path_for(name).is_file()

    def get(self, name: str) -> np.ndarray:
        if name in self._cache:
            return self._cache[name]
        path = self.path_for(name)
        if not path.is_file():
            raise TemplateError(
                f"Missing template {name!r} (expected {path}). "
                f"Capture it with: swreroll shot --crop"
            )
        img = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if img is None:
            raise TemplateError(f"Could not read template image at {path}")
        self._cache[name] = img
        return img

    def group(self, prefix: str) -> list[str]:
        """Every template under a subdirectory, e.g. `keepers`."""
        base = self.root / prefix
        if not base.is_dir():
            return []
        return sorted(
            str(p.relative_to(self.root).with_suffix("")).replace("\\", "/")
            for p in base.rglob("*.png")
        )

    def find(self, screen: np.ndarray, name: str, threshold: float = 0.85, **kw) -> Match:
        return find_template(screen, self.get(name), threshold=threshold, **kw)

    def find_any(
        self, screen: np.ndarray, names: list[str], threshold: float = 0.85, **kw
    ) -> tuple[str | None, Match]:
        """First template that clears the threshold, else the best near-miss."""
        best_name, best = None, Match(found=False, score=0.0)
        for name in names:
            match = self.find(screen, name, threshold=threshold, **kw)
            if match.found:
                return name, match
            if match.score > best.score:
                best_name, best = name, match
        return (best_name, best) if best.found else (None, best)
