"""Records the display geometry templates were captured at.

Templates are pixel crops. They stay valid only while the emulator renders at
the geometry they were cut from -- and resolution is only half of that. DPI
reflows the game's own layout: at tablet density Summoners War lays its UI out
differently than at phone density, at the same 1280x720. Change either and
matching degrades quietly, with no error and no obvious cause; you would just
watch the hit rate collapse and not know why.

So `shot` stamps what it captured at, and `run` refuses to start against a
device that no longer matches.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

log = logging.getLogger(__name__)

MANIFEST = "capture.json"


@dataclass
class Geometry:
    width: int
    height: int
    density: int | None = None

    def __str__(self) -> str:
        dpi = f"{self.density} DPI" if self.density else "unknown DPI"
        return f"{self.width}x{self.height} @ {dpi}"

    def matches(self, other: "Geometry") -> bool:
        if (self.width, self.height) != (other.width, other.height):
            return False
        # An unknown density on either side is not evidence of a mismatch.
        if self.density and other.density and self.density != other.density:
            return False
        return True

    def differences(self, other: "Geometry") -> list[str]:
        out = []
        if (self.width, self.height) != (other.width, other.height):
            out.append(f"resolution {self.width}x{self.height} -> {other.width}x{other.height}")
        if self.density and other.density and self.density != other.density:
            out.append(f"density {self.density} -> {other.density} DPI")
        return out


def manifest_path(templates_dir: str | Path) -> Path:
    return Path(templates_dir) / MANIFEST


def load(templates_dir: str | Path) -> Geometry | None:
    path = manifest_path(templates_dir)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return Geometry(
            width=int(data["width"]),
            height=int(data["height"]),
            density=int(data["density"]) if data.get("density") else None,
        )
    except (ValueError, KeyError, TypeError) as exc:
        log.warning("ignoring unreadable %s: %s", path, exc)
        return None


def save(templates_dir: str | Path, geometry: Geometry) -> Path:
    path = manifest_path(templates_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(geometry), indent=2) + "\n", encoding="utf-8")
    return path


def describe_mismatch(recorded: Geometry, actual: Geometry, serial: str) -> str:
    changes = "; ".join(recorded.differences(actual)) or "geometry changed"
    return (
        f"{serial}: display does not match the templates.\n"
        f"  templates captured at : {recorded}\n"
        f"  this device is now    : {actual}\n"
        f"  changed               : {changes}\n"
        f"Template matching will degrade silently -- the run would look normal "
        f"while missing hits. Either set the emulator back, or recapture the "
        f"templates at the new geometry. Pass --ignore-geometry to override."
    )
