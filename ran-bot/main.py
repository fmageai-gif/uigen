"""
Ran Online Auto-Target Bot
Detects mob name tags (red text) on screen and auto-clicks them.
"""

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import threading
import time
import json
import os
import sys

import numpy as np
import mss
import cv2
import pyautogui

try:
    import pytesseract
    if sys.platform == "win32":
        # Search common install locations
        _candidates = [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            r"C:\Users\Administrator\AppData\Local\Programs\Tesseract-OCR\tesseract.exe",
            r"C:\Tesseract-OCR\tesseract.exe",
        ]
        # Also search PATH
        import shutil
        _from_path = shutil.which("tesseract")
        if _from_path:
            _candidates.insert(0, _from_path)
        for _p in _candidates:
            if os.path.exists(_p):
                pytesseract.pytesseract.tesseract_cmd = _p
                break
    HAS_OCR = True
except ImportError:
    HAS_OCR = False

pyautogui.FAILSAFE = True  # move mouse to top-left corner to emergency stop

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.json")

DEFAULT_MONSTERS = [
    "Slasher",
    "Crook",
    "Brawler",
    "Prowler",
    "Hooligan",
    "Gangster",
    "Thug",
]

DEFAULT_CONFIG = {
    "scan_interval": 0.5,       # seconds between scans
    "attack_interval": 0.4,     # seconds between each attack click on current target
    "click_offset_y": 50,       # pixels below BOTTOM of name tag to click (mob body)
    "death_timeout": 10,        # seconds to wait before assuming mob is dead/gone
    "click_button": "left",     # "left" or "right" mouse button for attacking
    "red_lower": [0, 120, 100], # HSV lower bound for red name tags
    "red_upper": [8, 255, 255], # HSV upper bound for red name tags
    "min_area": 100,            # minimum contour area to consider
    "ocr_scale": 3,             # upscale factor for OCR accuracy
    "region": None,             # screen region {left, top, width, height} or None = fullscreen
    "selected_monsters": ["Slasher", "Crook", "Brawler", "Prowler"],
}


def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            cfg = json.load(f)
        # Merge with defaults for any missing keys
        for k, v in DEFAULT_CONFIG.items():
            cfg.setdefault(k, v)
        return cfg
    return dict(DEFAULT_CONFIG)


def save_config(cfg):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


def find_red_name_tags(frame, cfg):
    """
    Returns list of (cx, cy, text, rect) for each red name tag found.
    cx, cy = center of the name tag bounding box.
    """
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

    lower1 = np.array(cfg["red_lower"], dtype=np.uint8)
    upper1 = np.array(cfg["red_upper"], dtype=np.uint8)
    # Red wraps around in HSV, so also check the upper range (170-180)
    lower2 = np.array([170, 120, 100], dtype=np.uint8)
    upper2 = np.array([180, 255, 255], dtype=np.uint8)

    mask1 = cv2.inRange(hsv, lower1, upper1)
    mask2 = cv2.inRange(hsv, lower2, upper2)
    mask = cv2.bitwise_or(mask1, mask2)

    # Dilate to connect nearby characters
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (8, 4))
    mask = cv2.dilate(mask, kernel, iterations=1)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    results = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < cfg["min_area"]:
            continue

        x, y, w, h = cv2.boundingRect(cnt)

        # Name tags are wider than tall, skip tall thin blobs
        if h > w or h > 25:
            continue

        cx = x + w // 2
        cy = y + h // 2

        # Extract ROI and upscale for OCR
        roi = frame[max(0, y - 4): y + h + 4, max(0, x - 4): x + w + 4]
        if roi.size == 0:
            continue

        text = ""
        if HAS_OCR:
            scale = cfg["ocr_scale"]
            roi_up = cv2.resize(roi, (roi.shape[1] * scale, roi.shape[0] * scale),
                                interpolation=cv2.INTER_CUBIC)
            # Convert to grayscale and threshold for OCR
            gray = cv2.cvtColor(roi_up, cv2.COLOR_BGR2GRAY)
            _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            text = pytesseract.image_to_string(
                thresh,
                config="--psm 7 --oem 3 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
            ).strip()

        results.append((cx, cy, text, (x, y, w, h)))

    return results


class RanBotApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Ran Online Auto-Target Bot")
        self.root.geometry("420x620")
        self.root.configure(bg="#0d1220")
        self.root.resizable(False, False)

        self.cfg = load_config()
        self.running = False
        self.scan_thread = None
        self.status_var = tk.StringVar(value="Stopped")
        self.log_lines = []

        # Monster list with enabled state
        self.monster_vars = {}   # name -> BooleanVar
        self.all_monsters = list(DEFAULT_MONSTERS)
        for m in self.cfg.get("selected_monsters", []):
            if m not in self.all_monsters:
                self.all_monsters.append(m)

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------ UI --

    def _build_ui(self):
        bg = "#0d1220"
        fg = "#ccd6f6"
        accent = "#4466aa"
        btn_bg = "#1a2a4a"

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TCheckbutton", background=bg, foreground=fg,
                        font=("Courier New", 10))
        style.configure("TScrollbar", background="#1a2a4a", troughcolor=bg)

        # Title
        tk.Label(self.root, text="RAN ONLINE AUTO-TARGET BOT",
                 bg=bg, fg=accent, font=("Courier New", 11, "bold"),
                 pady=10).pack(fill="x")

        # ── Monster Selection ──────────────────────────────────────────────
        frame_mobs = tk.LabelFrame(self.root, text=" Select Monsters to Farm ",
                                   bg=bg, fg=accent, font=("Courier New", 9),
                                   bd=1, relief="solid")
        frame_mobs.pack(fill="x", padx=12, pady=(0, 8))

        scroll_canvas = tk.Canvas(frame_mobs, bg=bg, bd=0, highlightthickness=0, height=180)
        scrollbar = ttk.Scrollbar(frame_mobs, orient="vertical", command=scroll_canvas.yview)
        self.mob_frame = tk.Frame(scroll_canvas, bg=bg)

        self.mob_frame.bind("<Configure>",
            lambda e: scroll_canvas.configure(scrollregion=scroll_canvas.bbox("all")))
        scroll_canvas.create_window((0, 0), window=self.mob_frame, anchor="nw")
        scroll_canvas.configure(yscrollcommand=scrollbar.set)

        scroll_canvas.pack(side="left", fill="both", expand=True, padx=4, pady=4)
        scrollbar.pack(side="right", fill="y")

        self._populate_mob_list()

        btn_row = tk.Frame(frame_mobs, bg=bg)
        btn_row.pack(fill="x", padx=4, pady=4)
        tk.Button(btn_row, text="+ Add Monster", bg=btn_bg, fg=fg,
                  font=("Courier New", 9), relief="flat", cursor="hand2",
                  command=self._add_monster).pack(side="left", padx=4)
        tk.Button(btn_row, text="Select All", bg=btn_bg, fg=fg,
                  font=("Courier New", 9), relief="flat", cursor="hand2",
                  command=self._select_all).pack(side="left", padx=4)
        tk.Button(btn_row, text="Clear All", bg=btn_bg, fg=fg,
                  font=("Courier New", 9), relief="flat", cursor="hand2",
                  command=self._clear_all).pack(side="left", padx=4)

        # ── Settings ───────────────────────────────────────────────────────
        frame_cfg = tk.LabelFrame(self.root, text=" Settings ",
                                  bg=bg, fg=accent, font=("Courier New", 9),
                                  bd=1, relief="solid")
        frame_cfg.pack(fill="x", padx=12, pady=(0, 8))

        def row(parent, label, key, col=0):
            f = tk.Frame(parent, bg=bg)
            f.pack(fill="x", padx=8, pady=2)
            tk.Label(f, text=label, bg=bg, fg="#8899bb",
                     font=("Courier New", 9), width=22, anchor="w").pack(side="left")
            var = tk.StringVar(value=str(self.cfg[key]))
            entry = tk.Entry(f, textvariable=var, bg="#1a2a4a", fg=fg,
                             font=("Courier New", 9), width=8, relief="flat",
                             insertbackground=fg)
            entry.pack(side="left")
            var.trace_add("write", lambda *a, k=key, v=var: self._update_cfg(k, v))
            return var

        row(frame_cfg, "Scan interval (sec):", "scan_interval")
        row(frame_cfg, "Attack interval (sec):", "attack_interval")
        row(frame_cfg, "Click Y offset (px):", "click_offset_y")
        row(frame_cfg, "Death timeout (sec):", "death_timeout")

        # Click button selector
        f_click = tk.Frame(frame_cfg, bg=bg)
        f_click.pack(fill="x", padx=8, pady=(2, 6))
        tk.Label(f_click, text="Attack click type:", bg=bg, fg="#8899bb",
                 font=("Courier New", 9), width=22, anchor="w").pack(side="left")
        self.click_btn_var = tk.StringVar(value=self.cfg.get("click_button", "left"))
        for label, val in [("Left Click", "left"), ("Right Click", "right")]:
            tk.Radiobutton(
                f_click, text=label, variable=self.click_btn_var, value=val,
                bg=bg, fg=fg, selectcolor="#1a2a4a", activebackground=bg,
                font=("Courier New", 9),
                command=lambda: self._set_click_button(self.click_btn_var.get())
            ).pack(side="left", padx=6)

        # Region selector
        f_region = tk.Frame(frame_cfg, bg=bg)
        f_region.pack(fill="x", padx=8, pady=4)
        self.region_label = tk.Label(
            f_region,
            text=self._region_text(),
            bg=bg, fg="#8899bb", font=("Courier New", 8), anchor="w"
        )
        self.region_label.pack(side="left", fill="x", expand=True)
        tk.Button(f_region, text="Set Region", bg=btn_bg, fg=fg,
                  font=("Courier New", 8), relief="flat", cursor="hand2",
                  command=self._set_region).pack(side="right")
        tk.Button(f_region, text="Full Screen", bg=btn_bg, fg=fg,
                  font=("Courier New", 8), relief="flat", cursor="hand2",
                  command=self._clear_region).pack(side="right", padx=4)

        # ── Start / Stop ───────────────────────────────────────────────────
        self.btn_start = tk.Button(
            self.root, text="▶  START FARMING",
            bg="#1a4a1a", fg="#44ff66",
            font=("Courier New", 12, "bold"), relief="flat",
            cursor="hand2", pady=8,
            command=self._toggle
        )
        self.btn_start.pack(fill="x", padx=12, pady=(4, 2))

        tk.Button(
            self.root, text="🔍  TEST SCAN (see what bot detects)",
            bg="#1a2a3a", fg="#88aaff",
            font=("Courier New", 9), relief="flat",
            cursor="hand2", pady=4,
            command=self._test_scan
        ).pack(fill="x", padx=12, pady=(0, 4))

        # Status
        tk.Label(self.root, textvariable=self.status_var,
                 bg=bg, fg="#8899bb", font=("Courier New", 9)).pack()

        # ── Log ────────────────────────────────────────────────────────────
        frame_log = tk.LabelFrame(self.root, text=" Activity Log ",
                                  bg=bg, fg=accent, font=("Courier New", 9),
                                  bd=1, relief="solid")
        frame_log.pack(fill="both", expand=True, padx=12, pady=(6, 10))

        self.log_text = tk.Text(frame_log, bg="#080d14", fg="#556677",
                                font=("Courier New", 8), relief="flat",
                                state="disabled", height=8)
        self.log_text.pack(fill="both", expand=True, padx=4, pady=4)

    def _populate_mob_list(self):
        for widget in self.mob_frame.winfo_children():
            widget.destroy()
        selected = self.cfg.get("selected_monsters", [])
        for name in self.all_monsters:
            var = tk.BooleanVar(value=name in selected)
            self.monster_vars[name] = var
            cb = ttk.Checkbutton(self.mob_frame, text=name, variable=var,
                                 command=self._save_selected)
            cb.pack(anchor="w", padx=8, pady=1)

    def _region_text(self):
        r = self.cfg.get("region")
        if r:
            return f"Region: {r['left']},{r['top']}  {r['width']}×{r['height']}"
        return "Region: Full Screen"

    def _update_cfg(self, key, var):
        try:
            val = float(var.get()) if "." in var.get() or key == "scan_interval" or key == "click_delay" else int(var.get())
            self.cfg[key] = val
        except ValueError:
            pass

    def _set_click_button(self, val):
        self.cfg["click_button"] = val
        save_config(self.cfg)

    def _save_selected(self):
        self.cfg["selected_monsters"] = [n for n, v in self.monster_vars.items() if v.get()]
        save_config(self.cfg)

    def _add_monster(self):
        name = simpledialog.askstring("Add Monster", "Enter monster name (as shown in game):",
                                      parent=self.root)
        if name and name.strip():
            name = name.strip()
            if name not in self.all_monsters:
                self.all_monsters.append(name)
            self._populate_mob_list()
            self.monster_vars[name].set(True)
            self._save_selected()

    def _select_all(self):
        for v in self.monster_vars.values():
            v.set(True)
        self._save_selected()

    def _clear_all(self):
        for v in self.monster_vars.values():
            v.set(False)
        self._save_selected()

    def _set_region(self):
        messagebox.showinfo(
            "Set Game Region",
            "After clicking OK, you have 3 seconds to move your mouse to the\n"
            "TOP-LEFT corner of the game window, then 3 more seconds to move\n"
            "to the BOTTOM-RIGHT corner.\n\n"
            "The region between those two points will be used for scanning.",
            parent=self.root
        )
        self._log("Move mouse to TOP-LEFT of game window...")
        self.root.after(3000, self._capture_tl)

    def _capture_tl(self):
        self._tl = pyautogui.position()
        self._log(f"Top-left captured: {self._tl}")
        self._log("Now move mouse to BOTTOM-RIGHT of game window...")
        self.root.after(3000, self._capture_br)

    def _capture_br(self):
        br = pyautogui.position()
        tl = self._tl
        # Ensure top-left is actually the smaller coordinate
        left   = min(tl.x, br.x)
        top    = min(tl.y, br.y)
        width  = abs(br.x - tl.x)
        height = abs(br.y - tl.y)
        self.cfg["region"] = {
            "left": left, "top": top,
            "width": width, "height": height
        }
        self.region_label.config(text=self._region_text())
        save_config(self.cfg)
        self._log(f"Region set: {self._region_text()}")

    def _clear_region(self):
        self.cfg["region"] = None
        self.region_label.config(text=self._region_text())
        save_config(self.cfg)
        self._log("Region cleared — using full screen")

    def _toggle(self):
        if self.running:
            self._stop()
        else:
            self._start()

    def _start(self):
        selected = [n for n, v in self.monster_vars.items() if v.get()]
        if not selected:
            messagebox.showwarning("No Monsters", "Please select at least one monster to farm.", parent=self.root)
            return
        self.running = True
        self.btn_start.config(text="■  STOP FARMING", bg="#4a1a1a", fg="#ff4444")
        self.status_var.set("Running — scanning for mobs...")
        self._log(f"Started farming: {', '.join(selected)}")
        if HAS_OCR:
            self._log(f"Tesseract: {pytesseract.pytesseract.tesseract_cmd}")
        else:
            self._log("⚠ pytesseract not found — name detection disabled, using color only")
        save_config(self.cfg)
        self.scan_thread = threading.Thread(target=self._scan_loop, daemon=True)
        self.scan_thread.start()

    def _stop(self):
        self.running = False
        self.btn_start.config(text="▶  START FARMING", bg="#1a4a1a", fg="#44ff66")
        self.status_var.set("Stopped")
        self._log("Stopped.")

    def _log(self, msg):
        def _do():
            self.log_text.config(state="normal")
            self.log_text.insert("end", msg + "\n")
            self.log_text.see("end")
            self.log_text.config(state="disabled")
        self.root.after(0, _do)

    # --------------------------------------------------------- Scan Loop ---

    def _scan_loop(self):
        sct = mss.mss()
        while self.running:
            try:
                self._do_scan(sct)
            except Exception as e:
                self._log(f"Error: {e}")

    def _grab_frame(self, sct):
        region = self.cfg.get("region")
        monitor = region if region else sct.monitors[1]
        screenshot = sct.grab(monitor)
        frame = np.array(screenshot)
        return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR), region

    def _do_click(self, x, y):
        btn = self.cfg.get("click_button", "left")
        pyautogui.click(x, y, button=btn)

    def _find_target_still_alive(self, sct, tag_sx, tag_sy, name, tolerance=50):
        """Return updated click position if tag still visible, else None."""
        frame, region = self._grab_frame(sct)
        tags = find_red_name_tags(frame, self.cfg)
        offset_x = region["left"] if region else 0
        offset_y = region["top"] if region else 0
        best = None
        best_dist = tolerance
        for (cx, cy, text, _) in tags:
            sx = cx + offset_x
            sy = cy + offset_y
            dist = ((sx - tag_sx) ** 2 + (sy - tag_sy) ** 2) ** 0.5
            if dist < best_dist:
                if not HAS_OCR or not name or name.lower() in text.lower() or not text:
                    best_dist = dist
                    best = (sx, sy + self.cfg["click_offset_y"] + 8)
        return best

    def _do_scan(self, sct):
        frame, region = self._grab_frame(sct)
        tags = find_red_name_tags(frame, self.cfg)

        selected = [n.lower() for n, v in self.monster_vars.items() if v.get()]
        offset_x = region["left"] if region else 0
        offset_y = region["top"] if region else 0

        self.root.after(0, lambda n=len(tags): self.status_var.set(
            f"Running — {n} red tag(s) found" if tags else "Running — scanning..."))

        if not tags:
            time.sleep(self.cfg["scan_interval"])
            return

        # Filter to selected monsters only
        matched = []
        for (cx, cy, text, rect) in tags:
            if HAS_OCR and text:
                if any(mob in text.lower() for mob in selected):
                    matched.append((cx, cy, text, rect))
            else:
                matched.append((cx, cy, text, rect))  # no OCR — target all red tags

        if not matched:
            time.sleep(self.cfg["scan_interval"])
            return

        # Sort by distance to center of screen (closest to player first)
        frame_cx = frame.shape[1] // 2
        frame_cy = frame.shape[0] // 2
        matched.sort(key=lambda t: (t[0] - frame_cx) ** 2 + (t[1] - frame_cy) ** 2)

        cx, cy, text, rect = matched[0]
        rx, ry, rw, rh = rect
        tag_sx = cx + offset_x                        # screen coords of name tag center
        tag_sy = cy + offset_y
        tag_bottom_sy = (ry + rh) + offset_y          # screen coords of name tag bottom edge
        click_x = tag_sx                              # horizontally centered on the name tag
        click_y = tag_bottom_sy + self.cfg["click_offset_y"]  # below the tag = mob body
        name_display = text if text else "mob"
        btn = self.cfg.get("click_button", "left")

        self._log(f"Locked onto '{name_display}' at tag({tag_sx},{tag_sy}) → clicking body({click_x},{click_y})")
        self.root.after(0, lambda n=name_display: self.status_var.set(f"Attacking: {n}"))

        # Click to target first
        self._do_click(click_x, click_y)
        time.sleep(self.cfg["attack_interval"])

        # Keep attacking same target until it dies — do NOT switch
        deadline = time.time() + self.cfg["death_timeout"]
        while self.running and time.time() < deadline:
            alive_pos = self._find_target_still_alive(sct, tag_sx, tag_sy, text)
            if alive_pos is None:
                self._log(f"'{name_display}' is dead! Scanning for next target...")
                time.sleep(0.3)
                break
            # Update click position in case mob moved slightly
            click_x, click_y = alive_pos
            self._do_click(click_x, click_y)
            time.sleep(self.cfg["attack_interval"])
        else:
            if self.running:
                self._log(f"Timeout on '{name_display}' — moving to next")

    def _test_scan(self):
        """Take one screenshot, find red tags, log results and move mouse to each."""
        self._log("--- TEST SCAN ---")
        time.sleep(1)  # give user time to switch to game window
        with mss.mss() as sct:
            frame, region = self._grab_frame(sct)
        tags = find_red_name_tags(frame, self.cfg)
        offset_x = region["left"] if region else 0
        offset_y = region["top"] if region else 0

        if not tags:
            self._log("No red name tags found! Try using Full Screen mode.")
            return

        self._log(f"Found {len(tags)} red tag(s):")
        for i, (cx, cy, text, rect) in enumerate(tags):
            screen_x = cx + offset_x
            screen_y = cy + self.cfg["click_offset_y"] + offset_y
            self._log(f"  [{i+1}] name='{text}' tag=({cx+offset_x},{cy+offset_y}) click=({screen_x},{screen_y})")
            # Move mouse (don't click) to show where it would click
            try:
                pyautogui.moveTo(screen_x, screen_y, duration=0.3)
                time.sleep(0.5)
            except Exception:
                pass
        self._log("--- END TEST SCAN ---")

    def _on_close(self):
        self._stop()
        save_config(self.cfg)
        self.root.destroy()


def main():
    if not HAS_OCR:
        print("Warning: pytesseract not installed. Name-based filtering disabled.")
        print("Install with: pip install pytesseract")
        print("Also install Tesseract OCR: https://github.com/UB-Mannheim/tesseract/wiki")

    root = tk.Tk()
    app = RanBotApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
