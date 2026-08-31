"""The flow interpreter.

A flow is a YAML list of steps. Each step is one of the actions implemented
below. The interpreter is deliberately small: the intelligence lives in the
flow file, which is the part you will actually be editing every time Com2uS
reshuffles a menu.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import cv2
import numpy as np

from .adb import AdbDevice
from .config import ConfigError, Flow, Phase, Step
from .ocr import Ocr, OcrError, Word, similar
from .vision import Match, TemplateStore

log = logging.getLogger(__name__)


class StepTimeout(RuntimeError):
    """A step waited for something that never showed up."""


class AbortAccount(RuntimeError):
    """Give up on this account and recycle it. Not a crash."""


@dataclass
class Context:
    device: AdbDevice
    store: TemplateStore
    flow: Flow
    threshold: float = 0.85
    step_timeout: float = 45.0
    poll_interval: float = 0.6
    out_dir: Path | None = None
    save_shots: bool = True
    #  Set by the `evaluate` action.
    keep: bool = False
    hits: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    account_id: str = "acct"
    #  OCR is optional -- a flow that only does template matching never
    #  touches it, and tesseract is only required if a flow asks for text.
    ocr: Ocr | None = None
    #  Values captured by `read_text` / `read_number`, usable in later steps
    #  and written out with the account's result row.
    vars: dict[str, Any] = field(default_factory=dict)

    def require_ocr(self) -> Ocr:
        if self.ocr is None:
            raise ConfigError(
                "this flow uses an OCR step but no OCR engine is configured"
            )
        return self.ocr

    def screen(self) -> np.ndarray:
        return self.device.screencap()

    def save_shot(self, name: str, img: np.ndarray | None = None) -> Path | None:
        if not self.save_shots or self.out_dir is None:
            return None
        img = self.screen() if img is None else img
        d = Path(self.out_dir) / "shots"
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{self.account_id}-{name}.png"
        cv2.imwrite(str(path), img)
        return path


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _targets(step: Step) -> list[str]:
    """`target: foo` or `targets: [foo, bar]`, normalised to a list."""
    if "targets" in step.raw:
        value = step.raw["targets"]
        return [str(v) for v in (value if isinstance(value, list) else [value])]
    if "target" in step.raw:
        return [str(step.raw["target"])]
    return []


def _resolve_point(ctx: Context, point: Any) -> tuple[int, int]:
    """Accept [0.5, 0.9] as fractions of the screen or [640, 360] as pixels."""
    if not isinstance(point, (list, tuple)) or len(point) != 2:
        raise ConfigError(f"expected a two-element point, got {point!r}")
    x, y = float(point[0]), float(point[1])
    if 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0:
        w, h = ctx.device.screen_size()
        return int(x * w), int(y * h)
    return int(x), int(y)


def _region(step: Step) -> tuple[float, float, float, float] | None:
    region = step.get("region")
    if region is None:
        return None
    if not isinstance(region, (list, tuple)) or len(region) != 4:
        raise ConfigError(f"'region' must be [x, y, w, h] fractions, got {region!r}")
    return tuple(float(v) for v in region)  # type: ignore[return-value]


def _threshold(ctx: Context, step: Step) -> float:
    return float(step.get("threshold", ctx.threshold))


def _look(ctx: Context, step: Step, names: list[str]) -> tuple[str | None, Match]:
    screen = ctx.screen()
    return ctx.store.find_any(
        screen, names, threshold=_threshold(ctx, step), region=_region(step)
    )


def _wait_for(
    ctx: Context, step: Step, names: list[str], timeout: float
) -> tuple[str, Match]:
    deadline = time.monotonic() + timeout
    best = Match(found=False, score=0.0)
    while time.monotonic() < deadline:
        name, match = _look(ctx, step, names)
        if match.found and name:
            return name, match
        if match.score > best.score:
            best = match
        time.sleep(ctx.poll_interval)
    raise StepTimeout(
        f"waited {timeout:.0f}s for {names} (best score {best.score:.2f}, "
        f"need {_threshold(ctx, step):.2f})"
    )


# --------------------------------------------------------------------------
# actions
# --------------------------------------------------------------------------

Handler = Callable[[Context, Step], None]
ACTIONS: dict[str, Handler] = {}


def action(name: str) -> Callable[[Handler], Handler]:
    def register(fn: Handler) -> Handler:
        ACTIONS[name] = fn
        return fn
    return register


@action("wait")
def _act_wait(ctx: Context, step: Step) -> None:
    time.sleep(float(step.get("seconds", step.get("target", 1.0))))


@action("tap")
def _act_tap(ctx: Context, step: Step) -> None:
    """Tap a template once it is on screen, or tap a fixed point."""
    names = _targets(step)
    if not names:
        point = step.get("at") or step.get("point")
        if point is None:
            raise ConfigError("tap needs either 'target'/'targets' or 'at'")
        x, y = _resolve_point(ctx, point)
        ctx.device.tap(x, y)
        return

    timeout = float(step.get("timeout", ctx.step_timeout))
    try:
        name, match = _wait_for(ctx, step, names, timeout)
    except StepTimeout:
        if step.get("optional"):
            log.debug("optional tap %s: not present, skipping", names)
            return
        raise
    offset = step.get("offset") or [0, 0]
    ctx.device.tap(match.center[0] + int(offset[0]), match.center[1] + int(offset[1]))
    log.debug("tapped %s at %s (score %.2f)", name, match.center, match.score)
    if step.get("after"):
        time.sleep(float(step["after"]))


@action("wait_for")
def _act_wait_for(ctx: Context, step: Step) -> None:
    names = _targets(step)
    if not names:
        raise ConfigError("wait_for needs 'target' or 'targets'")
    timeout = float(step.get("timeout", ctx.step_timeout))
    try:
        name, match = _wait_for(ctx, step, names, timeout)
    except StepTimeout:
        if step.get("optional"):
            return
        raise
    if step.get("then_tap"):
        ctx.device.tap(*match.center)


@action("wait_gone")
def _act_wait_gone(ctx: Context, step: Step) -> None:
    """Block until a template stops being visible -- loading spinners, mostly."""
    names = _targets(step)
    timeout = float(step.get("timeout", ctx.step_timeout))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        _, match = _look(ctx, step, names)
        if not match.found:
            return
        time.sleep(ctx.poll_interval)
    if not step.get("optional"):
        raise StepTimeout(f"{names} still on screen after {timeout:.0f}s")


@action("tap_through")
def _act_tap_through(ctx: Context, step: Step) -> None:
    """Hammer a point until an expected screen appears.

    This is the tutorial-skipper. Cutscenes, dialogue boxes and 'tap to
    continue' prompts all fall to the same treatment, and unlike a fixed
    sleep it exits the moment the target screen is actually up.
    """
    names = _targets(step)
    if not names:
        raise ConfigError("tap_through needs 'target'/'targets' to stop on")
    point = step.get("at") or [0.5, 0.85]
    x, y = _resolve_point(ctx, point)
    timeout = float(step.get("timeout", ctx.step_timeout))
    interval = float(step.get("interval", 0.8))
    deadline = time.monotonic() + timeout
    best = Match(found=False, score=0.0)

    while time.monotonic() < deadline:
        name, match = _look(ctx, step, names)
        if match.found and name:
            log.debug("tap_through reached %s", name)
            return
        best = match if match.score > best.score else best
        ctx.device.tap(x, y)
        time.sleep(interval)

    if step.get("optional"):
        return
    raise StepTimeout(
        f"tap_through never reached {names} in {timeout:.0f}s "
        f"(best score {best.score:.2f})"
    )


@action("dismiss")
def _act_dismiss(ctx: Context, step: Step) -> None:
    """Close every popup we recognise, repeatedly, until the screen settles.

    A fresh account is buried in event banners, attendance popups and pack
    offers. This clears whatever is stacked up without caring about order.
    """
    names = _targets(step) or ctx.store.group("close")
    if not names:
        return
    rounds = int(step.get("rounds", 8))
    for _ in range(rounds):
        name, match = _look(ctx, step, names)
        if not (match.found and name):
            return
        ctx.device.tap(*match.center)
        log.debug("dismissed %s", name)
        time.sleep(float(step.get("interval", 0.7)))


@action("swipe")
def _act_swipe(ctx: Context, step: Step) -> None:
    x1, y1 = _resolve_point(ctx, step.require("from"))
    x2, y2 = _resolve_point(ctx, step.require("to"))
    ctx.device.swipe(x1, y1, x2, y2, int(step.get("duration_ms", 300)))


@action("key")
def _act_key(ctx: Context, step: Step) -> None:
    ctx.device.key(str(step.get("target", step.get("code", "KEYCODE_BACK"))))


@action("back")
def _act_back(ctx: Context, step: Step) -> None:
    ctx.device.back()


@action("text")
def _act_text(ctx: Context, step: Step) -> None:
    value = str(step.require("value"))
    ctx.device.text(value.replace("{account}", ctx.account_id))


@action("screenshot")
def _act_screenshot(ctx: Context, step: Step) -> None:
    path = ctx.save_shot(str(step.get("name", "shot")))
    if path:
        log.info("saved %s", path)


@action("start_app")
def _act_start_app(ctx: Context, step: Step) -> None:
    ctx.device.start_app(ctx.flow.package)
    time.sleep(float(step.get("after", 3.0)))


@action("stop_app")
def _act_stop_app(ctx: Context, step: Step) -> None:
    ctx.device.stop_app(ctx.flow.package)
    time.sleep(float(step.get("after", 2.0)))


@action("restart_app")
def _act_restart_app(ctx: Context, step: Step) -> None:
    ctx.device.stop_app(ctx.flow.package)
    time.sleep(2.0)
    ctx.device.start_app(ctx.flow.package)
    time.sleep(float(step.get("after", 4.0)))


@action("clear_data")
def _act_clear_data(ctx: Context, step: Step) -> None:
    """Discard the account. `pm clear` wipes the guest login along with it."""
    ctx.device.stop_app(ctx.flow.package)
    time.sleep(1.5)
    ctx.device.clear_app_data(ctx.flow.package)
    log.info("%s: wiped app data", ctx.device.serial)
    time.sleep(float(step.get("after", 2.0)))


@action("evaluate")
def _act_evaluate(ctx: Context, step: Step) -> None:
    """Decide whether this account is worth keeping.

    Every PNG under templates/<group>/ is a keeper condition. Drop a crop of
    the monster portrait (or of the 5-star + dark-element frame) in there and
    a match on the summon result screen banks the account.
    """
    group = str(step.get("group", "keepers"))
    names = _targets(step) or ctx.store.group(group)
    if not names:
        if step.get("optional"):
            return
        raise ConfigError(
            f"evaluate: no templates found under templates/{group}/. "
            f"Without at least one, every account looks like a miss."
        )
    screen = ctx.screen()
    threshold = _threshold(ctx, step)
    region = _region(step)

    hits = []
    for name in names:
        match = ctx.store.find(screen, name, threshold=threshold, region=region)
        if match.found:
            hits.append(name)
            log.info("HIT %s (score %.2f)", name, match.score)

    ctx.hits.extend(hits)
    if hits:
        ctx.keep = True
        ctx.save_shot("KEEP", screen)
    elif step.get("save_misses"):
        ctx.save_shot("miss", screen)


@action("evaluate_grade")
def _act_evaluate_grade(ctx: Context, step: Step) -> None:
    """Keeper check by natural grade and element, not by name.

    For "any LD nat 5" this beats a name roster: it counts the star glyphs and
    reads the element icon, so it keeps working when Com2uS releases a
    Light/Dark monster nobody has heard of yet, and it never stakes the run on
    OCR reading a stylised name correctly.

    The two mistakes here are not equally expensive. Banking a junk account
    costs two minutes of manual checking. Wiping a real LD5 costs the entire
    run and, worse, is silent -- you would grind hundreds of accounts and
    never learn why nothing hit. So when the element cannot be identified at
    all, this fails towards keeping.
    """
    star = str(step.get("star_template", "ui/star"))
    min_stars = int(step.get("min_stars", 5))
    star_region = step.get("star_region")
    if star_region is not None:
        star_region = tuple(float(v) for v in star_region)

    screen = ctx.screen()
    threshold = _threshold(ctx, step)

    stars = ctx.store.find_all(
        screen, star, threshold=threshold, region=star_region, max_hits=8
    )
    count = len(stars)
    ctx.vars["stars"] = count

    elements = step.get("elements") or {}
    elem_region = step.get("element_region")
    if elem_region is not None:
        elem_region = tuple(float(v) for v in elem_region)

    # Identify the element positively. Listing all five (not just light and
    # dark) is what turns "no match" from the common case into a real signal:
    # if fire matched, we KNOW it is not an LD5 and can wipe with confidence.
    element, best_score = None, 0.0
    for label, tpl in elements.items():
        m = ctx.store.find(screen, str(tpl), threshold=threshold, region=elem_region)
        if m.found and m.score > best_score:
            element, best_score = str(label), m.score
    ctx.vars["element"] = element
    ctx.vars["element_score"] = round(best_score, 3)

    keep_elements = [str(e) for e in (step.get("keep_elements") or [])]
    ok_stars = count >= min_stars
    log.info("grade: %d stars, element=%s (%.2f)", count, element, best_score)

    # --- keeper ----------------------------------------------------------
    if ok_stars and (not keep_elements or element in keep_elements):
        tag = f"{count}star-{element or 'unknown'}"
        ctx.keep = True
        ctx.hits.append(tag)
        log.warning("KEEPER by grade: %s", tag)
        ctx.save_shot("KEEP")
        return

    # --- ambiguous: right grade, but the element could not be read --------
    if ok_stars and element is None and keep_elements:
        unknown = str(step.get("on_unknown_element", "keep")).lower()
        if unknown == "keep":
            ctx.keep = True
            ctx.hits.append(f"{count}star-UNVERIFIED")
            ctx.notes.append("element-unreadable")
            log.warning(
                "nat %d with an UNREADABLE element -- banking it rather than "
                "risking a wipe. Check the KEEP screenshot by hand, then fix "
                "element_region / the element templates: if this fires often, "
                "element detection is broken and real LD5s are at risk.",
                count,
            )
            ctx.save_shot("KEEP-unverified")
            return
        log.warning(
            "nat %d with an unreadable element, discarding per "
            "on_unknown_element=discard", count,
        )

    # --- not a keeper ----------------------------------------------------
    # A nat 5 of the wrong element is still worth recording: it is the only
    # way to see whether the mystical scrolls are earning their time.
    if ok_stars:
        ctx.notes.append(f"nat{count}-{element or 'unknown'}")
        if step.get("save_notable"):
            ctx.save_shot(f"nat{count}-{element or 'unknown'}")
    elif element in keep_elements and step.get("save_notable"):
        # A light/dark monster below the star threshold. Almost always a
        # legitimate LD 3/4-star, but it is also exactly what a miscounted
        # LD5 looks like, so keep an audit trail.
        ctx.save_shot(f"ld-{count}star")
    elif step.get("save_misses"):
        ctx.save_shot("miss")


@action("if_found")
def _act_if_found(ctx: Context, step: Step) -> None:
    names = _targets(step)
    _, match = _look(ctx, step, names)
    branch = step.get("then") if match.found else step.get("else")
    if branch:
        run_steps(ctx, _coerce_steps(branch))


@action("repeat")
def _act_repeat(ctx: Context, step: Step) -> None:
    times = int(step.get("times", 1))
    body = _coerce_steps(step.require("steps"))
    for i in range(times):
        log.debug("repeat %d/%d", i + 1, times)
        run_steps(ctx, body)


@action("note")
def _act_note(ctx: Context, step: Step) -> None:
    ctx.notes.append(str(step.get("text", step.get("target", ""))))


@action("abort")
def _act_abort(ctx: Context, step: Step) -> None:
    raise AbortAccount(str(step.get("reason", "flow requested abort")))


# ---- OCR actions ---------------------------------------------------------
#
# These are the reason a fresh target does not need a new screenshot. Adding
# a monster to the wanted list is one line of YAML.

def _ocr_kwargs(step: Step) -> dict[str, Any]:
    kw: dict[str, Any] = {}
    if "psm" in step.raw:
        kw["psm"] = int(step.raw["psm"])
    if "invert" in step.raw:
        kw["invert"] = bool(step.raw["invert"])
    if "upscale" in step.raw:
        kw["upscale"] = float(step.raw["upscale"])
    return kw


@action("read_text")
def _act_read_text(ctx: Context, step: Step) -> None:
    """OCR a region and stash it under `into`."""
    ocr = ctx.require_ocr()
    key = str(step.get("into", "text"))
    value = ocr.read(ctx.screen(), _region(step), **_ocr_kwargs(step))
    ctx.vars[key] = value
    log.info("read %s = %r", key, value)


@action("read_number")
def _act_read_number(ctx: Context, step: Step) -> None:
    ocr = ctx.require_ocr()
    key = str(step.get("into", "number"))
    value = ocr.read_int(ctx.screen(), _region(step), default=None, **_ocr_kwargs(step))
    ctx.vars[key] = value
    log.info("read %s = %r", key, value)


@action("wait_for_text")
def _act_wait_for_text(ctx: Context, step: Step) -> None:
    """Wait until a phrase is legible on screen. The OCR twin of wait_for."""
    ocr = ctx.require_ocr()
    needle = str(step.require("text"))
    timeout = float(step.get("timeout", ctx.step_timeout))
    ratio = float(step.get("min_ratio", 0.8))
    region = _region(step)
    kw = _ocr_kwargs(step)
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        hit = ocr.find_text(ctx.screen(), needle, region, min_ratio=ratio, **kw)
        if hit:
            if step.get("then_tap"):
                ctx.device.tap(*hit.center)
            return
        time.sleep(ctx.poll_interval)
    if step.get("optional"):
        return
    raise StepTimeout(f"text {needle!r} never appeared within {timeout:.0f}s")


@action("tap_text")
def _act_tap_text(ctx: Context, step: Step) -> None:
    """Find a word on screen by OCR and tap its bounding box.

    Text buttons -- Summon, Confirm, Skip, Next, Start -- need no templates
    at all this way, which is most of what a tutorial skip has to click.
    """
    ocr = ctx.require_ocr()
    needle = str(step.require("text"))
    timeout = float(step.get("timeout", ctx.step_timeout))
    ratio = float(step.get("min_ratio", 0.8))
    region = _region(step)
    kw = _ocr_kwargs(step)
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        hit = ocr.find_text(ctx.screen(), needle, region, min_ratio=ratio, **kw)
        if hit:
            offset = step.get("offset") or [0, 0]
            ctx.device.tap(hit.center[0] + int(offset[0]), hit.center[1] + int(offset[1]))
            log.debug("tapped text %r at %s (conf %.0f)", hit.text, hit.center, hit.conf)
            if step.get("after"):
                time.sleep(float(step["after"]))
            return
        time.sleep(ctx.poll_interval)
    if step.get("optional"):
        return
    raise StepTimeout(f"could not find tappable text {needle!r} in {timeout:.0f}s")


@action("evaluate_names")
def _act_evaluate_names(ctx: Context, step: Step) -> None:
    """Keeper check by monster name rather than by reference image.

    Reads the name off the summon result screen and compares it -- fuzzily,
    because stylised game fonts confuse Tesseract in predictable ways -- to
    the wanted list.
    """
    ocr = ctx.require_ocr()
    wanted = step.get("wanted") or ctx.flow.defaults.get("wanted") or []
    if not wanted:
        raise ConfigError(
            "evaluate_names needs a 'wanted' list (or defaults.wanted in the flow)"
        )
    wanted = [str(w) for w in wanted]
    region = _region(step)
    ratio = float(step.get("min_ratio", 0.82))

    hit, raw, score = ocr.match_any(
        ctx.screen(), wanted, region, min_ratio=ratio, **_ocr_kwargs(step)
    )
    ctx.vars["summoned"] = raw
    log.info("summon read as %r (best %.2f)", raw, score)

    if hit:
        ctx.keep = True
        ctx.hits.append(hit)
        log.warning("KEEPER: %s (read %r, %.2f)", hit, raw, score)
        ctx.save_shot("KEEP")
    elif step.get("save_misses"):
        ctx.save_shot(f"miss-{(raw or 'unread')[:24].replace('/', '_')}")


def _coerce_steps(raw: Any) -> list[Step]:
    from .config import as_steps  # local import keeps the module graph flat
    return as_steps(raw, "<inline>")


# --------------------------------------------------------------------------
# driver
# --------------------------------------------------------------------------

def run_steps(ctx: Context, steps: list[Step]) -> None:
    for step in steps:
        handler = ACTIONS.get(step.action)
        if handler is None:
            raise ConfigError(
                f"Unknown action {step.action!r}. Known actions: "
                f"{', '.join(sorted(ACTIONS))}"
            )
        log.debug("-> %s", step.label)
        handler(ctx, step)


def run_phase(ctx: Context, phase: Phase) -> bool:
    """Returns True if the phase completed, False if an optional phase bailed."""
    log.info("%s: phase %s", ctx.device.serial, phase.name)
    try:
        run_steps(ctx, phase.steps)
        return True
    except StepTimeout as exc:
        if phase.optional:
            log.warning("%s: optional phase %s skipped (%s)", ctx.device.serial, phase.name, exc)
            ctx.notes.append(f"skipped:{phase.name}")
            return False
        ctx.save_shot(f"TIMEOUT-{phase.name}")
        raise
