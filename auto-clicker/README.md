# Auto Clicker & Macro Recorder

A general-purpose desktop automation tool, inspired by *Automatic Mouse and
Keyboard*. Record what you do, replay it, find images on screen and click them,
send keystrokes, and branch with **IF / ELSE** conditions.

Because it controls the real mouse and keyboard, this is a **desktop app** (not
a web page). It runs on Windows, macOS and Linux with Python 3.9+.

![step list UI](images/.gitkeep)

## Features

| Capability | How |
|---|---|
| **Record** mouse clicks, drags, scrolls and typing | `● Record` — captures everything globally, then press *Stop Rec* |
| **Click a fixed location** (left / right / double) | `Insert ▸ Click / Right-Click / Double-Click`, then click the point on screen |
| **Move / Drag** | `Insert ▸ Move / Drag` |
| **Smart Click** — find an image on screen and click it | `◎ Smart Click` — drag a box over the target; it's saved and matched at run time |
| **Key inputs & hotkeys** | `Insert ▸ Key` — e.g. `enter`, `f5`, `ctrl+c`, `alt+tab`, `ctrl+shift+esc` |
| **Type text** | `Insert ▸ Text` |
| **Waits / delays** | Per-step `Delay` column, or `Insert ▸ Wait` |
| **IF / ELSE / END IF conditions** | Branch on *image found / not found* or *pixel colour matches / not* |
| **Loops** | `Loops` box in the toolbar (`0` = infinite) |
| **Save / Open** routines | Stored as JSON; captured images live in `images/` |
| **Emergency stop** | Press **ESC** any time during playback |

## Setup

```bash
cd auto-clicker
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

### Platform notes

- **Windows** — works out of the box.
- **macOS** — grant the terminal (or your Python) **Accessibility** *and*
  **Screen Recording** permission in *System Settings ▸ Privacy & Security*,
  otherwise clicks and screen capture are blocked by the OS.
- **Linux** — requires an X11 session (pyautogui/pynput don't support Wayland
  input injection). On headless machines there's no screen to automate.

## How it works

1. **Steps** — a routine is an ordered list of steps shown in the table
   (`Step │ Action Description │ Delay`), exactly like the reference tool. Each
   step waits its `Delay` (in ms) after running.
2. **Smart Click / image conditions** — captured targets are saved as PNGs in
   `images/`. At run time the screen is grabbed with `mss` and matched with
   OpenCV template matching (`TM_CCOEFF_NORMED`); the `confidence` slider is the
   minimum match score. On a match, the step clicks the centre of the found
   region.
3. **IF blocks** — an `IF` step evaluates its condition; if true, the steps up to
   the matching `ELSE`/`END IF` run, otherwise they're skipped (and the `ELSE`
   branch runs instead). Blocks may be nested.

### Example: keep clicking a button whenever it appears

```
IF   image "play_button" is found
    Left click image "play_button"
    Wait 500 ms
END IF
```
Set **Loops = 0** (infinite) and it will click *Play* every time it pops up,
and do nothing when it doesn't.

## Files

| File | Purpose |
|---|---|
| `main.py` | Tkinter GUI: toolbar, step table, dialogs |
| `engine.py` | Recorder, Player, screen/image matching |
| `actions.py` | Step model + human-readable descriptions |
| `snipper.py` | Full-screen region selector for capturing target images |
| `images/` | Captured target PNGs |

## Safety

- **ESC** aborts playback instantly.
- Infinite loops (`Loops = 0`) run until you press ESC or close the window.
- The app only automates *your* machine locally; nothing is sent anywhere.
