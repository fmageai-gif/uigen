"""
Action / step model for the auto-clicker.

A routine is an ordered list of Step objects. Each Step has a `type`, a
`params` dict, and a `delay` (milliseconds to wait *after* the step runs).

Conditional flow is expressed with block markers:

    IF <condition>
        ... steps ...
    ELSE            (optional)
        ... steps ...
    ENDIF

Blocks may be nested. The engine (see engine.py) resolves the matching
ELSE/ENDIF for every IF before playback.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any


# ---- Step type constants -------------------------------------------------

# Input actions
CLICK = "click"                 # click at a fixed x,y (button = left/right/middle)
DOUBLE_CLICK = "double_click"
MOVE = "move"                   # move cursor to x,y
DRAG = "drag"                   # press at x,y, move to x2,y2, release
SCROLL = "scroll"               # scroll wheel by `amount` (negative = down)
IMAGE_CLICK = "image_click"     # find image on screen, then click it
KEY = "key"                     # press a key / hotkey combo, e.g. "ctrl+c", "enter"
TEXT = "text"                   # type a string of text
WAIT = "wait"                   # explicit pause (ms held in delay)

# Flow control
IF = "if"
ELSE = "else"
ENDIF = "endif"
LABEL = "label"
GOTO = "goto"

BLOCK_TYPES = {IF, ELSE, ENDIF}

# ---- Condition kinds (used by IF steps) ----------------------------------

COND_IMAGE_FOUND = "image_found"
COND_IMAGE_NOT_FOUND = "image_not_found"
COND_PIXEL_COLOR = "pixel_color"      # pixel at x,y ~= color (hex) within tolerance
COND_PIXEL_NOT_COLOR = "pixel_not_color"


@dataclass
class Step:
    type: str
    params: dict[str, Any] = field(default_factory=dict)
    delay: int = 1000  # ms after the step
    label: str = ""    # optional human name, shown in the "Action" column group

    # runtime-only fields (never serialised): index of matching else/endif
    _else: int = -1
    _endif: int = -1

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "params": self.params,
            "delay": self.delay,
            "label": self.label,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Step":
        return cls(
            type=d.get("type", WAIT),
            params=d.get("params", {}) or {},
            delay=int(d.get("delay", 0) or 0),
            label=d.get("label", "") or "",
        )

    def copy(self) -> "Step":
        return Step(
            type=self.type,
            params=copy.deepcopy(self.params),
            delay=self.delay,
            label=self.label,
        )

    # -- human-readable description for the step list -----------------------

    def describe(self) -> str:
        p = self.params
        t = self.type
        if t == CLICK:
            btn = p.get("button", "left")
            return f'{btn.capitalize()} click at X:{p.get("x", 0)} Y:{p.get("y", 0)}'
        if t == DOUBLE_CLICK:
            return f'Double click at X:{p.get("x", 0)} Y:{p.get("y", 0)}'
        if t == MOVE:
            return f'Move mouse to X:{p.get("x", 0)} Y:{p.get("y", 0)}'
        if t == DRAG:
            return (f'Drag from X:{p.get("x", 0)} Y:{p.get("y", 0)} '
                    f'to X:{p.get("x2", 0)} Y:{p.get("y2", 0)}')
        if t == SCROLL:
            amt = p.get("amount", 0)
            return f'Scroll {"up" if amt >= 0 else "down"} {abs(amt)}'
        if t == IMAGE_CLICK:
            btn = p.get("button", "left")
            name = p.get("image", "?")
            conf = p.get("confidence", 0.8)
            if p.get("wait", False):
                to = p.get("timeout", 0)
                limit = f", up to {to}s" if to else ", waits forever"
                return f'Wait for image "{name}", then {btn} click (match ≥ {conf:.0%}{limit})'
            return f'Find image "{name}" and {btn} click (match ≥ {conf:.0%})'
        if t == KEY:
            return f'Keystroke "{p.get("keys", "")}"'
        if t == TEXT:
            return f'Type text "{p.get("text", "")}"'
        if t == WAIT:
            return f'Wait {self.delay} ms'
        if t == IF:
            return f'IF {describe_condition(p)}'
        if t == ELSE:
            return "ELSE"
        if t == ENDIF:
            return "END IF"
        if t == LABEL:
            return f'Label: {p.get("name", "")}'
        if t == GOTO:
            return f'Go to label: {p.get("name", "")}'
        return t


def describe_condition(p: dict[str, Any]) -> str:
    kind = p.get("cond", COND_IMAGE_FOUND)
    if kind == COND_IMAGE_FOUND:
        return f'image "{p.get("image", "?")}" is found'
    if kind == COND_IMAGE_NOT_FOUND:
        return f'image "{p.get("image", "?")}" is NOT found'
    if kind == COND_PIXEL_COLOR:
        return f'pixel X:{p.get("x", 0)} Y:{p.get("y", 0)} is {p.get("color", "#000000")}'
    if kind == COND_PIXEL_NOT_COLOR:
        return f'pixel X:{p.get("x", 0)} Y:{p.get("y", 0)} is NOT {p.get("color", "#000000")}'
    return kind


def indent_of(steps: list[Step]) -> list[int]:
    """Return the visual indent level for each step (for the tree view)."""
    levels: list[int] = []
    depth = 0
    for s in steps:
        if s.type in (ELSE, ENDIF):
            levels.append(max(0, depth - 1))
        else:
            levels.append(depth)
        if s.type == IF:
            depth += 1
        elif s.type == ENDIF:
            depth = max(0, depth - 1)
    return levels
