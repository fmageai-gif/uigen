# sw-reroll

ADB-driven reroll automation for **Summoners War: Sky Arena**. It creates a
guest account, skips the tutorial, claims the free rewards, burns the scrolls,
**reads the summoned monster's name with OCR**, and either banks the account or
wipes it and starts over — across as many emulator instances as you can run.

## Read this first

Com2uS's Terms of Service prohibit macros, bots and automation, and they run
periodic ban waves. **Point this at disposable reroll accounts only.** A reroll
account is disposable by definition, so the risk is bounded; a main account is
not. Don't run this against anything you care about.

And the arithmetic, before you spend a weekend on it:

- A fresh account yields roughly **1–3 Light & Darkness scrolls** total.
- At ~0.5% for the 5★, that's about **1–1.5% chance of *any* LD5 per account**
  — roughly 70–100 accounts.
- The LD 5★ pool is 40+ monsters, so a **specific** one is ~0.03% per account.
  That's thousands of rerolls. Reroll for "any of these eight", not for one.

`swreroll stats` reports your real numbers so you can stop guessing.

## How it decides what to keep

Two independent routes, and either one banks an account:

**By name (OCR — preferred).** Tesseract reads the monster's name off the
summon result and fuzzy-matches it against a wanted list. Fuzzy because
stylised game fonts make Tesseract swap glyphs in predictable ways — `B`→`8`,
`l`→`1`, `S`→`5` — which the matcher folds together before comparing. Adding a
target is one line of YAML.

```yaml
defaults:
  wanted: [Ariel, Jeanne, Vigor, Beelzebub, Zeratu]
```
```bash
swreroll run --want Ariel --want Beelzebub
```

**By image.** Drop a portrait crop into `templates/keepers/`. Useful for a
monster whose name OCRs badly, or for matching a 5★ dark frame rather than a
specific monster.

## Install

```bash
cd sw-reroll
pip install -e .            # or: pip install -r requirements.txt
```

Two external binaries:

- **adb** — Android platform-tools, or the one bundled with your emulator
  (`LDPlayer/adb.exe`, `MuMuPlayer/shell/adb.exe`). Pass `--adb <path>`.
- **tesseract** — only needed for OCR steps.
  Windows: <https://github.com/UB-Mannheim/tesseract/wiki> ·
  macOS: `brew install tesseract` · Debian: `apt install tesseract-ocr`.
  Already have a `tessdata` folder? Point at it with `--tessdata-dir`.

## Connect the emulator

```bash
adb connect 127.0.0.1:5555     # LDPlayer instance 0; ports usually step by 2
swreroll devices
```

```
127.0.0.1:5555     1280x720   LDPlayer
127.0.0.1:5557     1280x720   LDPlayer
```

Confirm the package id — it differs between stores:

```bash
adb shell pm list packages | grep -i smon
```

## Calibration

The shipped flow has the right *structure*; the regions and templates are
yours to capture. Budget an hour once, then it runs unattended.

**1. Capture a screen with a coordinate grid.**

```bash
swreroll shot --grid --out shots/home.png
```

**2. Cut templates straight out of it.** Read the `x,y,w,h` off the grid:

```bash
swreroll shot --crop 540,300,200,80 --out templates/ui/summon_altar.png
```

Prefer a crop that is small, high-contrast, and free of anything animated —
a button's label beats the whole button, and never include a spinner or a
number that changes.

**3. Verify every template scores well before trusting it.**

```bash
swreroll check --image shots/home.png
```
```
HIT  0.981  ui/summon_altar    @ (640, 340)
miss 0.612  ui/mailbox         @ (120, 88)
```

A template that only scores 0.61 will not be found at 3am either. Recut it.

**4. Tune the OCR region over the monster's name.**

```bash
swreroll ocr --region 0.30,0.62,0.40,0.10 --save crop.png
```

Regions are `x,y,w,h` as **0–1 fractions** of the screen, so they survive a
resolution change. If nothing comes back, look at `crop.png` — that is exactly
what Tesseract was fed. Then try `--upscale 4`, `--no-invert` for dark-on-light
text, `--psm 8` for a single word, or tighten the region until it holds only
the name.

`swreroll ocr --words` lists every word with its box, which is how you find a
region in the first place.

**5. Run one phase at a time.** No account is burned; nothing is wiped.

```bash
swreroll phase launch
swreroll phase summon
swreroll phase evaluate
```

## Run it

```bash
# One device, stop at the first keeper
swreroll run --want Ariel --want Beelzebub

# Every connected instance, overnight, capped
swreroll run --max-accounts 500 --max-keeps 1

# Rehearse without sending a single tap
swreroll run --dry-run -v
```

Progress is logged per account:

```
14:22:07 INFO    [127.0.0.1:5555] account 63 reroll | 63 accounts, 0 keeps,
                 1 errors | 4.2 min/account, 14.3 accounts/hour | elapsed 4.41h
```

**Stopping.** Ctrl-C finishes the current account and exits. Unattended, drop a
file named `STOP` in the run directory — workers wind down cleanly at the next
account boundary rather than mid-tutorial.

**On a hit** the account's data is left intact and the device stops. Go bind it
to a Hive account before you touch anything else — the next `pm clear` on that
instance destroys it.

```bash
swreroll stats
```
```
accounts   : 412
keeps      : 2  (0.49%)
errors     : 9 (2.2%)
avg / acct : 4.1 min
throughput : 14.6 accounts/hour/device
```

## Writing flows

A flow is phases of steps in YAML. The interpreter is small on purpose — the
intelligence lives in the flow file, which is what you'll be editing every time
Com2uS reshuffles a menu.

| Action | What it does |
|---|---|
| `tap` | Tap a template once visible, or a fixed point |
| `tap_text` | OCR-locate a word and tap its box — no template needed |
| `tap_through` | Hammer a point until a target screen appears (tutorial skipper) |
| `wait_for` / `wait_gone` | Block until a template appears / disappears |
| `wait_for_text` | Block until a phrase is legible |
| `dismiss` | Close every popup matching `templates/close/`, repeatedly |
| `read_text` / `read_number` | OCR a region into a named variable |
| `evaluate_names` | Keeper check by OCR'd monster name |
| `evaluate` | Keeper check by template match |
| `if_found` / `repeat` | Branching and loops |
| `swipe`, `key`, `back`, `text` | Raw input |
| `start_app`, `stop_app`, `restart_app`, `clear_data` | App lifecycle |
| `screenshot`, `note`, `abort` | Diagnostics and control |

Three conventions worth internalising:

- **Points** are `[0.5, 0.85]` (fractions) or `[640, 612]` (pixels). Values
  ≤ 1.0 are read as fractions, so fractions survive a resolution change.
- **Regions** are always `[x, y, w, h]` fractions.
- **`optional: true`** on a step skips it on timeout instead of failing the
  account. Event banners and seasonal popups belong here — they are not
  present on every account and must never cost you a run.

Prefer `tap_text` over `tap`. Text buttons — Summon, Confirm, Skip, Next, OK —
need no captured images at all, which is most of what a tutorial skip clicks.

### Reliability

Phases are ordered, and `reset` is last. **The runner skips `reset` entirely
once a keeper is found**, so a hit is never wiped — there's a test pinning that
specific behaviour, because it's the one bug that would make the whole tool
worse than useless.

Steps wait for the screen they expect rather than sleeping a fixed duration, so
a slow patch download or a laggy server costs seconds, not a broken run. Taps
carry a few pixels of positional jitter and a randomised inter-tap delay:
pixel-identical input at pixel-identical intervals is the most obvious bot
signature there is.

After five consecutive failures a device stops itself and points you at the
`TIMEOUT-*.png` screenshots in the run directory — that's almost always a menu
that moved, and grinding out 400 identical failures overnight helps nobody.

## Layout

```
swreroll/
  adb.py      device control: taps, screencaps, pm clear
  vision.py   multi-scale template matching, resolution-independent
  ocr.py      tesseract wrapper, preprocessing, fuzzy name matching
  flow.py     the step interpreter
  runner.py   parallel orchestration, keeper safety, result logging
  cli.py      devices / shot / check / ocr / phase / run / stats
flows/        the reroll script (edit this)
templates/    your captured crops (not committed)
tests/        70 tests, no emulator required
```

```bash
python -m pytest tests/ -q
```

The whole test suite runs against a fake device and a stubbed Tesseract, so it
needs neither an emulator nor the game.
