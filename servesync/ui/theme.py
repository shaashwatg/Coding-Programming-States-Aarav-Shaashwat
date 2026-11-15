"""
Visual design system: tokens, four themes, text scaling, and comfort settings.

Design rationale (the longer version is in docs/design-rationale.md)
--------------------------------------------------------------------
* **Modelled on Cal.com's design system** (via its DESIGN.md in VoltAgent's
  awesome-design-md): a white canvas, near-black ink and primary buttons,
  light-gray cards, gray hairlines, and one blue accent used sparingly. It is
  scheduling software's own visual language, which suits shifts and
  volunteers, and its near-monochrome calm suits someone using it all day.
  Only the system is borrowed (type, spacing, surfaces, components); no
  Cal.com logo, wording or artwork.
* **Tokens, not one-off colors.** Screens ask for *meaning* ("primary",
  "text_muted", "attention_fill"), never a hex value; a test fails if a page,
  widget or dialog hard-codes a color.
* **WCAG 2.2 AAA contrast, verified by tests.** Every text color is at least
  7:1 against every background it can sit on (1.4.6); input borders and focus
  rings are at least 3:1 (1.4.11, 2.4.13). Where a Cal.com color is too light
  for text (its gray #6b7280, blue, green and red), text uses a deeper shade of
  the same hue and the original stays for fills, dots and charts.
* **Two typefaces, one scale.** Cal Sans for page titles and key figures,
  Inter for everything else (Regular, Medium, SemiBold). The comfort setting
  "Easier-to-read letters" switches body text to Atkinson Hyperlegible.
* **Hierarchical corners:** 8 px on buttons and inputs, 12 px on cards and
  dialogs; flat surfaces separated by gray card fills and 1 px hairlines.
* **Big targets.** Every button, field and tab is at least 44 px tall
  (2.5.5 Target Size, AAA), and grows with the text size.
* **Four themes.** Match my computer (follows macOS/Windows light or dark,
  live), Light, Dark (Cal.com's near-black #101010), High contrast
  (black/white/yellow, 3 px focus).
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

#: 4-point base with an 8-point rhythm (Cal.com: 4, 8, 12, 16, 24, 32, 48).
SPACE_HALF, SPACE_1, SPACE_2, SPACE_3, SPACE_4, SPACE_5, SPACE_6 = 4, 8, 16, 24, 32, 48, 64
#: Corner radii: buttons and inputs; cards and dialogs.
RADIUS_CONTROL, RADIUS_CARD = 8, 12
#: The one type scale (multiples of the body size): caption, body, section title, page title.
TYPE_CAPTION, TYPE_BODY, TYPE_SECTION, TYPE_TITLE = 0.88, 1.0, 1.15, 1.75
#: Minimum interactive height at 100% text (WCAG 2.5.5 AAA: 44 x 44 px).
MIN_TARGET = 44

# ------------------------------------------------------------ palette (Cal.com system)

INK = "#111111"  # headlines, primary text, and the primary button
INK_PRESSED = "#242424"
BLUE = "#3B82F6"  # the one accent: keyboard focus, the active chart series, links' family
GREEN = "#10B981"  # success as a shape: score bars, finished goals, open spots
AMBER = "#F59E0B"  # "needs attention" as a shape: markers, calendar dots

#: Cal.com's text colors below 7:1 get a deeper shade of the same hue for text.
BODY_TEXT = "#374151"  # secondary text (Cal.com's "body"; its #6b7280 is 4.8:1)
LINK_TEXT = "#1E40AF"
GREEN_TEXT = "#065F46"
RED_TEXT = "#991B1B"

CANVAS, CARD, SOFT, SUBTLE = "#FFFFFF", "#F5F5F5", "#F8F9FA", "#F3F4F6"
HAIRLINE, STRONG = "#E5E7EB", "#E5E7EB"
FIELD_BORDER = "#757B84"  # input borders: 3:1 or better on white and on gray cards
BUTTON_BORDER = "#D1D5DB"  # quieter edge for secondary buttons (their label identifies them)

DARK_CANVAS, DARK_SURFACE, DARK_SUNKEN, DARK_RAISED = "#101010", "#1A1A1A", "#242424", "#2A2A2A"
DARK_TEXT, DARK_TEXT_MUTED, DARK_BORDER = "#F3F4F6", "#B4B4BB", "#71717A"
DARK_BLUE, DARK_LINK, DARK_GREEN, DARK_AMBER, DARK_RED = "#60A5FA", "#93C5FD", "#6EE7B7", "#FBBF24", "#FCA5A5"


@dataclass(frozen=True, slots=True)
class Palette:
    name: str
    window: str  # page background ("canvas")
    surface: str  # tables, inputs, dialogs
    surface_alt: str  # cards and sunken fills
    text: str
    text_muted: str  # secondary text, still >= 7:1
    line: str  # decorative hairlines (cards, dividers)
    line_strong: str  # boundaries people must see: input borders (>= 3:1)
    primary: str  # the main button; also usable as text (>= 7:1)
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
    sidebar_accent: str  # the current page's text and icon
    sidebar_focus: str  # keyboard focus ring inside the sidebar (>= 3:1)
    brand: str = INK  # the logo square
    success_fill: str = GREEN  # success as a *shape* (score bars, open-spot dots)
    on_attention: str = INK  # dark text on an amber fill
    button_line: str = BUTTON_BORDER  # secondary buttons' edge
    is_dark: bool = False
    focus_width: int = 2
    #: Smart Match factors (availability, skills, reliability, experience, fair share), each also labeled.
    factors: tuple[str, str, str, str, str] = (INK, BLUE, GREEN, AMBER, "#9CA3AF")
    #: Chart series, in order: ink, blue (the active series), green. Charts print values on every bar.
    chart: tuple[str, str, str] = (INK, BLUE, GREEN)


LIGHT = Palette(
    name="Light",
    window=CANVAS,
    surface=CANVAS,
    surface_alt=CARD,
    text=INK,
    text_muted=BODY_TEXT,
    line=HAIRLINE,
    line_strong=FIELD_BORDER,
    primary=INK,
    primary_hover=INK_PRESSED,
    on_primary=CANVAS,
    primary_soft=SUBTLE,
    topbar=CANVAS,
    topbar_text=INK,
    topbar_muted=BODY_TEXT,
    topbar_active=SUBTLE,
    attention=INK,
    attention_fill=AMBER,
    danger=RED_TEXT,
    success=GREEN_TEXT,
    focus=BLUE,
    selection=STRONG,
    on_selection=INK,
    info=LINK_TEXT,
    cta=INK,
    on_cta=CANVAS,
    cta_hover=INK_PRESSED,
    banner=CARD,
    banner_line=HAIRLINE,
    callout=CANVAS,
    sidebar=SOFT,
    sidebar_text=INK,
    sidebar_muted=BODY_TEXT,
    sidebar_hover=SUBTLE,
    sidebar_active=STRONG,
    sidebar_accent=INK,
    sidebar_focus=BLUE,
)

DARK = Palette(
    name="Dark",
    window=DARK_CANVAS,
    surface=DARK_SURFACE,
    surface_alt=DARK_SUNKEN,
    text=DARK_TEXT,
    text_muted=DARK_TEXT_MUTED,
    line=DARK_RAISED,
    line_strong=DARK_BORDER,
    primary="#FFFFFF",  # Cal.com's dark surfaces flip the button: white with black text
    primary_hover=STRONG,
    on_primary=INK,
    primary_soft=DARK_RAISED,
    topbar=DARK_CANVAS,
    topbar_text=DARK_TEXT,
    topbar_muted=DARK_TEXT_MUTED,
    topbar_active=DARK_RAISED,
    attention=DARK_AMBER,  # amber may be text on a dark background
    attention_fill=DARK_AMBER,
    danger=DARK_RED,
    success=DARK_GREEN,
    focus=DARK_BLUE,
    selection="#33343A",
    on_selection="#FFFFFF",
    info=DARK_LINK,
    cta="#FFFFFF",
    on_cta=INK,
    cta_hover=STRONG,
    banner=DARK_SURFACE,
    banner_line=DARK_RAISED,
    callout=DARK_CANVAS,
    sidebar="#141414",
    sidebar_text=DARK_TEXT,
    sidebar_muted=DARK_TEXT_MUTED,
    sidebar_hover="#1F1F1F",
    sidebar_active=DARK_RAISED,
    sidebar_accent="#FFFFFF",
    sidebar_focus=DARK_BLUE,
    brand=DARK_RAISED,  # a dark square, so the white strokes of the mark still show
    success_fill="#34D399",
    on_attention=INK,
    button_line="#3A3A40",
    is_dark=True,
    factors=(DARK_TEXT, DARK_BLUE, "#34D399", DARK_AMBER, "#9CA3AF"),
    chart=(DARK_TEXT, DARK_BLUE, "#34D399"),
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


_fonts: dict[str, str] = {"body": "", "heading": "", "interface": "", "legible": ""}


def set_font_families(body: str, heading: str, legible: str = "") -> None:
    """
    Record the bundled font families (empty string = use the system font): the interface
    face, the heading face, and the easier-to-read face offered as a comfort setting.
    """
    _fonts["interface"], _fonts["heading"], _fonts["legible"] = body, heading, legible
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
    target = round(MIN_TARGET * max(1.0, size / 13))  # minimum interactive height in pixels
    ctl, card = RADIUS_CONTROL, RADIUS_CARD
    # Cal Sans is a display face drawn heavy at its regular weight, so it is never bolded further.
    title = f"{heading} font-size: {pt(TYPE_TITLE)}; font-weight: 400;"
    # Section titles stay in the interface face at SemiBold, as Cal.com's card and list titles do.
    section = f"font-size: {pt(TYPE_SECTION)}; font-weight: 600;"
    caption = f"font-size: {pt(TYPE_CAPTION)};"
    return f"""
    QWidget {{ color: {p.text}; {body} }}
    QMainWindow, QDialog {{ background: {p.window}; }}
    QToolTip {{ background: {p.surface}; color: {p.text}; border: 1px solid {p.line_strong}; padding: 4px 8px;
        border-radius: {ctl}px; }}

    /* ---------- text roles: page title, section title, body, caption ---------- */
    QLabel[role="title"], QLabel[role="display"], QLabel[role="figure"], QLabel[role="figure-attention"] {{ {title} }}
    QLabel[role="figure-attention"] {{ color: {p.attention}; }}
    QLabel[role="section"], QLabel[role="name"] {{ {section} }}
    QLabel[role="score"] {{ {section} color: {p.success}; }}
    QLabel[role="lead"], QLabel[role="insight"], QLabel[role="strength"] {{ color: {p.text}; }}
    QLabel[role="mission"], QLabel[role="subtitle"], QLabel[role="muted"], QLabel[role="figure-label"] {{
        color: {p.text_muted}; }}
    QLabel[role="eyebrow"] {{ color: {p.text_muted}; }}
    QLabel[role="hint"] {{ color: {p.text_muted}; {caption} }}
    QLabel[role="error"] {{ color: {p.danger}; {caption} }}
    QLabel[role="banner-error"] {{ color: {p.danger}; background: {p.surface};
        border: 1px solid {p.danger}; border-radius: {ctl}px; padding: 8px 12px; }}
    QLabel[role="link"] {{ color: {p.info}; }}
    QLabel[role="concern"] {{ color: {p.danger}; }}
    QLabel[role="ok"] {{ color: {p.success}; font-weight: 600; }}
    QLabel[role="kbd"] {{ color: {p.text_muted}; border: 1px solid {p.line}; border-radius: {ctl}px;
        padding: 2px 8px; {caption} }}
    QLabel[role="badge"] {{ color: {p.on_attention}; background: {p.attention_fill}; border-radius: 10px;
        padding: 2px 8px; {caption} font-weight: 600; }}

    /* ---------- containers: plain sections; light-gray cards for objects and figures ---------- */
    QFrame[panel="true"] {{ background: transparent; border: none; }}
    QFrame[kpi="true"] {{ background: {p.surface_alt}; border: none; border-radius: {card}px; }}
    QFrame[kpi="true"][attention="true"] {{ border-left: 4px solid {p.attention_fill}; }}
    QFrame[card="true"], QFrame[tile="true"], QFrame[banner="true"] {{ background: {p.surface_alt};
        border: none; border-radius: {card}px; }}
    QFrame[card="true"]:hover {{ background: {p.primary_soft}; }}
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

    /* ---------- sidebar (soft gray; the current page is a filled row in bold ink) ---------- */
    QWidget#Sidebar {{ background: {p.sidebar}; border-right: 1px solid {p.line}; }}
    QWidget#Sidebar QLabel {{ color: {p.sidebar_text}; }}
    QWidget#Sidebar QLabel#OrgName {{ color: {p.sidebar_muted}; }}
    QWidget#TopBar {{ background: {p.topbar}; border-bottom: 1px solid {p.line}; }}
    QWidget#TopBar QLabel {{ color: {p.topbar_text}; }}
    QLabel#Brand {{ {section} color: {p.sidebar_text}; }}
    QLabel#OrgName {{ color: {p.topbar_muted}; {caption} }}
    QWidget#NavIndicator {{ background: transparent; }}
    QPushButton[nav="true"] {{ background: transparent; color: {p.sidebar_text}; border: none; text-align: left;
        border-radius: {ctl}px; padding: 8px 16px; min-height: {target - 8}px; font-size: {pt(TYPE_BODY)}; }}
    QPushButton[nav="true"]:hover {{ background: {p.sidebar_hover}; }}
    QPushButton[nav="true"]:checked {{ background: {p.sidebar_active}; color: {p.sidebar_accent}; font-weight: 600; }}
    QPushButton[nav="true"]:focus {{ border: {fw}px solid {p.sidebar_focus}; }}

    /* ---------- header: search field, the one filled button, account ---------- */
    QPushButton#CallToAction {{ background: {p.cta}; color: {p.on_cta}; border: 1px solid {p.cta};
        border-radius: {ctl}px; padding: 8px 16px; min-height: {target - 16}px; font-weight: 600; }}
    QPushButton#CallToAction:hover {{ background: {p.cta_hover}; border-color: {p.cta_hover}; }}
    QPushButton#CallToAction:focus {{ border: {fw}px solid {p.on_cta}; }}
    QPushButton#AskButton {{ background: {p.surface_alt}; color: {p.text_muted}; border: 1px solid {p.line_strong};
        border-radius: {ctl}px; padding: 8px 12px; min-height: {target - 16}px; text-align: left; }}
    QPushButton#AskButton:hover {{ color: {p.text}; background: {p.surface_alt}; }}
    QPushButton#AskButton:focus {{ border: {fw}px solid {p.focus}; }}
    QToolButton {{ background: {p.surface}; color: {p.text}; border: 1px solid {p.line_strong};
        border-radius: {ctl}px; padding: 8px 16px; min-height: {target - 16}px; }}
    QToolButton:hover {{ background: {p.surface_alt}; }}
    QToolButton:focus {{ border: {fw}px solid {p.focus}; }}
    QToolButton::menu-indicator {{ image: none; }}
    QToolButton#UserMenu {{ background: transparent; color: {p.topbar_text}; border: 1px solid {p.line};
        border-radius: {ctl}px; padding: 8px 32px 8px 12px; min-height: {target - 16}px; }}
    QToolButton#UserMenu:hover {{ background: {p.surface_alt}; }}
    QToolButton#UserMenu:focus {{ border: {fw}px solid {p.focus}; }}
    QToolButton#UserMenu::menu-indicator {{ image: url("{down_arrow}"); subcontrol-origin: padding;
        subcontrol-position: center right; right: 10px; width: 14px; height: 14px; }}

    QToolButton#PageHelp {{ background: transparent; color: {p.text}; border: 1px solid {p.button_line};
        border-radius: {target // 2 - 4}px; min-width: {target - 18}px; min-height: {target - 18}px;
        padding: 4px; font-weight: 600; }}
    QToolButton#PageHelp:hover {{ background: {p.primary_soft}; }}
    QToolButton#PageHelp:focus {{ border: {fw}px solid {p.focus}; }}

    /* ---------- first-run tour: a card in the corner, and an outline around what it describes ---------- */
    QFrame#TourCard {{ background: {p.surface}; border: 1px solid {p.line_strong}; border-radius: {card}px; }}
    QFrame#TourOutline {{ background: transparent; border: 3px solid {p.focus}; border-radius: {ctl}px; }}

    /* ---------- toast ---------- */
    QFrame#Toast {{ background: {p.text}; border-radius: {card}px; }}
    QFrame#Toast QLabel {{ color: {p.window}; }}
    QFrame#Toast QPushButton {{ background: transparent; color: {p.window}; border: 1px solid {p.window};
        border-radius: {ctl}px; min-height: 0; padding: 4px 8px; }}
    QFrame#Toast QPushButton:focus {{ border: {fw}px solid {p.focus}; }}

    /* ---------- buttons: white with a soft edge by default; one black primary per screen ---------- */
    QPushButton {{ background: {p.surface}; color: {p.text}; border: 1px solid {p.button_line};
        border-radius: {ctl}px; padding: 8px 16px; min-height: {target - 16}px; font-weight: 500; }}
    QPushButton:hover {{ background: {p.surface_alt}; }}
    QPushButton:pressed {{ background: {p.line}; }}
    QPushButton:focus {{ border: {fw}px solid {p.focus}; }}
    QPushButton:disabled {{ color: {p.text_muted}; background: {p.surface_alt}; border-color: {p.line}; }}
    QPushButton[kind="primary"] {{ background: {p.primary}; color: {p.on_primary}; border: 1px solid {p.primary};
        font-weight: 600; }}
    QPushButton[kind="primary"]:hover {{ background: {p.primary_hover}; border-color: {p.primary_hover}; }}
    QPushButton[kind="primary"]:focus {{ border: {fw}px solid {p.on_primary}; }}
    QPushButton[kind="primary"]:disabled {{ background: {p.surface_alt}; color: {p.text_muted};
        border-color: {p.line}; }}
    QPushButton[kind="secondary"] {{ color: {p.text}; border: 1px solid {p.line_strong}; font-weight: 600; }}
    QPushButton[kind="secondary"]:hover {{ background: {p.surface_alt}; }}
    QPushButton[kind="secondary"]:focus {{ border: {fw}px solid {p.focus}; }}
    QPushButton[kind="danger"] {{ color: {p.danger}; border-color: {p.danger}; }}
    QPushButton[kind="link"] {{ background: transparent; border: none; color: {p.info};
        padding: 2px 0; text-align: left; min-height: 0; text-decoration: underline; }}
    QPushButton[kind="link"]:focus {{ border: {fw}px solid {p.focus}; }}
    QPushButton[kind="chip"] {{ background: transparent; color: {p.info}; border: none; border-radius: {ctl}px;
        padding: 8px 8px; min-height: {target - 16}px; text-align: left; }}
    QPushButton[kind="chip"]:hover {{ background: {p.primary_soft}; }}
    QPushButton[kind="chip"]:focus {{ border: {fw}px solid {p.focus}; }}
    QPushButton[kind="kiosk"] {{ background: {p.surface_alt}; color: {p.text}; border: 1px solid {p.surface_alt};
        border-radius: {card}px; padding: 16px 24px; min-height: {target + 32}px; font-size: {pt(TYPE_SECTION)};
        text-align: left; }}
    QPushButton[kind="kiosk"]:hover {{ background: {p.line}; border-color: {p.line_strong}; }}
    QPushButton[kind="kiosk"]:focus {{ border: {fw}px solid {p.focus}; }}
    QPushButton[kind="kiosk"]:disabled {{ color: {p.text_muted}; background: {p.surface_alt}; }}
    QLineEdit#KioskSearch {{ font-size: {pt(TYPE_SECTION)}; padding: 16px; min-height: {target}px; }}
    QPushButton[segment="true"] {{ background: {p.surface_alt}; color: {p.text_muted};
        border: 1px solid {p.surface_alt}; border-radius: 0; padding: 8px 16px; min-height: {target - 16}px; }}
    QPushButton[segment="true"]:hover {{ color: {p.text}; }}
    QPushButton[segment="true"][first="true"] {{ border-top-left-radius: {ctl}px;
        border-bottom-left-radius: {ctl}px; }}
    QPushButton[segment="true"][last="true"] {{ border-top-right-radius: {ctl}px;
        border-bottom-right-radius: {ctl}px; }}
    QPushButton[segment="true"]:checked {{ background: {p.surface}; color: {p.text};
        border-color: {p.line_strong}; font-weight: 600; }}
    QPushButton[segment="true"]:focus {{ border: {fw}px solid {p.focus}; }}

    /* ---------- inputs (borders >= 3:1 so every field is findable) ---------- */
    QLineEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QTimeEdit {{
        background: {p.surface}; color: {p.text}; border: 1px solid {p.line_strong}; border-radius: {ctl}px;
        padding: 8px 12px; selection-background-color: {p.selection}; selection-color: {p.on_selection}; }}
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QTimeEdit {{ min-height: {target - 20}px; }}
    QLineEdit#AskInput {{ padding: 8px 12px; }}
    QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus,
    QDateEdit:focus, QTimeEdit:focus {{ border: {fw}px solid {p.focus}; }}
    QLineEdit[invalid="true"], QPlainTextEdit[invalid="true"], QComboBox[invalid="true"],
    QDateEdit[invalid="true"], QSpinBox[invalid="true"], QTimeEdit[invalid="true"],
    QDoubleSpinBox[invalid="true"], QListWidget[invalid="true"] {{ border: 2px solid {p.danger}; }}
    QLineEdit:disabled, QPlainTextEdit:disabled, QComboBox:disabled, QSpinBox:disabled,
    QDoubleSpinBox:disabled, QDateEdit:disabled, QTimeEdit:disabled {{
        background: {p.surface_alt}; color: {p.text_muted}; border-color: {p.line}; }}
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
    QComboBox QAbstractItemView {{ background: {p.surface}; color: {p.text}; border: 1px solid {p.line_strong};
        selection-background-color: {p.selection}; selection-color: {p.on_selection}; }}
    QCheckBox, QRadioButton {{ spacing: 8px; min-height: {target - 16}px; }}
    QCheckBox::indicator, QRadioButton::indicator {{ width: {box}px; height: {box}px;
        border: 2px solid {p.line_strong}; background: {p.surface}; }}
    QCheckBox::indicator {{ border-radius: 4px; }}
    QRadioButton::indicator {{ border-radius: {box // 2 + 2}px; }}
    QCheckBox::indicator:checked {{ background: {p.primary}; border-color: {p.primary}; image: url("{check}"); }}
    QRadioButton::indicator:checked {{ background: {p.surface}; border: {max(5, box // 3)}px solid {p.primary}; }}
    QCheckBox::indicator:focus, QRadioButton::indicator:focus {{ border-color: {p.focus}; }}
    QCheckBox:focus, QRadioButton:focus {{ color: {p.focus}; }}

    /* ---------- tables and lists: no stripes, hairline dividers, soft gray hover ---------- */
    QTableView, QListWidget {{ background: {p.surface}; border: 1px solid {p.line}; border-radius: {card}px;
        gridline-color: {p.line}; selection-background-color: {p.selection}; selection-color: {p.on_selection}; }}
    QTableView:focus, QListWidget:focus {{ border: {fw}px solid {p.focus}; }}
    QTableView::item {{ padding: 8px 12px; border-bottom: 1px solid {p.line}; }}
    QTableView::item:hover {{ background: {p.primary_soft}; color: {p.text}; }}
    QTableView::item:selected {{ background: {p.selection}; color: {p.on_selection}; }}
    QListWidget::item {{ padding: 8px 12px; border-bottom: 1px solid {p.line}; }}
    QListWidget::item:hover {{ background: {p.primary_soft}; color: {p.text}; }}
    QListWidget::item:selected {{ background: {p.selection}; color: {p.on_selection}; }}
    QListWidget::indicator {{ width: {box}px; height: {box}px; border: 2px solid {p.line_strong};
        background: {p.surface}; border-radius: 4px; }}
    QListWidget::indicator:checked {{ background: {p.primary}; border-color: {p.primary}; image: url("{check}"); }}
    QHeaderView::section {{ background: {p.surface}; color: {p.text_muted}; border: none;
        border-bottom: 1px solid {p.line}; padding: 8px 12px; font-weight: 500; }}
    QTabWidget::pane {{ border: none; border-top: 1px solid {p.line}; background: transparent; top: -1px; }}
    QTabBar::tab {{ background: transparent; color: {p.text_muted}; padding: 8px 16px; min-height: {target - 20}px;
        border-bottom: 2px solid transparent; font-weight: 500; }}
    QTabBar::tab:selected {{ color: {p.text}; border-bottom: 2px solid {p.text}; font-weight: 600; }}
    QTabBar::tab:hover {{ color: {p.text}; }}
    QTabBar::tab:focus {{ color: {p.focus}; }}
    QProgressBar {{ background: {p.line}; border: none; border-radius: 4px;
        text-align: center; height: 16px; color: {p.text}; }}
    QProgressBar::chunk {{ background: {p.primary}; border-radius: 3px; }}
    QProgressBar[complete="true"]::chunk {{ background: {p.success_fill}; }}
    QSlider {{ min-height: {target - 16}px; }}
    QSlider::groove:horizontal {{ height: 4px; background: {p.line_strong}; border-radius: 2px; }}
    QSlider::handle:horizontal {{ background: {p.primary}; width: 20px; margin: -8px 0; border-radius: 10px; }}
    QSlider:focus {{ border: {fw}px solid {p.focus}; border-radius: {ctl}px; }}
    QStatusBar {{ background: {p.surface}; color: {p.text_muted}; border-top: 1px solid {p.line}; }}
    QMenuBar {{ background: {p.surface}; color: {p.text}; }}
    QMenu {{ background: {p.surface}; color: {p.text}; border: 1px solid {p.line_strong}; padding: 4px; }}
    QMenu::item {{ padding: 8px 16px; border-radius: {ctl}px; }}
    QMenu::item:selected {{ background: {p.selection}; color: {p.on_selection}; }}
    QSplitter::handle {{ background: transparent; }}
    QScrollBar:vertical {{ background: transparent; width: 12px; margin: 2px; }}
    QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {p.line_strong}; border-radius: 4px; min-height: 32px; }}
    QScrollBar::handle:horizontal {{ background: {p.line_strong}; border-radius: 4px; min-width: 32px; }}
    QScrollBar::handle:hover {{ background: {p.text_muted}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; border: none; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    QCalendarWidget QWidget#qt_calendar_navigationbar {{ background: {p.surface}; border-bottom: 1px solid {p.line}; }}
    QCalendarWidget QToolButton {{ color: {p.text}; background: transparent; border: none; font-weight: 600;
        padding: 4px 8px; min-height: 0; }}
    QCalendarWidget QToolButton:hover {{ background: {p.primary_soft}; color: {p.text}; }}
    QCalendarWidget QAbstractItemView {{ background: {p.surface}; color: {p.text}; outline: none;
        selection-background-color: {p.selection}; selection-color: {p.on_selection}; }}
    QCalendarWidget QSpinBox {{ min-height: 0; }}
    """
