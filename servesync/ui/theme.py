"""
Visual design system: tokens, four themes, text scaling, and comfort settings.

Design rationale (the longer version is in docs/design-rationale.md)
--------------------------------------------------------------------
* **A dark, editorial look in blue.** Near-black canvas, large light headings
  with one word picked out in blue, small monospaced labels and counters
  ("01 / 02"), fields drawn as a single underline, square corners and thin
  hairlines. One saturated blue does all the pointing: the main button, the
  current page, focus, progress and the highlighted word. Everything else is
  black, white and gray, so the blue always means "here" or "do this".
* **Tokens, not one-off colors.** Screens ask for *meaning* ("primary",
  "text_muted", "attention_fill"), never a hex value; a test fails if a page,
  widget or dialog hard-codes a color.
* **WCAG 2.2 AAA contrast, verified by tests.** Every text color is at least
  7:1 against every background it can sit on (1.4.6), including the blue used
  as text; field underlines and focus rings are at least 3:1 (1.4.11, 2.4.13).
  The blue button carries near-black text because white on a bright blue
  reaches only 4.5:1.
* **Three typefaces, one scale.** Geist Light for page titles and big figures,
  Figtree for everything people read and click, IBM Plex Mono for small labels
  and counters. The comfort setting "Easier-to-read letters" switches body text
  to Atkinson Hyperlegible.
* **Square corners, flat surfaces.** Areas are separated by space and 1 px
  hairlines; cards are a slightly lighter panel, never a shadow.
* **Big targets.** Every button, field and tab is at least 44 px tall
  (2.5.5 Target Size, AAA), and grows with the text size.
* **Four themes.** Dark is the signature look and the default; Light is the
  same system on paper-white; Match my computer follows macOS/Windows; High
  contrast (black/white/yellow, 3 px focus) is for maximum legibility.
* **Never color alone.** Every status also has words or a shape.
"""

from __future__ import annotations

import dataclasses
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QLibraryInfo, Qt, QTranslator
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPalette, QTransform
from PySide6.QtWidgets import QApplication

from servesync.core.i18n import Language, set_language
from servesync.models import Appearance, Theme

# ------------------------------------------------------------ scale tokens

#: 4-point base with an 8-point rhythm.
SPACE_HALF, SPACE_1, SPACE_2, SPACE_3, SPACE_4, SPACE_5, SPACE_6 = 4, 8, 16, 24, 32, 48, 64
#: Corner radii: square everywhere, as in the reference; 0 keeps edges crisp on any screen.
RADIUS_CONTROL, RADIUS_CARD = 0, 0
#: The one type scale (multiples of the body size): caption, body, section title, page title, display.
TYPE_CAPTION, TYPE_BODY, TYPE_SECTION, TYPE_TITLE, TYPE_DISPLAY = 0.85, 1.0, 1.2, 2.2, 3.4
#: Minimum interactive height at 100% text (WCAG 2.5.5 AAA: 44 x 44 px).
MIN_TARGET = 44

# ------------------------------------------------------------ palette

BLACK = "#111111"  # the dark canvas
PANEL = "#161616"  # cards and raised panels on the dark canvas
RAISED = "#1F1F1F"  # hover on dark panels
HAIRLINE = "#262626"  # decorative dividers on dark
EDGE = "#3A3A3A"  # button outlines on dark (their label identifies them)
UNDERLINE = "#7A7A7A"  # field underlines: 3:1 or better on every dark surface
WHITE_TEXT = "#F4F4F4"
GRAY_TEXT = "#ABABAB"  # secondary text, 7.6:1 or better on every dark surface
BLUE = "#6AA4FF"  # the one accent on dark: 7:1 as text, and a fill for near-black text
BLUE_HOVER = "#8AB8FF"
BLUE_SOFT = "#16233A"  # a blue-tinted row or hover on dark

PAPER = "#F4F4F4"  # the light canvas
CARD_WHITE = "#FFFFFF"
PAPER_HOVER = "#EAEAEA"
PAPER_LINE = "#DADADA"
INK = "#111111"
INK_MUTED = "#4A4A4A"
DEEP_BLUE = "#1840B8"  # the accent on light: 7:1 as text, and a fill for white text
DEEP_BLUE_HOVER = "#12329A"
BLUE_TINT = "#E3EBFB"

AMBER = "#FFB020"  # "needs attention" as a shape: markers, calendar dots
AMBER_TEXT_DARK = "#FFC75A"
GREEN = "#34D399"  # success as a shape on dark
GREEN_LIGHT = "#0E9F6E"  # success as a shape on light
GREEN_TEXT = "#05553F"
RED_TEXT_DARK, RED_TEXT_LIGHT = "#FF9E8F", "#9B1C1C"
GREEN_TEXT_DARK = "#7EE2B8"


@dataclass(frozen=True, slots=True)
class Palette:
    name: str
    window: str  # page background ("canvas")
    surface: str  # tables, inputs, dialogs
    surface_alt: str  # cards and sunken fills
    text: str
    text_muted: str  # secondary text, still >= 7:1
    line: str  # decorative hairlines (cards, dividers)
    line_strong: str  # boundaries people must see: field underlines (>= 3:1)
    primary: str  # the accent: main button fill, and usable as text (>= 7:1)
    primary_hover: str
    on_primary: str
    primary_soft: str  # hover tint for rows and quiet buttons
    topbar: str
    topbar_text: str
    topbar_muted: str
    topbar_active: str
    attention: str  # text of a figure that needs attention (>= 7:1); the amber marker sits beside it
    attention_fill: str  # amber as a *shape* (dots, bars, badges); text on it uses on_attention
    danger: str
    success: str  # success as *text* (>= 7:1)
    focus: str  # keyboard focus ring (>= 3:1 against surfaces)
    selection: str
    on_selection: str
    info: str  # links
    cta: str  # the header's main action: the one filled button on a screen
    on_cta: str
    cta_hover: str
    banner: str  # the featured event card
    banner_line: str
    callout: str
    sidebar: str
    sidebar_text: str
    sidebar_muted: str  # secondary sidebar text, still >= 7:1
    sidebar_hover: str
    sidebar_active: str  # background of the current page (its text stays >= 7:1)
    sidebar_accent: str  # the current page's text, icon and marker
    sidebar_focus: str  # keyboard focus ring inside the sidebar (>= 3:1)
    brand: str = BLACK  # the logo square
    success_fill: str = GREEN  # success as a *shape* (score bars, open-spot dots)
    on_attention: str = INK  # dark text on an amber fill
    button_line: str = EDGE  # outlined buttons' edge
    is_dark: bool = False
    focus_width: int = 2
    #: Smart Match factors (availability, skills, reliability, experience, fair share), each also labeled.
    factors: tuple[str, str, str, str, str] = (BLUE, WHITE_TEXT, GREEN, AMBER, "#6B6B6B")
    #: Chart series, in order: blue (the lead series), white, green. Charts print values on every bar.
    chart: tuple[str, str, str] = (BLUE, WHITE_TEXT, GREEN)


DARK = Palette(
    name="Dark",
    window=BLACK,
    surface=BLACK,
    surface_alt=PANEL,
    text=WHITE_TEXT,
    text_muted=GRAY_TEXT,
    line=HAIRLINE,
    line_strong=UNDERLINE,
    primary=BLUE,
    primary_hover=BLUE_HOVER,
    on_primary=BLACK,
    primary_soft=RAISED,
    topbar=BLACK,
    topbar_text=WHITE_TEXT,
    topbar_muted=GRAY_TEXT,
    topbar_active=RAISED,
    attention=AMBER_TEXT_DARK,  # amber may be text on a dark background
    attention_fill=AMBER,
    danger=RED_TEXT_DARK,
    success=GREEN_TEXT_DARK,
    focus=BLUE,
    selection=BLUE_SOFT,
    on_selection=WHITE_TEXT,
    info=BLUE,
    cta=BLUE,
    on_cta=BLACK,
    cta_hover=BLUE_HOVER,
    banner=PANEL,
    banner_line=HAIRLINE,
    callout=BLACK,
    sidebar=BLACK,
    sidebar_text=GRAY_TEXT,
    sidebar_muted=GRAY_TEXT,
    sidebar_hover=PANEL,
    sidebar_active=PANEL,
    sidebar_accent=BLUE,
    sidebar_focus=BLUE,
    brand=BLUE,
    success_fill=GREEN,
    on_attention=BLACK,
    button_line=EDGE,
    is_dark=True,
)

LIGHT = Palette(
    name="Light",
    window=PAPER,
    surface=PAPER,
    surface_alt=CARD_WHITE,
    text=INK,
    text_muted=INK_MUTED,
    line=PAPER_LINE,
    line_strong=UNDERLINE,
    primary=DEEP_BLUE,
    primary_hover=DEEP_BLUE_HOVER,
    on_primary=CARD_WHITE,
    primary_soft=PAPER_HOVER,
    topbar=PAPER,
    topbar_text=INK,
    topbar_muted=INK_MUTED,
    topbar_active=PAPER_HOVER,
    attention=INK,
    attention_fill=AMBER,
    danger=RED_TEXT_LIGHT,
    success=GREEN_TEXT,
    focus=DEEP_BLUE,
    selection=BLUE_TINT,
    on_selection=INK,
    info=DEEP_BLUE,
    cta=DEEP_BLUE,
    on_cta=CARD_WHITE,
    cta_hover=DEEP_BLUE_HOVER,
    banner=CARD_WHITE,
    banner_line=PAPER_LINE,
    callout=PAPER,
    sidebar=PAPER,
    sidebar_text=INK_MUTED,
    sidebar_muted=INK_MUTED,
    sidebar_hover=PAPER_HOVER,
    sidebar_active=CARD_WHITE,
    sidebar_accent=DEEP_BLUE,
    sidebar_focus=DEEP_BLUE,
    brand=DEEP_BLUE,
    success_fill=GREEN_LIGHT,
    on_attention=INK,
    button_line="#BDBDBD",
    factors=(DEEP_BLUE, INK, GREEN_LIGHT, AMBER, "#9A9A9A"),
    chart=(DEEP_BLUE, INK, GREEN_LIGHT),
)

# High contrast keeps its own black, white and yellow: it exists for people who need
# maximum contrast, which matters more there than any brand look.
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
    sidebar="#000000",
    sidebar_text="#FFFFFF",
    sidebar_muted="#FFFFFF",
    sidebar_hover="#1A1A1A",
    sidebar_active="#333333",
    sidebar_accent="#FFD400",
    sidebar_focus="#00E5FF",
    brand="#000000",  # the mark becomes white strokes on black
    success_fill="#7CFF9E",
    on_attention="#000000",
    button_line="#FFFFFF",
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
    """Apply language, colors, fonts, spacing, and the stylesheet to the whole application."""
    set_language(appearance.language)
    _install_qt_translations(app, appearance.language)
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
    # "Easier-to-read letters" swaps the interface face for Atkinson Hyperlegible (WCAG 1.4.8).
    _fonts["body"] = (_fonts["legible"] if appearance.legible_font else "") or _fonts["interface"]
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


_translators: list[QTranslator] = []


def _install_qt_translations(app: QApplication, language: Language) -> None:
    """Qt's own words (OK, Cancel, Close, Yes, No; text-box menus) in the same language as ServeSync."""
    for translator in _translators:
        app.removeTranslator(translator)
    _translators.clear()
    if language is Language.ENGLISH:
        return
    translator = QTranslator(app)
    folder = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    if translator.load(f"qtbase_{language.value}", folder):
        app.installTranslator(translator)
        _translators.append(translator)


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
    return icon_file("check", color, 16)


def icon_file(name: str, color: str, size: int) -> str:
    """A recolored icon saved as a PNG, for places that take a file path (stylesheets, rich text)."""
    from servesync.ui import assets

    _arrow_images(color)  # makes sure the temp folder exists
    path = _arrow_dir["path"] / f"{name}-{color.lstrip('#')}-{size}.png"
    if not path.exists():
        assets.pixmap(name, color, size).save(str(path))
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


_fonts: dict[str, str] = {"body": "", "heading": "", "interface": "", "legible": "", "mono": ""}


def set_font_families(body: str, heading: str, legible: str = "", mono: str = "") -> None:
    """
    Record the bundled font families (empty string = use the system font): the interface
    face, the heading face, the easier-to-read face offered as a comfort setting, and the
    monospaced face for counters.
    """
    _fonts["interface"], _fonts["heading"], _fonts["legible"], _fonts["mono"] = body, heading, legible, mono
    _fonts["body"] = body


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
    heading = f'font-family: "{_fonts["heading"]}";' if _fonts["heading"] else ""
    mono = f'font-family: "{_fonts["mono"]}";' if _fonts["mono"] else ""
    target = round(MIN_TARGET * max(1.0, size / 13))  # minimum interactive height in pixels
    card = RADIUS_CARD
    # Titles and big figures: Geist set large and light, as in an editorial layout.
    title = f"{heading} font-size: {pt(TYPE_TITLE)}; font-weight: 300;"
    display = f"{heading} font-size: {pt(TYPE_DISPLAY)}; font-weight: 300;"
    section = f"font-size: {pt(TYPE_SECTION)}; font-weight: 500;"
    caption = f"font-size: {pt(TYPE_CAPTION)};"
    label = f"{mono} font-size: {pt(TYPE_CAPTION)};"  # small monospaced labels and counters
    return f"""
    QWidget {{ color: {p.text}; {body} }}
    QMainWindow, QDialog {{ background: {p.window}; }}
    QToolTip {{ background: {p.surface_alt}; color: {p.text}; border: 1px solid {p.line_strong};
        padding: 4px 8px; }}

    /* ---------- text roles: display, page title, section, body, caption, mono label ---------- */
    QLabel[role="title"], QLabel[role="figure"], QLabel[role="figure-attention"] {{ {title} }}
    QLabel[role="display"] {{ {display} }}
    QLabel[role="figure-attention"] {{ color: {p.attention}; }}
    QLabel[role="accent"] {{ {heading} font-size: {pt(TYPE_TITLE * 0.7)}; font-weight: 300; color: {p.primary}; }}
    QLabel[role="section"], QLabel[role="name"] {{ {section} }}
    QLabel[role="score"] {{ {section} color: {p.success}; }}
    QLabel[role="lead"], QLabel[role="insight"], QLabel[role="strength"] {{ color: {p.text}; }}
    QLabel[role="mission"], QLabel[role="subtitle"], QLabel[role="muted"] {{ color: {p.text_muted}; }}
    QLabel[role="figure-label"] {{ color: {p.text_muted}; }}
    QLabel[role="eyebrow"], QLabel[role="counter"] {{ {label} color: {p.text_muted}; }}
    QLabel[role="counter"] {{ color: {p.primary}; }}
    QLabel[role="hint"] {{ color: {p.text_muted}; {caption} }}
    QLabel[role="error"] {{ color: {p.danger}; {caption} }}
    QLabel[role="banner-error"] {{ color: {p.danger}; background: transparent;
        border: none; border-left: 2px solid {p.danger}; padding: 8px 12px; }}
    QLabel[role="link"] {{ color: {p.info}; }}
    QLabel[role="concern"] {{ color: {p.danger}; }}
    QLabel[role="ok"] {{ color: {p.success}; font-weight: 600; }}
    QLabel[role="kbd"] {{ {label} color: {p.text_muted}; border: 1px solid {p.line_strong}; padding: 2px 8px; }}
    QLabel[role="badge"] {{ {label} color: {p.on_attention}; background: {p.attention_fill};
        padding: 2px 8px; font-weight: 600; }}

    /* ---------- containers: plain sections; flat panels for objects and figures ---------- */
    QFrame[panel="true"] {{ background: transparent; border: none; }}
    QFrame[kpi="true"] {{ background: transparent; border: none; border-top: 1px solid {p.line_strong};
        border-radius: 0; }}
    QFrame[kpi="true"][attention="true"] {{ border-top: 2px solid {p.attention_fill}; }}
    QFrame[card="true"], QFrame[tile="true"], QFrame[banner="true"] {{ background: {p.surface_alt};
        border: 1px solid {p.line}; border-radius: {card}px; }}
    QFrame[card="true"]:hover {{ border-color: {p.line_strong}; }}
    QFrame[callout="true"] {{ background: transparent; border: none; border-top: 1px solid {p.line};
        border-radius: 0; }}
    QFrame[answer="true"] {{ background: transparent; border: none; border-bottom: 1px solid {p.line};
        border-radius: 0; }}
    QScrollArea {{ background: transparent; border: none; }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}
    QGroupBox {{ background: transparent; border: none; border-top: 1px solid {p.line};
        margin-top: 24px; padding: 16px 0 0 0; {section} }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 0; padding: 0; }}
    QGroupBox > QWidget {{ font-size: {pt(TYPE_BODY)}; font-weight: 400; }}

    /* ---------- sidebar: same canvas; the current page is white text with a blue marker ---------- */
    QWidget#Sidebar {{ background: {p.sidebar}; border-right: 1px solid {p.line}; }}
    QWidget#Sidebar QLabel {{ color: {p.text}; }}
    QWidget#Sidebar QLabel#OrgName {{ color: {p.sidebar_muted}; }}
    QWidget#TopBar {{ background: {p.topbar}; border-bottom: 1px solid {p.line}; }}
    QWidget#TopBar QLabel {{ color: {p.topbar_text}; }}
    QLabel#Brand {{ {heading} font-size: {pt(TYPE_SECTION)}; font-weight: 400; color: {p.primary}; }}
    QLabel#OrgName {{ color: {p.topbar_muted}; {caption} }}
    QWidget#NavIndicator {{ background: {p.sidebar_accent}; border-radius: 0; }}
    QPushButton[nav="true"] {{ background: transparent; color: {p.sidebar_text}; border: none; text-align: left;
        border-radius: 0; padding: 8px 16px; min-height: {target - 8}px; font-size: {pt(TYPE_BODY)}; }}
    QPushButton[nav="true"]:hover {{ background: {p.sidebar_hover}; color: {p.text}; }}
    QPushButton[nav="true"]:checked {{ background: {p.sidebar_active}; color: {p.text}; font-weight: 600; }}
    QPushButton[nav="true"]:focus {{ border: {fw}px solid {p.sidebar_focus}; }}

    /* ---------- header: search field, the one filled button, account ---------- */
    QPushButton#CallToAction {{ background: {p.cta}; color: {p.on_cta}; border: 1px solid {p.cta};
        border-radius: 0; padding: 8px 20px; min-height: {target - 16}px; font-weight: 600; }}
    QPushButton#CallToAction:hover {{ background: {p.cta_hover}; border-color: {p.cta_hover}; }}
    QPushButton#CallToAction:focus {{ border: {fw}px solid {p.text}; }}
    QPushButton#AskButton {{ background: transparent; color: {p.text_muted}; border: none;
        border-bottom: 1px solid {p.line_strong}; border-radius: 0; padding: 8px 4px;
        min-height: {target - 16}px; text-align: left; }}
    QPushButton#AskButton:hover {{ color: {p.text}; border-bottom-color: {p.text}; }}
    QPushButton#AskButton:focus {{ border-bottom: {fw}px solid {p.focus}; }}
    QToolButton {{ background: transparent; color: {p.text}; border: 1px solid {p.button_line};
        border-radius: 0; padding: 8px 16px; min-height: {target - 16}px; }}
    QToolButton:hover {{ background: {p.primary_soft}; }}
    QToolButton:focus {{ border: {fw}px solid {p.focus}; }}
    QToolButton::menu-indicator {{ image: none; }}
    QToolButton#UserMenu {{ background: transparent; color: {p.topbar_text}; border: 1px solid {p.button_line};
        border-radius: 0; padding: 8px 32px 8px 12px; min-height: {target - 16}px; }}
    QToolButton#UserMenu:hover {{ background: {p.primary_soft}; }}
    QToolButton#UserMenu:focus {{ border: {fw}px solid {p.focus}; }}
    QToolButton#UserMenu::menu-indicator {{ image: url("{down_arrow}"); subcontrol-origin: padding;
        subcontrol-position: center right; right: 10px; width: 14px; height: 14px; }}

    QToolButton#PageHelp {{ background: transparent; color: {p.text}; border: 1px solid {p.button_line};
        border-radius: 0; min-width: {target - 18}px; min-height: {target - 18}px;
        padding: 4px; font-weight: 600; }}
    QToolButton#PageHelp:hover {{ background: {p.primary_soft}; }}
    QToolButton#PageHelp:focus {{ border: {fw}px solid {p.focus}; }}

    /* ---------- first-run tour: a panel in the corner, and an outline around what it describes ---------- */
    QFrame#TourCard {{ background: {p.surface_alt}; border: 1px solid {p.line_strong}; border-radius: 0; }}
    QFrame#TourOutline {{ background: transparent; border: 2px solid {p.focus}; border-radius: 0; }}

    /* ---------- toast ---------- */
    QFrame#Toast {{ background: {p.text}; border-radius: 0; }}
    QFrame#Toast QLabel {{ color: {p.window}; }}
    QFrame#Toast QPushButton {{ background: transparent; color: {p.window}; border: 1px solid {p.window};
        border-radius: 0; min-height: 0; padding: 4px 8px; }}
    QFrame#Toast QPushButton:focus {{ border: {fw}px solid {p.focus}; }}

    /* ---------- buttons: thin outline by default; one blue primary per screen ---------- */
    QPushButton {{ background: transparent; color: {p.text}; border: 1px solid {p.button_line};
        border-radius: 0; padding: 8px 16px; min-height: {target - 16}px; }}
    QPushButton:hover {{ background: {p.primary_soft}; border-color: {p.line_strong}; }}
    QPushButton:pressed {{ background: {p.line}; }}
    QPushButton:focus {{ border: {fw}px solid {p.focus}; }}
    QPushButton:disabled {{ color: {p.text_muted}; background: transparent; border-color: {p.line}; }}
    QPushButton[kind="primary"] {{ background: {p.primary}; color: {p.on_primary}; border: 1px solid {p.primary};
        font-weight: 600; }}
    QPushButton[kind="primary"]:hover {{ background: {p.primary_hover}; border-color: {p.primary_hover}; }}
    QPushButton[kind="primary"]:focus {{ border: {fw}px solid {p.text}; }}
    QPushButton[kind="primary"]:disabled {{ background: {p.surface_alt}; color: {p.text_muted};
        border-color: {p.line}; }}
    QPushButton[kind="secondary"] {{ color: {p.text}; border: 1px solid {p.line_strong}; font-weight: 500; }}
    QPushButton[kind="secondary"]:hover {{ background: {p.primary_soft}; border-color: {p.text}; }}
    QPushButton[kind="secondary"]:focus {{ border: {fw}px solid {p.focus}; }}
    QPushButton[kind="danger"] {{ color: {p.danger}; border-color: {p.danger}; }}
    QPushButton[kind="link"] {{ background: transparent; border: none; border-bottom: 1px solid {p.text};
        color: {p.text}; padding: 2px 0; text-align: left; min-height: 0; }}
    QPushButton[kind="link"]:hover {{ color: {p.primary}; border-bottom-color: {p.primary}; }}
    QPushButton[kind="link"]:focus {{ border: {fw}px solid {p.focus}; }}
    QPushButton[kind="chip"] {{ background: transparent; color: {p.info}; border: none; border-radius: 0;
        padding: 8px 8px; min-height: {target - 16}px; text-align: left; }}
    QPushButton[kind="chip"]:hover {{ background: {p.primary_soft}; }}
    QPushButton[kind="chip"]:focus {{ border: {fw}px solid {p.focus}; }}
    QPushButton[kind="kiosk"] {{ background: {p.surface_alt}; color: {p.text}; border: 1px solid {p.line};
        border-radius: 0; padding: 16px 24px; min-height: {target + 32}px; font-size: {pt(TYPE_SECTION)};
        text-align: left; }}
    QPushButton[kind="kiosk"]:hover {{ border-color: {p.primary}; }}
    QPushButton[kind="kiosk"]:focus {{ border: {fw}px solid {p.focus}; }}
    QPushButton[kind="kiosk"]:disabled {{ color: {p.text_muted}; background: {p.surface_alt}; }}
    QLineEdit#KioskSearch {{ font-size: {pt(TYPE_SECTION)}; padding: 16px 0; min-height: {target}px; }}
    QPushButton[segment="true"] {{ background: transparent; color: {p.text_muted};
        border: 1px solid {p.button_line}; border-radius: 0; padding: 8px 16px; min-height: {target - 16}px; }}
    QPushButton[segment="true"]:hover {{ color: {p.text}; }}
    QPushButton[segment="true"]:checked {{ background: {p.surface_alt}; color: {p.text};
        border-color: {p.primary}; font-weight: 600; }}
    QPushButton[segment="true"]:focus {{ border: {fw}px solid {p.focus}; }}

    /* ---------- inputs: a single underline (>= 3:1); it turns blue and thicker on focus ---------- */
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QTimeEdit {{
        background: transparent; color: {p.text}; border: none; border-bottom: 1px solid {p.line_strong};
        border-radius: 0; padding: 8px 2px; min-height: {target - 20}px;
        selection-background-color: {p.selection}; selection-color: {p.on_selection}; }}
    QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QTimeEdit {{ padding-right: 28px; }}
    QPlainTextEdit {{ background: transparent; color: {p.text}; border: 1px solid {p.line_strong};
        border-radius: 0; padding: 8px 12px; selection-background-color: {p.selection};
        selection-color: {p.on_selection}; }}
    QLineEdit#AskInput {{ padding: 8px 2px; }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QDateEdit:focus,
    QTimeEdit:focus {{ border-bottom: {fw}px solid {p.focus}; }}
    QPlainTextEdit:focus {{ border: {fw}px solid {p.focus}; }}
    QLineEdit[invalid="true"], QComboBox[invalid="true"], QDateEdit[invalid="true"],
    QSpinBox[invalid="true"], QTimeEdit[invalid="true"], QDoubleSpinBox[invalid="true"] {{
        border-bottom: 2px solid {p.danger}; }}
    QPlainTextEdit[invalid="true"], QListWidget[invalid="true"] {{ border: 2px solid {p.danger}; }}
    QLineEdit:disabled, QPlainTextEdit:disabled, QComboBox:disabled, QSpinBox:disabled,
    QDoubleSpinBox:disabled, QDateEdit:disabled, QTimeEdit:disabled {{
        color: {p.text_muted}; border-color: {p.line}; }}
    QComboBox::drop-down, QDateEdit::drop-down {{ subcontrol-origin: padding; subcontrol-position: center right;
        width: 24px; border: none; }}
    QComboBox::down-arrow, QDateEdit::down-arrow {{ image: url("{down_arrow}"); width: 14px; height: 14px; }}
    QSpinBox::up-button, QDoubleSpinBox::up-button, QTimeEdit::up-button, QDateEdit::up-button {{
        subcontrol-origin: border; subcontrol-position: top right; width: 24px; border: none; }}
    QSpinBox::down-button, QDoubleSpinBox::down-button, QTimeEdit::down-button, QDateEdit::down-button {{
        subcontrol-origin: border; subcontrol-position: bottom right; width: 24px; border: none; }}
    QSpinBox::up-arrow, QDoubleSpinBox::up-arrow, QTimeEdit::up-arrow, QDateEdit::up-arrow {{
        image: url("{up_arrow}"); width: 11px; height: 11px; }}
    QSpinBox::down-arrow, QDoubleSpinBox::down-arrow, QTimeEdit::down-arrow, QDateEdit::down-arrow {{
        image: url("{down_arrow}"); width: 11px; height: 11px; }}
    QComboBox QAbstractItemView {{ background: {p.surface_alt}; color: {p.text}; border: 1px solid {p.line_strong};
        selection-background-color: {p.selection}; selection-color: {p.on_selection}; }}
    QCheckBox, QRadioButton {{ spacing: 8px; min-height: {target - 16}px; }}
    QCheckBox::indicator, QRadioButton::indicator {{ width: {box}px; height: {box}px;
        border: 1px solid {p.line_strong}; background: transparent; }}
    QCheckBox::indicator {{ border-radius: 0; }}
    QRadioButton::indicator {{ border-radius: {box // 2 + 1}px; }}
    QCheckBox::indicator:checked {{ background: {p.primary}; border-color: {p.primary}; image: url("{check}"); }}
    QRadioButton::indicator:checked {{ background: {p.window}; border: {max(5, box // 3)}px solid {p.primary}; }}
    QCheckBox::indicator:focus, QRadioButton::indicator:focus {{ border: {fw}px solid {p.focus}; }}
    QCheckBox:focus, QRadioButton:focus {{ color: {p.primary}; }}

    /* ---------- tables and lists: no stripes, hairline rows, mono column labels ---------- */
    QTableView, QListWidget {{ background: transparent; border: none; border-top: 1px solid {p.line_strong};
        border-radius: 0; gridline-color: {p.line}; selection-background-color: {p.selection};
        selection-color: {p.on_selection}; }}
    QTableView:focus, QListWidget:focus {{ border: {fw}px solid {p.focus}; }}
    QTableView::item {{ padding: 8px 12px; border-bottom: 1px solid {p.line}; }}
    QTableView::item:hover {{ background: {p.primary_soft}; color: {p.text}; }}
    QTableView::item:selected {{ background: {p.selection}; color: {p.on_selection}; }}
    QListWidget::item {{ padding: 8px 12px; border-bottom: 1px solid {p.line}; }}
    QListWidget::item:hover {{ background: {p.primary_soft}; color: {p.text}; }}
    QListWidget::item:selected {{ background: {p.selection}; color: {p.on_selection}; }}
    QListWidget::indicator {{ width: {box}px; height: {box}px; border: 1px solid {p.line_strong};
        background: transparent; border-radius: 0; }}
    QListWidget::indicator:checked {{ background: {p.primary}; border-color: {p.primary}; image: url("{check}"); }}
    QHeaderView {{ background: transparent; }}
    QHeaderView::section {{ {label} background: {p.window}; color: {p.text_muted}; border: none;
        border-bottom: 1px solid {p.line}; padding: 8px 12px; }}
    QTableCornerButton::section {{ background: {p.window}; border: none; }}
    QTabWidget::pane {{ border: none; border-top: 1px solid {p.line}; background: transparent; top: -1px; }}
    QTabBar::tab {{ background: transparent; color: {p.text_muted}; padding: 8px 16px; min-height: {target - 20}px;
        border-bottom: 2px solid transparent; }}
    QTabBar::tab:selected {{ color: {p.text}; border-bottom: 2px solid {p.primary}; }}
    QTabBar::tab:hover {{ color: {p.text}; }}
    QTabBar::tab:focus {{ color: {p.primary}; }}
    QProgressBar {{ background: {p.line}; border: none; border-radius: 0;
        text-align: center; height: 4px; max-height: 6px; color: transparent; }}
    QProgressBar::chunk {{ background: {p.primary}; border-radius: 0; }}
    QProgressBar[complete="true"]::chunk {{ background: {p.success_fill}; }}
    QSlider {{ min-height: {target - 16}px; }}
    QSlider::groove:horizontal {{ height: 2px; background: {p.line_strong}; }}
    QSlider::handle:horizontal {{ background: {p.primary}; width: 16px; margin: -7px 0; border-radius: 0; }}
    QSlider:focus {{ border: {fw}px solid {p.focus}; }}
    QStatusBar {{ {label} background: {p.window}; color: {p.text_muted}; border-top: 1px solid {p.line}; }}
    QMenuBar {{ background: {p.window}; color: {p.text}; }}
    QMenuBar::item:selected {{ background: {p.primary_soft}; }}
    QMenu {{ background: {p.surface_alt}; color: {p.text}; border: 1px solid {p.line_strong}; padding: 4px; }}
    QMenu::item {{ padding: 8px 16px; }}
    QMenu::item:selected {{ background: {p.selection}; color: {p.on_selection}; }}
    QSplitter::handle {{ background: transparent; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {p.button_line}; min-height: 32px; }}
    QScrollBar::handle:horizontal {{ background: {p.button_line}; min-width: 32px; }}
    QScrollBar::handle:hover {{ background: {p.line_strong}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; border: none; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    QCalendarWidget QWidget#qt_calendar_navigationbar {{ background: {p.window}; border-bottom: 1px solid {p.line}; }}
    QCalendarWidget QToolButton {{ color: {p.text}; background: transparent; border: none; font-weight: 600;
        padding: 4px 8px; min-height: 0; }}
    QCalendarWidget QToolButton:hover {{ background: {p.primary_soft}; color: {p.text}; }}
    QCalendarWidget QAbstractItemView {{ background: {p.window}; color: {p.text}; outline: none;
        selection-background-color: {p.selection}; selection-color: {p.on_selection}; }}
    QCalendarWidget QSpinBox {{ min-height: 0; }}
    """
