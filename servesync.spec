# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller build recipe: turns ServeSync into a standalone app that runs
without Python installed (the FBLA "runs standalone" requirement).

    pyinstaller servesync.spec        (or double-click build_mac.command)

Produces a one-folder build in dist/ — on macOS, dist/ServeSync.app.
One-folder (not one-file) starts in about a second instead of unpacking
~150 MB to a temp folder on every launch, which matters in a 3-minute setup.
"""

import sys
from pathlib import Path

ROOT = Path(SPECPATH)  # noqa: F821 - provided by PyInstaller
sys.path.insert(0, str(ROOT))
from servesync import __version__  # noqa: E402
ICON = ROOT / "build" / "ServeSync.icns"

# Only the Qt parts ServeSync uses ship (smaller download, faster start).
EXCLUDES = [
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebChannel",
    "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.QtQml",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtMultimedia", "PySide6.QtBluetooth", "PySide6.QtPositioning", "PySide6.QtSensors",
    "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtDesigner",
    "tkinter", "pytest", "pytestqt", "mypy", "ruff", "PyInstaller",
]

a = Analysis(  # noqa: F821
    ["main.py"],
    pathex=[str(ROOT)],
    datas=[(str(ROOT / "servesync" / "ui" / "assets"), "servesync/ui/assets")],
    hiddenimports=["PySide6.QtSvg"],
    excludes=EXCLUDES,
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ServeSync",
    console=False,  # a windowed app: no terminal appears
    icon=str(ICON) if ICON.exists() else None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="ServeSync")  # noqa: F821

if sys.platform == "darwin":
    app = BUNDLE(  # noqa: F821
        coll,
        name="ServeSync.app",
        icon=str(ICON) if ICON.exists() else None,
        bundle_identifier="org.servesync.desktop",
        version=__version__,
        info_plist={
            "CFBundleDisplayName": "ServeSync",
            "CFBundleShortVersionString": __version__,
            "NSHighResolutionCapable": True,
            "NSRequiresAquaSystemAppearance": False,  # follow macOS Dark Mode ("Match my computer")
            "LSApplicationCategoryType": "public.app-category.productivity",
        },
    )
