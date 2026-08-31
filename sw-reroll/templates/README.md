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

## Names the shipped flow expects

- `ui/title` — the title / "Touch to Start" screen
- `ui/tutorial_start` — first real screen after the title
- `ui/home` — the town/home screen, i.e. "tutorial is over"
- `ui/summon_altar` — the summoning altar entrance
- `ui/summon_screen` — you are inside the altar
- `ui/scroll_ld` — the Light & Darkness scroll tab
- `ui/summon_result` — the panel showing what you pulled
- `ui/mailbox`, `ui/summoners_way` — reward sources
- `ui/battle_start` — used only to detect the scripted tutorial fight

Rename them freely; the flow file is the only thing that refers to them.
