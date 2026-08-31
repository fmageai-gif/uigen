"""Runner behaviour. The invariant that matters: a keeper is never wiped."""

import json

import pytest

from swreroll.config import Flow, Phase, RunConfig, as_steps
from swreroll.runner import Runner
from tests.conftest import FakeDevice


def build_flow(**phase_overrides):
    phases = {
        "summon": Phase(name="summon", steps=as_steps([{"back": {}}], "t")),
        "evaluate": Phase(name="evaluate", steps=as_steps([], "t")),
        "reset": Phase(name="reset", steps=as_steps([{"clear_data": {"after": 0}}], "t")),
    }
    phases.update(phase_overrides)
    return Flow(
        package="com.example.game",
        phases=phases,
        order=["summon", "evaluate", "reset"],
    )


def build_runner(tmp_path, flow, **cfg):
    cfg.setdefault("max_accounts", 1)
    return Runner(
        RunConfig(
            flow_path=tmp_path / "flow.yaml",
            templates_dir=tmp_path / "templates",
            out_dir=tmp_path / "run",
            serials=["fake:5555"],
            **cfg,
        ),
        flow,
    )


def test_a_miss_wipes_the_account(tmp_path):
    runner = build_runner(tmp_path, build_flow())
    dev = FakeDevice()
    result = runner._run_account(dev, 1)
    assert result.keep is False
    assert ("clear", "com.example.game") in dev.calls


def test_a_keeper_is_never_wiped(tmp_path, monkeypatch):
    """If this ever regresses, the tool throws away the account it was built to find."""
    import swreroll.runner as runnermod

    flow = build_flow()
    runner = build_runner(tmp_path, flow)
    dev = FakeDevice()

    real = runnermod.run_phase

    def patched(ctx, phase):
        out = real(ctx, phase)
        if phase.name == "evaluate":
            ctx.keep = True
            ctx.hits.append("Beelzebub")
        return out

    monkeypatch.setattr(runnermod, "run_phase", patched)

    result = runner._run_account(dev, 1)
    assert result.keep is True
    assert result.hits == ["Beelzebub"]
    assert ("clear", "com.example.game") not in dev.calls


def test_results_are_appended_to_jsonl(tmp_path):
    runner = build_runner(tmp_path, build_flow())
    runner._record(runner._run_account(FakeDevice(), 1))
    runner._record(runner._run_account(FakeDevice(), 2))

    rows = [
        json.loads(line)
        for line in (tmp_path / "run" / "results.jsonl").read_text().splitlines()
    ]
    assert len(rows) == 2
    assert rows[0]["serial"] == "fake:5555"
    assert set(rows[0]) >= {"keep", "hits", "vars", "seconds", "error", "finished_at"}


def test_stats_track_keeps_and_errors(tmp_path):
    runner = build_runner(tmp_path, build_flow())
    for i in range(3):
        runner._record(runner._run_account(FakeDevice(), i))
    assert runner.stats.accounts == 3
    assert runner.stats.keeps == 0
    assert "accounts/hour" in runner.stats.summary()


def test_a_missing_template_is_recorded_not_raised(tmp_path):
    """A typo in a flow must not take the worker thread down with it."""
    bad = Phase(
        name="summon",
        steps=as_steps([{"wait_for": {"target": "ui/typo", "timeout": 0.1}}], "t"),
    )
    runner = build_runner(tmp_path, build_flow(summon=bad))
    result = runner._run_account(FakeDevice(), 1)
    assert result.keep is False
    assert "config:" in result.error and "ui/typo" in result.error


def test_a_timeout_is_recorded_not_raised(tmp_path):
    (tmp_path / "templates" / "ui").mkdir(parents=True)
    import cv2, numpy as np
    rng = np.random.default_rng(7)
    cv2.imwrite(
        str(tmp_path / "templates" / "ui" / "nope.png"),
        rng.integers(0, 255, (40, 40, 3), dtype=np.uint8),
    )
    slow = Phase(
        name="summon",
        steps=as_steps([{"wait_for": {"target": "ui/nope", "timeout": 0.1}}], "t"),
    )
    runner = build_runner(tmp_path, build_flow(summon=slow))
    result = runner._run_account(FakeDevice(), 1)
    assert result.keep is False
    assert "timeout" in result.error


def test_stop_file_halts_the_loop(tmp_path):
    runner = build_runner(tmp_path, build_flow(), max_accounts=0)
    assert runner._should_stop() is False
    (tmp_path / "run" / "STOP").touch()
    assert runner._should_stop() is True


def test_max_accounts_halts_the_loop(tmp_path):
    runner = build_runner(tmp_path, build_flow(), max_accounts=2)
    for i in range(2):
        runner._record(runner._run_account(FakeDevice(), i))
    assert runner._should_stop() is True


def test_cli_wanted_list_overrides_flow_defaults(tmp_path):
    flow = build_flow()
    flow.defaults["wanted"] = ["Ariel"]
    build_runner(tmp_path, flow, wanted=["Beelzebub", "Zeratu"])
    assert flow.defaults["wanted"] == ["Beelzebub", "Zeratu"]
