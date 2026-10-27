"""
Visual design system: tokens, four themes, text scaling, and comfort settings.

Design rationale (for the UX portion of the presentation)
---------------------------------------------------------
* **Tokens, not one-off colors.** Every color, space, radius and duration in
  the app comes from this file. Screens ask for *meaning* ("primary",
  "text_muted", "attention"), so a theme is just a different set of values.
* **WCAG 2.2 AAA contrast, verified by tests.** Every text color is at least
  7:1 against every background it can sit on (1.4.6 Contrast Enhanced); input
  borders and focus rings are at least 3:1 (1.4.11, 2.4.13). See
  ``tests/test_theme.py``, which computes the ratios for all four themes.
* **Calm, content-first chrome.** A light top bar with one hairline, generous
  4-point spacing, and a single accent per purpose: evergreen for actions,
  harbor blue for information, marigold for the one call to action.
* **Two complementary fonts.** Atkinson Hyperlegible (Braille Institute) for
  interface text; Source Serif 4 for titles and key figures.
* **Big targets.** Every button, field and tab is at least 44 px tall
  (2.5.5 Target Size, AAA), and grows with the text size.
* **Four themes.** Match my computer (follows macOS/Windows light or dark,
  live), Light, Dark (low glare), High contrast (black/white/yellow, 3 px focus).
* **Text 85%-200%, plus optional extra letter and word spacing** (1.4.4,
  1.4.12) — the whole interface scales from one base size, so nothing clips.
* **Never color alone.** Every status also has words or a shape.
"""

from __future__ import annotations

import dataclasses
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPalette, QTransform
from PySide6.QtWidgets import QApplication

from servesync.models import Appearance, Theme

# ------------------------------------------------------------ scale tokens

#: 4-point spacing scale (px). Layouts use these, never arbitrary numbers.
SPACE_1, SPACE_2, SPACE_3, SPACE_4, SPACE_5, SPACE_6, SPACE_7 = 4, 8, 12, 16, 24, 32, 48
#: Corner radii: controls, cards, and large surfaces (dialogs, banners).
RADIUS_SM, RADIUS_MD, RADIUS_LG = 8, 12, 16
#: Type scale (multiples of the body size; a 1.2 "minor third" progression).
TYPE_CAPTION, TYPE_BODY, TYPE_LEAD, TYPE_H3, TYPE_H2, TYPE_H1, TYPE_DISPLAY = 0.88, 1.0, 1.12, 1.25, 1.5, 1.85, 2.3
#: Minimum interactive height at 100% text (WCAG 2.5.5 AAA: 44 x 44 px).
MIN_TARGET = 44


@dataclass(frozen=True, slots=True)
class Palette:
    name: str
    window: str  # page background ("canvas")
    surface: str  # panels, tables, inputs
    surface_alt: str  # alternate rows, sunken fills, hover
    text: str
    text_muted: str  # secondary text — still >= 7:1
    line: str  # decorative hairlines (cards, dividers)
    line_strong: str  # boundaries people must see: input borders (>= 3:1)
    primary: str  # actions; also usable as text (>= 7:1)
    primary_hover: str
    on_primary: str
    primary_soft: str  # tinted background for selected/active states
    topbar: str
    topbar_text: str
    topbar_muted: str
    topbar_active: str
    attention: str  # attention as *text* (>= 7:1)
    attention_fill: str  # attention as a *shape* (dots, bars) — never carries text
    danger: str
    success: str
    focus: str  # keyboard focus ring (>= 3:1 against surfaces)
    selection: str
    on_selection: str
    info: str
    cta: str
    on_cta: str
    cta_hover: str
    banner: str
    banner_line: str
    callout: str
    glow: str  # soft halo around the focused featured surface
    is_dark: bool = False
    focus_width: int = 2
    #: Smart Match factors (availability, skills, reliability, experience, fair share)
    #: — distinguishable with color-vision differences, and always labeled.
    factors: tuple[str, str, str, str, str] = ("#175B45", "#24547B", "#6B3F92", "#8A5A00", "#2F6A66")
    #: Chart series colors; charts also print values on every bar.
    chart: tuple[str, str, str] = ("#175B45", "#24547B", "#8A5A00")


LIGHT = Palette(
    name="Light",
    window="#F6F8F7",
    surface="#FFFFFF",
    surface_alt="#EEF2F0",
    text="#14212B",
    text_muted="#465359",
    line="#DCE3E0",
    line_strong="#7D8F89",
    primary="#175B45",
    primary_hover="#124A38",
    on_primary="#FFFFFF",
    primary_soft="#E3EFE9",
    topbar="#FFFFFF",
    topbar_text="#14212B",
    topbar_muted="#465359",
    topbar_active="#E3EFE9",
    attention="#6C4A00",
    attention_fill="#E0A526",
    danger="#8C3324",
    success="#175B45",
    focus="#2F6FA3",
    selection="#D4E8DE",
    on_selection="#14212B",
    info="#24547B",
    cta="#F2C14E",
    on_cta="#14212B",
    cta_hover="#F6D27A",
    banner="#EAF3EE",
    banner_line="#C6DDD1",
    callout="#EDF3F9",
    glow="#A9CCBC",
)

DARK = Palette(
    name="Dark",
    window="#0F1416",
    surface="#161D20",
    surface_alt="#1D2629",
    text="#E4EBE8",
    text_muted="#A3B1B8",
    line="#26333A",
    line_strong="#5F7178",
    primary="#56C29A",
    primary_hover="#72D0AC",
    on_primary="#0B1A14",
    primary_soft="#173229",
    topbar="#0B1012",
    topbar_text="#E4EBE8",
    topbar_muted="#A3B1B8",
    topbar_active="#173229",
    attention="#E8B23A",
    attention_fill="#E8B23A",
    danger="#F29786",
    success="#56C29A",
    focus="#7FB6E6",
    selection="#1F4236",
    on_selection="#F2F7F5",
    info="#7FB6E6",
    cta="#F2C14E",
    on_cta="#14212B",
    cta_hover="#F6D27A",
    banner="#132722",
    banner_line="#244238",
    callout="#14212B",
    glow="#2C5A4A",
    is_dark=True,
    factors=("#56C29A", "#7FB6E6", "#C3A1E6", "#E8B23A", "#7FCFC8"),
    chart=("#56C29A", "#7FB6E6", "#E8B23A"),
)

HIGH_CONTRAST = Palette(
    name="High contrast",
    window="#000000",
    surface="#000000",
    surface_alt="#1A1A1A",
    text="#FFFFFF",
    text_muted="#FFFFFF",
    line="#FFFFFF",
    line_strong="#FFFFFF",
    primary="#FFD400",
    primary_hover="#FFE566",
    on_primary="#000000",
    primary_soft="#333300",
    topbar="#000000",
    topbar_text="#FFFFFF",
    topbar_muted="#FFFFFF",
    topbar_active="#333333",
    attention="#FFD400",
    attention_fill="#FFD400",
    danger="#FF9E94",
    success="#7CFF9E",
    focus="#00E5FF",
    selection="#FFD400",
    on_selection="#000000",
    info="#80D8FF",
    cta="#FFD400",
    on_cta="#000000",
    cta_hover="#FFE566",
    banner="#000000",
    banner_line="#FFFFFF",
    callout="#000000",
    glow="#00E5FF",
    is_dark=True,
    focus_width=3,
    factors=("#7CFF9E", "#80D8FF", "#EA80FC", "#FFD400", "#FFFFFF"),
    chart=("#FFD400", "#80D8FF", "#7CFF9E"),
)

PALETTES: dict[Theme, Palette] = {Theme.LIGHT: LIGHT, Theme.DARK: DARK, Theme.HIGH_CONTRAST: HIGH_CONTRAST}

_state: dict[str, object] = {"palette": LIGHT, "scale": 1.0, "appearance": Appearance(theme=Theme.LIGHT)}


def current_palette() -> Palette:
    """The palette in use (custom-painted widgets read their colors from here)."""
    palette = _state["palette"]
    assert isinstance(palette, Palette)
    return palette


def current_scale() -> float:
    scale = _state["scale"]
    assert isinstance(scale, float)
    return scale


def current_appearance() -> Appearance:
    """The comfort settings in effect (motion, spacing, simplified layout, message timing)."""
    appearance = _state["appearance"]
    assert isinstance(appearance, Appearance)
    return appearance


def motion_allowed() -> bool:
    """False when the person asked for reduced motion (WCAG 2.3.3)."""
    return not current_appearance().reduce_motion


def resolve_theme(theme: Theme, app: QGuiApplication | None = None) -> Theme:
    """'Match my computer' becomes Light or Dark from the operating system's setting."""
    if theme is not Theme.SYSTEM:
        return theme
    app = app or QGuiApplication.instance()  # type: ignore[assignment]
    if isinstance(app, QGuiApplication) and app.styleHints().colorScheme() == Qt.ColorScheme.Dark:
        return Theme.DARK
    return Theme.LIGHT


def apply_appearance(app: QApplication, appearance: Appearance) -> Palette:
    """Apply colors, fonts, spacing, and the stylesheet to the whole application."""
    palette = PALETTES[resolve_theme(appearance.theme, app)]
    _state["palette"] = palette
    _state["scale"] = float(appearance.font_scale)
    _state["appearance"] = appearance

    app.setStyle("Fusion")  # identical look on macOS and Windows, fully themeable

    base_size = app.property("baseFontPointSize")
    if not isinstance(base_size, float):
        base_size = float(max(app.font().pointSizeF(), 11.0))
        app.setProperty("baseFontPointSize", base_size)
    size = round(base_size * appearance.font_scale, 1)
    font = QFont(app.font())
    if _fonts["body"]:
        font.setFamily(_fonts["body"])
    font.setPointSizeF(size)
    # WCAG 1.4.12 Text Spacing: wider letters and words help many dyslexic readers.
    font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 108 if appearance.text_spacing else 100)
    font.setWordSpacing(size * 0.45 if appearance.text_spacing else 0.0)
    app.setFont(font)

    app.setPalette(_qt_palette(palette))
    app.setStyleSheet(
        build_stylesheet(palette, size, _arrow_images(palette.text_muted), _check_image(palette.on_primary))
    )
    return palette


def apply_theme(app: QApplication, theme: Theme, font_scale: float) -> Palette:
    """Change only theme and size, keeping the other comfort settings."""
    return apply_appearance(app, dataclasses.replace(current_appearance(), theme=theme, font_scale=font_scale))


_arrow_dir: dict[str, Path] = {}


def _arrow_images(color: str) -> tuple[str, str]:
    """Render themed up/down chevrons to PNG files the stylesheet can reference."""
    from servesync.ui import assets  # local import: assets has no dependency on this module

    folder = _arrow_dir.get("path")
    if folder is None:
        folder = Path(tempfile.mkdtemp(prefix="servesync-ui-"))
        _arrow_dir["path"] = folder
    down_path = folder / f"down-{color.lstrip('#')}.png"
    up_path = folder / f"up-{color.lstrip('#')}.png"
    if not down_path.exists():
        down = assets.pixmap("chevron-down", color, 14)
        down.save(str(down_path))
        down.transformed(QTransform().rotate(180)).save(str(up_path))
    return up_path.as_posix(), down_path.as_posix()


def _check_image(color: str) -> str:
    """A themed check mark for check boxes (drawn by us so it is visible in every theme)."""
    from servesync.ui import assets

    _arrow_images(color)  # makes sure the temp folder exists
    path = _arrow_dir["path"] / f"check-{color.lstrip('#')}.png"
    if not path.exists():
        assets.pixmap("check", color, 16).save(str(path))
    return path.as_posix()


def _qt_palette(p: Palette) -> QPalette:
    qp = QPalette()
    roles = {
        QPalette.ColorRole.Window: p.window,
        QPalette.ColorRole.WindowText: p.text,
        QPalette.ColorRole.Base: p.surface,
        QPalette.ColorRole.AlternateBase: p.surface_alt,
        QPalette.ColorRole.Text: p.text,
        QPalette.ColorRole.Button: p.surface,
        QPalette.ColorRole.ButtonText: p.text,
        QPalette.ColorRole.Highlight: p.selection,
        QPalette.ColorRole.HighlightedText: p.on_selection,
        QPalette.ColorRole.ToolTipBase: p.surface,
        QPalette.ColorRole.ToolTipText: p.text,
        QPalette.ColorRole.PlaceholderText: p.text_muted,
        QPalette.ColorRole.Link: p.info,
    }
    for role, color in roles.items():
        qp.setColor(role, QColor(color))
    qp.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(p.text_muted))
    qp.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(p.text_muted))
    qp.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor(p.text_muted))
    return qp


_fonts: dict[str, str] = {"body": "", "heading": ""}


def set_font_families(body: str, heading: str) -> None:
    """Record the bundled font families (empty string = use the system font)."""
    _fonts["body"], _fonts["heading"] = body, heading


def heading_family() -> str:
    return _fonts["heading"]


def build_stylesheet(p: Palette, size: float, arrows: tuple[str, str] = ("", ""), check: str = "") -> str:
    """Qt stylesheet built from tokens; every font size derives from ``size``."""
    up_arrow, down_arrow = arrows
    box = round(18 * max(1.0, size / 13))

    def pt(factor: float) -> str:
        return f"{round(size * factor, 1)}pt"

    fw = p.focus_width
    body = f'font-family: "{_fonts["body"]}";' if _fonts["body"] else ""
    serif = f'font-family: "{_fonts["heading"]}";' if _fonts["heading"] else ""
    target = round(MIN_TARGET * max(1.0, size / 13))  # minimum interactive height in pixels
    sm, md, lg = RADIUS_SM, RADIUS_MD, RADIUS_LG
    return f"""
    QWidget {{ color: {p.text}; {body} }}
    QMainWindow, QDialog {{ background: {p.window}; }}
    QToolTip {{ background: {p.surface}; color: {p.text}; border: 1px solid {p.line_strong}; padding: 6px 8px;
        border-radius: {sm}px; }}

    /* ---------- text roles (type scale) ---------- */
    QLabel[role="title"] {{ {serif} font-size: {pt(TYPE_H1)}; font-weight: 600; }}
    QLabel[role="display"] {{ {serif} font-size: {pt(TYPE_DISPLAY)}; font-weight: 600; }}
    QLabel[role="mission"] {{ {serif} font-size: {pt(TYPE_LEAD)}; font-style: italic; color: {p.text}; }}
    QLabel[role="subtitle"] {{ font-size: {pt(TYPE_BODY)}; color: {p.text_muted}; }}
    QLabel[role="section"] {{ {serif} font-size: {pt(TYPE_H3)}; font-weight: 600; padding-top: 2px; }}
    QLabel[role="muted"] {{ color: {p.text_muted}; }}
    QLabel[role="error"] {{ color: {p.danger}; font-size: {pt(TYPE_CAPTION)}; }}
    QLabel[role="banner-error"] {{ color: {p.danger}; background: {p.surface};
        border: 1px solid {p.danger}; border-radius: {sm}px; padding: 8px 10px; }}
    QLabel[role="hint"] {{ color: {p.text_muted}; font-size: {pt(TYPE_CAPTION)}; }}
    QLabel[role="figure"] {{ {serif} font-size: {pt(2.1)}; font-weight: 600; }}
    QLabel[role="figure-attention"] {{ {serif} font-size: {pt(2.1)}; font-weight: 600; color: {p.attention}; }}
    QLabel[role="figure-label"] {{ color: {p.text_muted}; font-size: {pt(0.95)}; }}
    QLabel[role="name"] {{ {serif} font-size: {pt(1.35)}; font-weight: 600; }}
    QLabel[role="link"] {{ color: {p.info}; }}
    QLabel[role="eyebrow"] {{ color: {p.info}; font-weight: 700; }}
    QLabel[role="strength"] {{ color: {p.text}; }}
    QLabel[role="concern"] {{ color: {p.danger}; }}
    QLabel[role="ok"] {{ color: {p.success}; font-weight: 600; }}
    QLabel[role="score"] {{ {serif} font-size: {pt(1.6)}; font-weight: 600; color: {p.primary}; }}
    QLabel[role="kbd"] {{ color: {p.text_muted}; border: 1px solid {p.line_strong}; border-radius: 5px;
        padding: 1px 6px; font-size: {pt(TYPE_CAPTION)}; }}
    QLabel[role="insight"] {{ color: {p.text}; padding: 2px 0; }}
    QLabel[role="pill"] {{ color: {p.primary}; background: {p.primary_soft}; border-radius: 10px;
        padding: 2px 10px; font-size: {pt(TYPE_CAPTION)}; font-weight: 600; }}

    /* ---------- containers ---------- */
    QFrame[panel="true"] {{ background: {p.surface}; border: 1px solid {p.line}; border-radius: {md}px; }}
    QFrame[strip="true"] {{ background: {p.surface}; border: 1px solid {p.line}; border-radius: {md}px; }}
    QFrame[rule="true"] {{ background: {p.line}; max-width: 1px; min-width: 1px; border: none; }}
    QFrame[card="true"] {{ background: {p.surface}; border: 1px solid {p.line}; border-radius: {md}px; }}
    QFrame[tile="true"] {{ background: {p.surface}; border: 1px solid {p.line}; border-radius: {md}px; }}
    QFrame[bubble="assistant"] {{ background: {p.surface}; border: 1px solid {p.line}; border-radius: {md}px; }}
    QFrame[bubble="user"] {{ background: {p.primary_soft}; border: none; border-radius: {md}px; }}
    QScrollArea {{ background: transparent; border: none; }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}
    QGroupBox {{ background: {p.surface}; border: 1px solid {p.line}; border-radius: {md}px;
        margin-top: 18px; padding: 14px 12px 12px 12px; font-weight: 600; }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 4px; }}

    /* ---------- top bar (logo top-left, navigation top-right) ---------- */
    QWidget#TopBar {{ background: {p.topbar}; border-bottom: 1px solid {p.line}; }}
    QWidget#TopBar QLabel {{ color: {p.topbar_text}; }}
    QLabel#Brand {{ {serif} font-size: {pt(1.45)}; font-weight: 600; color: {p.topbar_text}; }}
    QLabel#OrgName {{ color: {p.topbar_muted}; font-size: {pt(TYPE_CAPTION)}; }}
    QWidget#NavIndicator {{ background: {p.primary}; border-radius: 2px; }}
    QPushButton[nav="true"] {{ background: transparent; color: {p.topbar_text}; border: none;
        border-radius: {sm}px; padding: 8px 12px; min-height: {target - 8}px; font-size: {pt(TYPE_BODY)}; }}
    QPushButton[nav="true"]:hover {{ background: {p.surface_alt}; }}
    QPushButton[nav="true"]:checked {{ background: {p.topbar_active}; color: {p.topbar_text}; }}
    QPushButton[nav="true"]:focus {{ border: {fw}px solid {p.focus}; }}
    QPushButton#CallToAction {{ background: {p.cta}; color: {p.on_cta}; border: none; border-radius: {target // 2}px;
        padding: 8px 18px; min-height: {target - 8}px; font-weight: 700; }}
    QPushButton#CallToAction:hover {{ background: {p.cta_hover}; }}
    QPushButton#CallToAction:focus {{ border: {fw}px solid {p.focus}; }}
    QPushButton#AskButton {{ background: {p.surface}; color: {p.topbar_text}; border: 1px solid {p.line_strong};
        border-radius: {target // 2}px; padding: 6px 14px; min-height: {target - 8}px; }}
    QPushButton#AskButton:hover {{ background: {p.surface_alt}; }}
    QPushButton#AskButton:focus {{ border: {fw}px solid {p.focus}; }}
    QToolButton {{ background: {p.surface}; color: {p.text}; border: 1px solid {p.line_strong};
        border-radius: {sm}px; padding: 7px 14px; min-height: {target - 16}px; }}
    QToolButton:hover {{ background: {p.surface_alt}; }}
    QToolButton:focus {{ border: {fw}px solid {p.focus}; }}
    QToolButton::menu-indicator {{ image: none; }}
    QToolButton#UserMenu {{ background: transparent; color: {p.topbar_text}; border: 1px solid {p.line_strong};
        border-radius: {sm}px; padding: 6px 10px; min-height: {target - 12}px; }}
    QToolButton#UserMenu:hover {{ background: {p.surface_alt}; }}
    QToolButton#UserMenu:focus {{ border: {fw}px solid {p.focus}; }}
    QToolButton#UserMenu::menu-indicator {{ image: none; }}

    /* ---------- featured banner, callout, toast ---------- */
    QFrame[banner="true"] {{ background: {p.banner}; border: 1px solid {p.banner_line}; border-radius: {lg}px; }}
    QFrame[callout="true"] {{ background: {p.callout}; border: 1px solid {p.line}; border-left: 4px solid {p.info};
        border-radius: {md}px; }}
    QFrame#Toast {{ background: {p.text}; border-radius: {md}px; }}
    QFrame#Toast QLabel {{ color: {p.window}; }}
    QFrame#Toast QPushButton {{ background: transparent; color: {p.window}; border: 1px solid {p.window};
        border-radius: {sm}px; min-height: 0; padding: 4px 10px; }}
    QFrame#Toast QPushButton:focus {{ border: {fw}px solid {p.focus}; }}

    /* ---------- buttons ---------- */
    QPushButton {{ background: {p.surface}; color: {p.text}; border: 1px solid {p.line_strong};
        border-radius: {sm}px; padding: 7px 14px; min-height: {target - 16}px; }}
    QPushButton:hover {{ background: {p.surface_alt}; }}
    QPushButton:pressed {{ background: {p.primary_soft}; }}
    QPushButton:focus {{ border: {fw}px solid {p.focus}; }}
    QPushButton:disabled {{ color: {p.text_muted}; background: {p.surface_alt}; border-color: {p.line}; }}
    QPushButton[kind="primary"] {{ background: {p.primary}; color: {p.on_primary}; border: 1px solid {p.primary};
        font-weight: 600; }}
    QPushButton[kind="primary"]:hover {{ background: {p.primary_hover}; }}
    QPushButton[kind="primary"]:focus {{ border: {fw}px solid {p.focus}; }}
    QPushButton[kind="primary"]:disabled {{ background: {p.surface_alt}; color: {p.text_muted};
        border-color: {p.line}; }}
    QPushButton[kind="danger"] {{ color: {p.danger}; border-color: {p.danger}; }}
    QPushButton[kind="link"] {{ background: transparent; border: none; color: {p.info};
        padding: 2px 0; text-align: left; min-height: 0; text-decoration: underline; }}
    QPushButton[kind="link"]:focus {{ border: {fw}px solid {p.focus}; }}
    QPushButton[kind="chip"] {{ background: {p.surface}; color: {p.text}; border: 1px solid {p.line_strong};
        border-radius: {target // 2 - 4}px; padding: 4px 14px; min-height: {target - 12}px; text-align: left; }}
    QPushButton[kind="chip"]:hover {{ background: {p.primary_soft}; }}
    QPushButton[kind="chip"]:focus {{ border: {fw}px solid {p.focus}; }}
    QPushButton[segment="true"] {{ background: {p.surface}; color: {p.text}; border: 1px solid {p.line_strong};
        border-radius: 0; padding: 7px 14px; min-height: {target - 16}px; }}
    QPushButton[segment="true"][first="true"] {{ border-top-left-radius: {sm}px; border-bottom-left-radius: {sm}px; }}
    QPushButton[segment="true"][last="true"] {{ border-top-right-radius: {sm}px; border-bottom-right-radius: {sm}px; }}
    QPushButton[segment="true"]:checked {{ background: {p.primary}; color: {p.on_primary}; border-color: {p.primary};
        font-weight: 600; }}
    QPushButton[segment="true"]:focus {{ border: {fw}px solid {p.focus}; }}

    /* ---------- inputs (borders >= 3:1 so every field is findable) ---------- */
    QLineEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QTimeEdit {{
        background: {p.surface}; color: {p.text}; border: 1px solid {p.line_strong}; border-radius: {sm}px;
        padding: 6px 10px; selection-background-color: {p.selection}; selection-color: {p.on_selection}; }}
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QTimeEdit {{ min-height: {target - 18}px; }}
    QLineEdit#AskInput {{ font-size: {pt(TYPE_LEAD)}; padding: 10px 14px; border-radius: {md}px; }}
    QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus,
    QDateEdit:focus, QTimeEdit:focus {{ border: {fw}px solid {p.focus}; }}
    QLineEdit[invalid="true"], QPlainTextEdit[invalid="true"], QComboBox[invalid="true"],
    QDateEdit[invalid="true"], QSpinBox[invalid="true"], QTimeEdit[invalid="true"],
    QDoubleSpinBox[invalid="true"], QListWidget[invalid="true"] {{ border: 2px solid {p.danger}; }}
    QLineEdit:disabled, QPlainTextEdit:disabled, QComboBox:disabled, QSpinBox:disabled,
    QDoubleSpinBox:disabled, QDateEdit:disabled, QTimeEdit:disabled {{
        background: {p.surface_alt}; color: {p.text_muted}; border-color: {p.line}; }}
    QComboBox::drop-down, QDateEdit::drop-down {{ subcontrol-origin: padding; subcontrol-position: center right;
        width: 26px; border: none; }}
    QComboBox::down-arrow, QDateEdit::down-arrow {{ image: url("{down_arrow}"); width: 14px; height: 14px; }}
    QSpinBox::up-button, QDoubleSpinBox::up-button, QTimeEdit::up-button, QDateEdit::up-button {{
        subcontrol-origin: border; subcontrol-position: top right; width: 22px; border: none; }}
    QSpinBox::down-button, QDoubleSpinBox::down-button, QTimeEdit::down-button, QDateEdit::down-button {{
        subcontrol-origin: border; subcontrol-position: bottom right; width: 22px; border: none; }}
    QSpinBox::up-arrow, QDoubleSpinBox::up-arrow, QTimeEdit::up-arrow, QDateEdit::up-arrow {{
        image: url("{up_arrow}"); width: 11px; height: 11px; }}
    QSpinBox::down-arrow, QDoubleSpinBox::down-arrow, QTimeEdit::down-arrow, QDateEdit::down-arrow {{
        image: url("{down_arrow}"); width: 11px; height: 11px; }}
    QComboBox QAbstractItemView {{ background: {p.surface}; color: {p.text}; border: 1px solid {p.line_strong};
        selection-background-color: {p.selection}; selection-color: {p.on_selection}; }}
    QCheckBox, QRadioButton {{ spacing: 10px; min-height: {target - 16}px; }}
    QCheckBox::indicator, QRadioButton::indicator {{ width: {box}px; height: {box}px;
        border: 2px solid {p.line_strong}; background: {p.surface}; }}
    QCheckBox::indicator {{ border-radius: 4px; }}
    QRadioButton::indicator {{ border-radius: {box // 2 + 2}px; }}
    QCheckBox::indicator:checked {{ background: {p.primary}; border-color: {p.primary}; image: url("{check}"); }}
    QRadioButton::indicator:checked {{ background: {p.surface}; border: {max(5, box // 3)}px solid {p.primary}; }}
    QCheckBox::indicator:focus, QRadioButton::indicator:focus {{ border-color: {p.focus}; }}
    QCheckBox:focus, QRadioButton:focus {{ color: {p.focus}; }}

    /* ---------- tables and lists ---------- */
    QTableView, QListWidget {{ background: {p.surface}; alternate-background-color: {p.surface_alt};
        border: 1px solid {p.line}; border-radius: {md}px; gridline-color: {p.line};
        selection-background-color: {p.selection}; selection-color: {p.on_selection}; }}
    QTableView:focus, QListWidget:focus {{ border: {fw}px solid {p.focus}; }}
    QTableView::item, QListWidget::item {{ padding: 6px 8px; }}
    QHeaderView::section {{ background: {p.surface}; color: {p.text_muted}; border: none;
        border-bottom: 1px solid {p.line_strong}; padding: 8px; font-weight: 600; }}
    QTabWidget::pane {{ border: 1px solid {p.line}; border-radius: {md}px; background: {p.surface}; top: -1px; }}
    QTabBar::tab {{ background: transparent; color: {p.text_muted}; padding: 9px 16px; min-height: {target - 20}px;
        border-bottom: 3px solid transparent; }}
    QTabBar::tab:selected {{ color: {p.text}; border-bottom: 3px solid {p.primary}; font-weight: 600; }}
    QTabBar::tab:focus {{ color: {p.focus}; }}
    QProgressBar {{ background: {p.surface_alt}; border: 1px solid {p.line}; border-radius: 5px;
        text-align: center; height: 14px; color: {p.text}; }}
    QProgressBar::chunk {{ background: {p.primary}; border-radius: 4px; }}
    QSlider {{ min-height: {target - 16}px; }}
    QSlider::groove:horizontal {{ height: 6px; background: {p.line_strong}; border-radius: 3px; }}
    QSlider::handle:horizontal {{ background: {p.primary}; width: 20px; margin: -8px 0; border-radius: 10px; }}
    QSlider:focus {{ border: {fw}px solid {p.focus}; border-radius: {sm}px; }}
    QStatusBar {{ background: {p.surface}; color: {p.text_muted}; border-top: 1px solid {p.line}; }}
    QMenuBar {{ background: {p.surface}; color: {p.text}; }}
    QMenu {{ background: {p.surface}; color: {p.text}; border: 1px solid {p.line_strong}; padding: 4px; }}
    QMenu::item {{ padding: 6px 18px; border-radius: 6px; }}
    QMenu::item:selected {{ background: {p.selection}; color: {p.on_selection}; }}
    QSplitter::handle {{ background: transparent; }}
    QScrollBar:vertical {{ background: transparent; width: 12px; margin: 2px; }}
    QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {p.line_strong}; border-radius: 4px; min-height: 32px; }}
    QScrollBar::handle:horizontal {{ background: {p.line_strong}; border-radius: 4px; min-width: 32px; }}
    QScrollBar::handle:hover {{ background: {p.text_muted}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; border: none; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    QCalendarWidget QWidget#qt_calendar_navigationbar {{ background: {p.surface_alt}; border-radius: {sm}px; }}
    QCalendarWidget QToolButton {{ color: {p.text}; background: transparent; border: none; font-weight: 600;
        padding: 4px 10px; min-height: 0; }}
    QCalendarWidget QToolButton:hover {{ background: {p.selection}; color: {p.on_selection}; }}
    QCalendarWidget QAbstractItemView {{ background: {p.surface}; color: {p.text}; outline: none;
        selection-background-color: {p.selection}; selection-color: {p.on_selection}; }}
    QCalendarWidget QSpinBox {{ min-height: 0; }}
    """
