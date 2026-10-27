"""
Render the ServeSync logo into the image sizes app icons need.

    python tools/make_icon.py build/ServeSync.iconset

macOS's ``iconutil -c icns build/ServeSync.iconset`` then packs them into
ServeSync.icns (build_mac.command does both steps).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from servesync.ui import assets

SIZES = (16, 32, 128, 256, 512)


def main() -> int:
    folder = Path(sys.argv[1] if len(sys.argv) > 1 else "build/ServeSync.iconset")
    folder.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    for size in SIZES:
        for scale, suffix in ((1, ""), (2, "@2x")):
            image = assets.pixmap("logo", "#FFFFFF", size, ratio=scale).toImage()
            image.save(str(folder / f"icon_{size}x{size}{suffix}.png"))
    print(f"Wrote {len(SIZES) * 2} icon images to {folder}")
    del app
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
