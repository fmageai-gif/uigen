"""
Full-screen region snipper. Lets the user drag a rectangle over the screen;
the selected region is saved as a PNG for later template matching.

Returns (image_path, (left, top, width, height)) or None if cancelled.
"""

from __future__ import annotations

import os
import time
import tkinter as tk
from typing import Optional

import engine


def snip_region(root: tk.Tk, image_dir: str, name: str) -> Optional[str]:
    """
    Open a translucent full-screen overlay, let the user drag a box, grab that
    region from the real screen and save it to image_dir/<name>.png.
    Returns the saved filename (not full path) or None.
    """
    if not engine.HAS_VISION:
        return None

    # Hide the main window so it isn't captured in the shot.
    root.withdraw()
    root.update()
    time.sleep(0.25)

    overlay = tk.Toplevel()
    overlay.attributes("-fullscreen", True)
    overlay.attributes("-alpha", 0.25)
    overlay.configure(bg="black")
    overlay.attributes("-topmost", True)
    overlay.config(cursor="crosshair")

    canvas = tk.Canvas(overlay, bg="gray20", highlightthickness=0)
    canvas.pack(fill="both", expand=True)
    canvas.create_text(overlay.winfo_screenwidth() // 2, 30,
                       text="Drag to select the target image  •  Esc to cancel",
                       fill="white", font=("Segoe UI", 14))

    state = {"x0": 0, "y0": 0, "rect": None, "result": None}

    def on_press(e):
        state["x0"], state["y0"] = e.x_root, e.y_root
        state["rect"] = canvas.create_rectangle(
            e.x, e.y, e.x, e.y, outline="#4f8cff", width=2)

    def on_drag(e):
        if state["rect"] is not None:
            x0 = state["x0"] - overlay.winfo_rootx()
            y0 = state["y0"] - overlay.winfo_rooty()
            canvas.coords(state["rect"], x0, y0, e.x, e.y)

    def on_release(e):
        x1, y1 = e.x_root, e.y_root
        left = min(state["x0"], x1)
        top = min(state["y0"], y1)
        w = abs(x1 - state["x0"])
        h = abs(y1 - state["y0"])
        state["result"] = (left, top, w, h) if w > 3 and h > 3 else None
        overlay.destroy()

    def on_cancel(e):
        state["result"] = None
        overlay.destroy()

    canvas.bind("<ButtonPress-1>", on_press)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_release)
    overlay.bind("<Escape>", on_cancel)
    overlay.focus_force()
    overlay.wait_window()

    root.deiconify()
    root.update()

    region = state["result"]
    if not region:
        return None

    time.sleep(0.15)  # let overlay disappear before grabbing
    img = engine.grab_screen(region)
    os.makedirs(image_dir, exist_ok=True)
    fname = _safe_name(name) + ".png"
    path = os.path.join(image_dir, fname)
    engine.cv2.imwrite(path, img)
    return fname


def _safe_name(name: str) -> str:
    keep = "-_. abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    cleaned = "".join(c for c in name if c in keep).strip().replace(" ", "_")
    return cleaned or f"target_{int(time.time())}"
