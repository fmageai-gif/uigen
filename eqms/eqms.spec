# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for HP Mainstream EQMS.

Builds a single self-contained Windows executable that does not require Python
to be installed on the target machine.

    pyinstaller eqms.spec --noconfirm

Notes
-----
* CustomTkinter ships JSON themes and assets as *data files*; they must be
  collected explicitly or the UI fails to start. ``collect_data_files`` handles
  this for customtkinter (and we include matplotlib data too).
* Hidden imports cover packages PyInstaller's static analysis misses
  (office365 sub-packages, msal extensions, PIL plugins).
* ``console=False`` produces a windowed app (no terminal window).
"""

import os
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# Use a branded icon only if one is present (and only on Windows).
_icon_path = os.path.join("src", "eqms", "resources", "app.ico")
_icon = _icon_path if (sys.platform.startswith("win") and os.path.exists(_icon_path)) else None

datas = []
datas += collect_data_files("customtkinter")
datas += collect_data_files("matplotlib", includes=["mpl-data/**"])

hiddenimports = []
hiddenimports += collect_submodules("office365")
hiddenimports += collect_submodules("msal")
hiddenimports += [
    "PIL._tkinter_finder",
    "matplotlib.backends.backend_tkagg",
    "darkdetect",
    "openpyxl",
    "pandas",
]

a = Analysis(
    ["run_eqms.py"],
    pathex=["src"],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter.test", "test", "pytest"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="HP-Mainstream-EQMS",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_icon,
)
