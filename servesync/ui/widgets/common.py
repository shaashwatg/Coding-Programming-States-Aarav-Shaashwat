"""
Small reusable widgets and helpers shared by every screen.

Error handling lives here: :func:`guarded` wraps every button handler, so an
expected problem (a business rule, a validation error) becomes a clear message,
and an unexpected bug is logged and reported politely instead of crashing the
app in front of the judges.
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable, Sequence
from datetime import date, datetime, time
from enum import Enum
from typing import Any, Generic, ParamSpec, TypeVar

from PySide6.QtCore import QDate, Qt, QTime
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
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


def make_label(text: str = "", role: str | None = None, *, wrap: bool = False, selectable: bool = False) -> QLabel:
    label = QLabel(text)
    if role:
        label.setProperty("role", role)
    label.setWordWrap(wrap)
    if selectable:
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


def make_button(
    text: str,
    *,
    kind: str | None = None,
    tooltip: str | None = None,
    on_click: Callable[[], object] | None = None,
) -> QPushButton:
    button = QPushButton(text)
    if kind:
        button.setProperty("kind", kind)
    if tooltip:
        button.setToolTip(tooltip)
        button.setAccessibleDescription(tooltip)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    if on_click is not None:
        button.clicked.connect(lambda _checked=False: on_click())
    return button


class Panel(QFrame):
    """A bordered surface with an optional section title."""

    def __init__(self, title: str | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("panel", True)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(16, 14, 16, 16)
        self.body.setSpacing(10)
        if title:
            heading = make_label(title, "section")
            heading.setAccessibleName(title)
            self.body.addWidget(heading)


class PageHeader(QWidget):
    """Title, one-line instructions, and the page's main actions on the right."""

    def __init__(self, title: str, instructions: str, actions: Sequence[QWidget] = ()) -> None:
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 4)
        text = QVBoxLayout()
        text.setSpacing(2)
        self.title = make_label(title, "title")
        self.title.setAccessibleName(title)
        self.instructions = make_label(instructions, "subtitle", wrap=True)
        text.addWidget(self.title)
        text.addWidget(self.instructions)
        row.addLayout(text, 1)
        for action in actions:
            row.addWidget(action, 0, Qt.AlignmentFlag.AlignBottom)

    def set_title(self, title: str) -> None:
        self.title.setText(title)
        self.title.setAccessibleName(title)


class ImpactStrip(QFrame):
    """
    Key figures in one quiet band separated by thin rules.

    ``set_figures`` takes (value, label, attention) triples; ``attention``
    colors the number marigold when it calls for action.
    """

    def __init__(self, count: int) -> None:
        super().__init__()
        self.setProperty("strip", True)
        row = QHBoxLayout(self)
        row.setContentsMargins(20, 14, 20, 14)
        row.setSpacing(20)
        self._values: list[QLabel] = []
        self._labels: list[QLabel] = []
        for index in range(count):
            if index:
                rule = QFrame()
                rule.setProperty("rule", True)
                row.addWidget(rule)
            cell = QVBoxLayout()
            cell.setSpacing(0)
            value = make_label("-", "figure")
            label = make_label("", "figure-label", wrap=True)
            cell.addWidget(value)
            cell.addWidget(label)
            row.addLayout(cell, 1)
            self._values.append(value)
            self._labels.append(label)

    def set_figures(self, figures: Sequence[tuple[str, str, bool]]) -> None:
        for (value, label, attention), value_label, text_label in zip(figures, self._values, self._labels, strict=True):
            value_label.setText(value)
            text_label.setText(label)
            set_prop(value_label, "role", "figure-attention" if attention else "figure")
            value_label.setAccessibleName(f"{label}: {value}")


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


def clear_layout(layout: QVBoxLayout | QHBoxLayout) -> None:
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
        if isinstance(child, (QVBoxLayout, QHBoxLayout)):
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


def show_error(parent: QWidget | None, error: BaseException, title: str = "") -> None:
    if isinstance(error, ValidationError):
        text = "\n".join(f"• {message}" for message in error.errors.values())
    elif isinstance(error, ServeSyncError):
        text = error.message
    else:
        text = tr("Something unexpected went wrong. Your data is safe; details were saved to the log file.")
    QMessageBox.warning(parent, title or tr("Can't do that yet"), text)


def inform(parent: QWidget | None, title: str, text: str) -> None:
    QMessageBox.information(parent, title, text)


def confirm(parent: QWidget | None, title: str, text: str, accept_text: str) -> bool:
    """Ask before doing something significant; the safe choice is the default."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle(title)
    box.setText(text)
    yes = box.addButton(accept_text, QMessageBox.ButtonRole.AcceptRole)
    no = box.addButton(tr("Go back"), QMessageBox.ButtonRole.RejectRole)
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
