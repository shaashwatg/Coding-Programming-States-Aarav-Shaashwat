"""
Small reusable widgets and helpers shared by every screen.

Error handling lives here: :func:`guarded` wraps every button handler, so an
expected problem (a business rule, a validation error) becomes a clear message,
and an unexpected bug is logged and reported politely instead of crashing the
app in front of the judges.
"""

from __future__ import annotations

import functools
import html
import logging
from collections.abc import Callable, Sequence
from datetime import date, datetime, time
from enum import Enum
from typing import Any, Generic, ParamSpec, TypeVar

from PySide6.QtCore import QDate, QRectF, QSize, Qt, QTime
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractButton,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QMessageBox,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from servesync.core.errors import ServeSyncError, ValidationError
from servesync.core.i18n import format_clock, format_day, format_weekday_day, tr

logger = logging.getLogger(__name__)

P = ParamSpec("P")
R = TypeVar("R")
E = TypeVar("E", bound=Enum)


# ------------------------------------------------------------------- styling


def set_prop(widget: QWidget, name: str, value: object) -> None:
    """Set a dynamic property used by the stylesheet and re-apply styling."""
    widget.setProperty(name, value)
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


#: Roles that show a problem. These always get a warning icon as well as red text,
#: so an error never depends on color alone (WCAG 1.4.1).
ERROR_ROLES = ("error", "banner-error")


class ErrorLabel(QLabel):
    """
    A problem message drawn with a warning icon in front of it.

    ``text()`` still returns the plain message, so callers and screen readers
    deal with words only; the icon is added just for display.
    """

    def __init__(self, text: str = "") -> None:
        super().__init__()
        self.setTextFormat(Qt.TextFormat.RichText)
        self._message = ""
        self.setText(text)

    def setText(self, text: str) -> None:  # noqa: N802 - Qt API
        self._message = text
        if not text:
            super().setText("")
            return
        from servesync.ui.theme import current_palette, current_scale, icon_file

        size = round(16 * current_scale())
        image = icon_file("triangle-alert", current_palette().danger, size)
        body = html.escape(text).replace("\n", "<br>")
        super().setText(
            f'<table cellspacing="0" cellpadding="0"><tr><td valign="top">'
            f'<img src="{image}" width="{size}" height="{size}">&nbsp;&nbsp;</td><td>{body}</td></tr></table>'
        )
        self.setAccessibleName(text)

    def text(self) -> str:
        return self._message


def make_label(text: str = "", role: str | None = None, *, wrap: bool = False, selectable: bool = False) -> QLabel:
    label = ErrorLabel(text) if role in ERROR_ROLES else QLabel(text)
    if role:
        label.setProperty("role", role)
    label.setWordWrap(wrap)
    if selectable:
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


#: Icon color for each kind of button, as a theme token name.
_ICON_TOKENS = {"primary": "on_primary", "secondary": "primary", "danger": "danger", "link": "primary"}
ICON_NAME, ICON_TOKEN, ICON_SIZE = "icon_name", "icon_token", "icon_px"


def set_icon(button: QAbstractButton, name: str, *, token: str | None = None, size: int = 16) -> None:
    """
    Give a button an icon that follows the theme. The icon's name is remembered
    on the button, so :func:`apply_icons` can redraw it when the theme changes.
    """
    from servesync.ui.theme import px

    kind = str(button.property("kind") or "")
    button.setProperty(ICON_NAME, name)
    button.setProperty(ICON_TOKEN, token or _ICON_TOKENS.get(kind, "text_muted"))
    button.setProperty(ICON_SIZE, size)
    button.setIconSize(QSize(px(size), px(size)))
    _draw_icon(button)


#: Space between a button's icon and its label (Qt's own gap is too tight to read as deliberate).
ICON_GAP = 5


def _padded_icon(name: str, color: str, size: int, gap: int) -> QPixmap:
    """The icon with ``gap`` pixels of empty space on its right, so the label sits a clear step away."""
    from servesync.ui import assets

    ratio = 2.0
    image = QPixmap(int((size + gap) * ratio), int(size * ratio))
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    glyph = assets.pixmap(name, color, size, ratio)
    painter.drawPixmap(QRectF(0, 0, size * ratio, size * ratio), glyph, QRectF(glyph.rect()))
    painter.end()
    image.setDevicePixelRatio(ratio)
    return image


def _draw_icon(button: QAbstractButton) -> None:
    from PySide6.QtGui import QIcon

    from servesync.ui.theme import current_palette, px

    name = button.property(ICON_NAME)
    if not name:
        return
    palette = current_palette()
    color = getattr(palette, str(button.property(ICON_TOKEN)), palette.text_muted)
    size = px(int(button.property(ICON_SIZE) or 16))
    gap = ICON_GAP if button.text().strip() else 0
    icon = QIcon(_padded_icon(str(name), color, size, gap))
    icon.addPixmap(_padded_icon(str(name), palette.text_muted, size, gap), QIcon.Mode.Disabled)
    button.setIcon(icon)
    button.setIconSize(QSize(size + gap, size))


def apply_icons(root: QWidget) -> None:
    """Redraw every themed icon under ``root`` in the current theme's colors and text size."""
    for button in root.findChildren(QAbstractButton):
        if button.property(ICON_NAME):
            _draw_icon(button)


def make_button(
    text: str,
    *,
    kind: str | None = None,
    tooltip: str | None = None,
    on_click: Callable[[], object] | None = None,
    icon: str | None = None,
) -> QPushButton:
    button = QPushButton(text)
    if kind:
        button.setProperty("kind", kind)
    if tooltip:
        button.setToolTip(tooltip)
        button.setAccessibleDescription(tooltip)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    if icon:
        set_icon(button, icon)
    if on_click is not None:
        button.clicked.connect(lambda _checked=False: on_click())
    return button


def add_search_icon(field: QWidget) -> None:
    """Put a magnifying glass at the start of a search box, so its purpose is clear before reading."""
    from PySide6.QtGui import QAction
    from PySide6.QtWidgets import QLineEdit

    from servesync.ui import assets
    from servesync.ui.theme import current_palette

    if isinstance(field, QLineEdit):
        action = QAction(assets.icon("search", current_palette().text_muted, 16), "", field)
        field.addAction(action, QLineEdit.ActionPosition.LeadingPosition)


def make_menu_button(text: str, *, tooltip: str = "", icon: str | None = None) -> QToolButton:
    """A button that opens a menu (it shows a small chevron so that is clear before clicking)."""
    button = QToolButton()
    button.setText(text)
    button.setProperty("menu", True)
    button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    if tooltip:
        button.setToolTip(tooltip)
    if icon:
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        set_icon(button, icon)
    return button


class Panel(QFrame):
    """
    A section of a page. With a title it is a white card with a heading; without
    one it is an invisible container (``card=True`` or ``False`` overrides that).

    Fill ``body``. ``flush=True`` lets the content run edge to edge (tables and
    lists, whose rows carry their own inset so they line up with the heading).
    ``add_action`` puts a control at the right end of the heading row.
    """

    PAD = 20

    def __init__(
        self,
        title: str | None = None,
        parent: QWidget | None = None,
        *,
        card: bool | None = None,
        flush: bool = False,
        subtitle: str = "",
    ) -> None:
        super().__init__(parent)
        is_card = bool(title) if card is None else card
        self.setProperty("card" if is_card else "panel", True)
        pad = self.PAD if is_card else 0
        self._flush = flush and is_card
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.heading: QLabel | None = None
        self.subheading: QLabel | None = None
        self._header: QHBoxLayout | None = None
        if title:
            self._header = QHBoxLayout()
            self._header.setContentsMargins(pad, 16 if is_card else 0, pad, 12)
            self._header.setSpacing(8)
            text = QVBoxLayout()
            text.setSpacing(2)
            self.heading = make_label(title, "section", wrap=True)
            self.heading.setAccessibleName(title)
            text.addWidget(self.heading)
            self.subheading = make_label(subtitle, "muted", wrap=True)
            self.subheading.setVisible(bool(subtitle))
            text.addWidget(self.subheading)
            self._header.addLayout(text, 1)
            outer.addLayout(self._header)
        self.body = QVBoxLayout()
        top = 0 if title else pad
        if flush:
            self.body.setContentsMargins(0, top, 0, 10 if is_card else 0)
        else:
            self.body.setContentsMargins(pad, top, pad, pad)
        self.body.setSpacing(12)
        outer.addLayout(self.body, 1)

    def set_title(self, title: str) -> None:
        if self.heading is not None:
            self.heading.setText(title)
            self.heading.setAccessibleName(title)

    def set_subtitle(self, text: str) -> None:
        if self.subheading is not None:
            self.subheading.setText(text)
            self.subheading.setVisible(bool(text))

    def add_action(self, widget: QWidget) -> None:
        if self._header is not None:
            self._header.addWidget(widget, 0, Qt.AlignmentFlag.AlignVCenter)

    def add_row(self, *widgets: QWidget, stretch: bool = True, top: int = 0, bottom: int = 0) -> QHBoxLayout:
        """A row of controls (buttons, filters) inset to line up with the heading, even in a flush panel."""
        row = QHBoxLayout()
        inset = self.PAD if self._flush else 0
        row.setContentsMargins(inset, top, inset, bottom)
        row.setSpacing(8)
        for widget in widgets:
            row.addWidget(widget)
        if stretch:
            row.addStretch(1)
        self.body.addLayout(row)
        return row


class PageHeader(QWidget):
    """Title, one-line instructions, and the page's main actions on the right."""

    def __init__(self, title: str, instructions: str, actions: Sequence[QWidget] = ()) -> None:
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        text = QVBoxLayout()
        text.setSpacing(4)
        self.title = make_label(title, "title", wrap=True)
        self.title.setAccessibleName(title)
        self.instructions = make_label(instructions, "subtitle", wrap=True)
        self.instructions.setVisible(bool(instructions))
        text.addWidget(self.title)
        text.addWidget(self.instructions)
        row.addLayout(text, 1)
        row.addSpacing(16)
        for action in actions:
            row.addWidget(action, 0, Qt.AlignmentFlag.AlignTop)

    def set_title(self, title: str) -> None:
        self.title.setText(title)
        self.title.setAccessibleName(title)

    def set_instructions(self, text: str) -> None:
        self.instructions.setText(text)
        self.instructions.setVisible(bool(text))


class ImpactStrip(QWidget):
    """
    Key figures in a row, one tile each.

    ``set_figures`` takes (value, label, attention) triples; ``attention`` gives
    the tile an amber bar and an amber icon and says so to screen readers, so
    the figure that needs action stands out by shape and words, not only color.
    """

    def __init__(self, count: int, icons: Sequence[str] = ()) -> None:
        from servesync.ui.widgets.elements import StatTile

        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(16)
        self.tiles: list[StatTile] = []
        for index in range(count):
            tile = StatTile(icons[index] if index < len(icons) else "")
            row.addWidget(tile, 1)
            self.tiles.append(tile)

    def set_figures(self, figures: Sequence[tuple[str, str, bool]]) -> None:
        for (value, label, attention), tile in zip(figures, self.tiles, strict=True):
            tile.set_figure(value, label, attention)


class EnumComboBox(QComboBox, Generic[E]):
    """
    Drop-down for an enum. Qt turns string-based enum members into plain text
    when it stores them, so this stores each member's code and converts it back,
    giving callers a real enum member (or None for the optional "all" choice).
    """

    def __init__(
        self, enum_type: type[E], *, all_label: str | None = None, label: Callable[[E], str] | None = None
    ) -> None:
        super().__init__()
        self._enum = enum_type
        if all_label is not None:
            self.addItem(all_label, "")
        for member in enum_type:
            text = label(member) if label else str(getattr(member, "label", member.name))
            self.addItem(text, str(member.value))

    def value(self) -> E | None:
        code = self.currentData()
        return self._enum(code) if code not in (None, "") else None

    def set_value(self, member: E | None) -> None:
        index = self.findData("" if member is None else str(member.value))
        self.setCurrentIndex(max(index, 0))


def clear_layout(layout: QLayout) -> None:
    """Remove and delete every widget in a layout (used when rebuilding lists)."""
    while layout.count():
        item = layout.takeAt(0)
        if item is None:
            break
        widget = item.widget()
        if widget is not None:
            widget.hide()  # hide now: deletion only happens on the next event-loop pass
            widget.deleteLater()
        child = item.layout()
        if isinstance(child, QLayout):
            clear_layout(child)


# ------------------------------------------------------- Qt <-> Python dates


def to_qdate(day: date) -> QDate:
    return QDate(day.year, day.month, day.day)


def from_qdate(day: QDate) -> date:
    return date(day.year(), day.month(), day.day())


def from_qtime(moment: QTime) -> time:
    return time(moment.hour(), moment.minute())


def to_qtime(moment: time) -> QTime:
    return QTime(moment.hour, moment.minute)


# ---------------------------------------------------------------- formatting


def format_when(start: datetime, end: datetime | None = None) -> str:
    """'Sat, Nov 7, 9:00 AM – 12:00 PM' (12-hour clock, no leading zeros)."""
    text = f"{format_weekday_day(start.date())}, {_clock(start)}"
    return f"{text} \u2013 {_clock(end)}" if end else text


def format_date(day: date) -> str:
    return format_day(day)


def _clock(moment: datetime) -> str:
    return format_clock(moment)


def format_hours(hours: float) -> str:
    return f"{hours:,.1f} h" if hours % 1 else f"{hours:,.0f} h"


def format_money(amount: float) -> str:
    return f"${amount:,.0f}" if amount >= 1000 else f"${amount:,.2f}"


# ------------------------------------------------------------ user messages


def message_icon(icon_name: str, tone: str, size: int = 44) -> QPixmap:
    """The picture beside a message box's text: an icon on a tinted circle, in the theme's colors."""
    from servesync.ui import assets
    from servesync.ui.theme import current_palette

    background, foreground = current_palette().tone(tone)
    ratio = 2.0
    image = QPixmap(int(size * ratio), int(size * ratio))
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(ratio, ratio)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(background))
    painter.drawEllipse(QRectF(0, 0, size, size))
    glyph = size * 0.5
    icon = assets.pixmap(icon_name, foreground, round(glyph))
    painter.drawPixmap(QRectF((size - glyph) / 2, (size - glyph) / 2, glyph, glyph), icon, QRectF(icon.rect()))
    painter.end()
    image.setDevicePixelRatio(ratio)
    return image


def _message_box(parent: QWidget | None, title: str, text: str, icon_name: str, tone: str) -> QMessageBox:
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(f"<b>{html.escape(title)}</b>")
    box.setInformativeText(text)
    box.setIconPixmap(message_icon(icon_name, tone))
    return box


def show_error(parent: QWidget | None, error: BaseException, title: str = "") -> None:
    if isinstance(error, ValidationError):
        text = "\n".join(f"• {message}" for message in error.errors.values())
    elif isinstance(error, ServeSyncError):
        text = error.message
    else:
        logger.exception("Unexpected error in the interface", exc_info=error)
        text = tr("Something unexpected went wrong. Your data is safe; details were saved to the log file.")
    QMessageBox.warning(parent, title or tr("Can't do that yet"), text)


def inform(parent: QWidget | None, title: str, text: str) -> None:
    QMessageBox.information(parent, title, text)


def confirm(parent: QWidget | None, title: str, text: str, accept_text: str) -> bool:
    """Ask before doing something significant; the safe choice is the default."""
    box = _message_box(parent, title, text, "help", "info")
    yes = box.addButton(accept_text, QMessageBox.ButtonRole.AcceptRole)
    no = box.addButton(tr("Go back"), QMessageBox.ButtonRole.RejectRole)
    yes.setProperty("kind", "primary")
    box.setDefaultButton(no)
    box.setEscapeButton(no)
    box.exec()
    return box.clickedButton() is yes


def guarded(handler: Callable[P, R]) -> Callable[P, R | None]:
    """
    Decorator for UI actions: shows friendly messages instead of crashing.

    The first argument of the wrapped method must be a QWidget (``self``),
    which becomes the parent of any message box.
    """

    @functools.wraps(handler)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R | None:
        parent = args[0] if args and isinstance(args[0], QWidget) else None
        try:
            return handler(*args, **kwargs)
        except ServeSyncError as error:
            show_error(parent, error)
        except Exception as error:  # last line of defense for the live demo
            logger.exception("Unexpected error in %s", handler.__qualname__)
            show_error(parent, error, tr("Something went wrong"))
        finally:
            while QGuiApplication.overrideCursor() is not None:
                QGuiApplication.restoreOverrideCursor()
        return None

    return wrapper


class BusyCursor:
    """``with BusyCursor():`` shows a wait cursor during slow work (e.g. password hashing)."""

    def __enter__(self) -> BusyCursor:
        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        return self

    def __exit__(self, *_exc: Any) -> None:
        QGuiApplication.restoreOverrideCursor()
