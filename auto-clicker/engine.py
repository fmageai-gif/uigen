"""
Playback + recording engine for the auto-clicker.

- Recorder: captures mouse clicks/drags/scrolls and keyboard input into Steps
  using pynput (global hooks, works while another window is focused).
- Player: executes a list of Steps, honouring IF/ELSE/ENDIF blocks, loops,
  and a global hotkey (ESC) to abort.
- Screen matching: locate a saved target image on screen with OpenCV template
  matching, and read a pixel colour for conditions.

All OS input during playback goes through pyautogui.
"""

from __future__ import annotations

import os
import time
import threading
from typing import Callable, Optional

import numpy as np

import actions
from actions import Step

# --- Optional heavy deps: fail gracefully with a clear message ------------
try:
    import mss
    import cv2
    HAS_VISION = True
except Exception:  # pragma: no cover
    HAS_VISION = False

try:
    import pyautogui
    pyautogui.FAILSAFE = False   # we provide our own ESC abort
    pyautogui.PAUSE = 0
    HAS_PYAUTOGUI = True
except Exception:  # pragma: no cover
    HAS_PYAUTOGUI = False

try:
    from pynput import mouse as pynmouse, keyboard as pynkeyboard
    HAS_PYNPUT = True
except Exception:  # pragma: no cover
    HAS_PYNPUT = False


# =========================================================================
# Screen helpers
# =========================================================================

def grab_screen(region: Optional[tuple[int, int, int, int]] = None) -> np.ndarray:
    """Return a BGR screenshot. region = (left, top, width, height)."""
    with mss.mss() as sct:
        if region:
            l, t, w, h = region
            mon = {"left": l, "top": t, "width": w, "height": h}
        else:
            mon = sct.monitors[0]  # full virtual screen (all monitors)
        img = np.array(sct.grab(mon))
    return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)


def locate_image(image_path: str, confidence: float = 0.8,
                 region: Optional[tuple[int, int, int, int]] = None
                 ) -> Optional[tuple[int, int, float]]:
    """
    Template-match `image_path` against the screen.
    Returns (center_x, center_y, score) in absolute screen coords, or None.
    """
    if not HAS_VISION or not os.path.exists(image_path):
        return None
    template = cv2.imread(image_path, cv2.IMREAD_COLOR)
    if template is None:
        return None
    screen = grab_screen(region)
    th, tw = template.shape[:2]
    if screen.shape[0] < th or screen.shape[1] < tw:
        return None
    res = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(res)
    if max_val < confidence:
        return None
    off_l = region[0] if region else 0
    off_t = region[1] if region else 0
    cx = off_l + max_loc[0] + tw // 2
    cy = off_t + max_loc[1] + th // 2
    return (cx, cy, float(max_val))


def pixel_color(x: int, y: int) -> tuple[int, int, int]:
    """Return the (r, g, b) colour of the pixel at screen x,y."""
    img = grab_screen((x, y, 1, 1))
    b, g, r = img[0, 0]
    return (int(r), int(g), int(b))


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def color_matches(rgb: tuple[int, int, int], hexcolor: str, tol: int = 20) -> bool:
    target = _hex_to_rgb(hexcolor)
    return all(abs(a - b) <= tol for a, b in zip(rgb, target))


# =========================================================================
# Recorder
# =========================================================================

class Recorder:
    """
    Captures global mouse + keyboard events into Steps.
    Delays are the real elapsed time between events (capped).
    """

    def __init__(self, on_step: Callable[[Step], None]):
        if not HAS_PYNPUT:
            raise RuntimeError("pynput is required for recording (pip install pynput)")
        self.on_step = on_step
        self._mouse_listener = None
        self._kbd_listener = None
        self._last_time = 0.0
        self._press_pos: Optional[tuple[int, int]] = None
        self._press_time = 0.0
        self._typing_buffer = ""
        self.recording = False

    # -- lifecycle ------------------------------------------------------
    def start(self):
        self.recording = True
        self._last_time = time.time()
        self._mouse_listener = pynmouse.Listener(
            on_click=self._on_click, on_scroll=self._on_scroll)
        self._kbd_listener = pynkeyboard.Listener(on_press=self._on_press)
        self._mouse_listener.start()
        self._kbd_listener.start()

    def stop(self):
        self.recording = False
        self._flush_text()
        if self._mouse_listener:
            self._mouse_listener.stop()
        if self._kbd_listener:
            self._kbd_listener.stop()

    # -- timing helper --------------------------------------------------
    def _delay_since_last(self) -> int:
        now = time.time()
        d = min(int((now - self._last_time) * 1000), 10000)
        self._last_time = now
        return max(d, 0)

    def _emit(self, step: Step):
        self.on_step(step)

    # -- mouse ----------------------------------------------------------
    def _on_click(self, x, y, button, pressed):
        if not self.recording:
            return
        btn = "left" if button == pynmouse.Button.left else \
              "right" if button == pynmouse.Button.right else "middle"
        if pressed:
            self._press_pos = (int(x), int(y))
            self._press_time = time.time()
            return
        # released -> decide click vs drag
        self._flush_text()
        delay = self._delay_since_last()
        sx, sy = self._press_pos or (int(x), int(y))
        ex, ey = int(x), int(y)
        moved = abs(ex - sx) > 4 or abs(ey - sy) > 4
        if moved:
            self._emit(Step(actions.DRAG,
                            {"x": sx, "y": sy, "x2": ex, "y2": ey, "button": btn},
                            delay=delay))
        else:
            self._emit(Step(actions.CLICK, {"x": ex, "y": ey, "button": btn},
                            delay=delay))

    def _on_scroll(self, x, y, dx, dy):
        if not self.recording:
            return
        self._flush_text()
        self._emit(Step(actions.SCROLL,
                        {"x": int(x), "y": int(y), "amount": int(dy)},
                        delay=self._delay_since_last()))

    # -- keyboard -------------------------------------------------------
    def _on_press(self, key):
        if not self.recording:
            return
        try:
            char = key.char
        except AttributeError:
            char = None
        if char is not None and char.isprintable() and len(char) == 1:
            # buffer plain typing into a single TEXT step
            self._typing_buffer += char
            return
        # special key -> flush any buffered text, emit a KEY step
        self._flush_text()
        name = _pynput_key_name(key)
        if name:
            self._emit(Step(actions.KEY, {"keys": name},
                            delay=self._delay_since_last()))

    def _flush_text(self):
        if self._typing_buffer:
            self._emit(Step(actions.TEXT, {"text": self._typing_buffer},
                            delay=self._delay_since_last()))
            self._typing_buffer = ""


def _pynput_key_name(key) -> str:
    """Map a pynput special key to a pyautogui key name."""
    try:
        return key.char  # shouldn't happen (handled above) but just in case
    except AttributeError:
        pass
    name = str(key).replace("Key.", "")
    mapping = {
        "enter": "enter", "space": "space", "tab": "tab", "backspace": "backspace",
        "esc": "esc", "delete": "delete", "up": "up", "down": "down",
        "left": "left", "right": "right", "home": "home", "end": "end",
        "page_up": "pageup", "page_down": "pagedown",
        "ctrl_l": "ctrl", "ctrl_r": "ctrl", "alt_l": "alt", "alt_r": "alt",
        "shift": "shift", "shift_l": "shift", "shift_r": "shift",
        "cmd": "win", "cmd_l": "win", "cmd_r": "win",
        "caps_lock": "capslock",
    }
    if name.startswith("f") and name[1:].isdigit():
        return name  # f1..f12
    return mapping.get(name, "")


# =========================================================================
# Player
# =========================================================================

class Player:
    """
    Executes a list of Steps. Runs on a background thread.
    Call stop() (or press ESC) to abort.
    """

    def __init__(self,
                 image_dir: str,
                 on_status: Callable[[str], None] = lambda s: None,
                 on_highlight: Callable[[int], None] = lambda i: None,
                 on_finish: Callable[[], None] = lambda: None):
        self.image_dir = image_dir
        self.on_status = on_status
        self.on_highlight = on_highlight
        self.on_finish = on_finish
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._esc_listener = None

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, steps: list[Step], loops: int = 1):
        if self.is_running():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, args=(steps, loops), daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    # -- ESC global abort ----------------------------------------------
    def _install_esc(self):
        if not HAS_PYNPUT:
            return

        def on_press(key):
            if key == pynkeyboard.Key.esc:
                self._stop.set()
        self._esc_listener = pynkeyboard.Listener(on_press=on_press)
        self._esc_listener.start()

    def _remove_esc(self):
        if self._esc_listener:
            self._esc_listener.stop()
            self._esc_listener = None

    # -- block resolution ----------------------------------------------
    @staticmethod
    def _resolve_blocks(steps: list[Step]):
        """Fill in _else / _endif indices for every IF. Returns None or error str."""
        stack: list[int] = []
        for i, s in enumerate(steps):
            if s.type == actions.IF:
                s._else = -1
                s._endif = -1
                stack.append(i)
            elif s.type == actions.ELSE:
                if not stack:
                    return f"ELSE at step {i+1} has no matching IF"
                steps[stack[-1]]._else = i
            elif s.type == actions.ENDIF:
                if not stack:
                    return f"END IF at step {i+1} has no matching IF"
                if_idx = stack.pop()
                steps[if_idx]._endif = i
                # let the matching ELSE know where the block ends, so a true
                # branch can jump past the else branch to here.
                if steps[if_idx]._else >= 0:
                    steps[steps[if_idx]._else]._endif = i
        if stack:
            return f"IF at step {stack[-1]+1} has no matching END IF"
        return None

    # -- condition evaluation ------------------------------------------
    def _eval_condition(self, p: dict) -> bool:
        kind = p.get("cond", actions.COND_IMAGE_FOUND)
        if kind in (actions.COND_IMAGE_FOUND, actions.COND_IMAGE_NOT_FOUND):
            path = os.path.join(self.image_dir, p.get("image", ""))
            found = locate_image(path, p.get("confidence", 0.8)) is not None
            return found if kind == actions.COND_IMAGE_FOUND else not found
        if kind in (actions.COND_PIXEL_COLOR, actions.COND_PIXEL_NOT_COLOR):
            rgb = pixel_color(int(p.get("x", 0)), int(p.get("y", 0)))
            m = color_matches(rgb, p.get("color", "#000000"), int(p.get("tol", 20)))
            return m if kind == actions.COND_PIXEL_COLOR else not m
        return False

    # -- main loop ------------------------------------------------------
    def _run(self, steps: list[Step], loops: int):
        err = self._resolve_blocks(steps)
        if err:
            self.on_status(f"Error: {err}")
            self.on_finish()
            return
        self._install_esc()
        try:
            loop = 0
            while not self._stop.is_set() and (loops <= 0 or loop < loops):
                loop += 1
                if loops != 1:
                    self.on_status(f"Loop {loop}" + (f"/{loops}" if loops > 0 else ""))
                if not self._run_once(steps):
                    break
            if self._stop.is_set():
                self.on_status("Stopped")
            else:
                self.on_status("Finished")
        finally:
            self._remove_esc()
            self.on_highlight(-1)
            self.on_finish()

    def _run_once(self, steps: list[Step]) -> bool:
        i = 0
        n = len(steps)
        while i < n:
            if self._stop.is_set():
                return False
            s = steps[i]
            self.on_highlight(i)

            if s.type == actions.IF:
                cond = self._eval_condition(s.params)
                if cond:
                    i += 1  # enter the true branch
                else:
                    # jump to else+1 or endif+1
                    i = (s._else + 1) if s._else >= 0 else (s._endif + 1 if s._endif >= 0 else i + 1)
                continue
            if s.type == actions.ELSE:
                # reached only by falling out of a true branch -> skip to endif
                i = s._endif + 1 if s._endif >= 0 else i + 1
                continue
            if s.type == actions.ENDIF:
                i += 1
                continue
            if s.type == actions.GOTO:
                target = _find_label(steps, s.params.get("name", ""))
                i = target if target >= 0 else i + 1
                continue
            if s.type == actions.LABEL:
                i += 1
                continue

            self._execute(s)
            if self._stop.is_set():
                return False
            self._sleep(s.delay)
            i += 1
        return True

    def _sleep(self, ms: int):
        end = time.time() + ms / 1000.0
        while time.time() < end:
            if self._stop.is_set():
                return
            time.sleep(min(0.03, end - time.time()))

    def _execute(self, s: Step):
        if not HAS_PYAUTOGUI:
            self.on_status("pyautogui not installed — cannot send input")
            return
        p = s.params
        t = s.type
        try:
            if t == actions.CLICK:
                pyautogui.click(p["x"], p["y"], button=p.get("button", "left"))
            elif t == actions.DOUBLE_CLICK:
                pyautogui.doubleClick(p["x"], p["y"])
            elif t == actions.MOVE:
                pyautogui.moveTo(p["x"], p["y"])
            elif t == actions.DRAG:
                pyautogui.moveTo(p["x"], p["y"])
                pyautogui.dragTo(p["x2"], p["y2"], duration=0.3,
                                 button=p.get("button", "left"))
            elif t == actions.SCROLL:
                pyautogui.scroll(int(p.get("amount", 0)) * 100)
            elif t == actions.IMAGE_CLICK:
                self._do_image_click(p)
            elif t == actions.KEY:
                self._do_key(p.get("keys", ""))
            elif t == actions.TEXT:
                pyautogui.write(p.get("text", ""), interval=0.02)
            elif t == actions.WAIT:
                pass  # delay handled by caller
        except Exception as e:  # keep going, report
            self.on_status(f"Step error: {e}")

    def _do_image_click(self, p: dict):
        path = os.path.join(self.image_dir, p.get("image", ""))
        hit = locate_image(path, p.get("confidence", 0.8))
        if hit is None:
            self.on_status(f'Image "{p.get("image")}" not found on screen')
            return
        cx, cy, score = hit
        btn = p.get("button", "left")
        if p.get("double"):
            pyautogui.doubleClick(cx, cy)
        else:
            pyautogui.click(cx, cy, button=btn)
        self.on_status(f'Clicked "{p.get("image")}" ({score:.0%})')

    def _do_key(self, keys: str):
        keys = keys.strip()
        if not keys:
            return
        if "+" in keys:
            parts = [k.strip().lower() for k in keys.split("+")]
            pyautogui.hotkey(*parts)
        else:
            pyautogui.press(keys.lower())


def _find_label(steps: list[Step], name: str) -> int:
    for i, s in enumerate(steps):
        if s.type == actions.LABEL and s.params.get("name") == name:
            return i
    return -1
