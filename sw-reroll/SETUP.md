# Setup — Windows + MuMu Player 12

From nothing to a calibrated bot. Budget about an hour; most of it is step 6.

Commands are for **PowerShell**. Open it with `Win+X` → "Terminal" or
"Windows PowerShell".

---

## 1. Install Python

Download from <https://www.python.org/downloads/> and run the installer.

> **Tick "Add python.exe to PATH" on the first screen.** Nothing below works
> without it, and it is off by default.

Check it took:

```powershell
python --version
```

If you get "not recognized", the PATH box wasn't ticked — re-run the
installer and choose Modify.

## 2. Get the code

```powershell
cd $HOME\Desktop
git clone https://github.com/fmageai-gif/uigen.git
cd uigen
git checkout claude/summoners-war-autoclicker-bh19yp
cd sw-reroll
```

No git? Download the ZIP instead: open the repo on GitHub, switch the branch
dropdown to `claude/summoners-war-autoclicker-bh19yp`, then **Code → Download
ZIP**, and extract it.

## 3. Install the dependencies

```powershell
pip install -e .
```

That gives you the `swreroll` command. If PowerShell can't find it afterwards,
use `python -m swreroll` in place of `swreroll` everywhere below — identical
behaviour.

## 4. Install Tesseract

Only needed for the text-tapping steps, but the tutorial skip uses them.

Download the installer from
<https://github.com/UB-Mannheim/tesseract/wiki> (take the 64-bit `.exe`),
run it, and **tick "Add to PATH"** if offered. Otherwise add
`C:\Program Files\Tesseract-OCR` to PATH yourself.

```powershell
tesseract --version
```

Not on PATH and you'd rather not fix that? Pass it explicitly:
`swreroll --tesseract "C:\Program Files\Tesseract-OCR\tesseract.exe" ...`

## 5. Connect MuMu

**5a. Turn ADB on inside MuMu.** Open **Device Settings** (the ☰ / gear icon
in MuMu's toolbar) → **Developer options** in the left sidebar → set
**ADB debug** to **"Enable local connection"**.

"Local connection" is the one you want — it listens on 127.0.0.1, which is
what `connect mumu` dials. `Enable root` is unrelated and can be left alone.

If you had to change the setting, restart the instance. If it was already set,
carry straight on.

**5b. Find MuMu's adb.exe.** It ships one, so you don't need Android
platform-tools:

```powershell
Get-ChildItem "C:\Program Files\Netease" -Recurse -Filter adb.exe -ErrorAction SilentlyContinue | Select-Object -First 3 FullName
```

Usually `C:\Program Files\Netease\MuMuPlayer-12.0\shell\adb.exe`. Save it to a
variable so the rest of this page is copy-pasteable:

```powershell
$ADB = "C:\Program Files\Netease\MuMuPlayer-12.0\shell\adb.exe"
```

**5c. Connect.**

```powershell
swreroll --adb $ADB connect mumu
swreroll --adb $ADB devices
```

Expected:

```
127.0.0.1:16384    1280x720    240 dpi   MuMu
```

**Nothing found?** In order:

- Is the instance actually running, with Android booted?
- Try the older port: `swreroll --adb $ADB connect mumu6`
- Read the real port off MuMu's **Multi-Instance Manager** — it shows one per
  instance — then connect by hand:
  `& $ADB connect 127.0.0.1:<port>`
- Re-check ADB debug is on "Enable local connection" (5a), and restart the
  instance if you just changed it.

**5d. More instances.** `-n 4` connects instances 0–3. This is the only real
throughput lever: 4 instances turns a ~2-day expectation into ~2 hours.

```powershell
swreroll --adb $ADB connect mumu -n 4
```

## 6. Capture the templates

Launch Summoners War in MuMu and leave it running.

**6a. Get the package id.** Note `findstr`, not `grep` — this is Windows:

```powershell
& $ADB shell pm list packages | findstr smon
```

Copy what it prints (after `package:`) into `flows/summoners_war.yaml` on the
`package:` line, if it differs from what's already there.

**6b. Take a gridded screenshot of whatever is on screen.**

```powershell
swreroll --adb $ADB shot --grid --out shots\result.png
```

Open `shots\result.png`. It has a labelled 100px grid over it — those numbers
are the coordinates you feed to `--crop`.

**6c. Read off `x,y,w,h` and cut the crop.** `x,y` is the top-left corner,
`w,h` the size. For example, if a star sits between gridlines 900 and 930
across and 300 to 330 down:

```powershell
swreroll --adb $ADB shot --crop 900,300,30,30 --out templates\ui\star.png
```

The crop is taken from a **fresh** capture, so the same screen must still be
on display. Take the grid shot and the crops back to back.

**6d. Work through the list.** Get to each screen, grid-shot it, cut what it
gives you. In rough priority order:

| Screen to be on | Cut |
|---|---|
| **Summon result panel** | `ui/star`, `ui/elem_light`, `ui/elem_dark`, `ui/elem_fire`, `ui/elem_water`, `ui/elem_wind`, `ui/summon_result` |
| Summon altar, scroll tabs visible | `ui/summon_screen`, `ui/scroll_ld`, `ui/scroll_mystical` |
| Home / town | `ui/home`, `ui/summon_altar`, `ui/mailbox`, `ui/summoners_way` |
| Tutorial battle | `ui/arrow_green`, `ui/arrow_yellow` |
| Title screen | `ui/title` |
| Any event popup | `close/<anything>` — its X or Close button |

You will not have every element icon at once; cut each as you happen to summon
one. The bot runs fine with some missing — it just falls back to the
"bank it, unverified" path more often.

**Cut tight.** Two crops decide everything:

- `ui/star` — **one** star, no part of its neighbour in frame. `find_all`
  counts occurrences, so a loose crop miscounts, and a 4-vs-5 miscount is
  what throws away your LD5.
- `ui/arrow_green` / `ui/arrow_yellow` — the arrow head only, no sky or
  terrain behind it. Include background and the crop becomes scene-specific
  and stops matching on the next tutorial stage.

**6e. Check every crop scores well** before trusting any of it:

```powershell
swreroll --adb $ADB check --image shots\result.png
```

```
HIT  0.981  ui/star           @ (912, 315)
miss 0.612  ui/elem_dark      @ (880, 268)
```

Anything below ~0.9 on a screen where it *should* match will fail at 3am too.
Recut it.

**6f. Tune the two regions.** `swreroll ocr --words` prints every word it can
read with its box, which is the quickest way to locate the panel:

```powershell
swreroll --adb $ADB ocr --words
```

Then narrow `star_region` and `element_region` in
`flows/summoners_war.yaml` — both are `[x, y, w, h]` as **0–1 fractions** of
the screen, not pixels — until they cover only the star row and only the
element icon.

## 7. Rehearse before running

One phase at a time. No account is burned and nothing is wiped:

```powershell
swreroll --adb $ADB phase launch -v
swreroll --adb $ADB phase summon_ld -v
```

`-v` shows every step. On the grade check you want to see:

```
INFO  grade: 5 stars, element=dark
```

If the star count is wrong, fix that before anything else.

## 8. Run it

```powershell
swreroll --adb $ADB run --max-accounts 20 -v
```

Start with a small cap and read `swreroll stats` before committing to an
overnight session. Once it looks right:

```powershell
swreroll --adb $ADB run --max-accounts 500 --max-keeps 1
```

Stopping: `Ctrl-C` finishes the current account and exits. Unattended, create
a file named `STOP` in the run directory and workers wind down at the next
account boundary.

**On a hit** the account is left intact and that device stops. Go bind it to a
Hive account immediately — the next `pm clear` on that instance destroys it.

---

## The shortcut, if the setup is a hassle

You don't need any of the above just to unblock the calibration. Use **MuMu's
own screenshot button** (the camera icon in its toolbar) — it captures the
Android screen without the window chrome, which is what matters.

Grab the **summon result panel** at minimum, plus the tutorial battle if you
can, and send the PNGs. Coordinates can be worked out from those and handed
back to you as ready-to-paste `--crop` commands.

What does *not* work: screenshotting the MuMu window with `Win+Shift+S` or
Print Screen. That includes the tab bar and window border, which shifts every
coordinate down by ~44px and adds a ~1% scale error.
