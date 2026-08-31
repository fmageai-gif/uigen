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

Three routes, any of which banks an account. **For "any LD nat 5" — the
default — use grade detection, not names.**

**By grade (default).** Counts the star glyphs on the result panel and reads
the element icon. "Five stars and light-or-dark" banks the account *whoever
the monster is*. This is strictly better than a name roster for your goal: it
keeps working the day Com2uS releases an LD5 nobody has heard of, and it never
depends on OCR reading a stylised name correctly.

```yaml
- evaluate_grade:
    star_region: [0.30, 0.70, 0.40, 0.09]
    min_stars: 5
    elements:
      light: ui/elem_light
      dark:  ui/elem_dark
      fire:  ui/elem_fire     # list all five, see below
      water: ui/elem_water
      wind:  ui/elem_wind
    keep_elements: [light, dark]
    on_unknown_element: keep
```

**Only an LD5 stops the run.** A fire/water/wind nat 5 is recorded as a note
and the reroll continues, so `swreroll stats` shows what the mystical scrolls
are actually buying without ever ending a run on a monster you didn't want.

### The asymmetry that shapes this

The two mistakes cost wildly different amounts:

- Banking a dud → two minutes of manual checking.
- Wiping a real LD5 → the entire run, **silently**. You'd grind 500 accounts,
  hit nothing, and never learn why.

So two rules follow. **List all five elements, not just light and dark.**
Identifying fire *positively* is what lets the bot wipe a fire nat 5 with
confidence; with only light/dark templates, "a fire monster" and "my crop is
broken" are the same observation. And **`on_unknown_element: keep`** — a nat 5
whose element can't be read at all is banked, flagged `UNVERIFIED`, and
screenshotted for you to check by hand.

If `UNVERIFIED` shows up more than rarely, element detection is broken and
real LD5s are at risk — recut the icons before running overnight.

**By name (OCR).** For a specific shortlist rather than any LD5. Tesseract
reads the monster's name and fuzzy-matches it against a wanted list — fuzzy
because stylised game fonts make Tesseract swap glyphs predictably (`B`→`8`,
`l`→`1`, `S`→`5`), which the matcher folds together before comparing.

```bash
swreroll run --want Ariel --want Beelzebub
```

**By image.** Drop a portrait crop into `templates/keepers/`. Useful for a
monster whose name OCRs badly.

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
swreroll connect mumu -n 4      # MuMu Player 12: ports 16384, +32 per instance
swreroll devices
```

```
127.0.0.1:16384    1280x720   MuMu
127.0.0.1:16416    1280x720   MuMu
```

Known port patterns, in case you need to connect by hand:

| Emulator | Base port | Stride |
|---|---|---|
| `mumu` — MuMu Player 12 | 16384 | +32 |
| `mumu6` — MuMu 6 / Nebula | 7555 | +1 |
| `ldplayer` | 5555 | +2 |
| `bluestacks` | 5555 | +10 |
| `nox` | 62001 | +24 |

If nothing connects: check the instances are running, that ADB is enabled in
the emulator's settings, and read the actual port off MuMu's **Multi-Instance
Manager** — it displays it per instance.

MuMu's adb binary lives at `MuMuPlayer-12.0/shell/adb.exe`; pass it with
`--adb` if platform-tools isn't on your PATH.

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

**5. Cut the grade templates.** These are the three that decide everything:

```bash
swreroll shot --crop 512,505,30,30 --out templates/ui/star.png
# The element icon sits in the same spot every time; cut one per element as
# you happen to summon them. All five, not just light and dark.
swreroll shot --crop 592,412,44,44 --out templates/ui/elem_light.png
swreroll shot --crop 592,412,44,44 --out templates/ui/elem_dark.png
swreroll shot --crop 592,412,44,44 --out templates/ui/elem_fire.png
swreroll shot --crop 592,412,44,44 --out templates/ui/elem_water.png
swreroll shot --crop 592,412,44,44 --out templates/ui/elem_wind.png
```

Then verify the count on a known result screen — five stars must read as
exactly five, never four or six:

```bash
swreroll phase summon_ld -v
```
```
INFO  grade: 5 stars, element=dark
```

If it miscounts, tighten `star_region` in the flow so it covers only the star
row, and recut `star.png` from a single clean star with no neighbours.

**6. Run one phase at a time.** No account is burned; nothing is wiped.

```bash
swreroll phase launch
swreroll phase summon_ld
```

## Run it

```bash
# Every connected instance, stop each at its first LD5
swreroll run

# Overnight, capped
swreroll run --max-accounts 500 --max-keeps 1

# A specific shortlist instead of any LD5 (switch the flow to evaluate_names)
swreroll run --want Ariel --want Beelzebub

# Rehearse without sending a single tap
swreroll run --dry-run -v
```

Four MuMu instances at ~14 accounts/hour each is ~56/hour, which puts a
70-100 account expectation at **roughly 1.5-2 hours** rather than a weekend.
Instance count is the only lever that really matters here.

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
| `evaluate_grade` | Keeper check by star count + element — the default |
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
worse than useless. A flow can list other phases under `skip_on_keep`; the
shipped one lists `summon_mystical`, since once you have the LD5 there is
nothing left for mystical scrolls to win.

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
  cli.py      connect / devices / shot / check / ocr / phase / run / stats
flows/        the reroll script (edit this)
templates/    your captured crops (not committed)
tests/        94 tests, no emulator required
```

```bash
python -m pytest tests/ -q
```

The whole test suite runs against a fake device and a stubbed Tesseract, so it
needs neither an emulator nor the game.
