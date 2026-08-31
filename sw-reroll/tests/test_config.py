import textwrap

import pytest

from swreroll.config import ConfigError, as_steps, load_flow


def write(tmp_path, body):
    p = tmp_path / "flow.yaml"
    p.write_text(textwrap.dedent(body))
    return p


def test_loads_phases_and_order(tmp_path):
    flow = load_flow(write(tmp_path, """
        package: com.example.game
        defaults:
          wanted: [Ariel, Beelzebub]
        order: [launch, reset]
        phases:
          launch:
            steps:
              - start_app: {after: 2}
              - wait_for: {target: ui/title, timeout: 30}
          reset:
            steps:
              - clear_data: {}
    """))
    assert flow.package == "com.example.game"
    assert flow.order == ["launch", "reset"]
    assert flow.defaults["wanted"] == ["Ariel", "Beelzebub"]
    assert flow.phase("launch").steps[0].action == "start_app"
    assert flow.phase("launch").steps[1].get("target") == "ui/title"


def test_phase_may_be_a_bare_list(tmp_path):
    flow = load_flow(write(tmp_path, """
        phases:
          go:
            - back: {}
            - wait: {seconds: 1}
    """))
    assert [s.action for s in flow.phase("go").steps] == ["back", "wait"]


def test_optional_phase_flag(tmp_path):
    flow = load_flow(write(tmp_path, """
        phases:
          popups:
            optional: true
            steps: [{dismiss: {}}]
    """))
    assert flow.phase("popups").optional is True


def test_order_referencing_unknown_phase_is_rejected(tmp_path):
    with pytest.raises(ConfigError, match="undefined phases"):
        load_flow(write(tmp_path, """
            order: [launch, nope]
            phases:
              launch: {steps: []}
        """))


def test_unknown_phase_lookup_lists_available(tmp_path):
    flow = load_flow(write(tmp_path, "phases:\n  launch: {steps: []}\n"))
    with pytest.raises(ConfigError, match="launch"):
        flow.phase("missing")


def test_step_shorthands():
    steps = as_steps(
        [
            "back",                          # bare string
            {"tap": {"target": "ui/x"}},     # shorthand mapping
            {"action": "wait", "seconds": 3},  # explicit form
            {"wait_for": "ui/y"},            # scalar body becomes `target`
        ],
        "t",
    )
    assert [s.action for s in steps] == ["back", "tap", "wait", "wait_for"]
    assert steps[1].get("target") == "ui/x"
    assert steps[2].get("seconds") == 3
    assert steps[3].get("target") == "ui/y"


def test_missing_required_key_names_the_step():
    step = as_steps([{"swipe": {"from": [0, 0]}}], "t")[0]
    with pytest.raises(ConfigError, match="'to'"):
        step.require("to")


def test_shipped_flow_is_valid():
    """The flow we ship must parse and only use real actions."""
    from pathlib import Path

    from swreroll.flow import ACTIONS

    flow = load_flow(Path(__file__).resolve().parent.parent / "flows" / "summoners_war.yaml")

    def walk(steps):
        for s in steps:
            assert s.action in ACTIONS, f"unknown action {s.action!r}"
            for key in ("steps", "then", "else"):
                if s.get(key):
                    walk(as_steps(s.get(key), "inline"))

    for name in flow.order:
        walk(flow.phase(name).steps)
    # The reset phase must be last, or a keeper could be wiped before it is seen.
    assert flow.order[-1] == "reset"
