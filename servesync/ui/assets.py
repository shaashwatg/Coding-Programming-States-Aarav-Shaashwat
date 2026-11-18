"""
Bundled design assets: fonts and icons.

Fonts (SIL Open Font License, bundled so every computer looks the same):
* **Figtree** — all interface text, in four weights (Regular, Medium,
  SemiBold, Bold). A clean, friendly sans with open shapes and even spacing,
  so it stays easy to read for hours; its tabular figures keep columns of
  hours and dates lined up.
* **Atkinson Hyperlegible** — the optional *Easy-read font* (Settings).
  Designed by the Braille Institute so similar letters (I/l/1, O/0, b/d) are
  easy to tell apart for readers with low vision.

Icons: the open-source **Lucide** set (ISC license). Each area of the app uses
one icon everywhere (people = "users", shifts = "calendar-days", ...), so
users learn the visual language once. Icons are recolored on the fly to
match the active theme, and drawn with a slightly finer line than Lucide's
default so they sit quietly beside text.
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
LEGIBLE_FAMILY = "Atkinson Hyperlegible"
#: Lucide draws 2 px lines on a 24 px grid; at interface sizes a finer line reads as calmer.
ICON_STROKE = "1.75"


def assets_dir() -> Path:
    root = resource_root()
    return root / "servesync" / "ui" / "assets" if is_frozen() else root / "ui" / "assets"


def load_fonts() -> tuple[str, str]:
    """
    Register the bundled fonts and return (interface family, easy-read family).
    Either is an empty string if its files are missing (the system font is used).
    """
    body, legible = "", ""
    for font_file in sorted((assets_dir() / "fonts").glob("*.ttf")):
        font_id = QFontDatabase.addApplicationFont(str(font_file))
        if font_id < 0:
            logger.warning("Could not load font %s", font_file.name)
            continue
        families = QFontDatabase.applicationFontFamilies(font_id)
        if BODY_FAMILY in families:
            body = BODY_FAMILY
        if LEGIBLE_FAMILY in families:
            legible = LEGIBLE_FAMILY
    return body, legible


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
    if name != "logo":
        text = text.replace('stroke-width="2"', f'stroke-width="{ICON_STROKE}"')
    return text.replace("currentColor", color).encode("utf-8")


_pixmaps: dict[tuple[str, str, int, float], QPixmap] = {}


def pixmap(name: str, color: str, size: int = 20, ratio: float = 2.0) -> QPixmap:
    """Render an icon at ``size`` logical pixels (sharp on Retina screens). Results are cached."""
    key = (name, color, size, ratio)
    cached = _pixmaps.get(key)
    if cached is not None:
        return cached
    image = _render(name, color, size, ratio)
    _pixmaps[key] = image
    return image


def _render(name: str, color: str, size: int, ratio: float) -> QPixmap:
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
