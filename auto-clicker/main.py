"""
Auto Clicker & Macro Recorder
=============================
A general-purpose desktop automation tool inspired by "Automatic Mouse and
Keyboard": record mouse/keyboard input, click fixed locations, find images on
screen and click them, send key inputs, and branch with IF/ELSE conditions.

Run:  python main.py
See README.md for setup.
"""

from __future__ import annotations

import os
import sys
import json
import time
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog, colorchooser

import actions
from actions import Step
import engine
import snipper

APP_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGE_DIR = os.path.join(APP_DIR, "images")
os.makedirs(IMAGE_DIR, exist_ok=True)


class AutoClickerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.steps: list[Step] = []
        self.current_file: str | None = None
        self.recorder: engine.Recorder | None = None
        self.player = engine.Player(
            IMAGE_DIR,
            on_status=self._threadsafe_status,
            on_highlight=self._threadsafe_highlight,
            on_finish=self._threadsafe_play_finished,
        )
        self._record_lock = threading.Lock()

        root.title("Auto Clicker & Macro Recorder")
        root.geometry("820x560")
        root.minsize(680, 420)

        self._build_toolbar()
        self._build_tree()
        self._build_statusbar()
        self._refresh_tree()
        self._check_deps()

        root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_toolbar(self):
        bar = ttk.Frame(self.root, padding=(6, 6))
        bar.pack(side="top", fill="x")

        def btn(text, cmd, width=None):
            b = ttk.Button(bar, text=text, command=cmd, width=width)
            b.pack(side="left", padx=2)
            return b

        btn("New", self.new_routine)
        btn("Open", self.open_routine)
        btn("Save", self.save_routine)
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=6)

        self.record_btn = btn("● Record", self.toggle_record)
        btn("◎ Smart Click", self.add_image_click)
        self.play_btn = btn("▶ Play", self.play)
        self.stop_btn = btn("■ Stop", self.stop)
        self.stop_btn.state(["disabled"])

        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=6)
        ttk.Label(bar, text="Loops:").pack(side="left")
        self.loops_var = tk.StringVar(value="1")
        ttk.Spinbox(bar, from_=0, to=99999, width=5,
                    textvariable=self.loops_var).pack(side="left", padx=2)
        ttk.Label(bar, text="(0 = ∞)").pack(side="left")

        # Second row: insert / edit steps
        bar2 = ttk.Frame(self.root, padding=(6, 0))
        bar2.pack(side="top", fill="x")
        ttk.Label(bar2, text="Insert:").pack(side="left", padx=(0, 4))
        ttk.Button(bar2, text="Click", command=lambda: self.add_click("left")).pack(side="left", padx=1)
        ttk.Button(bar2, text="Right-Click", command=lambda: self.add_click("right")).pack(side="left", padx=1)
        ttk.Button(bar2, text="Double-Click", command=self.add_double_click).pack(side="left", padx=1)
        ttk.Button(bar2, text="Move", command=self.add_move).pack(side="left", padx=1)
        ttk.Button(bar2, text="Drag", command=self.add_drag).pack(side="left", padx=1)
        ttk.Button(bar2, text="Key", command=self.add_key).pack(side="left", padx=1)
        ttk.Button(bar2, text="Text", command=self.add_text).pack(side="left", padx=1)
        ttk.Button(bar2, text="Wait", command=self.add_wait).pack(side="left", padx=1)
        ttk.Button(bar2, text="IF…", command=self.add_if).pack(side="left", padx=1)
        ttk.Button(bar2, text="ELSE", command=lambda: self._append(Step(actions.ELSE, delay=0))).pack(side="left", padx=1)
        ttk.Button(bar2, text="END IF", command=lambda: self._append(Step(actions.ENDIF, delay=0))).pack(side="left", padx=1)

        # Third row: reorder / remove
        bar3 = ttk.Frame(self.root, padding=(6, 4))
        bar3.pack(side="top", fill="x")
        ttk.Button(bar3, text="Edit", command=self.edit_selected).pack(side="left", padx=1)
        ttk.Button(bar3, text="Delete", command=self.delete_selected).pack(side="left", padx=1)
        ttk.Button(bar3, text="▲ Up", command=lambda: self.move_selected(-1)).pack(side="left", padx=1)
        ttk.Button(bar3, text="▼ Down", command=lambda: self.move_selected(1)).pack(side="left", padx=1)
        ttk.Button(bar3, text="Duplicate", command=self.duplicate_selected).pack(side="left", padx=1)
        ttk.Button(bar3, text="Set Delay", command=self.set_delay_selected).pack(side="left", padx=1)

    def _build_tree(self):
        frame = ttk.Frame(self.root)
        frame.pack(side="top", fill="both", expand=True, padx=6, pady=(0, 4))

        cols = ("step", "action", "delay")
        self.tree = ttk.Treeview(frame, columns=cols, show="headings", selectmode="browse")
        self.tree.heading("step", text="Step")
        self.tree.heading("action", text="Action Description")
        self.tree.heading("delay", text="Delay")
        self.tree.column("step", width=60, anchor="center", stretch=False)
        self.tree.column("action", width=560, anchor="w")
        self.tree.column("delay", width=90, anchor="center", stretch=False)

        vsb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self.tree.tag_configure("running", background="#fff3b0")
        self.tree.tag_configure("block", foreground="#0057d8")
        self.tree.bind("<Double-1>", lambda e: self.edit_selected())

    def _build_statusbar(self):
        self.status_var = tk.StringVar(value="Ready")
        bar = ttk.Frame(self.root, padding=(8, 4), relief="sunken")
        bar.pack(side="bottom", fill="x")
        ttk.Label(bar, textvariable=self.status_var).pack(side="left")

    def _check_deps(self):
        missing = []
        if not engine.HAS_PYAUTOGUI:
            missing.append("pyautogui")
        if not engine.HAS_VISION:
            missing.append("opencv-python / mss")
        if not engine.HAS_PYNPUT:
            missing.append("pynput")
        if missing:
            self.status_var.set("Missing packages: " + ", ".join(missing) +
                                "  — run: pip install -r requirements.txt")

    # ------------------------------------------------------------------
    # Tree rendering
    # ------------------------------------------------------------------
    def _refresh_tree(self, running_index: int = -1):
        self.tree.delete(*self.tree.get_children())
        indents = actions.indent_of(self.steps)
        group = ""
        for i, s in enumerate(self.steps):
            prefix = "    " * indents[i]
            desc = prefix + s.describe()
            label = s.label or ("" if s.type not in (actions.IF, actions.ELSE, actions.ENDIF) else "")
            delay = "" if s.type in (actions.IF, actions.ELSE, actions.ENDIF, actions.LABEL) else f"{s.delay} ms"
            tags = []
            if i == running_index:
                tags.append("running")
            if s.type in (actions.IF, actions.ELSE, actions.ENDIF):
                tags.append("block")
            self.tree.insert("", "end", iid=str(i),
                             values=(i + 1, desc, delay), tags=tags)
        if 0 <= running_index < len(self.steps):
            self.tree.see(str(running_index))

    def _selected_index(self) -> int:
        sel = self.tree.selection()
        return int(sel[0]) if sel else -1

    def _append(self, step: Step):
        idx = self._selected_index()
        if idx >= 0:
            self.steps.insert(idx + 1, step)
            new_sel = idx + 1
        else:
            self.steps.append(step)
            new_sel = len(self.steps) - 1
        self._refresh_tree()
        self.tree.selection_set(str(new_sel))
        self.tree.see(str(new_sel))
        self._mark_dirty()

    # ------------------------------------------------------------------
    # File ops
    # ------------------------------------------------------------------
    def new_routine(self):
        if self.steps and not messagebox.askyesno("New", "Discard the current routine?"):
            return
        self.steps = []
        self.current_file = None
        self.root.title("Auto Clicker & Macro Recorder")
        self._refresh_tree()

    def open_routine(self):
        path = filedialog.askopenfilename(
            title="Open routine", initialdir=APP_DIR,
            filetypes=[("Auto-clicker routine", "*.json"), ("All files", "*.*")])
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.steps = [Step.from_dict(d) for d in data.get("steps", [])]
            self.loops_var.set(str(data.get("loops", 1)))
            self.current_file = path
            self.root.title(f"Auto Clicker — {os.path.basename(path)}")
            self._refresh_tree()
            self.status_var.set(f"Opened {os.path.basename(path)}")
        except Exception as e:
            messagebox.showerror("Open failed", str(e))

    def save_routine(self):
        if not self.current_file:
            path = filedialog.asksaveasfilename(
                title="Save routine", initialdir=APP_DIR, defaultextension=".json",
                filetypes=[("Auto-clicker routine", "*.json")])
            if not path:
                return
            self.current_file = path
        data = {
            "loops": int(self.loops_var.get() or 1),
            "steps": [s.to_dict() for s in self.steps],
        }
        try:
            with open(self.current_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            self.root.title(f"Auto Clicker — {os.path.basename(self.current_file)}")
            self.status_var.set(f"Saved {os.path.basename(self.current_file)}")
        except Exception as e:
            messagebox.showerror("Save failed", str(e))

    def _mark_dirty(self):
        pass  # (hook for a future "unsaved changes" indicator)

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------
    def toggle_record(self):
        if self.recorder and self.recorder.recording:
            self._stop_recording()
        else:
            self._start_recording()

    def _start_recording(self):
        if not engine.HAS_PYNPUT:
            messagebox.showerror("Recording unavailable",
                                 "Install pynput:  pip install pynput")
            return

        def on_step(step: Step):
            # called from listener threads
            with self._record_lock:
                self.root.after(0, self._append_recorded, step)

        self.recorder = engine.Recorder(on_step)
        self.recorder.start()
        self.record_btn.configure(text="● Stop Rec")
        self.status_var.set("Recording…  (click/type anywhere; press Stop Rec to finish)")

    def _append_recorded(self, step: Step):
        self.steps.append(step)
        self._refresh_tree()
        self.tree.see(str(len(self.steps) - 1))

    def _stop_recording(self):
        if self.recorder:
            self.recorder.stop()
            self.recorder = None
        self.record_btn.configure(text="● Record")
        self.status_var.set(f"Recorded {len(self.steps)} steps")

    # ------------------------------------------------------------------
    # Insert-step actions
    # ------------------------------------------------------------------
    def add_click(self, button: str):
        pos = self._pick_position(f"{button}-click")
        if pos:
            self._append(Step(actions.CLICK, {"x": pos[0], "y": pos[1], "button": button}))

    def add_double_click(self):
        pos = self._pick_position("double-click")
        if pos:
            self._append(Step(actions.DOUBLE_CLICK, {"x": pos[0], "y": pos[1]}))

    def add_move(self):
        pos = self._pick_position("move to")
        if pos:
            self._append(Step(actions.MOVE, {"x": pos[0], "y": pos[1]}))

    def add_drag(self):
        start = self._pick_position("drag START")
        if not start:
            return
        end = self._pick_position("drag END")
        if not end:
            return
        self._append(Step(actions.DRAG,
                          {"x": start[0], "y": start[1], "x2": end[0], "y2": end[1],
                           "button": "left"}))

    def add_key(self):
        keys = simpledialog.askstring(
            "Key input",
            "Enter a key or hotkey.\nExamples:  enter   tab   f5   ctrl+c   alt+tab   ctrl+shift+esc",
            parent=self.root)
        if keys:
            self._append(Step(actions.KEY, {"keys": keys.strip()}))

    def add_text(self):
        text = simpledialog.askstring("Type text", "Text to type:", parent=self.root)
        if text is not None:
            self._append(Step(actions.TEXT, {"text": text}))

    def add_wait(self):
        ms = simpledialog.askinteger("Wait", "Milliseconds to wait:",
                                     parent=self.root, initialvalue=1000, minvalue=0)
        if ms is not None:
            self._append(Step(actions.WAIT, {}, delay=ms))

    def add_image_click(self):
        """Smart Click: snip a target image, then insert a find-and-click step."""
        if not engine.HAS_VISION:
            messagebox.showerror("Unavailable",
                                 "Install opencv-python and mss for image matching.")
            return
        name = simpledialog.askstring("Smart Click",
                                      "Name this target image (e.g. 'ok_button'):",
                                      parent=self.root)
        if not name:
            return
        self.status_var.set("Select the target on screen…")
        fname = snipper.snip_region(self.root, IMAGE_DIR, name)
        if not fname:
            self.status_var.set("Smart Click cancelled")
            return
        dlg = ImageClickDialog(self.root, fname)
        if dlg.result:
            self._append(Step(actions.IMAGE_CLICK, dlg.result))
        self.status_var.set(f"Saved target image: {fname}")

    def add_if(self):
        dlg = ConditionDialog(self.root, IMAGE_DIR)
        if dlg.result:
            self._append(Step(actions.IF, dlg.result, delay=0))

    # ------------------------------------------------------------------
    # Position picker: user clicks anywhere on screen to capture coords
    # ------------------------------------------------------------------
    def _pick_position(self, verb: str):
        if not engine.HAS_PYNPUT:
            # fallback: ask for numbers
            x = simpledialog.askinteger("X", f"X coordinate to {verb}:", parent=self.root)
            if x is None:
                return None
            y = simpledialog.askinteger("Y", f"Y coordinate to {verb}:", parent=self.root)
            if y is None:
                return None
            return (x, y)

        result = {"pos": None}
        self.root.withdraw()
        self.root.update()
        time.sleep(0.2)

        overlay = tk.Toplevel()
        overlay.attributes("-fullscreen", True)
        overlay.attributes("-alpha", 0.15)
        overlay.configure(bg="blue")
        overlay.attributes("-topmost", True)
        overlay.config(cursor="crosshair")
        c = tk.Canvas(overlay, bg="gray15", highlightthickness=0)
        c.pack(fill="both", expand=True)
        c.create_text(overlay.winfo_screenwidth() // 2, 40,
                      text=f"Click the point to {verb}   •   Esc to cancel",
                      fill="white", font=("Segoe UI", 16))

        def on_click(e):
            result["pos"] = (e.x_root, e.y_root)
            overlay.destroy()

        def on_cancel(e):
            overlay.destroy()

        c.bind("<Button-1>", on_click)
        overlay.bind("<Escape>", on_cancel)
        overlay.focus_force()
        overlay.wait_window()

        self.root.deiconify()
        self.root.update()
        return result["pos"]

    # ------------------------------------------------------------------
    # Edit / reorder
    # ------------------------------------------------------------------
    def edit_selected(self):
        idx = self._selected_index()
        if idx < 0:
            return
        s = self.steps[idx]
        if s.type == actions.IF:
            dlg = ConditionDialog(self.root, IMAGE_DIR, initial=s.params)
            if dlg.result:
                s.params = dlg.result
        elif s.type == actions.IMAGE_CLICK:
            dlg = ImageClickDialog(self.root, s.params.get("image", ""), initial=s.params)
            if dlg.result:
                s.params = dlg.result
        elif s.type == actions.KEY:
            keys = simpledialog.askstring("Key input", "Key or hotkey:",
                                          parent=self.root, initialvalue=s.params.get("keys", ""))
            if keys is not None:
                s.params["keys"] = keys.strip()
        elif s.type == actions.TEXT:
            text = simpledialog.askstring("Type text", "Text:",
                                          parent=self.root, initialvalue=s.params.get("text", ""))
            if text is not None:
                s.params["text"] = text
        elif s.type in (actions.CLICK, actions.DOUBLE_CLICK, actions.MOVE):
            self._edit_xy(s)
        elif s.type == actions.WAIT:
            self.set_delay_selected()
            return
        else:
            self.set_delay_selected()
            return
        self._refresh_tree(); self.tree.selection_set(str(idx))

    def _edit_xy(self, s: Step):
        x = simpledialog.askinteger("X", "X:", parent=self.root, initialvalue=s.params.get("x", 0))
        if x is None:
            return
        y = simpledialog.askinteger("Y", "Y:", parent=self.root, initialvalue=s.params.get("y", 0))
        if y is None:
            return
        s.params["x"], s.params["y"] = x, y

    def set_delay_selected(self):
        idx = self._selected_index()
        if idx < 0:
            return
        s = self.steps[idx]
        ms = simpledialog.askinteger("Delay", "Delay after this step (ms):",
                                     parent=self.root, initialvalue=s.delay, minvalue=0)
        if ms is not None:
            s.delay = ms
            self._refresh_tree(); self.tree.selection_set(str(idx))

    def delete_selected(self):
        idx = self._selected_index()
        if idx < 0:
            return
        del self.steps[idx]
        self._refresh_tree()
        if self.steps:
            self.tree.selection_set(str(min(idx, len(self.steps) - 1)))

    def duplicate_selected(self):
        idx = self._selected_index()
        if idx < 0:
            return
        self.steps.insert(idx + 1, self.steps[idx].copy())
        self._refresh_tree(); self.tree.selection_set(str(idx + 1))

    def move_selected(self, direction: int):
        idx = self._selected_index()
        if idx < 0:
            return
        j = idx + direction
        if 0 <= j < len(self.steps):
            self.steps[idx], self.steps[j] = self.steps[j], self.steps[idx]
            self._refresh_tree(); self.tree.selection_set(str(j))

    # ------------------------------------------------------------------
    # Playback
    # ------------------------------------------------------------------
    def play(self):
        if self.recorder and self.recorder.recording:
            self._stop_recording()
        if not self.steps:
            self.status_var.set("Nothing to play — add some steps first")
            return
        if self.player.is_running():
            return
        try:
            loops = int(self.loops_var.get() or 1)
        except ValueError:
            loops = 1
        self.play_btn.state(["disabled"])
        self.stop_btn.state(["!disabled"])
        self.status_var.set("Playing…  (press ESC to abort)")
        # minimise so the routine drives the target app, not us
        self.root.iconify()
        self.player.start([s.copy() for s in self.steps], loops)

    def stop(self):
        self.player.stop()

    # -- thread-safe callbacks from the player --------------------------
    def _threadsafe_status(self, msg: str):
        self.root.after(0, self.status_var.set, msg)

    def _threadsafe_highlight(self, index: int):
        self.root.after(0, self._refresh_tree, index)

    def _threadsafe_play_finished(self):
        self.root.after(0, self._play_finished)

    def _play_finished(self):
        self.play_btn.state(["!disabled"])
        self.stop_btn.state(["disabled"])
        self.root.deiconify()
        self._refresh_tree()

    # ------------------------------------------------------------------
    def _on_close(self):
        if self.recorder and self.recorder.recording:
            self.recorder.stop()
        self.player.stop()
        self.root.destroy()


# =========================================================================
# Dialogs
# =========================================================================

class ImageClickDialog(tk.Toplevel):
    """Configure an image-click step: button, confidence, double-click."""

    def __init__(self, parent, image_name: str, initial: dict | None = None):
        super().__init__(parent)
        self.title("Image Click settings")
        self.resizable(False, False)
        self.result: dict | None = None
        initial = initial or {}

        ttk.Label(self, text=f"Target image:  {image_name}").grid(
            row=0, column=0, columnspan=2, padx=10, pady=(10, 6), sticky="w")

        ttk.Label(self, text="Click button:").grid(row=1, column=0, padx=10, sticky="w")
        self.button_var = tk.StringVar(value=initial.get("button", "left"))
        ttk.Combobox(self, textvariable=self.button_var, width=10,
                     values=["left", "right", "middle"], state="readonly").grid(
            row=1, column=1, padx=10, pady=4, sticky="w")

        self.double_var = tk.BooleanVar(value=initial.get("double", False))
        ttk.Checkbutton(self, text="Double click", variable=self.double_var).grid(
            row=2, column=0, columnspan=2, padx=10, sticky="w")

        ttk.Label(self, text="Match confidence:").grid(row=3, column=0, padx=10, sticky="w")
        self.conf_var = tk.DoubleVar(value=initial.get("confidence", 0.8))
        ttk.Spinbox(self, from_=0.5, to=1.0, increment=0.05, width=8,
                    textvariable=self.conf_var).grid(row=3, column=1, padx=10, pady=4, sticky="w")

        self.image_name = image_name
        btns = ttk.Frame(self)
        btns.grid(row=4, column=0, columnspan=2, pady=10)
        ttk.Button(btns, text="OK", command=self._ok).pack(side="left", padx=4)
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="left", padx=4)

        self.transient(parent); self.grab_set(); self.wait_window()

    def _ok(self):
        self.result = {
            "image": self.image_name,
            "button": self.button_var.get(),
            "double": self.double_var.get(),
            "confidence": round(float(self.conf_var.get()), 2),
        }
        self.destroy()


class ConditionDialog(tk.Toplevel):
    """Build an IF condition: image found / not found, or pixel colour."""

    def __init__(self, parent, image_dir: str, initial: dict | None = None):
        super().__init__(parent)
        self.title("IF condition")
        self.resizable(False, False)
        self.image_dir = image_dir
        self.result: dict | None = None
        initial = initial or {}

        ttk.Label(self, text="Trigger the following steps when:").grid(
            row=0, column=0, columnspan=3, padx=10, pady=(10, 6), sticky="w")

        self.cond_var = tk.StringVar(value=initial.get("cond", actions.COND_IMAGE_FOUND))
        conds = [
            ("Image is found on screen", actions.COND_IMAGE_FOUND),
            ("Image is NOT found on screen", actions.COND_IMAGE_NOT_FOUND),
            ("Pixel colour matches", actions.COND_PIXEL_COLOR),
            ("Pixel colour does NOT match", actions.COND_PIXEL_NOT_COLOR),
        ]
        self.cond_combo = ttk.Combobox(
            self, width=34, state="readonly",
            values=[c[0] for c in conds])
        self._cond_map = {c[0]: c[1] for c in conds}
        self._cond_rev = {c[1]: c[0] for c in conds}
        self.cond_combo.set(self._cond_rev.get(self.cond_var.get(), conds[0][0]))
        self.cond_combo.grid(row=1, column=0, columnspan=3, padx=10, pady=4, sticky="w")
        self.cond_combo.bind("<<ComboboxSelected>>", lambda e: self._update_visibility())

        # Image row
        self.img_frame = ttk.Frame(self)
        self.img_frame.grid(row=2, column=0, columnspan=3, padx=10, pady=4, sticky="w")
        ttk.Label(self.img_frame, text="Image:").pack(side="left")
        self.image_var = tk.StringVar(value=initial.get("image", ""))
        imgs = [f for f in os.listdir(image_dir) if f.lower().endswith((".png", ".jpg"))]
        self.img_combo = ttk.Combobox(self.img_frame, textvariable=self.image_var,
                                      width=22, values=imgs)
        self.img_combo.pack(side="left", padx=4)
        ttk.Button(self.img_frame, text="Capture…", command=self._capture).pack(side="left")

        # Pixel row
        self.px_frame = ttk.Frame(self)
        self.px_frame.grid(row=3, column=0, columnspan=3, padx=10, pady=4, sticky="w")
        ttk.Label(self.px_frame, text="X:").pack(side="left")
        self.px_x = tk.StringVar(value=str(initial.get("x", 0)))
        ttk.Entry(self.px_frame, textvariable=self.px_x, width=6).pack(side="left", padx=(2, 8))
        ttk.Label(self.px_frame, text="Y:").pack(side="left")
        self.px_y = tk.StringVar(value=str(initial.get("y", 0)))
        ttk.Entry(self.px_frame, textvariable=self.px_y, width=6).pack(side="left", padx=(2, 8))
        self.color_var = tk.StringVar(value=initial.get("color", "#ff0000"))
        ttk.Button(self.px_frame, text="Pick colour…", command=self._pick_color).pack(side="left")
        self.color_swatch = tk.Label(self.px_frame, textvariable=self.color_var,
                                     width=9, relief="sunken")
        self.color_swatch.pack(side="left", padx=4)
        self._update_swatch()

        btns = ttk.Frame(self)
        btns.grid(row=4, column=0, columnspan=3, pady=10)
        ttk.Button(btns, text="OK", command=self._ok).pack(side="left", padx=4)
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="left", padx=4)

        self._update_visibility()
        self.transient(parent); self.grab_set(); self.wait_window()

    def _current_cond(self) -> str:
        return self._cond_map.get(self.cond_combo.get(), actions.COND_IMAGE_FOUND)

    def _update_visibility(self):
        cond = self._current_cond()
        is_image = cond in (actions.COND_IMAGE_FOUND, actions.COND_IMAGE_NOT_FOUND)
        if is_image:
            self.img_frame.grid()
            self.px_frame.grid_remove()
        else:
            self.img_frame.grid_remove()
            self.px_frame.grid()

    def _capture(self):
        name = simpledialog.askstring("Capture image", "Name for this image:", parent=self)
        if not name:
            return
        fname = snipper.snip_region(self.master, self.image_dir, name)
        if fname:
            vals = list(self.img_combo["values"]) + [fname]
            self.img_combo["values"] = sorted(set(vals))
            self.image_var.set(fname)
        self.lift(); self.focus_force()

    def _pick_color(self):
        c = colorchooser.askcolor(color=self.color_var.get(), parent=self)
        if c and c[1]:
            self.color_var.set(c[1])
            self._update_swatch()

    def _update_swatch(self):
        try:
            self.color_swatch.configure(bg=self.color_var.get())
        except tk.TclError:
            pass

    def _ok(self):
        cond = self._current_cond()
        res = {"cond": cond}
        if cond in (actions.COND_IMAGE_FOUND, actions.COND_IMAGE_NOT_FOUND):
            if not self.image_var.get():
                messagebox.showwarning("Missing image", "Choose or capture an image.", parent=self)
                return
            res["image"] = self.image_var.get()
            res["confidence"] = 0.8
        else:
            try:
                res["x"] = int(self.px_x.get())
                res["y"] = int(self.px_y.get())
            except ValueError:
                messagebox.showwarning("Bad coordinates", "X and Y must be numbers.", parent=self)
                return
            res["color"] = self.color_var.get()
            res["tol"] = 20
        self.result = res
        self.destroy()


def main():
    root = tk.Tk()
    try:
        ttk.Style().theme_use("clam")
    except tk.TclError:
        pass
    AutoClickerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
