"""OCR screen reading, via the Tesseract CLI.

Template matching finds *buttons*. OCR reads *text* -- and for a reroll bot
that difference is the whole game: instead of needing a captured PNG for
every monster you would accept, you read the monster's name off the summon
result and check it against a list. Adding a target becomes editing a YAML
line rather than cropping a new reference image.

This mirrors the charlesw/tesseract .NET wrapper approach, but drives the
`tesseract` binary directly rather than P/Invoking libtesseract, so the same
`eng.traineddata` works unchanged on Windows, macOS and Linux.
"""

from __future__ import annotations

import difflib
import logging
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .vision import normalise

log = logging.getLogger(__name__)

# Page segmentation modes worth knowing:
#   6  = uniform block of text      7  = single line
#   8  = single word               11 = sparse text, no ordering  (best for HUDs)
#   13 = raw line, no layout analysis
PSM_LINE, PSM_WORD, PSM_SPARSE, PSM_BLOCK = 7, 8, 11, 6

DIGITS = "0123456789"
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"

# Glyph pairs Tesseract routinely swaps in stylised game fonts. Folding these
# together before comparison turns "Beelzebub" vs "8eelzebub" into a match.
_CONFUSIONS = str.maketrans({
    "0": "o", "O": "o", "1": "l", "I": "l", "|": "l",
    "5": "s", "S": "s", "8": "b", "B": "b", "2": "z", "Z": "z",
})


class OcrError(RuntimeError):
    pass


@dataclass
class Word:
    text: str
    conf: float
    rect: tuple[int, int, int, int]  # x, y, w, h in device pixels

    @property
    def center(self) -> tuple[int, int]:
        x, y, w, h = self.rect
        return (x + w // 2, y + h // 2)


def canonical(text: str) -> str:
    """Fold case, punctuation and common OCR glyph swaps for comparison."""
    return re.sub(r"[^a-z0-9]", "", text.translate(_CONFUSIONS).lower())


def similar(a: str, b: str) -> float:
    ca, cb = canonical(a), canonical(b)
    if not ca or not cb:
        return 0.0
    if ca == cb:
        return 1.0
    return difflib.SequenceMatcher(None, ca, cb).ratio()


def crop(img: np.ndarray, region: tuple[float, float, float, float] | None):
    """Crop by 0..1 fractions. Returns (image, x_offset, y_offset) in source px."""
    if not region:
        return img, 0, 0
    h, w = img.shape[:2]
    rx, ry, rw, rh = region
    x0, y0 = max(0, int(rx * w)), max(0, int(ry * h))
    x1, y1 = min(w, int((rx + rw) * w)), min(h, int((ry + rh) * h))
    if x1 <= x0 or y1 <= y0:
        raise OcrError(f"region {region} is empty for a {w}x{h} frame")
    return img[y0:y1, x0:x1], x0, y0


def preprocess(
    img: np.ndarray,
    upscale: float = 3.0,
    invert: bool = True,
    binarize: bool = True,
    pad: int = 12,
) -> np.ndarray:
    """Turn a game HUD crop into something Tesseract can actually read.

    Game text is small, anti-aliased, and usually light-on-dark over a busy
    background -- close to the worst case for an engine trained on scanned
    documents. Upscaling, inverting to dark-on-light, and hard binarising
    routinely takes recognition from garbage to exact.
    """
    out = img
    if upscale and upscale != 1.0:
        out = cv2.resize(out, None, fx=upscale, fy=upscale, interpolation=cv2.INTER_CUBIC)
    if out.ndim == 3:
        out = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)
    if invert:
        out = cv2.bitwise_not(out)
    if binarize:
        out = cv2.threshold(out, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]
    if pad:
        # Tesseract wants breathing room around the glyphs.
        out = cv2.copyMakeBorder(out, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=255)
    return out


@dataclass
class Ocr:
    """Runs the tesseract binary. One instance is reusable and stateless."""

    binary: str = "tesseract"
    lang: str = "eng"
    tessdata_dir: str | None = None
    timeout: float = 20.0

    def __post_init__(self) -> None:
        self._resolved: str | None = None

    def _bin(self) -> str:
        if self._resolved:
            return self._resolved
        found = shutil.which(self.binary)
        if not found:
            raise OcrError(
                f"Could not find {self.binary!r} on PATH.\n"
                f"  Windows : https://github.com/UB-Mannheim/tesseract/wiki\n"
                f"  macOS   : brew install tesseract\n"
                f"  Debian  : sudo apt install tesseract-ocr\n"
                f"You already have eng.traineddata -- point --tessdata-dir at "
                f"the folder holding it if it lives outside the default prefix."
            )
        self._resolved = found
        return found

    def _argv(self, psm: int, whitelist: str | None, tsv: bool) -> list[str]:
        argv = [self._bin(), "-", "-", "-l", self.lang, "--psm", str(psm)]
        if self.tessdata_dir:
            argv += ["--tessdata-dir", str(self.tessdata_dir)]
        if whitelist:
            argv += ["-c", f"tessedit_char_whitelist={whitelist}"]
        # A game HUD has no dictionary words; the language model does more harm
        # than good on monster names, so switch it off.
        argv += ["-c", "load_system_dawg=0", "-c", "load_freq_dawg=0"]
        if tsv:
            argv.append("tsv")
        return argv

    def _run(self, img: np.ndarray, psm: int, whitelist: str | None, tsv: bool) -> str:
        ok, buf = cv2.imencode(".png", img)
        if not ok:
            raise OcrError("failed to encode the crop as PNG")
        argv = self._argv(psm, whitelist, tsv)
        try:
            proc = subprocess.run(
                argv, input=buf.tobytes(), capture_output=True, timeout=self.timeout
            )
        except subprocess.TimeoutExpired as exc:
            raise OcrError(f"tesseract timed out after {self.timeout}s") from exc
        if proc.returncode != 0:
            stderr = proc.stderr.decode("utf-8", "replace").strip()
            # Older builds refuse stdin on some platforms; fall back to a temp file.
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as fh:
                fh.write(buf.tobytes())
                tmp = fh.name
            try:
                argv[1] = tmp
                proc = subprocess.run(argv, capture_output=True, timeout=self.timeout)
                if proc.returncode != 0:
                    raise OcrError(f"tesseract failed: {stderr}")
            finally:
                Path(tmp).unlink(missing_ok=True)
        return proc.stdout.decode("utf-8", "replace")

    # ---- public API ------------------------------------------------------

    def read(
        self,
        screen: np.ndarray,
        region: tuple[float, float, float, float] | None = None,
        psm: int = PSM_LINE,
        whitelist: str | None = None,
        **pre,
    ) -> str:
        """Read a region as a single string."""
        sub, _, _ = crop(screen, region)
        text = self._run(preprocess(sub, **pre), psm, whitelist, tsv=False)
        return " ".join(text.split()).strip()

    def read_int(
        self,
        screen: np.ndarray,
        region: tuple[float, float, float, float] | None = None,
        default: int | None = None,
        **kw,
    ) -> int | None:
        """Read a counter -- mana, crystals, scroll stock, summon count."""
        kw.setdefault("psm", PSM_LINE)
        raw = self.read(screen, region, whitelist=DIGITS + ",.", **kw)
        digits = re.sub(r"[^0-9]", "", raw)
        return int(digits) if digits else default

    def words(
        self,
        screen: np.ndarray,
        region: tuple[float, float, float, float] | None = None,
        psm: int = PSM_SPARSE,
        min_conf: float = 45.0,
        upscale: float = 3.0,
        pad: int = 12,
        **pre,
    ) -> list[Word]:
        """Every recognised word with a bounding box in *device* pixels.

        This is what makes `tap_text` possible: OCR the screen, find the word
        you want, tap its box. No template needed for text buttons at all.
        """
        norm, factor = normalise(screen)
        sub, off_x, off_y = crop(norm, region)
        tsv = self._run(
            preprocess(sub, upscale=upscale, pad=pad, **pre), psm, None, tsv=True
        )

        found: list[Word] = []
        for line in tsv.splitlines()[1:]:
            parts = line.split("\t")
            if len(parts) < 12:
                continue
            text = parts[11].strip()
            if not text:
                continue
            try:
                conf = float(parts[10])
                left, top, w, h = (int(parts[i]) for i in (6, 7, 8, 9))
            except ValueError:
                continue
            if conf < min_conf:
                continue
            # Undo the padding and upscale, then the reference-width scaling.
            x = (left - pad) / upscale + off_x
            y = (top - pad) / upscale + off_y
            found.append(
                Word(
                    text=text,
                    conf=conf,
                    rect=(
                        int(x * factor), int(y * factor),
                        int(w / upscale * factor), int(h / upscale * factor),
                    ),
                )
            )
        return found

    def find_text(
        self,
        screen: np.ndarray,
        needle: str,
        region: tuple[float, float, float, float] | None = None,
        min_ratio: float = 0.8,
        **kw,
    ) -> Word | None:
        """Locate a phrase on screen, tolerating OCR noise.

        Multi-word needles are matched against sliding windows of the word
        list, so "Summon Again" is found even though Tesseract emits it as
        two separate boxes.
        """
        words = self.words(screen, region, **kw)
        if not words:
            return None
        parts = needle.split()
        n = len(parts)

        best, best_ratio = None, 0.0
        for i in range(len(words) - n + 1):
            window = words[i : i + n]
            joined = " ".join(w.text for w in window)
            ratio = similar(joined, needle)
            if ratio > best_ratio:
                xs = [w.rect[0] for w in window]
                ys = [w.rect[1] for w in window]
                x2s = [w.rect[0] + w.rect[2] for w in window]
                y2s = [w.rect[1] + w.rect[3] for w in window]
                best_ratio = ratio
                best = Word(
                    text=joined,
                    conf=min(w.conf for w in window),
                    rect=(min(xs), min(ys), max(x2s) - min(xs), max(y2s) - min(ys)),
                )
        if best and best_ratio >= min_ratio:
            log.debug("ocr found %r as %r (%.2f)", needle, best.text, best_ratio)
            return best
        return None

    def match_any(
        self,
        screen: np.ndarray,
        candidates: list[str],
        region: tuple[float, float, float, float] | None = None,
        min_ratio: float = 0.82,
        **kw,
    ) -> tuple[str | None, str, float]:
        """Best match of a read-out region against a wanted list.

        Returns (matched_candidate_or_None, raw_text, ratio). This is the
        keeper check: OCR the monster name, compare it to your target list.
        """
        raw = self.read(screen, region, **kw)
        if not raw:
            return None, "", 0.0
        best, ratio = None, 0.0
        for cand in candidates:
            r = similar(raw, cand)
            # Also accept the candidate appearing inside a longer read, which
            # happens when the name shares a line with a rank or element tag.
            if canonical(cand) and canonical(cand) in canonical(raw):
                r = max(r, 0.95)
            if r > ratio:
                best, ratio = cand, r
        return (best if ratio >= min_ratio else None), raw, ratio
