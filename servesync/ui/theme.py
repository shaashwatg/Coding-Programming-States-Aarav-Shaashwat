"""
Visual design system: tokens, four themes, text scaling, and comfort settings.

Design rationale (the longer version is in docs/design-rationale.md)
--------------------------------------------------------------------
* **Three colors, each with one job, defined once.** Cobalt blue is the
  working color (the main button, links, selection, focus) and, as deep navy,
  frames the app in the sidebar. Warm amber is cobalt's complement and only
  *marks* things (needs attention, calendar dots, the active chart series, the
  current page's marker). Emerald is saved for the one thing that should
  stand out: success, open spots, the Smart Match score, finished goals.
  Everything else is cool neutral. Screens ask for *meaning* ("primary",
  "text_muted", "attention_fill"), never a hex value, so a theme is just a
  different set of values.
* **WCAG 2.2 AAA contrast, verified by tests.** Every text color is at least
  7:1 against every background it can sit on (1.4.6), including the tinted
  status tags; input borders and focus rings are at least 3:1 (1.4.11,
  2.4.13). Where a brand color is too light to be text at 7:1 (amber,
  emerald), a darker shade of the same hue is used for text and the bright
  one only for shapes. See ``tests/test_theme.py``.
* **Quiet surfaces, clear layers.** A cool canvas, white cards with hairline
  borders, and a navy sidebar: three layers, so the eye knows where content
  is. Only things that float (messages, the tour) cast a shadow.
* **One typeface, one scale.** Figtree (SIL Open Font License) for
  everything, in four weights and five sizes. Numbers use tabular figures so
  columns line up. Anyone who prefers it can switch all text to Atkinson
  Hyperlegible, designed by the Braille Institute for low-vision readers
  (Settings > Easy-read font).
* **Big targets, calm controls.** Buttons and fields are drawn 36 px tall for
  a tidy look but respond across a 44 px tall area (2.5.5 Target Size, AAA):
  the extra is an invisible margin. Both grow with the text size.
* **Four themes.** Match my computer (follows macOS/Windows light or dark,
  live), Light, Dark (low glare), High contrast (black/white/yellow, 3 px focus).
* **Text 85%-200%, plus optional extra letter and word spacing** (1.4.4,
  1.4.12). The whole interface scales from one base size, so nothing clips.
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

#: Body text size in pixels at 100% (the same on macOS, Windows and Linux).
BASE_TEXT_PX = 14.0
#: 8-point spacing grid (px), with a 4 px half step for tight pairs (a label and its hint).
SPACE_HALF, SPACE_1, SPACE_2, SPACE_3, SPACE_4, SPACE_5, SPACE_6 = 4, 8, 16, 24, 32, 48, 64
#: Corner radii: status tags; buttons and inputs; cards and dialogs.
RADIUS_TAG, RADIUS_CONTROL, RADIUS_CARD = 6, 8, 12
#: The one type scale (multiples of the body size).
TYPE_CAPTION, TYPE_SMALL, TYPE_BODY, TYPE_SECTION, TYPE_FIGURE, TYPE_TITLE, TYPE_DISPLAY = (
    0.86,  # 12 px: hints, table headers, tags
    0.93,  # 13 px: secondary text, form labels
    1.0,  # 14 px: body
    1.14,  # 16 px: section and card titles
    1.86,  # 26 px: key figures
    1.72,  # 24 px: page titles
    2.0,  # 28 px: the sign-in and kiosk headlines
)
#: Minimum interactive height at 100% text (WCAG 2.5.5 AAA: 44 x 44 px).
MIN_TARGET = 44
#: How tall a button or field is *drawn*; the rest of the 44 px target is an invisible margin.
CONTROL_HEIGHT = 36

# ------------------------------------------------------------ brand colors
# The three brand colors. Each theme below uses these or a lighter/darker
# shade of the same hue, chosen so that text keeps 7:1.

COBALT = "#1D43C6"  # primary: the main button, links, selection, focus
AMBER = "#F4A62A"  # complement: markers only (badges, attention, dots, active series)
EMERALD = "#0E9F6E"  # stand-out: success, open spots, Smart Match score, finished goals
NAVY = "#101C3F"  # cobalt at its deepest: the sidebar that frames the app

COBALT_HOVER, COBALT_PRESSED = "#1736A6", "#122C8A"
COBALT_TINT, COBALT_TINT_STRONG = "#EEF2FE", "#E2E9FD"  # tonal buttons, selected rows
COBALT_ON_TINT = "#1D3A9E"
#: Amber and emerald are too light to be text on white, so text uses these deeper shades (7:1+).
AMBER_TEXT, AMBER_TINT = "#6E4205", "#FDF1D6"
EMERALD_TEXT, EMERALD_TINT = "#055C3C", "#E1F5EC"
ERROR_RED, ERROR_ON_TINT, ERROR_TINT = "#9B1C13", "#8F1A12", "#FCE9E6"

# Neutrals (light theme): a cool canvas, white cards, ink text.
CANVAS, SURFACE, SURFACE_SUNKEN, SURFACE_HOVER = "#F4F6FA", "#FFFFFF", "#F1F3F8", "#F6F8FC"
INK, INK_MUTED, INK_FAINT = "#111A2E", "#4A5264", "#98A1B3"
HAIRLINE, CONTROL_LINE, BORDER = "#E4E8F0", "#D3D9E4", "#828C9F"
NEUTRAL_TINT, NEUTRAL_ON_TINT = "#EEF0F4", "#3D4556"

# Dark theme: low glare, and lighter tints of the same three colors.
DARK_CANVAS, DARK_SURFACE, DARK_SUNKEN, DARK_HOVER = "#0D111C", "#151A28", "#1C2233", "#1A2030"
DARK_TEXT, DARK_TEXT_MUTED, DARK_TEXT_FAINT = "#E9ECF5", "#B5BDD0", "#6F7890"
DARK_HAIRLINE, DARK_CONTROL_LINE, DARK_BORDER = "#252C3F", "#343C54", "#6B7590"
COBALT_LIGHT, COBALT_LIGHTER, COBALT_DEEP = "#A3B8FF", "#BCCBFF", "#1F2B55"
AMBER_LIGHT, EMERALD_LIGHT, DARK_ERROR = "#F7C66E", "#63DCAB", "#FFAA9F"

#: (background, text) pairs for the tags that name a status, and for initials avatars.
Tone = tuple[str, str]


@dataclass(frozen=True, slots=True)
class Palette:
    name: str
    window: str  # page background ("canvas")
    surface: str  # cards, tables, inputs, dialogs
    surface_alt: str  # sunken fills: table headers, tracks, quiet panels
    surface_hover: str  # the row or item under the pointer
    text: str
    text_muted: str  # secondary text, still >= 7:1
    text_faint: str  # decoration only (empty meter segments, separators inside art): never text
    line: str  # decorative hairlines (cards, dividers)
    line_control: str  # the edge of a button (its label identifies it, so the edge may be quiet)
    line_strong: str  # boundaries people must see: input borders (>= 3:1)
    primary: str  # actions; also usable as text (>= 7:1)
    primary_hover: str
    primary_pressed: str
    on_primary: str
    primary_soft: str  # tinted background for tonal buttons and selected states
    primary_soft_hover: str
    topbar: str
    topbar_text: str
    topbar_muted: str
    topbar_active: str
    attention: str  # text of a figure that needs attention (>= 7:1); the amber marker sits beside it
    attention_fill: str  # amber as a *shape* (dots, bars, badges); text on it uses on_attention
    on_attention: str  # dark text on an amber fill
    danger: str
    success: str  # success as *text* (>= 7:1)
    success_fill: str  # success as a *shape* (score rings, open-spot dots)
    focus: str  # keyboard focus ring (>= 3:1 against surfaces)
    selection: str
    on_selection: str
    info: str
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
    sidebar_accent: str  # the bar beside the current page
    sidebar_focus: str  # keyboard focus ring inside the sidebar (>= 3:1)
    sidebar_line: str
    brand: str  # the logo square
    #: Status tags: a tinted background with text of the same hue (each pair >= 7:1).
    tone_neutral: Tone
    tone_info: Tone
    tone_attention: Tone
    tone_success: Tone
    tone_danger: Tone
    #: Message bar across the bottom corner (toast) and tooltips: the inverse of the page.
    inverse: str
    on_inverse: str
    shadow: str  # the color floating things cast (drawn at low opacity)
    is_dark: bool = False
    focus_width: int = 2
    #: Smart Match factors (availability, skills, reliability, experience, fair share):
    #: the brand colors first, then neutrals; every factor is also labeled in words.
    factors: tuple[str, str, str, str, str] = (COBALT, EMERALD, AMBER, "#7A86A8", "#A9B8F2")
    #: Chart series, in order: cobalt, amber, emerald. Charts also print values on every bar.
    chart: tuple[str, str, str] = (COBALT, AMBER, EMERALD)

    def tone(self, name: str) -> Tone:
        """The (background, text) pair for a status tone: neutral, info, attention, success, danger."""
        return {
            "info": self.tone_info,
            "attention": self.tone_attention,
            "success": self.tone_success,
            "danger": self.tone_danger,
        }.get(name, self.tone_neutral)

    @property
    def avatar_tones(self) -> tuple[Tone, ...]:
        """Initials avatars rotate through the brand tints, so a roster reads as people, not rows."""
        return (self.tone_info, self.tone_success, self.tone_attention, self.tone_neutral)


LIGHT = Palette(
    name="Light",
    window=CANVAS,
    surface=SURFACE,
    surface_alt=SURFACE_SUNKEN,
    surface_hover=SURFACE_HOVER,
    text=INK,
    text_muted=INK_MUTED,
    text_faint=INK_FAINT,
    line=HAIRLINE,
    line_control=CONTROL_LINE,
    line_strong=BORDER,
    primary=COBALT,
    primary_hover=COBALT_HOVER,
    primary_pressed=COBALT_PRESSED,
    on_primary=SURFACE,
    primary_soft=COBALT_TINT,
    primary_soft_hover=COBALT_TINT_STRONG,
    topbar=SURFACE,
    topbar_text=INK,
    topbar_muted=INK_MUTED,
    topbar_active=COBALT_TINT,
    attention=INK,
    attention_fill=AMBER,
    on_attention=INK,
    danger=ERROR_RED,
    success=EMERALD_TEXT,
    success_fill=EMERALD,
    focus=COBALT,
    selection=COBALT_TINT_STRONG,
    on_selection=INK,
    info=COBALT,
    cta=COBALT,
    on_cta=SURFACE,
    cta_hover=COBALT_HOVER,
    banner=SURFACE,
    banner_line=HAIRLINE,
    callout=SURFACE_SUNKEN,
    sidebar=NAVY,
    sidebar_text="#F2F4FA",
    sidebar_muted="#B2BCD8",
    sidebar_hover="#1A2853",
    sidebar_active="#243569",
    sidebar_accent=AMBER,
    sidebar_focus="#9DB4FF",
    sidebar_line="#22305C",
    brand="#2B55E0",
    tone_neutral=(NEUTRAL_TINT, NEUTRAL_ON_TINT),
    tone_info=("#E9EEFD", COBALT_ON_TINT),
    tone_attention=(AMBER_TINT, AMBER_TEXT),
    tone_success=(EMERALD_TINT, EMERALD_TEXT),
    tone_danger=(ERROR_TINT, ERROR_ON_TINT),
    inverse=INK,
    on_inverse="#F4F6FA",
    shadow="#0B1638",
)

DARK = Palette(
    name="Dark",
    window=DARK_CANVAS,
    surface=DARK_SURFACE,
    surface_alt=DARK_SUNKEN,
    surface_hover=DARK_HOVER,
    text=DARK_TEXT,
    text_muted=DARK_TEXT_MUTED,
    text_faint=DARK_TEXT_FAINT,
    line=DARK_HAIRLINE,
    line_control=DARK_CONTROL_LINE,
    line_strong=DARK_BORDER,
    primary=COBALT_LIGHT,
    primary_hover=COBALT_LIGHTER,
    primary_pressed="#D2DCFF",
    on_primary=DARK_CANVAS,
    primary_soft=COBALT_DEEP,
    primary_soft_hover="#273668",
    topbar=DARK_SURFACE,
    topbar_text=DARK_TEXT,
    topbar_muted=DARK_TEXT_MUTED,
    topbar_active=COBALT_DEEP,
    attention=AMBER_LIGHT,  # amber may be text on a dark background
    attention_fill=AMBER_LIGHT,
    on_attention=DARK_CANVAS,
    danger=DARK_ERROR,
    success=EMERALD_LIGHT,
    success_fill=EMERALD_LIGHT,
    focus=COBALT_LIGHT,
    selection="#2A3766",
    on_selection="#F4F6FC",
    info=COBALT_LIGHT,
    cta=COBALT_LIGHT,
    on_cta=DARK_CANVAS,
    cta_hover=COBALT_LIGHTER,
    banner=DARK_SURFACE,
    banner_line=DARK_HAIRLINE,
    callout=DARK_SUNKEN,
    sidebar="#090C15",
    sidebar_text=DARK_TEXT,
    sidebar_muted=DARK_TEXT_MUTED,
    sidebar_hover=DARK_SURFACE,
    sidebar_active=COBALT_DEEP,
    sidebar_accent=AMBER_LIGHT,
    sidebar_focus=COBALT_LIGHT,
    sidebar_line=DARK_HAIRLINE,
    brand="#3559E0",
    tone_neutral=("#262D40", "#D0D6E4"),
    tone_info=(COBALT_DEEP, "#C3D0FF"),
    tone_attention=("#3D2E0F", "#FAD591"),
    tone_success=("#0F3526", "#8DE8C4"),
    tone_danger=("#451A15", "#FFC2B9"),
    inverse="#E9ECF5",
    on_inverse=DARK_CANVAS,
    shadow="#000000",
    is_dark=True,
    factors=(COBALT_LIGHT, EMERALD_LIGHT, AMBER_LIGHT, DARK_TEXT_MUTED, "#7C8CC8"),
    chart=(COBALT_LIGHT, AMBER_LIGHT, EMERALD_LIGHT),
)

# High contrast keeps its own black, white and yellow: it exists for people who need
# maximum contrast, which matters more there than the brand colors.
HIGH_CONTRAST = Palette(
    name="High contrast",
    window="#000000",
    surface="#000000",
    surface_alt="#1A1A1A",
    surface_hover="#262626",
    text="#FFFFFF",
    text_muted="#FFFFFF",
    text_faint="#8C8C8C",
    line="#FFFFFF",
    line_control="#FFFFFF",
    line_strong="#FFFFFF",
    primary="#FFD400",
    primary_hover="#FFE566",
    primary_pressed="#FFF0A3",
    on_primary="#000000",
    primary_soft="#333300",
    primary_soft_hover="#4D4D00",
    topbar="#000000",
    topbar_text="#FFFFFF",
    topbar_muted="#FFFFFF",
    topbar_active="#333333",
    attention="#FFD400",
    attention_fill="#FFD400",
    on_attention="#000000",
    danger="#FF9E94",
    success="#7CFF9E",
    success_fill="#7CFF9E",
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
    sidebar_line="#FFFFFF",
    brand="#000000",  # the mark becomes white strokes on black
    tone_neutral=("#1A1A1A", "#FFFFFF"),
    tone_info=("#00263D", "#80D8FF"),
    tone_attention=("#333300", "#FFD400"),
    tone_success=("#003312", "#7CFF9E"),
    tone_danger=("#3D0A05", "#FF9E94"),
    inverse="#FFFFFF",
    on_inverse="#000000",
    shadow="#000000",
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


def px(value: float) -> int:
    """A size in pixels at 100% text, grown with the person's text size (never shrunk below 100%)."""
    return round(value * max(1.0, current_scale()))


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


def _logical_dpi(app: QGuiApplication) -> float:
    screen = app.primaryScreen()
    dpi = screen.logicalDotsPerInch() if screen is not None else 96.0
    return dpi if dpi > 0 else 96.0


def apply_appearance(app: QApplication, appearance: Appearance) -> Palette:
    """Apply language, colors, fonts, spacing, and the stylesheet to the whole application."""
    set_language(appearance.language)
    _install_qt_translations(app, appearance.language)
    palette = PALETTES[resolve_theme(appearance.theme, app)]
    _state["palette"] = palette
    _state["scale"] = float(appearance.font_scale)
    _state["appearance"] = appearance

    app.setStyle("Fusion")  # identical look on macOS and Windows, fully themeable

    # Text is sized in pixels so every computer shows the same proportions (macOS counts
    # 72 points to the inch and Windows 96, so the same point size would differ by a third).
    size = round(BASE_TEXT_PX * appearance.font_scale, 1)
    family = interface_family()
    font = QFont(app.font())
    if family:
        font.setFamily(family)
    font.setPointSizeF(size * 72.0 / _logical_dpi(app))
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)  # true letter shapes at every size
    # WCAG 1.4.12 Text Spacing: wider letters and words help many dyslexic readers.
    font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 108 if appearance.text_spacing else 100)
    font.setWordSpacing(size * 0.45 if appearance.text_spacing else 0.0)
    app.setFont(font)

    app.setPalette(_qt_palette(palette))
    app.setStyleSheet(
        build_stylesheet(
            palette,
            size,
            _arrow_images(palette.text_muted),
            _check_image(palette.on_primary),
            sort_arrows=_arrow_images(palette.text, 10),
        )
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


def _image_folder() -> Path:
    folder = _arrow_dir.get("path")
    if folder is None:
        folder = Path(tempfile.mkdtemp(prefix="servesync-ui-"))
        _arrow_dir["path"] = folder
    return folder


def _arrow_images(color: str, size: int = 14) -> tuple[str, str]:
    """Render themed up/down chevrons to PNG files the stylesheet can reference."""
    from servesync.ui import assets  # local import: assets has no dependency on this module

    folder = _image_folder()
    down_path = folder / f"down-{color.lstrip('#')}-{size}.png"
    up_path = folder / f"up-{color.lstrip('#')}-{size}.png"
    if not down_path.exists():
        down = assets.pixmap("chevron-down", color, size)
        down.save(str(down_path))
        down.transformed(QTransform().rotate(180)).save(str(up_path))
    return up_path.as_posix(), down_path.as_posix()


def _check_image(color: str) -> str:
    """A themed check mark for check boxes (drawn by us so it is visible in every theme)."""
    return icon_file("check", color, 14)


def icon_file(name: str, color: str, size: int) -> str:
    """A recolored icon saved as a PNG, for places that take a file path (stylesheets, rich text)."""
    from servesync.ui import assets

    path = _image_folder() / f"{name}-{color.lstrip('#')}-{size}.png"
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
        QPalette.ColorRole.ToolTipBase: p.inverse,
        QPalette.ColorRole.ToolTipText: p.on_inverse,
        QPalette.ColorRole.PlaceholderText: p.text_muted,
        QPalette.ColorRole.Link: p.info,
    }
    for role, color in roles.items():
        qp.setColor(role, QColor(color))
    qp.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(p.text_muted))
    qp.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(p.text_muted))
    qp.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor(p.text_muted))
    return qp


_fonts: dict[str, str] = {"body": "", "legible": ""}


def set_font_families(body: str, legible: str) -> None:
    """Record the bundled font families (empty string = use the system font)."""
    _fonts["body"], _fonts["legible"] = body, legible


def interface_family() -> str:
    """The family for all text: Figtree, or Atkinson Hyperlegible when Easy-read font is on."""
    if current_appearance().legible_font and _fonts["legible"]:
        return _fonts["legible"]
    return _fonts["body"]


def heading_family() -> str:
    """Headings use the interface family (one typeface, several weights)."""
    return interface_family()


def ui_font(factor: float = 1.0, weight: int = 400, *, tabular: bool = False) -> QFont:
    """
    A font for custom-painted widgets: the interface family at ``factor`` times
    the body size. ``tabular`` gives every digit the same width, so numbers in
    a column line up.
    """
    font = QFont(QGuiApplication.font())
    size = font.pointSizeF()
    if size > 0:
        font.setPointSizeF(size * factor)
    font.setWeight(QFont.Weight(weight))
    if tabular:
        font.setFeature(QFont.Tag("tnum"), 1)
    return font


def build_stylesheet(
    p: Palette,
    size: float,
    arrows: tuple[str, str] = ("", ""),
    check: str = "",
    *,
    sort_arrows: tuple[str, str] = ("", ""),
) -> str:
    """Qt stylesheet built from tokens; ``size`` is the body text size in pixels and everything derives from it."""
    up_arrow, down_arrow = arrows
    sort_up, sort_down = sort_arrows
    grow = max(1.0, size / BASE_TEXT_PX)  # controls never shrink below their 100% size

    def fs(factor: float) -> str:
        return f"font-size: {max(round(size * factor), 9)}px;"

    def s(value: float) -> int:
        return round(value * grow)

    family = interface_family()
    body = f'font-family: "{family}";' if family else ""
    fw = p.focus_width
    ctl, card, tag = RADIUS_CONTROL, RADIUS_CARD, RADIUS_TAG
    target = s(MIN_TARGET)  # the area that responds to a click or tap
    height = s(CONTROL_HEIGHT)  # the part that is drawn
    gap = (target - height) // 2  # invisible margin above and below each control
    inner = height - 2  # content height inside a 1 px border
    box = s(18)
    title = f"{fs(TYPE_TITLE)} font-weight: 600;"
    section = f"{fs(TYPE_SECTION)} font-weight: 600;"
    caption = fs(TYPE_CAPTION)
    small = fs(TYPE_SMALL)
    return f"""
    QWidget {{ color: {p.text}; {body} }}
    QMainWindow {{ background: {p.window}; }}
    QDialog {{ background: {p.surface}; }}
    QDialog#Kiosk, QDialog#SignIn {{ background: {p.window}; }}
    QToolTip {{ background: {p.inverse}; color: {p.on_inverse}; border: 1px solid {p.inverse}; padding: 6px 8px;
        border-radius: {tag}px; {small} }}

    /* ---------- text roles ---------- */
    QLabel[role="title"] {{ {title} }}
    QLabel[role="display"] {{ {fs(TYPE_DISPLAY)} font-weight: 600; }}
    QLabel[role="figure"], QLabel[role="figure-attention"] {{ {fs(TYPE_FIGURE)} font-weight: 600; }}
    QLabel[role="figure-attention"] {{ color: {p.attention}; }}
    QLabel[role="section"], QLabel[role="name"] {{ {section} }}
    QLabel[role="heading"] {{ {fs(1.29)} font-weight: 600; }}
    QLabel[role="score"] {{ {section} color: {p.success}; }}
    QLabel[role="strong"] {{ font-weight: 600; }}
    QLabel[role="lead"], QLabel[role="insight"], QLabel[role="strength"] {{ color: {p.text}; }}
    QLabel[role="mission"], QLabel[role="subtitle"], QLabel[role="muted"] {{ color: {p.text_muted}; }}
    QLabel[role="figure-label"], QLabel[role="label"] {{ color: {p.text_muted}; {small} font-weight: 500; }}
    QLabel[role="eyebrow"] {{ color: {p.text_muted}; {small} font-weight: 500; }}
    QLabel[role="hint"] {{ color: {p.text_muted}; {caption} }}
    QLabel[role="error"] {{ color: {p.danger}; {small} }}
    QLabel[role="banner-error"] {{ color: {p.tone_danger[1]}; background: {p.tone_danger[0]};
        border: 1px solid {p.danger}; border-radius: {ctl}px; padding: 10px 12px; }}
    QLabel[role="notice"] {{ color: {p.tone_info[1]}; background: {p.tone_info[0]}; border-radius: {ctl}px;
        padding: 10px 12px; }}
    QLabel[role="link"] {{ color: {p.primary}; }}
    QLabel[role="concern"] {{ color: {p.danger}; }}
    QLabel[role="ok"] {{ color: {p.success}; font-weight: 600; }}
    QLabel[role="kbd"] {{ color: {p.text_muted}; background: {p.surface}; border: 1px solid {p.line_control};
        border-radius: 5px; padding: 1px 6px; {caption} font-weight: 500; }}
    QLabel[role="badge"] {{ color: {p.on_attention}; background: {p.attention_fill}; border-radius: {tag}px;
        padding: 1px 7px; {caption} font-weight: 600; }}
    QFormLayout QLabel, QLabel[role="field"] {{ {small} font-weight: 500; }}

    /* ---------- containers: a canvas, white cards, quiet insets ---------- */
    QFrame[panel="true"] {{ background: transparent; border: none; }}
    QFrame[card="true"], QFrame[tile="true"], QFrame[banner="true"], QFrame[kpi="true"] {{
        background: {p.surface}; border: 1px solid {p.line}; border-radius: {card}px; }}
    QFrame[inset="true"], QFrame[panel="true"][inset="true"] {{ background: {p.surface_alt}; border: none;
        border-radius: {ctl + 2}px; }}
    QFrame[callout="true"] {{ background: {p.primary_soft}; border: none; border-radius: {card}px; }}
    QFrame[answer="true"] {{ background: transparent; border: none; border-bottom: 1px solid {p.line};
        border-radius: 0; }}
    QFrame[divider="true"] {{ background: {p.line}; border: none; max-height: 1px; min-height: 1px; }}
    QFrame#DialogHeader {{ background: {p.surface}; border: none; border-bottom: 1px solid {p.line}; }}
    QFrame#DialogFooter {{ background: {p.surface_alt}; border: none; border-top: 1px solid {p.line}; }}
    QScrollArea {{ background: transparent; border: none; }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}
    QGroupBox {{ background: transparent; border: none; border-top: 1px solid {p.line};
        margin-top: 24px; padding: 16px 0 0 0; {section} }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 0; padding: 0; }}
    QGroupBox > QWidget {{ {fs(TYPE_BODY)} font-weight: 400; }}

    /* ---------- sidebar: deep navy, with an amber bar beside the current page ---------- */
    QWidget#Sidebar {{ background: {p.sidebar}; border-right: 1px solid {p.sidebar_line}; }}
    QWidget#Sidebar QLabel {{ color: {p.sidebar_text}; }}
    QWidget#Sidebar QLabel#OrgName, QWidget#Sidebar QLabel[role="sidebar-muted"] {{ color: {p.sidebar_muted};
        {small} }}
    QWidget#Sidebar QLabel[role="sidebar-heading"] {{ color: {p.sidebar_muted}; {caption} font-weight: 600; }}
    QWidget#Sidebar QLabel[role="sidebar-lead"] {{ color: {p.sidebar_text}; {fs(1.14)} }}
    QWidget#Sidebar QFrame[divider="true"] {{ background: {p.sidebar_line}; }}
    QWidget#TopBar {{ background: {p.topbar}; border-bottom: 1px solid {p.line}; }}
    QWidget#TopBar QLabel {{ color: {p.topbar_text}; }}
    QLabel#Brand {{ {fs(1.21)} font-weight: 700; color: {p.sidebar_text}; }}
    QWidget#NavIndicator {{ background: {p.sidebar_accent}; border-radius: 2px; }}
    QPushButton[nav="true"] {{ background: transparent; color: {p.sidebar_muted}; border: none; text-align: left;
        border-radius: {ctl}px; padding: 0px 12px; margin: 2px 0px; min-height: {target - 4}px;
        {fs(TYPE_BODY)} font-weight: 500; }}
    QPushButton[nav="true"]:hover {{ background: {p.sidebar_hover}; color: {p.sidebar_text}; }}
    QPushButton[nav="true"]:checked {{ background: {p.sidebar_active}; color: {p.sidebar_text}; font-weight: 600; }}
    QPushButton[nav="true"]:focus {{ border: {fw}px solid {p.sidebar_focus}; padding: 0px {12 - fw}px; }}
    QLabel[role="nav-badge"] {{ color: {p.on_attention}; background: {p.attention_fill}; border-radius: {s(9)}px;
        min-width: {s(8)}px; min-height: {s(18)}px; max-height: {s(18)}px; padding: 0px {s(5)}px; {caption}
        font-weight: 700; }}

    /* ---------- header: search field, the one filled button, account ---------- */
    QPushButton#CallToAction {{ background: {p.cta}; color: {p.on_cta}; border: 1px solid {p.cta};
        border-radius: {ctl}px; padding: 0px 16px; margin: {gap}px 0px; min-height: {inner}px; font-weight: 600; }}
    QPushButton#CallToAction:hover {{ background: {p.cta_hover}; border-color: {p.cta_hover}; }}
    QPushButton#CallToAction:pressed {{ background: {p.primary_pressed}; border-color: {p.primary_pressed}; }}
    QPushButton#CallToAction:focus {{ border: {fw}px solid {p.on_cta}; padding: 0px {16 - fw + 1}px;
        min-height: {inner - 2 * (fw - 1)}px; }}
    QPushButton#AskButton {{ background: {p.surface_alt}; color: {p.text_muted}; border: 1px solid {p.line};
        border-radius: {ctl}px; padding: 0px 12px; margin: {gap}px 0px; min-height: {inner}px; text-align: left; }}
    QPushButton#AskButton:hover {{ color: {p.text}; border-color: {p.line_strong}; background: {p.surface}; }}
    QPushButton#AskButton:focus {{ border: {fw}px solid {p.focus}; padding: 0px {12 - fw + 1}px;
        min-height: {inner - 2 * (fw - 1)}px; }}
    QToolButton {{ background: {p.surface}; color: {p.text}; border: 1px solid {p.line_control};
        border-radius: {ctl}px; padding: 0px 14px; margin: {gap}px 0px; min-height: {inner}px; font-weight: 500; }}
    QToolButton:hover {{ background: {p.surface_alt}; border-color: {p.line_strong}; }}
    QToolButton:focus {{ border: {fw}px solid {p.focus}; padding: 0px {14 - fw + 1}px;
        min-height: {inner - 2 * (fw - 1)}px; }}
    QToolButton::menu-indicator {{ image: none; }}
    /* The small buttons Qt puts inside fields (clear text, search) are icons, not buttons with a frame. */
    QLineEdit QToolButton, QLineEdit QToolButton:hover, QLineEdit QToolButton:focus,
    QLineEdit QToolButton:pressed {{ background: transparent; border: none; margin: 0px; padding: 0px;
        min-height: 0px; }}
    QToolButton[menu="true"] {{ padding-right: 30px; }}
    QToolButton[menu="true"]::menu-indicator {{ image: url("{down_arrow}"); subcontrol-origin: padding;
        subcontrol-position: center right; right: 10px; width: 14px; height: 14px; }}
    QToolButton#UserMenu {{ background: transparent; color: {p.topbar_text}; border: 1px solid transparent;
        border-radius: {ctl}px; padding: 0px 30px 0px 6px; margin: {gap}px 0px; min-height: {inner}px;
        font-weight: 500; }}
    QToolButton#UserMenu:hover {{ background: {p.surface_alt}; }}
    QToolButton#UserMenu:focus {{ border: {fw}px solid {p.focus}; }}
    QToolButton#UserMenu::menu-indicator {{ image: url("{down_arrow}"); subcontrol-origin: padding;
        subcontrol-position: center right; right: 8px; width: 14px; height: 14px; }}
    QToolButton#PageHelp {{ background: transparent; color: {p.text_muted}; border: 1px solid transparent;
        border-radius: {ctl}px; min-width: {target - 2}px; max-width: {target - 2}px; min-height: {inner}px;
        padding: 0px; margin: {gap}px 0px; font-weight: 600; }}
    QToolButton#PageHelp:hover {{ background: {p.surface_alt}; }}
    QToolButton#PageHelp:focus {{ border: {fw}px solid {p.focus}; }}

    /* ---------- first-run tour: a card in the corner, and an outline around what it describes ---------- */
    QFrame#TourCard {{ background: {p.surface}; border: 1px solid {p.line_control}; border-radius: {card}px; }}
    QFrame#TourOutline {{ background: transparent; border: 3px solid {p.attention_fill}; border-radius: {ctl + 2}px; }}

    /* ---------- toast ---------- */
    QFrame#Toast {{ background: {p.inverse}; border-radius: {ctl + 2}px; }}
    QFrame#Toast QLabel {{ color: {p.on_inverse}; }}
    QFrame#Toast QPushButton {{ background: transparent; color: {p.on_inverse}; border: 1px solid transparent;
        border-radius: {tag}px; min-height: 0; margin: 0; padding: 4px 8px; font-weight: 600; }}
    QFrame#Toast QPushButton:hover {{ border-color: {p.on_inverse}; }}
    QFrame#Toast QPushButton:focus {{ border: {fw}px solid {p.focus}; }}

    /* ---------- buttons: quiet by default, tonal for a section's action, one filled per screen ---------- */
    QPushButton {{ background: {p.surface}; color: {p.text}; border: 1px solid {p.line_control};
        border-radius: {ctl}px; padding: 0px 14px; margin: {gap}px 0px; min-height: {inner}px; font-weight: 500; }}
    QPushButton:hover {{ background: {p.surface_alt}; border-color: {p.line_strong}; }}
    QPushButton:pressed {{ background: {p.primary_soft}; }}
    QPushButton:focus {{ border: {fw}px solid {p.focus}; padding: 0px {14 - fw + 1}px;
        min-height: {inner - 2 * (fw - 1)}px; }}
    QPushButton:disabled {{ color: {p.text_muted}; background: {p.surface_alt}; border-color: {p.line}; }}
    QPushButton[kind="primary"] {{ background: {p.primary}; color: {p.on_primary}; border: 1px solid {p.primary};
        font-weight: 600; }}
    QPushButton[kind="primary"]:hover {{ background: {p.primary_hover}; border-color: {p.primary_hover}; }}
    QPushButton[kind="primary"]:pressed {{ background: {p.primary_pressed}; border-color: {p.primary_pressed}; }}
    QPushButton[kind="primary"]:focus {{ border: {fw}px solid {p.on_primary}; }}
    QPushButton[kind="primary"]:disabled {{ background: {p.surface_alt}; color: {p.text_muted};
        border-color: {p.line}; }}
    QPushButton[kind="secondary"] {{ background: {p.primary_soft}; color: {p.primary};
        border: 1px solid {p.primary_soft}; font-weight: 600; }}
    QPushButton[kind="secondary"]:hover {{ background: {p.primary_soft_hover}; border-color: {p.primary_soft_hover}; }}
    QPushButton[kind="secondary"]:focus {{ border: {fw}px solid {p.focus}; }}
    QPushButton[kind="secondary"]:disabled {{ background: {p.surface_alt}; color: {p.text_muted};
        border-color: {p.line}; }}
    QPushButton[kind="danger"] {{ color: {p.danger}; }}
    QPushButton[kind="danger"]:hover {{ background: {p.tone_danger[0]}; border-color: {p.danger}; }}
    QPushButton[kind="danger"]:disabled {{ color: {p.text_muted}; }}
    QPushButton[kind="ghost"] {{ background: transparent; border: 1px solid transparent; color: {p.text_muted}; }}
    QPushButton[kind="ghost"]:hover {{ background: {p.surface_alt}; color: {p.text}; }}
    QPushButton[kind="ghost"]:focus {{ border: {fw}px solid {p.focus}; }}
    QPushButton[kind="link"] {{ background: transparent; border: none; color: {p.primary}; font-weight: 500;
        padding: 2px 0; margin: 0; text-align: left; min-height: {s(24)}px; text-decoration: underline; }}
    QPushButton[kind="link"]:hover {{ color: {p.primary_hover}; background: transparent; }}
    QPushButton[kind="link"]:focus {{ border: {fw}px solid {p.focus}; padding: 0px; }}
    QPushButton[kind="chip"] {{ background: transparent; color: {p.text}; border: 1px solid transparent;
        border-radius: {ctl}px; padding: 0px 10px; margin: 0; min-height: {target - 6}px; text-align: left;
        font-weight: 400; }}
    QPushButton[kind="chip"]:hover {{ background: {p.surface_alt}; color: {p.primary}; }}
    QPushButton[kind="chip"]:focus {{ border: {fw}px solid {p.focus}; }}
    QPushButton[kind="kiosk"] {{ background: {p.surface}; color: {p.text}; border: 1px solid {p.line_control};
        border-radius: {card}px; padding: 16px 20px; margin: 0; min-height: {target + 28}px;
        {fs(TYPE_SECTION)} text-align: left; }}
    QPushButton[kind="kiosk"]:hover {{ background: {p.primary_soft}; border-color: {p.primary}; }}
    QPushButton[kind="kiosk"]:focus {{ border: {fw}px solid {p.focus}; }}
    QPushButton[kind="kiosk"]:disabled {{ color: {p.text_muted}; background: {p.surface_alt}; }}
    QLineEdit#KioskSearch {{ {fs(TYPE_SECTION)} padding: 0px 16px; min-height: {target + 8}px; }}
    QPushButton[segment="true"] {{ background: {p.surface}; color: {p.text}; border: 1px solid {p.line_control};
        border-radius: 0; padding: 0px 14px; margin: {gap}px 0px; min-height: {inner}px; font-weight: 500; }}
    QPushButton[segment="true"]:hover {{ background: {p.surface_alt}; }}
    QPushButton[segment="true"][first="true"] {{ border-top-left-radius: {ctl}px;
        border-bottom-left-radius: {ctl}px; }}
    QPushButton[segment="true"][last="true"] {{ border-top-right-radius: {ctl}px;
        border-bottom-right-radius: {ctl}px; }}
    QPushButton[segment="true"]:checked {{ background: {p.primary_soft}; color: {p.primary};
        border-color: {p.primary}; font-weight: 600; }}
    QPushButton[segment="true"]:focus {{ border: {fw}px solid {p.focus}; }}

    /* ---------- inputs (borders >= 3:1 so every field is findable) ---------- */
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QTimeEdit {{
        background: {p.surface}; color: {p.text}; border: 1px solid {p.line_strong}; border-radius: {ctl}px;
        padding: 0px 11px; margin: {gap}px 0px; min-height: {inner}px;
        selection-background-color: {p.selection}; selection-color: {p.on_selection}; }}
    QPlainTextEdit, QTextEdit {{ background: {p.surface}; color: {p.text}; border: 1px solid {p.line_strong};
        border-radius: {ctl}px; padding: 8px 10px; selection-background-color: {p.selection};
        selection-color: {p.on_selection}; }}
    QTextBrowser {{ background: {p.surface}; color: {p.text}; border: none; padding: 4px 0px;
        selection-background-color: {p.selection}; selection-color: {p.on_selection}; }}
    QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover, QDateEdit:hover, QTimeEdit:hover,
    QPlainTextEdit:hover {{ border-color: {p.text_muted}; }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus,
    QDateEdit:focus, QTimeEdit:focus {{ border: {fw}px solid {p.focus}; padding: 0px {11 - fw + 1}px;
        min-height: {inner - 2 * (fw - 1)}px; }}
    QPlainTextEdit:focus, QTextEdit:focus {{ border: {fw}px solid {p.focus}; padding: {8 - fw + 1}px {10 - fw + 1}px; }}
    QLineEdit[invalid="true"], QPlainTextEdit[invalid="true"], QComboBox[invalid="true"],
    QDateEdit[invalid="true"], QSpinBox[invalid="true"], QTimeEdit[invalid="true"],
    QDoubleSpinBox[invalid="true"], QListWidget[invalid="true"] {{ border: 2px solid {p.danger}; }}
    QLineEdit:disabled, QPlainTextEdit:disabled, QComboBox:disabled, QSpinBox:disabled,
    QDoubleSpinBox:disabled, QDateEdit:disabled, QTimeEdit:disabled {{
        background: {p.surface_alt}; color: {p.text_muted}; border-color: {p.line_control}; }}
    QComboBox::drop-down, QDateEdit::drop-down {{ subcontrol-origin: padding; subcontrol-position: center right;
        width: 28px; border: none; }}
    QComboBox::down-arrow, QDateEdit::down-arrow {{ image: url("{down_arrow}"); width: 14px; height: 14px; }}
    QSpinBox::up-button, QDoubleSpinBox::up-button, QTimeEdit::up-button, QDateEdit::up-button {{
        subcontrol-origin: border; subcontrol-position: top right; width: 24px; border: none; }}
    QSpinBox::down-button, QDoubleSpinBox::down-button, QTimeEdit::down-button, QDateEdit::down-button {{
        subcontrol-origin: border; subcontrol-position: bottom right; width: 24px; border: none; }}
    QSpinBox::up-arrow, QDoubleSpinBox::up-arrow, QTimeEdit::up-arrow, QDateEdit::up-arrow {{
        image: url("{up_arrow}"); width: 11px; height: 11px; }}
    QSpinBox::down-arrow, QDoubleSpinBox::down-arrow, QTimeEdit::down-arrow, QDateEdit::down-arrow {{
        image: url("{down_arrow}"); width: 11px; height: 11px; }}
    QComboBox QAbstractItemView {{ background: {p.surface}; color: {p.text}; border: 1px solid {p.line_control};
        border-radius: {ctl}px; padding: 4px; outline: 0; selection-background-color: {p.selection};
        selection-color: {p.on_selection}; }}
    QComboBox QAbstractItemView::item {{ min-height: {s(32)}px; padding: 0px 8px; border-radius: {tag}px;
        border: none; }}
    QComboBox QAbstractItemView::item:hover, QComboBox QAbstractItemView::item:selected {{
        background: {p.selection}; color: {p.on_selection}; }}
    QCheckBox, QRadioButton {{ spacing: 10px; min-height: {target - 12}px; }}
    QCheckBox::indicator, QRadioButton::indicator {{ width: {box}px; height: {box}px;
        border: 1px solid {p.line_strong}; background: {p.surface}; }}
    QCheckBox::indicator {{ border-radius: 5px; }}
    QRadioButton::indicator {{ border-radius: {box // 2 + 1}px; }}
    QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: {p.primary}; }}
    QCheckBox::indicator:checked {{ background: {p.primary}; border-color: {p.primary}; image: url("{check}"); }}
    QRadioButton::indicator:checked {{ background: {p.surface}; border: {max(5, box // 3)}px solid {p.primary}; }}
    QCheckBox::indicator:focus, QRadioButton::indicator:focus {{ border: {fw}px solid {p.focus}; }}
    QCheckBox:focus, QRadioButton:focus {{ color: {p.focus}; }}

    /* ---------- tables and lists: no stripes, hairline dividers, a soft tint under the pointer ---------- */
    QTableView, QListWidget {{ background: {p.surface}; border: 1px solid {p.line}; border-radius: {ctl + 2}px;
        gridline-color: {p.line}; outline: 0; selection-background-color: {p.selection};
        selection-color: {p.on_selection}; }}
    QTableView[flat="true"], QListWidget[flat="true"] {{ border: {fw}px solid transparent; border-radius: {ctl}px;
        background: transparent; }}
    QTableView:focus, QListWidget:focus {{ border: {fw}px solid {p.focus}; }}
    QTableView[flat="true"]:focus, QListWidget[flat="true"]:focus {{ border: {fw}px solid {p.focus}; }}
    QTableView[edge="true"] QHeaderView::section:first {{ padding-left: 18px; }}
    QTableView[edge="true"] QHeaderView::section:last {{ padding-right: 18px; }}
    QTableView[edge="true"] QHeaderView::section:only-one {{ padding-left: 18px; padding-right: 18px; }}
    QTableView::item {{ padding: 0px 12px; border: none; }}
    QListWidget::item {{ padding: 9px 12px; border: none; border-bottom: 1px solid {p.line}; }}
    QListWidget::item:hover {{ background: {p.surface_hover}; color: {p.text}; }}
    QListWidget::item:selected {{ background: {p.selection}; color: {p.on_selection}; }}
    QListWidget::indicator {{ width: {box}px; height: {box}px; border: 1px solid {p.line_strong};
        background: {p.surface}; border-radius: 5px; }}
    QListWidget::indicator:checked {{ background: {p.primary}; border-color: {p.primary}; image: url("{check}"); }}
    QHeaderView {{ background: transparent; border: none; }}
    QHeaderView::section {{ background: {p.surface}; color: {p.text_muted}; border: none;
        border-bottom: 1px solid {p.line}; padding: 0px 12px; min-height: {s(38)}px; {small} font-weight: 500; }}
    QHeaderView::section:hover {{ color: {p.text}; }}
    QHeaderView::up-arrow {{ image: url("{sort_up}"); width: 10px; height: 10px; subcontrol-origin: padding;
        subcontrol-position: center right; right: 6px; }}
    QHeaderView::down-arrow {{ image: url("{sort_down}"); width: 10px; height: 10px; subcontrol-origin: padding;
        subcontrol-position: center right; right: 6px; }}
    QTableCornerButton::section {{ background: {p.surface}; border: none; }}
    QTabWidget::pane {{ border: none; border-top: 1px solid {p.line}; background: transparent; top: -1px; }}
    QTabBar {{ background: transparent; }}
    QTabBar::tab {{ background: transparent; color: {p.text_muted}; padding: 0px 2px; margin: 0px 20px 0px 0px;
        min-height: {target - 4}px; border-bottom: 2px solid transparent; font-weight: 500; }}
    QTabBar::tab:selected {{ color: {p.primary}; border-bottom: 2px solid {p.primary}; font-weight: 600; }}
    QTabBar::tab:hover {{ color: {p.text}; }}
    QTabBar::tab:focus {{ color: {p.focus}; }}
    QProgressBar {{ background: {p.surface_alt}; border: none; border-radius: {s(4)}px;
        text-align: center; min-height: {s(8)}px; max-height: {s(8)}px; color: {p.text}; }}
    QProgressBar::chunk {{ background: {p.primary}; border-radius: {s(4)}px; }}
    QProgressBar[complete="true"]::chunk {{ background: {p.success_fill}; }}
    QSlider {{ min-height: {target - 12}px; }}
    QSlider::groove:horizontal {{ height: 4px; background: {p.line_control}; border-radius: 2px; }}
    QSlider::sub-page:horizontal {{ background: {p.primary}; border-radius: 2px; }}
    QSlider::handle:horizontal {{ background: {p.surface}; border: 2px solid {p.primary}; width: 16px;
        margin: -8px 0; border-radius: 10px; }}
    QSlider:focus {{ border: {fw}px solid {p.focus}; border-radius: {ctl}px; }}
    QStatusBar {{ background: {p.window}; color: {p.text_muted}; border: none; {caption} }}
    QMenuBar {{ background: {p.topbar}; color: {p.text}; border-bottom: 1px solid {p.line}; {small} }}
    QMenuBar::item {{ padding: 4px 10px; border-radius: {tag}px; background: transparent; }}
    QMenuBar::item:selected {{ background: {p.surface_alt}; }}
    QMenu {{ background: {p.surface}; color: {p.text}; border: 1px solid {p.line_control}; border-radius: {ctl}px;
        padding: 6px; }}
    QMenu::item {{ padding: 8px 28px 8px 12px; border-radius: {tag}px; }}
    QMenu::item:selected {{ background: {p.selection}; color: {p.on_selection}; }}
    QMenu::item:disabled {{ color: {p.text_muted}; {small} }}
    QMenu::separator {{ height: 1px; background: {p.line}; margin: 6px 4px; }}
    QMenu::indicator {{ width: {box}px; height: {box}px; left: 8px; border: 1px solid {p.line_strong};
        border-radius: 5px; background: {p.surface}; }}
    QMenu::indicator:checked {{ background: {p.primary}; border-color: {p.primary}; image: url("{check}"); }}
    QMenu::item:checked, QMenu::item:unchecked {{ padding-left: {box + 18}px; }}
    QSplitter::handle {{ background: transparent; }}
    QScrollBar:vertical {{ background: transparent; width: 12px; margin: 2px; }}
    QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {p.line_control}; border-radius: 4px; min-height: 36px; }}
    QScrollBar::handle:horizontal {{ background: {p.line_control}; border-radius: 4px; min-width: 36px; }}
    QScrollBar::handle:hover {{ background: {p.line_strong}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; border: none; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    QAbstractScrollArea::corner {{ background: transparent; border: none; }}
    QCalendarWidget QWidget#qt_calendar_navigationbar {{ background: {p.surface}; border: none; }}
    QCalendarWidget QToolButton {{ color: {p.text}; background: transparent; border: 1px solid transparent;
        border-radius: {ctl}px; {fs(TYPE_SECTION)} font-weight: 600; padding: 4px 10px; margin: 2px;
        min-height: {s(28)}px; }}
    QCalendarWidget QToolButton:hover {{ background: {p.surface_alt}; color: {p.text}; }}
    QCalendarWidget QToolButton::menu-indicator {{ image: none; }}
    QCalendarWidget QAbstractItemView {{ background: {p.surface}; color: {p.text}; outline: none; border: none;
        selection-background-color: {p.selection}; selection-color: {p.on_selection}; }}
    QCalendarWidget QSpinBox {{ min-height: 0; margin: 0; }}
    QMessageBox QLabel {{ {fs(TYPE_BODY)} }}
    """
