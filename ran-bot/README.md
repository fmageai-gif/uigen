# Ran Online Auto-Target Bot

Detects mob name tags (red text) on screen and auto-clicks them.

## Setup

### 1. Install Python 3.10+
Download from https://python.org

### 2. Install Python dependencies
```bash
cd ran-bot
pip install -r requirements.txt
```

### 3. Install Tesseract OCR (for name reading)
- **Windows:** Download from https://github.com/UB-Mannheim/tesseract/wiki  
  Install to `C:\Program Files\Tesseract-OCR\` (default)
- **Mac:** `brew install tesseract`
- **Linux:** `sudo apt install tesseract-ocr`

### 4. Run the bot
```bash
python main.py
```

## How to use

1. **Select monsters** — check the ones you want to farm (Slasher, Crook, Brawler, Prowler are pre-loaded)
2. **Set Region** (optional but recommended) — click "Set Region" then point to the top-left and bottom-right corners of your game window. This makes scanning faster and avoids false positives.
3. **Click START FARMING** — the bot will scan for red name tags, read their names, and click the ones you selected.
4. **Emergency stop** — move mouse to the top-left corner of your screen (PyAutoGUI failsafe).

## Adding new monsters

Click **+ Add Monster** and type the name exactly as it appears in-game.

## Settings

| Setting | Default | Description |
|---|---|---|
| Scan interval | 0.5s | How often to scan the screen |
| Click delay | 0.3s | Pause between clicks |
| Click Y offset | 30px | How far below the name tag to click (the mob body) |

## How detection works

1. Captures your screen (or the defined region)
2. Filters for **red pixels** in HSV color space — mob name tags in Ran Online are red
3. Groups red blobs into likely name tag regions
4. Runs OCR (Tesseract) on each region to read the mob name
5. Clicks mobs whose names match your selection

If Tesseract is not installed, the bot clicks **all red name tags** regardless of name.
