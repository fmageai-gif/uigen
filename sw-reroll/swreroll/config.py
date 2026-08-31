"""Configuration and flow-file loading."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# Google Play package for the global build of Summoners War: Sky Arena.
# Other stores ship different ids -- confirm yours with:
#   adb shell pm list packages | grep -i smon
DEFAULT_PACKAGE = "com.com2us.smon.normal.freefull.google.kr.android.common"


class ConfigError(RuntimeError):
    pass


@dataclass
class Step:
    """One instruction in a flow."""

    action: str
    raw: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        return self.raw.get(key, default)

    def require(self, key: str) -> Any:
        if key not in self.raw:
            raise ConfigError(f"step {self.action!r} is missing required key {key!r}")
        return self.raw[key]

    @property
    def label(self) -> str:
        return str(self.raw.get("name") or self.action)


@dataclass
class Phase:
    name: str
    steps: list[Step]
    #  A phase marked optional logs and moves on instead of failing the account
    #  when a step times out. Event popups and seasonal banners belong here.
    optional: bool = False


@dataclass
class Flow:
    package: str
    phases: dict[str, Phase]
    order: list[str]
    defaults: dict[str, Any] = field(default_factory=dict)

    def phase(self, name: str) -> Phase:
        if name not in self.phases:
            raise ConfigError(
                f"Unknown phase {name!r}. Available: {', '.join(self.phases)}"
            )
        return self.phases[name]


@dataclass
class RunConfig:
    flow_path: Path
    templates_dir: Path
    out_dir: Path
    serials: list[str] = field(default_factory=list)
    adb_path: str = "adb"
    max_accounts: int = 0          # 0 == unlimited
    max_keeps: int = 1             # stop the device once it banks this many
    match_threshold: float = 0.85
    step_timeout: float = 45.0
    dry_run: bool = False
    save_shots: bool = True
    verbose: bool = False
    # OCR
    tesseract: str = "tesseract"
    tessdata_dir: str | None = None
    lang: str = "eng"
    wanted: list[str] = field(default_factory=list)


def _as_steps(raw: Any, phase_name: str) -> list[Step]:
    if not isinstance(raw, list):
        raise ConfigError(f"phase {phase_name!r}: 'steps' must be a list")
    steps: list[Step] = []
    for i, item in enumerate(raw):
        if isinstance(item, str):
            steps.append(Step(action=item, raw={}))
            continue
        if not isinstance(item, dict) or len(item) == 0:
            raise ConfigError(f"phase {phase_name!r} step {i}: expected a mapping")
        if "action" in item:
            body = dict(item)
            action = body.pop("action")
        else:
            # Shorthand:  - tap: {target: foo}
            action, body = next(iter(item.items()))
            if body is None:
                body = {}
            elif not isinstance(body, dict):
                body = {"target": body}
            else:
                body = dict(body)
        steps.append(Step(action=str(action), raw=body))
    return steps


def load_flow(path: str | Path) -> Flow:
    path = Path(path)
    if not path.is_file():
        raise ConfigError(f"Flow file not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: top level must be a mapping")

    raw_phases = data.get("phases") or {}
    if not raw_phases:
        raise ConfigError(f"{path}: no 'phases' defined")

    phases: dict[str, Phase] = {}
    for name, body in raw_phases.items():
        if isinstance(body, list):
            body = {"steps": body}
        if not isinstance(body, dict):
            raise ConfigError(f"{path}: phase {name!r} must be a mapping or a list")
        phases[name] = Phase(
            name=name,
            steps=_as_steps(body.get("steps", []), name),
            optional=bool(body.get("optional", False)),
        )

    order = data.get("order") or list(phases)
    unknown = [p for p in order if p not in phases]
    if unknown:
        raise ConfigError(f"{path}: 'order' names undefined phases: {unknown}")

    return Flow(
        package=str(data.get("package", DEFAULT_PACKAGE)),
        phases=phases,
        order=list(order),
        defaults=dict(data.get("defaults") or {}),
    )


# Public alias -- the flow interpreter parses inline step lists too.
as_steps = _as_steps
