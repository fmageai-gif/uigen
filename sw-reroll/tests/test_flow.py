"""The interpreter, exercised against a fake device -- no adb, no emulator."""

import pytest

from swreroll.config import Flow, Phase, as_steps
from swreroll.flow import AbortAccount, StepTimeout, run_phase, run_steps
from swreroll.config import ConfigError
from tests.conftest import FakeDevice, make_screen, stamp


def steps(raw):
    return as_steps(raw, "test")


def test_tap_a_fixed_fractional_point(ctx_factory):
    dev = FakeDevice()
    ctx = ctx_factory(dev)
    run_steps(ctx, steps([{"tap": {"at": [0.5, 0.25]}}]))
    assert dev.taps == [(640, 180)]


def test_tap_absolute_pixels_are_passed_through(ctx_factory):
    dev = FakeDevice()
    ctx = ctx_factory(dev)
    run_steps(ctx, steps([{"tap": {"at": [900, 400]}}]))
    assert dev.taps == [(900, 400)]


def test_tap_waits_for_the_template_then_taps_its_centre(ctx_factory, badge):
    #  Two blank frames, then the button appears.
    screens = [make_screen(), make_screen(), stamp(make_screen(), badge, 300, 200)]
    dev = FakeDevice(screens)
    ctx = ctx_factory(dev, step_timeout=5.0)
    run_steps(ctx, steps([{"tap": {"target": "ui/badge", "threshold": 0.9}}]))
    assert len(dev.taps) == 1
    assert dev.taps[0] == pytest.approx((345, 230), abs=4)


def test_tap_on_a_missing_template_times_out(ctx_factory):
    ctx = ctx_factory(FakeDevice(), step_timeout=0.15)
    with pytest.raises(StepTimeout, match="ui/badge"):
        run_steps(ctx, steps([{"tap": {"target": "ui/badge"}}]))


def test_optional_tap_is_skipped_rather_than_raising(ctx_factory):
    dev = FakeDevice()
    ctx = ctx_factory(dev, step_timeout=0.15)
    run_steps(ctx, steps([{"tap": {"target": "ui/badge", "optional": True}}]))
    assert dev.taps == []


def test_tap_through_hammers_until_the_target_shows(ctx_factory, badge):
    screens = [make_screen()] * 4 + [stamp(make_screen(), badge, 100, 100)]
    dev = FakeDevice(screens)
    ctx = ctx_factory(dev, step_timeout=5.0)
    run_steps(ctx, steps([
        {"tap_through": {"target": "ui/badge", "at": [0.5, 0.9], "interval": 0.01}}
    ]))
    #  It tapped while waiting, and stopped once the screen was recognised.
    assert 1 <= len(dev.taps) <= 6
    assert set(dev.taps) == {(640, 648)}


def test_tap_through_that_never_arrives_raises(ctx_factory):
    ctx = ctx_factory(FakeDevice(), step_timeout=0.2)
    with pytest.raises(StepTimeout, match="tap_through"):
        run_steps(ctx, steps([{"tap_through": {"target": "ui/badge", "interval": 0.01}}]))


def test_dismiss_closes_popups_until_the_screen_is_clean(ctx_factory, badge):
    popup = stamp(make_screen(), badge, 500, 400)
    dev = FakeDevice([popup, popup, make_screen()])
    ctx = ctx_factory(dev)
    run_steps(ctx, steps([
        {"dismiss": {"target": "ui/badge", "rounds": 5, "interval": 0.01}}
    ]))
    assert len(dev.taps) == 2  # two popups closed, then it stopped


def test_wait_gone_returns_once_the_spinner_clears(ctx_factory, badge):
    dev = FakeDevice([stamp(make_screen(), badge, 10, 10), make_screen()])
    ctx = ctx_factory(dev, step_timeout=5.0)
    run_steps(ctx, steps([{"wait_gone": {"target": "ui/badge"}}]))


def test_if_found_takes_the_else_branch_when_absent(ctx_factory):
    dev = FakeDevice()
    ctx = ctx_factory(dev)
    run_steps(ctx, steps([{
        "if_found": {
            "target": "ui/badge",
            "then": [{"tap": {"at": [0, 0]}}],
            "else": [{"tap": {"at": [100, 100]}}],
        }
    }]))
    assert dev.taps == [(100, 100)]


def test_repeat_runs_the_body_n_times(ctx_factory):
    dev = FakeDevice()
    ctx = ctx_factory(dev)
    run_steps(ctx, steps([{"repeat": {"times": 3, "steps": [{"back": {}}]}}]))
    assert dev.keys == ["KEYCODE_BACK"] * 3


def test_evaluate_marks_a_keeper(ctx_factory, badge, tmp_path, store):
    import cv2
    cv2.imwrite(str(tmp_path / "keepers" / "ariel.png"), badge)
    dev = FakeDevice([stamp(make_screen(), badge, 600, 300)])
    ctx = ctx_factory(dev)
    run_steps(ctx, steps([{"evaluate": {"group": "keepers", "threshold": 0.9}}]))
    assert ctx.keep is True
    assert ctx.hits == ["keepers/ariel"]


def test_evaluate_leaves_keep_false_on_a_miss(ctx_factory, badge, tmp_path):
    import cv2
    cv2.imwrite(str(tmp_path / "keepers" / "ariel.png"), badge)
    ctx = ctx_factory(FakeDevice([make_screen()]))
    run_steps(ctx, steps([{"evaluate": {"group": "keepers", "threshold": 0.9}}]))
    assert ctx.keep is False
    assert ctx.hits == []


def test_evaluate_without_any_keeper_templates_is_a_config_error(ctx_factory):
    ctx = ctx_factory(FakeDevice())
    with pytest.raises(ConfigError, match="no templates"):
        run_steps(ctx, steps([{"evaluate": {"group": "keepers"}}]))


def test_clear_data_stops_the_app_first(ctx_factory):
    dev = FakeDevice()
    flow = Flow(package="com.example.game", phases={}, order=[])
    ctx = ctx_factory(dev, flow=flow)
    run_steps(ctx, steps([{"clear_data": {"after": 0}}]))
    assert dev.calls == [("stop", "com.example.game"), ("clear", "com.example.game")]


def test_abort_raises_abort_account(ctx_factory):
    ctx = ctx_factory(FakeDevice())
    with pytest.raises(AbortAccount, match="stuck"):
        run_steps(ctx, steps([{"abort": {"reason": "stuck"}}]))


def test_unknown_action_lists_the_valid_ones(ctx_factory):
    ctx = ctx_factory(FakeDevice())
    with pytest.raises(ConfigError, match="Known actions"):
        run_steps(ctx, steps([{"teleport": {}}]))


def test_optional_phase_swallows_a_timeout(ctx_factory):
    ctx = ctx_factory(FakeDevice(), step_timeout=0.1)
    phase = Phase(name="popups", steps=steps([{"wait_for": {"target": "ui/badge"}}]), optional=True)
    assert run_phase(ctx, phase) is False
    assert "skipped:popups" in ctx.notes


def test_required_phase_propagates_a_timeout(ctx_factory):
    ctx = ctx_factory(FakeDevice(), step_timeout=0.1)
    phase = Phase(name="summon", steps=steps([{"wait_for": {"target": "ui/badge"}}]))
    with pytest.raises(StepTimeout):
        run_phase(ctx, phase)


def test_ocr_step_without_an_engine_fails_loudly(ctx_factory):
    ctx = ctx_factory(FakeDevice())
    with pytest.raises(ConfigError, match="OCR"):
        run_steps(ctx, steps([{"read_text": {"region": [0, 0, 1, 1]}}]))
