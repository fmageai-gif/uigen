"""GUI smoke tests.

Skipped where tkinter or a display is unavailable, so the suite still runs
headless. Where they do run they catch the class of bug that is invisible
until a user hits it: Tk is not thread-safe, and a worker thread touching a
widget wedges the window rather than raising anywhere visible.
"""

import queue
import time

import pytest

tk = pytest.importorskip("tkinter")


@pytest.fixture
def app():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available")
    from swreroll.gui import App

    instance = App(root)
    root.update()
    yield instance
    root.destroy()


def test_every_button_is_wired(app):
    expected = {
        "1. Connect", "2. Screenshot", "3. Sweep tutorial",
        "Check templates", "Run reroll", "Open folders",
    }
    assert expected <= set(app.buttons)


def test_log_messages_reach_the_widget(app):
    app.log("hello", "good")
    app._drain()
    assert "hello" in app.out.get("1.0", "end")


def test_workers_never_touch_widgets_directly(app):
    """The bug this file exists for.

    Every UI change from a worker must go through the queue. A direct
    root.after() from a worker thread raises 'main thread is not in main
    loop' and leaves the Stop button stuck enabled, with the app unusable.
    """
    app._post_status("connected", "#3ec46d")
    app._post_done()
    app._drain()
    assert app.status["text"] == "connected"
    assert str(app.stop_btn["state"]) == "disabled"


def test_a_failing_action_is_logged_and_resets_the_ui(app):
    def boom():
        raise ValueError("deliberate failure")

    app._go(boom)
    for _ in range(50):
        time.sleep(0.02)
        if not app._busy():
            break
    app._drain()

    assert "deliberate failure" in app.out.get("1.0", "end")
    assert str(app.stop_btn["state"]) == "disabled"


def test_actions_refuse_to_run_before_connecting(app):
    with pytest.raises(RuntimeError, match="Connect"):
        app._need_device()


def test_stop_sets_the_event_workers_watch(app):
    app.stop_event.clear()
    app._stop()
    assert app.stop_event.is_set()
