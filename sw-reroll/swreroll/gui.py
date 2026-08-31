"""A small desktop window for driving the reroll bot.

Tkinter on purpose: it ships with Python, so this needs no install beyond
what the bot already requires, and it opens as a normal Windows window.

Everything slow runs on a worker thread. Tk is not thread-safe, so workers
never touch a widget -- they push text onto a queue that the UI drains on a
timer. The Stop button sets an event the workers check between steps.
"""

from __future__ import annotations

import queue
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

from . import capture
from .adb import AdbDevice, AdbError, connect_instances, list_devices
from .config import load_flow
from .vision import TemplateStore

HERE = Path(__file__).resolve().parent.parent
DEFAULT_FLOW = HERE / "flows" / "summoners_war.yaml"
TEMPLATES = HERE / "templates"
SHOTS = HERE / "shots"

BG = "#1e1f26"
FG = "#e8e8ea"
ACCENT = "#4a9eff"
GOOD = "#3ec46d"
WARN = "#e5a03c"
BAD = "#e5544b"


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        # Workers never touch a widget. They post (kind, payload) here and the
        # main thread applies it in _drain. Calling root.after() off-thread
        # looks like it works and then wedges the UI, so nothing does.
        self.messages: queue.Queue[tuple[str, object]] = queue.Queue()
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.device: AdbDevice | None = None
        self.adb_path = tk.StringVar(value="adb")

        root.title("Summoners War Reroll")
        root.geometry("760x620")
        root.configure(bg=BG)
        root.minsize(680, 520)

        self._build()
        self.root.after(80, self._drain)
        self.log("Ready. Start with 1. Connect.", "info")

    # ---- layout ---------------------------------------------------------

    def _build(self) -> None:
        pad = {"padx": 10, "pady": 6}

        top = tk.Frame(self.root, bg=BG)
        top.pack(fill="x", **pad)

        tk.Label(top, text="adb.exe", bg=BG, fg=FG).pack(side="left")
        tk.Entry(top, textvariable=self.adb_path, width=48, bg="#2a2c36", fg=FG,
                 insertbackground=FG, relief="flat").pack(side="left", padx=8)
        tk.Button(top, text="Find it for me", command=lambda: self._go(self._find_adb),
                  bg="#2a2c36", fg=FG, relief="flat",
                  activebackground=ACCENT).pack(side="left")

        self.status = tk.Label(
            self.root, text="Not connected", bg=BG, fg=WARN,
            font=("Segoe UI", 10, "bold"), anchor="w",
        )
        self.status.pack(fill="x", padx=10)

        # --- actions ---
        grid = tk.Frame(self.root, bg=BG)
        grid.pack(fill="x", **pad)
        for c in range(3):
            grid.columnconfigure(c, weight=1)

        self.buttons: dict[str, tk.Button] = {}
        actions = [
            ("1. Connect", self._connect, "Attach to the running MuMu instance"),
            ("2. Screenshot", self._screenshot, "Save the game screen with a grid"),
            ("3. Sweep tutorial", self._sweep, "Tap through the tutorial (no setup needed)"),
            ("Check templates", self._check, "Score every captured crop"),
            ("Run reroll", self._run, "The full loop -- needs templates"),
            ("Open folders", self._open_folder, "Screenshots and templates on disk"),
        ]
        for i, (label, fn, tip) in enumerate(actions):
            b = tk.Button(
                grid, text=label, command=lambda f=fn: self._go(f),
                bg="#2a2c36", fg=FG, relief="flat", height=2,
                activebackground=ACCENT, activeforeground="#ffffff",
                font=("Segoe UI", 10),
            )
            b.grid(row=i // 3, column=i % 3, sticky="ew", padx=4, pady=4)
            self._tooltip(b, tip)
            self.buttons[label] = b

        bar = tk.Frame(self.root, bg=BG)
        bar.pack(fill="x", padx=10)
        self.stop_btn = tk.Button(
            bar, text="STOP", command=self._stop, bg="#3a2226", fg=BAD,
            relief="flat", state="disabled", font=("Segoe UI", 10, "bold"),
        )
        self.stop_btn.pack(side="right")
        self.spinner = tk.Label(bar, text="", bg=BG, fg=ACCENT)
        self.spinner.pack(side="left")

        tk.Label(self.root, text="Log", bg=BG, fg="#8a8d99", anchor="w").pack(
            fill="x", padx=10, pady=(8, 0)
        )
        self.out = scrolledtext.ScrolledText(
            self.root, bg="#15161c", fg=FG, relief="flat", wrap="word",
            font=("Consolas", 9), insertbackground=FG,
        )
        self.out.pack(fill="both", expand=True, padx=10, pady=(2, 10))
        for tag, colour in (
            ("info", FG), ("good", GOOD), ("warn", WARN), ("bad", BAD),
            ("dim", "#8a8d99"),
        ):
            self.out.tag_config(tag, foreground=colour)

    def _tooltip(self, widget: tk.Widget, text: str) -> None:
        def enter(_):
            self.spinner.config(text=text, fg="#8a8d99")

        def leave(_):
            if not self._busy():
                self.spinner.config(text="")

        widget.bind("<Enter>", enter)
        widget.bind("<Leave>", leave)

    # ---- threading ------------------------------------------------------

    def log(self, text: str, tag: str = "info") -> None:
        self.messages.put(("log", (text, tag)))

    def _post_status(self, text: str, colour: str) -> None:
        self.messages.put(("status", (text, colour)))

    def _post_done(self) -> None:
        self.messages.put(("done", None))

    def _drain(self) -> None:
        """Runs on the main thread only. The single place widgets are touched."""
        try:
            while True:
                kind, payload = self.messages.get_nowait()
                if kind == "log":
                    text, tag = payload
                    self.out.insert("end", text + "\n", tag)
                    self.out.see("end")
                elif kind == "status":
                    text, colour = payload
                    self.status.config(text=text, fg=colour)
                elif kind == "done":
                    self.stop_btn.config(state="disabled")
                    self.spinner.config(text="")
        except queue.Empty:
            pass
        self.root.after(80, self._drain)

    def _busy(self) -> bool:
        return self.worker is not None and self.worker.is_alive()

    def _go(self, fn) -> None:
        if self._busy():
            self.log("Still busy -- press STOP first.", "warn")
            return
        self.stop_event.clear()
        self.stop_btn.config(state="normal")
        self.spinner.config(text="working...", fg=ACCENT)

        def wrapper():
            try:
                fn()
            except (AdbError, RuntimeError) as exc:
                self.log(str(exc), "bad")
            except Exception:
                self.log(traceback.format_exc(), "bad")
            finally:
                self._post_done()

        self.worker = threading.Thread(target=wrapper, daemon=True)
        self.worker.start()

    def _stop(self) -> None:
        self.stop_event.set()
        self.log("Stopping after the current step...", "warn")

    def _need_device(self) -> AdbDevice:
        if self.device is None:
            raise RuntimeError("Not connected yet -- press 1. Connect first.")
        return self.device



    # ---- actions --------------------------------------------------------

    def _find_adb(self) -> None:
        """Hunt for the adb.exe that ships with the common emulators."""
        self.log("Looking for adb.exe...", "dim")
        roots = [
            Path(r"C:\Program Files\Netease"),
            Path(r"C:\Program Files (x86)\Netease"),
            Path(r"C:\Program Files\BlueStacks_nxt"),
            Path(r"C:\LDPlayer"),
            Path(r"C:\Program Files\Nox"),
        ]
        for root in roots:
            if not root.is_dir():
                continue
            for found in root.rglob("adb.exe"):
                self.adb_path.set(str(found))
                self.log(f"Found: {found}", "good")
                return
        self.log(
            "No bundled adb.exe found. If you installed Android platform-tools, "
            "leaving this as 'adb' is fine.", "warn",
        )

    def _connect(self) -> None:
        adb = self.adb_path.get().strip() or "adb"
        self.log("Connecting to MuMu...", "dim")
        attached = []
        for kind in ("mumu", "mumu6", "ldplayer", "bluestacks", "nox"):
            try:
                attached = connect_instances(kind, count=4, adb_path=adb)
            except AdbError as exc:
                self.log(str(exc), "bad")
                return
            if attached:
                self.log(f"Connected via {kind}: {', '.join(attached)}", "good")
                break

        serials = list_devices(adb)
        if not serials:
            self._post_status("Not connected", BAD)
            self.log(
                "No device found.\n"
                "  - Is MuMu running with Android booted?\n"
                "  - MuMu: Device Settings > Developer options > ADB debug >\n"
                "    'Enable local connection', then restart the instance.",
                "bad",
            )
            return

        self.device = AdbDevice(serial=serials[0], adb_path=adb)
        w, h = self.device.screen_size()
        dpi = self.device.screen_density()
        self._post_status(f"Connected  {serials[0]}   {w}x{h} @ {dpi} dpi", GOOD)
        self.log(f"Using {serials[0]} ({w}x{h}, {dpi} dpi)", "good")
        if (w, h) != (1280, 720):
            self.log(
                f"Heads up: templates and coordinates assume 1280x720. "
                f"This is {w}x{h}, so taps will land in the wrong place.", "warn",
            )

        flow = load_flow(DEFAULT_FLOW)
        if not self.device.is_installed(flow.package):
            self.log(
                f"Summoners War not detected as '{flow.package}'.\n"
                f"Press 'Check templates' later; first confirm the package with:\n"
                f"  adb shell pm list packages | findstr smon", "warn",
            )

    def _screenshot(self) -> None:
        from .cli import _draw_grid
        import cv2

        dev = self._need_device()
        SHOTS.mkdir(parents=True, exist_ok=True)
        img = dev.screencap()
        stamp = time.strftime("%H%M%S")
        plain = SHOTS / f"screen-{stamp}.png"
        grid = SHOTS / f"grid-{stamp}.png"
        cv2.imwrite(str(plain), img)
        cv2.imwrite(str(grid), _draw_grid(img))

        w, h = dev.screen_size()
        capture.save(TEMPLATES, capture.Geometry(w, h, dev.screen_density()))
        self.log(f"Saved {plain.name} and {grid.name}", "good")
        self.log(f"  in {SHOTS}", "dim")
        self.log(
            "Open the grid one -- the numbers on it are the coordinates you "
            "send me, or type into a crop.", "dim",
        )

    def _sweep(self) -> None:
        """Tap the tutorial points on a loop. Needs nothing captured."""
        dev = self._need_device()
        flow = load_flow(DEFAULT_FLOW)
        raw = []
        for step in flow.phase("tutorial").steps:
            if step.action == "tap_through":
                raw = step.get("points") or []
                break
        if not raw:
            raise RuntimeError("no tap points found in the tutorial phase")

        w, h = dev.screen_size()
        points = [(int(x * w), int(y * h)) for x, y in raw]
        self.log(f"Sweeping {len(points)} points. Press STOP to end.", "info")
        self.log("Order: SKIP, dialogue, skill 3, 2, 1, dialogue, boss, left, right", "dim")

        taps = 0
        started = time.monotonic()
        while not self.stop_event.is_set():
            dev.tap(*points[taps % len(points)])
            taps += 1
            if taps % len(points) == 0:
                self.log(f"  {taps} taps ({time.monotonic() - started:.0f}s)", "dim")
            time.sleep(0.6)
        self.log(f"Stopped after {taps} taps.", "info")
        self.log(
            "Did the tutorial move along? If yes, adb and the coordinates are "
            "good. If nothing happened, the taps are not reaching the game.", "info",
        )

    def _check(self) -> None:
        dev = self._need_device()
        store = TemplateStore(TEMPLATES)
        names = sorted(
            str(p.relative_to(TEMPLATES).with_suffix("")).replace("\\", "/")
            for p in TEMPLATES.rglob("*.png")
        )
        if not names:
            self.log(
                "No templates captured yet.\n"
                "That is expected -- press 2. Screenshot, send me the grid "
                "image, and I will give you the exact crops to cut.", "warn",
            )
            return

        screen = dev.screencap()
        self.log(f"Scoring {len(names)} templates against the current screen:", "info")
        for name in names:
            m = store.find(screen, name, threshold=0.85)
            tag = "good" if m.found else "dim"
            self.log(f"  {'HIT ' if m.found else 'miss'} {m.score:.3f}  {name}", tag)
        self.log(
            "A template should score above ~0.9 on a screen where it belongs. "
            "Anything lower will fail during a real run.", "dim",
        )

    def _run(self) -> None:
        from .config import RunConfig
        from .runner import Runner

        dev = self._need_device()
        store = TemplateStore(TEMPLATES)
        if not store.group("keepers") and not list(TEMPLATES.rglob("elem_*.png")):
            raise RuntimeError(
                "Cannot run yet: no element or keeper templates captured.\n"
                "Without them every account looks like a miss and the loop "
                "would reroll forever, throwing away a good account if it found one.\n"
                "Press 2. Screenshot on a summon result screen and send it to me."
            )

        flow = load_flow(DEFAULT_FLOW)
        cfg = RunConfig(
            flow_path=DEFAULT_FLOW,
            templates_dir=TEMPLATES,
            out_dir=HERE / "runs" / "gui",
            serials=[dev.serial],
            adb_path=self.adb_path.get().strip() or "adb",
            max_accounts=0,
            max_keeps=1,
        )
        runner = Runner(cfg, flow)

        watcher = threading.Thread(
            target=lambda: (self.stop_event.wait(), runner.stop()), daemon=True
        )
        watcher.start()

        self.log("Starting the reroll loop. Press STOP to end cleanly.", "info")
        stats = runner.run()
        self.log(stats.summary(), "good")

    def _open_folder(self) -> None:
        SHOTS.mkdir(parents=True, exist_ok=True)
        TEMPLATES.mkdir(parents=True, exist_ok=True)
        for folder in (SHOTS, TEMPLATES):
            try:
                if sys.platform == "win32":
                    subprocess.Popen(["explorer", str(folder)])
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", str(folder)])
                else:
                    subprocess.Popen(["xdg-open", str(folder)])
            except OSError as exc:
                self.log(f"Could not open {folder}: {exc}", "warn")
        self.log(f"Screenshots: {SHOTS}", "dim")
        self.log(f"Templates:   {TEMPLATES}", "dim")


def main() -> int:
    root = tk.Tk()
    try:
        App(root)
    except Exception:
        messagebox.showerror("Startup failed", traceback.format_exc())
        return 1
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
