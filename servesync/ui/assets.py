"""
Bundled design assets: fonts and icons.

Fonts (SIL Open Font License, bundled so every computer looks the same):
* **Geist** (Light and Regular): page titles and big figures, set large and light.
* **Figtree**: interface and body text; a clean geometric sans that stays
  readable at small sizes (Regular, Medium and SemiBold).
* **IBM Plex Mono**: step counters and small labels such as "01 / 02".
* **Atkinson Hyperlegible** (Braille Institute): the "Easier-to-read letters"
  comfort setting. Similar letters (I/l/1, O/0, b/d) are drawn to differ, for
  readers with low vision.

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

BODY_FAMILY = "Figtree"
HEADING_FAMILY = "Geist"
MONO_FAMILY = "IBM Plex Mono"  # step counters and small labels
LEGIBLE_FAMILY = "Atkinson Hyperlegible"  # the "Easier-to-read letters" comfort setting


def assets_dir() -> Path:
    root = resource_root()
    return root / "servesync" / "ui" / "assets" if is_frozen() else root / "ui" / "assets"


def load_fonts() -> tuple[str, str, str, str]:
    """Register the bundled fonts: (body, heading, legible, mono). An empty name means use the system font."""
    body, heading, legible, mono = "", "", "", ""
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
        if LEGIBLE_FAMILY in families:
            legible = LEGIBLE_FAMILY
        if MONO_FAMILY in families:
            mono = MONO_FAMILY
    return body, heading, legible, mono


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


def two_state_icon(name: str, color: str, checked_color: str, size: int = 20) -> QIcon:
    """An icon drawn in ``color``, and in ``checked_color`` while its button is checked."""
    result = QIcon(pixmap(name, color, size))
    result.addPixmap(pixmap(name, checked_color, size), QIcon.Mode.Normal, QIcon.State.On)
    return result


def logo_pixmap(color: str, size: int = 36) -> QPixmap:
    """The logo mark drawn in ``color`` (the theme's primary), so it matches every theme."""
    return pixmap("logo", color, size)
