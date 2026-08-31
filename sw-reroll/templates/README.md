# Templates

Reference crops the bot matches against. Everything here is **specific to your
emulator**, so nothing is committed — capture your own with `swreroll shot`.

Crops are matched against a screen normalised to 1280px wide, and searched at
several scales, so a crop taken at 1600x900 still works at 1280x720.

## Layout

| Folder | Purpose |
|---|---|
| `ui/` | Screens and buttons the flow waits for or taps |
| `close/` | Every popup close button. `dismiss` taps anything it finds here |
| `keepers/` | Image-based keeper conditions — a match banks the account |

`keepers/` is optional. The OCR route (`--want Ariel`) is easier to maintain:
adding a target is one line of YAML instead of a new screenshot.

## The three that matter most

Grade detection needs only these, and they decide every keep:

- `ui/star` — **one** star glyph, cut tight, with no neighbouring star in the
  crop. `find_all` counts occurrences, so a loose crop that swallows part of
  the next star will miscount.
- `ui/elem_light`, `ui/elem_dark`, `ui/elem_fire`, `ui/elem_water`,
  `ui/elem_wind` — the element icons. Cut all five from the same spot on the
  result panel so they are directly comparable.

  Capturing fire/water/wind is not optional busywork: identifying them
  positively is what lets the bot discard a non-LD nat 5 with confidence.
  With only light and dark, "this is a fire monster" and "my crop is broken"
  produce the same result, and the fail-safe then banks every nat 5.

  If two element icons score similarly on the same screen, tighten both crops
  until they don't.

## The tutorial guide arrows

The game tells you what to tap: a **green arrow** floats over the thing to tap
now, a **yellow arrow** over what comes next. The flow follows them, which is
far more robust than guessing battle coordinates.

- `ui/arrow_green` — cut the arrow head only, no background, no monster
- `ui/arrow_yellow` — same

Both are solid flat colours with a distinct silhouette, so they match reliably.
Cut them tight: including sky or terrain behind the arrow makes the crop
scene-specific and it will stop matching on the next tutorial stage.

If you skip these, the flow falls back to sweeping fixed points and will very
likely stall on the scripted battle turns.

## Names the shipped flow expects

- `ui/title` — the title / "Touch to Start" screen
- `ui/tutorial_start` — first real screen after the title
- `ui/home` — the town/home screen, i.e. "tutorial is over"
- `ui/summon_altar` — the summoning altar entrance
- `ui/summon_screen` — you are inside the altar
- `ui/scroll_ld` — the Light & Darkness scroll tab
- `ui/scroll_mystical` — the Mystical scroll tab
- `ui/summon_result` — the panel showing what you pulled
- `ui/mailbox`, `ui/summoners_way` — reward sources
- `ui/battle_start` — used only to detect the scripted tutorial fight

Rename them freely; the flow file is the only thing that refers to them.
