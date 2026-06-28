# Packaging & Deployment

This guide explains how to build the single-file Windows executable and deploy
it to QA workstations.

## Prerequisites

- **Windows 10/11** (build on the same OS family you target).
- **Python 3.13+** (the [python.org] installer; tick *Add python.exe to PATH*).
- The repository checked out locally.

## 1. Create an isolated environment

```bat
py -3.13 -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## 2. (Optional) run from source first

```bat
python run_eqms.py
```

Confirm the app launches, you can sign in, and the dashboard renders. This
catches environment issues before bundling.

## 3. Build the executable

The simplest path is the provided script:

```bat
scripts\build.bat
```

…which creates the venv, installs dependencies and runs PyInstaller. Or, inside
an already-activated environment:

```bat
python scripts\build.py --clean
```

Under the hood this runs:

```bat
pyinstaller eqms.spec --noconfirm
```

The output is:

```
dist\HP-Mainstream-EQMS.exe
```

A **single self-contained executable** — the target machine does **not** need
Python installed.

## What the spec bundles

`eqms.spec` takes care of the things PyInstaller cannot infer automatically:

- **CustomTkinter assets** (its JSON themes/colour files) via
  `collect_data_files("customtkinter")` — without these the UI won't start.
- **matplotlib `mpl-data`** for charting.
- **Hidden imports** for `office365.*`, `msal.*`, the Tk matplotlib backend and
  `PIL._tkinter_finder`.
- `console=False` for a windowed app (no console window).
- An optional icon at `src/eqms/resources/app.ico` (drop one in to brand the
  `.exe`).

## 4. First-run configuration on a workstation

On first launch the app creates its data directory:

```
%LOCALAPPDATA%\HP-Mainstream-EQMS\
├── config\local_config.json   # optional: client id / tenant / site url
├── auth\token_cache.bin        # encrypted MSAL token cache
├── cache\eqms_cache.sqlite     # offline/perf cache
├── logs\eqms.log               # rotating application logs
├── backups\                    # automatic backups, reports, outbox
└── local_store\                # offline Excel store (when SharePoint disabled)
```

To connect to SharePoint, the **administrator** signs in and, in
**Admin Center → SharePoint**, enables SharePoint storage and sets the site URL
and folder path. These are written to `Settings.xlsx`; they take effect on the
next sign-in. (Connection-only bootstrap values — client id, tenant — can also
be placed in `config\local_config.json` or the `EQMS_CLIENT_ID` /
`EQMS_TENANT` environment variables.)

## 5. Distribution

- Copy `dist\HP-Mainstream-EQMS.exe` to a shared location or push via your
  software-distribution tool (Intune/SCCM).
- No installer is strictly required; for a nicer experience wrap it with Inno
  Setup or WiX to create Start-menu shortcuts.
- Code-sign the executable with your organisation's certificate to avoid
  SmartScreen warnings (`signtool sign /fd SHA256 …`).

## Automatic updates

Set **Admin Center → Backups & Updates → Update manifest URL** to a JSON file:

```json
{ "version": "1.1.0", "url": "https://…/HP-Mainstream-EQMS-1.1.0.exe",
  "notes": "What changed", "mandatory": false }
```

The app checks it hourly and notifies users when a newer version is available.

## Troubleshooting builds

| Symptom | Fix |
|---------|-----|
| UI fails with a CustomTkinter theme error | Ensure the spec's `collect_data_files("customtkinter")` ran; rebuild with `--clean`. |
| `ModuleNotFoundError: office365…` at runtime | Add the missing submodule to `hiddenimports` in `eqms.spec`. |
| Antivirus/SmartScreen blocks the exe | Code-sign it; UPX compression can also trigger heuristics — set `upx=False` in the spec if needed. |
| Large exe / slow start | Expected for a bundled scientific stack; consider `--onedir` instead of one-file for faster start. |

[python.org]: https://www.python.org/downloads/
