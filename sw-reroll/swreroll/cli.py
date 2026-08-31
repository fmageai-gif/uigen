"""Command line entry point: `python -m swreroll ...` or `swreroll ...`."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

from .adb import EMULATOR_PORTS, AdbDevice, AdbError, connect_instances, list_devices
from .config import ConfigError, RunConfig, load_flow
from .flow import Context, run_phase
from .ocr import Ocr, OcrError, PSM_LINE, PSM_SPARSE
from .runner import Runner
from .vision import TemplateStore, normalise

HERE = Path(__file__).resolve().parent.parent
DEFAULT_FLOW = HERE / "flows" / "summoners_war.yaml"
DEFAULT_TEMPLATES = HERE / "templates"
DEFAULT_OUT = HERE / "runs" / "latest"

log = logging.getLogger("swreroll")


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )


def _pick_serials(args) -> list[str]:
    available = list_devices(args.adb)
    if args.device:
        missing = [d for d in args.device if d not in available]
        if missing:
            raise SystemExit(
                f"Not connected: {', '.join(missing)}\nAvailable: {', '.join(available) or '(none)'}"
            )
        return list(args.device)
    if not available:
        raise SystemExit(
            "No adb devices found.\n"
            "  - Emulator running? LDPlayer/MuMu/BlueStacks need ADB enabled in settings.\n"
            "  - Try: adb connect 127.0.0.1:5555   (LDPlayer instance 0)\n"
            "  - Multi-instance ports usually step by 2: 5555, 5557, 5559, ..."
        )
    return available


# --------------------------------------------------------------------------

def cmd_devices(args) -> int:
    serials = list_devices(args.adb)
    if not serials:
        print("No devices in the `device` state.")
        return 1
    for s in serials:
        try:
            dev = AdbDevice(serial=s, adb_path=args.adb)
            w, h = dev.screen_size()
            model = dev.shell("getprop", "ro.product.model").strip()
            print(f"{s:<24} {w}x{h:<8} {model}")
        except AdbError as exc:
            print(f"{s:<24} <error: {exc}>")
    return 0


def cmd_connect(args) -> int:
    """Attach emulator instances without hunting for their ports by hand."""
    base, stride = EMULATOR_PORTS[args.emulator]
    print(
        f"{args.emulator}: trying {args.instances} instance(s) from port {base} "
        f"(+{stride} each)"
    )
    attached = connect_instances(args.emulator, args.instances, args.adb)
    if not attached:
        print(
            f"\nNothing connected. Check that:\n"
            f"  - the instances are actually running\n"
            f"  - ADB is enabled in the emulator's settings\n"
            f"  - the port matches: MuMu shows it in the Multi-Instance Manager\n"
            f"    (MuMu 6 and Nebula use 7555 -- try --emulator mumu6)",
            file=sys.stderr,
        )
        return 1
    for serial in attached:
        print(f"  connected {serial}")
    print(f"\n{len(attached)} instance(s) ready. Verify with: swreroll devices")
    return 0


def cmd_shot(args) -> int:
    serial = (args.device or _pick_serials(args))[0]
    dev = AdbDevice(serial=serial, adb_path=args.adb)
    img = dev.screencap()

    if args.crop:
        try:
            x, y, w, h = (int(v) for v in args.crop.split(","))
        except ValueError:
            raise SystemExit("--crop wants four integers: x,y,w,h (in reference-width pixels)")
        norm, _ = normalise(img)
        crop = norm[y : y + h, x : x + w]
        if crop.size == 0:
            raise SystemExit(f"Crop {args.crop} is empty for a {norm.shape[1]}x{norm.shape[0]} frame")
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(out), crop)
        print(f"template written: {out}  ({crop.shape[1]}x{crop.shape[0]})")
        return 0

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if args.grid:
        img = _draw_grid(img)
    cv2.imwrite(str(out), img)
    print(f"screenshot: {out}  ({img.shape[1]}x{img.shape[0]})")
    if args.grid:
        print("Grid labels are reference-width pixels -- feed them straight to --crop.")
    return 0


def _draw_grid(img: np.ndarray, step: int = 100) -> np.ndarray:
    """Overlay a labelled pixel grid so crops can be eyeballed off the image."""
    norm, _ = normalise(img)
    out = norm.copy()
    h, w = out.shape[:2]
    for x in range(0, w, step):
        cv2.line(out, (x, 0), (x, h), (0, 200, 255), 1)
        cv2.putText(out, str(x), (x + 3, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 200, 255), 1)
    for y in range(0, h, step):
        cv2.line(out, (0, y), (w, y), (0, 200, 255), 1)
        cv2.putText(out, str(y), (3, y + 14), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 200, 255), 1)
    return out


def cmd_check(args) -> int:
    """Score every template against a live screen or a saved PNG.

    Run this before a long session. If your 'summon result' template only
    scores 0.71, the loop will not find it at 3am either.
    """
    store = TemplateStore(Path(args.templates))
    if args.image:
        screen = cv2.imread(args.image, cv2.IMREAD_COLOR)
        if screen is None:
            raise SystemExit(f"Could not read {args.image}")
    else:
        serial = (args.device or _pick_serials(args))[0]
        screen = AdbDevice(serial=serial, adb_path=args.adb).screencap()

    names = args.name or sorted(
        str(p.relative_to(store.root).with_suffix("")).replace("\\", "/")
        for p in Path(store.root).rglob("*.png")
    )
    if not names:
        raise SystemExit(f"No templates under {store.root}")

    worst = 1.0
    for name in names:
        match = store.find(screen, name, threshold=args.threshold)
        flag = "HIT " if match.found else "miss"
        print(f"{flag} {match.score:.3f}  {name:<40} @ {match.center}")
        worst = min(worst, match.score)
    return 0


def _parse_region(value: str | None):
    if not value:
        return None
    try:
        parts = tuple(float(v) for v in value.split(","))
    except ValueError:
        raise SystemExit("--region wants four numbers: x,y,w,h")
    if len(parts) != 4:
        raise SystemExit("--region wants exactly four numbers: x,y,w,h")
    if any(v > 1.0 for v in parts):
        raise SystemExit("--region values are 0..1 fractions of the screen, not pixels")
    return parts


def _make_ocr(args) -> Ocr:
    return Ocr(binary=args.tesseract, lang=args.lang, tessdata_dir=args.tessdata_dir)


def cmd_ocr(args) -> int:
    """Read a region, so you can tune it before trusting it in a loop."""
    ocr = _make_ocr(args)
    if args.image:
        screen = cv2.imread(args.image, cv2.IMREAD_COLOR)
        if screen is None:
            raise SystemExit(f"Could not read {args.image}")
    else:
        serial = (args.device or _pick_serials(args))[0]
        screen = AdbDevice(serial=serial, adb_path=args.adb).screencap()

    region = _parse_region(args.region)
    pre = {"invert": not args.no_invert, "upscale": args.upscale}

    if args.save:
        from .ocr import crop, preprocess
        sub, _, _ = crop(screen, region)
        cv2.imwrite(args.save, preprocess(sub, **pre))
        print(f"preprocessed crop written to {args.save}")

    if args.words:
        words = ocr.words(screen, region, psm=PSM_SPARSE, **pre)
        if not words:
            print("(nothing recognised)")
            return 1
        for w in words:
            print(f"{w.conf:5.1f}  {w.text:<28} @ {w.rect}")
        return 0

    text = ocr.read(screen, region, psm=args.psm, **pre)
    print(repr(text))
    if not text:
        print(
            "\nNothing came back. Things to try, in order:\n"
            "  --save crop.png    and look at what tesseract is actually being fed\n"
            "  --no-invert        if the text is already dark on a light panel\n"
            "  --upscale 4        small text needs more\n"
            "  --psm 8            if the region holds exactly one word\n"
            "  tighten --region   so the crop is only the text, no border art",
            file=sys.stderr,
        )
        return 1
    return 0


def cmd_phase(args) -> int:
    """Run a single phase once, against a live device. The debugging workhorse."""
    flow = load_flow(args.flow)
    serial = (args.device or _pick_serials(args))[0]
    ctx = Context(
        device=AdbDevice(serial=serial, adb_path=args.adb, dry_run=args.dry_run),
        store=TemplateStore(Path(args.templates)),
        flow=flow,
        threshold=args.threshold,
        step_timeout=args.timeout,
        out_dir=Path(args.out),
        account_id="debug",
        ocr=_make_ocr(args),
    )
    ok = run_phase(ctx, flow.phase(args.name))
    print(f"phase {args.name}: {'ok' if ok else 'skipped'} | keep={ctx.keep} hits={ctx.hits}")
    return 0


def cmd_run(args) -> int:
    flow = load_flow(args.flow)
    templates = Path(args.templates)
    keepers = TemplateStore(templates).group(args.keeper_group)
    wanted = list(args.want or flow.defaults.get("wanted") or [])
    # A run with no keeper condition at all would reroll forever and throw
    # away every account it ever made, including the good one.
    if not keepers and not wanted and not args.dry_run:
        raise SystemExit(
            f"No keeper condition set -- every account would be discarded.\n"
            f"Give the loop at least one of:\n"
            f"  by name (OCR, preferred):  --want Ariel --want Beelzebub\n"
            f"                             or a 'wanted:' list in {args.flow}\n"
            f"  by image:                  drop a crop in {templates / args.keeper_group}/\n"
            f"                             swreroll shot --grid --out shots/result.png\n"
            f"                             swreroll shot --crop X,Y,W,H "
            f"--out {templates / args.keeper_group}/target.png"
        )
    log.info(
        "keeper conditions: names=[%s] templates=[%s]",
        ", ".join(wanted) or "-",
        ", ".join(keepers) or "-",
    )

    cfg = RunConfig(
        flow_path=Path(args.flow),
        templates_dir=templates,
        out_dir=Path(args.out),
        serials=_pick_serials(args),
        adb_path=args.adb,
        max_accounts=args.max_accounts,
        max_keeps=args.max_keeps,
        match_threshold=args.threshold,
        step_timeout=args.timeout,
        dry_run=args.dry_run,
        save_shots=not args.no_shots,
        verbose=args.verbose,
        tesseract=args.tesseract,
        tessdata_dir=args.tessdata_dir,
        lang=args.lang,
        wanted=list(args.want or []),
    )
    stats = Runner(cfg, flow).run()
    print(stats.summary())
    return 0


def cmd_stats(args) -> int:
    path = Path(args.out) / "results.jsonl"
    if not path.is_file():
        raise SystemExit(f"No results at {path}")
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if not rows:
        print("no accounts recorded yet")
        return 0

    keeps = [r for r in rows if r["keep"]]
    errors = [r for r in rows if r["error"]]
    good = [r["seconds"] for r in rows if not r["error"]]
    avg = sum(good) / len(good) if good else 0.0

    print(f"accounts   : {len(rows)}")
    print(f"keeps      : {len(keeps)}  ({len(keeps) / len(rows) * 100:.2f}%)")
    print(f"errors     : {len(errors)} ({len(errors) / len(rows) * 100:.1f}%)")
    print(f"avg / acct : {avg / 60:.1f} min")
    if good:
        print(f"throughput : {3600 / avg:.1f} accounts/hour/device")
    if keeps:
        print("\nkeepers:")
        for r in keeps:
            print(f"  {r['account_id']}  {', '.join(r['hits'])}")
    if errors:
        print("\ntop failures:")
        for reason, n in Counter(r["error"].split("(")[0][:70] for r in errors).most_common(5):
            print(f"  {n:>4}x  {reason}")
    return 0


# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="swreroll",
        description="ADB-driven reroll automation for Summoners War.",
    )
    p.add_argument("--adb", default="adb", help="path to the adb binary")
    p.add_argument("-d", "--device", action="append", help="target serial (repeatable)")
    p.add_argument("--templates", default=str(DEFAULT_TEMPLATES))
    p.add_argument("--out", default=str(DEFAULT_OUT), help="run directory for logs and shots")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--tesseract", default="tesseract", help="path to the tesseract binary")
    p.add_argument(
        "--tessdata-dir",
        help="folder holding eng.traineddata, if it is outside the default prefix",
    )
    p.add_argument("--lang", default="eng", help="tesseract language")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("devices", help="list connected devices").set_defaults(func=cmd_devices)

    s = sub.add_parser("connect", help="adb-connect emulator instances by name")
    s.add_argument(
        "emulator", choices=sorted(EMULATOR_PORTS),
        help="mumu = MuMu Player 12; mumu6 = MuMu 6 / Nebula",
    )
    s.add_argument("-n", "--instances", type=int, default=1)
    s.set_defaults(func=cmd_connect)

    s = sub.add_parser("shot", help="capture a screenshot or cut a template from one")
    s.add_argument("--grid", action="store_true", help="overlay a labelled 100px grid")
    s.add_argument("--crop", help="x,y,w,h -- save just this rectangle as a template")
    s.set_defaults(func=cmd_shot, out=str(HERE / "shots" / "screen.png"))

    s = sub.add_parser("check", help="score templates against a screen")
    s.add_argument("--image", help="score against a saved PNG instead of a device")
    s.add_argument("--name", action="append", help="only these templates (repeatable)")
    s.add_argument("--threshold", type=float, default=0.85)
    s.set_defaults(func=cmd_check)

    s = sub.add_parser("ocr", help="read text off a region -- use this to tune regions")
    s.add_argument("--image", help="read a saved PNG instead of a device")
    s.add_argument(
        "--region",
        help="x,y,w,h as 0..1 fractions, e.g. 0.30,0.62,0.40,0.10. Omit for the whole screen.",
    )
    s.add_argument("--psm", type=int, default=PSM_LINE)
    s.add_argument("--words", action="store_true", help="list every word with its box")
    s.add_argument("--no-invert", action="store_true", help="for dark-on-light text")
    s.add_argument("--upscale", type=float, default=3.0)
    s.add_argument("--save", help="write the preprocessed crop here to eyeball it")
    s.set_defaults(func=cmd_ocr)

    s = sub.add_parser("phase", help="run one phase against a live device")
    s.add_argument("name")
    s.add_argument("--flow", default=str(DEFAULT_FLOW))
    s.add_argument("--threshold", type=float, default=0.85)
    s.add_argument("--timeout", type=float, default=45.0)
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(func=cmd_phase)

    s = sub.add_parser("run", help="run the reroll loop")
    s.add_argument("--flow", default=str(DEFAULT_FLOW))
    s.add_argument("--max-accounts", type=int, default=0, help="0 = unlimited")
    s.add_argument("--max-keeps", type=int, default=1, help="stop a device after N keepers")
    s.add_argument("--keeper-group", default="keepers")
    s.add_argument(
        "--want",
        action="append",
        help="monster name to keep, for OCR flows (repeatable). "
             "Overrides defaults.wanted in the flow file.",
    )
    s.add_argument("--threshold", type=float, default=0.85)
    s.add_argument("--timeout", type=float, default=45.0)
    s.add_argument("--dry-run", action="store_true", help="no input is sent to the device")
    s.add_argument("--no-shots", action="store_true")
    s.set_defaults(func=cmd_run)

    s = sub.add_parser("stats", help="summarise a run directory")
    s.set_defaults(func=cmd_stats)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _setup_logging(args.verbose)
    try:
        return args.func(args)
    except (ConfigError, AdbError, OcrError) as exc:
        log.error("%s", exc)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
