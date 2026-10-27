"""
Bundled design assets: fonts and icons.

Fonts (SIL Open Font License, bundled so every computer looks the same):
* **Atkinson Hyperlegible** — body and interface text. Designed by the Braille
  Institute so similar letters (I/l/1, O/0, b/d) are easy to tell apart for
  readers with low vision.
* **Source Serif 4** — page titles and key figures; a warm, editorial serif
  that gives the organization a trustworthy, annual-report voice.

Icons: the open-source **Lucide** set (ISC license). Each area of the app uses
one icon everywhere (people = "users", shifts = "calendar-days", ...), so
users learn the visual language once. Icons are recolored on the fly to
match the active theme.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QFontDatabase, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from servesync.config import is_frozen, resource_root
from servesync.models import OpportunityCategory

logger = logging.getLogger(__name__)

BODY_FAMILY = "Atkinson Hyperlegible"
HEADING_FAMILY = "Source Serif 4"


def assets_dir() -> Path:
    root = resource_root()
    return root / "servesync" / "ui" / "assets" if is_frozen() else root / "ui" / "assets"


def load_fonts() -> tuple[str, str]:
    """Register the bundled fonts. Falls back to the system font if a file is missing."""
    body, heading = "", ""
    for font_file in sorted((assets_dir() / "fonts").glob("*.ttf")):
        font_id = QFontDatabase.addApplicationFont(str(font_file))
        if font_id < 0:
            logger.warning("Could not load font %s", font_file.name)
            continue
        families = QFontDatabase.applicationFontFamilies(font_id)
        if BODY_FAMILY in families:
            body = BODY_FAMILY
        if HEADING_FAMILY in families:
            heading = HEADING_FAMILY
    return body, heading


# ------------------------------------------------------------------- icons

#: One icon per idea, used consistently everywhere (Gestalt "similarity").
NAV_ICONS = {
    "dashboard": "layout-dashboard",
    "volunteers": "users",
    "programs": "clipboard-list",
    "calendar": "calendar-days",
    "settings": "settings",
    "home": "house",
    "find": "search",
    "profile": "user-round",
}

CATEGORY_ICONS: dict[OpportunityCategory, str] = {
    OpportunityCategory.FOOD_SECURITY: "shopping-basket",
    OpportunityCategory.EDUCATION: "book-open",
    OpportunityCategory.ENVIRONMENT: "trees",
    OpportunityCategory.HEALTH: "heart-pulse",
    OpportunityCategory.ANIMAL_WELFARE: "paw-print",
    OpportunityCategory.HOUSING: "house",
    OpportunityCategory.COMMUNITY_EVENTS: "flag",
    OpportunityCategory.ADMINISTRATIVE: "clipboard-list",
}


@lru_cache(maxsize=512)
def _svg_bytes(name: str, color: str) -> bytes:
    path = assets_dir() / "icons" / f"{name}.svg"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        logger.warning("Missing icon %s", name)
        return b""
    return text.replace("currentColor", color).encode("utf-8")


def pixmap(name: str, color: str, size: int = 20, ratio: float = 2.0) -> QPixmap:
    """Render an icon at ``size`` logical pixels (sharp on Retina screens)."""
    image = QPixmap(int(size * ratio), int(size * ratio))
    image.fill(Qt.GlobalColor.transparent)
    data = _svg_bytes(name, color)
    if data:
        renderer = QSvgRenderer(QByteArray(data))
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(painter, QRectF(0, 0, size * ratio, size * ratio))
        painter.end()
    image.setDevicePixelRatio(ratio)
    return image


def icon(name: str, color: str, size: int = 20) -> QIcon:
    return QIcon(pixmap(name, color, size))


def logo_pixmap(size: int = 36) -> QPixmap:
    return pixmap("logo", "#FFFFFF", size)
