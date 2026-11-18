"""
Small custom-drawn building blocks used on every screen.

Qt's stock widgets cover buttons and fields; these cover the things that make
records easy to scan:

* :class:`Avatar`: a person's initials in a tinted circle, so a roster reads
  as people rather than rows of text.
* :class:`Tag`: a status in words on a tinted background ("Active",
  "Applicant", "No-show"). The tint helps scanning; the word carries the
  meaning, so nothing depends on color alone (WCAG 1.4.1).
* :class:`SpotMeter`: how full a shift is, one segment per spot.
* :class:`ScoreRing`: a Smart Match score drawn as part of a circle.
* :class:`IconBadge`: an icon on a tinted square, used to head a figure or row.
* :class:`StatTile`: one key figure.
* :class:`FactList`: label and value pairs, such as a profile's contact details.
* :class:`EmptyState`: what to show (and do) when a list has nothing in it.

The same drawing functions (``paint_tag``, ``paint_avatar``, ``paint_meter``)
are used by table cells, so a status looks identical in a table and a card.
Colors come from the theme by meaning; nothing here names a color.
"""

from __future__ import annotations

import zlib
from collections.abc import Sequence
from enum import Enum

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from servesync.core.i18n import tr
from servesync.models import AssignmentStatus, OpportunityStatus, VolunteerStatus
from servesync.ui import assets
from servesync.ui.theme import RADIUS_TAG, Palette, Tone, current_palette, px, ui_font

#: Tone names understood by :meth:`Palette.tone`.
NEUTRAL, INFO, ATTENTION, SUCCESS, DANGER = "neutral", "info", "attention", "success", "danger"
#: Only for :class:`IconBadge`: a white tile, for badges that sit on a tinted background.
PLAIN = "plain"

_STATUS_TONES: dict[Enum, str] = {
    VolunteerStatus.ACTIVE: SUCCESS,
    VolunteerStatus.APPLICANT: ATTENTION,
    VolunteerStatus.INACTIVE: NEUTRAL,
    OpportunityStatus.OPEN: SUCCESS,
    OpportunityStatus.DRAFT: ATTENTION,
    OpportunityStatus.CLOSED: NEUTRAL,
    AssignmentStatus.SCHEDULED: INFO,
    AssignmentStatus.ATTENDED: SUCCESS,
    AssignmentStatus.NO_SHOW: DANGER,
    AssignmentStatus.CANCELLED: NEUTRAL,
}


def status_tone(status: Enum | None) -> str:
    """The tone that goes with a record's status (unknown statuses are neutral)."""
    return _STATUS_TONES.get(status, NEUTRAL) if status is not None else NEUTRAL


# ------------------------------------------------------------------ painting


def initials(name: str) -> str:
    """'Priya Patel' -> 'PP'; 'Cher' -> 'C'; '' -> '?'."""
    parts = [part for part in name.replace(",", " ").split() if part and part[0].isalnum()]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][0].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def avatar_tone(name: str, palette: Palette | None = None) -> Tone:
    """The same person always gets the same tint (a stable hash of their name)."""
    tones = (palette or current_palette()).avatar_tones
    return tones[zlib.crc32(name.casefold().encode("utf-8")) % len(tones)]


def paint_avatar(painter: QPainter, rect: QRectF, name: str, palette: Palette | None = None) -> None:
    """Draw ``name``'s initials in a tinted circle that fills ``rect``."""
    background, foreground = avatar_tone(name, palette)
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(background))
    painter.drawEllipse(rect)
    font = ui_font(1.0, 600)
    font.setPixelSize(max(round(rect.height() * 0.38), 8))
    painter.setFont(font)
    painter.setPen(QColor(foreground))
    painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, initials(name))
    painter.restore()


def avatar_pixmap(name: str, size: int = 28, ratio: float = 2.0) -> QPixmap:
    """An avatar as a picture, for places that take an icon (list rows, the account button)."""
    image = QPixmap(int(size * ratio), int(size * ratio))
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.scale(ratio, ratio)
    paint_avatar(painter, QRectF(0, 0, size, size), name)
    painter.end()
    image.setDevicePixelRatio(ratio)
    return image


def avatar_icon(name: str, size: int = 28) -> QIcon:
    return QIcon(avatar_pixmap(name, size))


def tag_font() -> QFont:
    return ui_font(0.86, 600)


def tag_size(text: str, *, dot: bool = True) -> QSize:
    """How much room :func:`paint_tag` needs for ``text``."""
    metrics = QFontMetricsF(tag_font())
    width = metrics.horizontalAdvance(text) + px(16) + (px(11) if dot else 0)
    return QSize(round(width), round(metrics.height() + px(6)))


def paint_tag(
    painter: QPainter, rect: QRectF, text: str, tone: str, *, dot: bool = True, palette: Palette | None = None
) -> None:
    """Draw a status tag (tinted rounded rectangle, optional dot, the word) inside ``rect``."""
    background, foreground = (palette or current_palette()).tone(tone)
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(background))
    painter.drawRoundedRect(rect, RADIUS_TAG, RADIUS_TAG)
    left = rect.left() + px(8)
    if dot:
        radius = px(3)
        painter.setBrush(QColor(foreground))
        painter.drawEllipse(QPointF(left + radius, rect.center().y()), radius, radius)
        left += px(11)
    painter.setFont(tag_font())
    painter.setPen(QColor(foreground))
    painter.drawText(
        QRectF(left, rect.top(), rect.right() - left - px(6), rect.height()),
        Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
        text,
    )
    painter.restore()


#: Up to this many spots, a meter shows one segment per spot; beyond it, a continuous bar.
METER_MAX_SEGMENTS = 12


def paint_meter(painter: QPainter, rect: QRectF, filled: int, capacity: int, *, palette: Palette | None = None) -> None:
    """Draw how full something is: ``filled`` of ``capacity``, emerald once it is full."""
    palette = palette or current_palette()
    capacity = max(capacity, 1)
    filled = max(0, min(filled, capacity))
    done = QColor(palette.success_fill if filled >= capacity else palette.primary)
    empty = QColor(palette.line_control)
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    radius = min(rect.height() / 2, 4.0)
    if capacity <= METER_MAX_SEGMENTS:
        gap = 3.0
        width = (rect.width() - gap * (capacity - 1)) / capacity
        for index in range(capacity):
            painter.setBrush(done if index < filled else empty)
            painter.drawRoundedRect(
                QRectF(rect.left() + index * (width + gap), rect.top(), width, rect.height()), radius, radius
            )
    else:
        painter.setBrush(empty)
        painter.drawRoundedRect(rect, radius, radius)
        if filled:
            painter.setBrush(done)
            painter.drawRoundedRect(
                QRectF(rect.left(), rect.top(), max(rect.width() * filled / capacity, rect.height()), rect.height()),
                radius,
                radius,
            )
    painter.restore()


def add_shadow(widget: QWidget, *, blur: int = 32, offset: int = 10, opacity: float = 0.18) -> None:
    """Give a *floating* widget (a message, the tour card) a soft shadow. Cards on the page stay flat."""
    effect = QGraphicsDropShadowEffect(widget)
    color = QColor(current_palette().shadow)
    color.setAlphaF(opacity)
    effect.setColor(color)
    effect.setBlurRadius(blur)
    effect.setOffset(0, offset)
    widget.setGraphicsEffect(effect)


# ------------------------------------------------------------------- widgets


class Avatar(QWidget):
    """A person's initials in a tinted circle."""

    def __init__(self, name: str = "", size: int = 36) -> None:
        super().__init__()
        self._name = name
        self._size = size
        self.setFixedSize(px(size), px(size))
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def set_name(self, name: str) -> None:
        self._name = name
        self.update()

    def paintEvent(self, _event: object) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        paint_avatar(painter, QRectF(self.rect()), self._name)
        painter.end()


class Tag(QWidget):
    """A status in words on a tinted background. ``tone`` is one of the tone names above."""

    def __init__(self, text: str = "", tone: str = NEUTRAL, *, dot: bool = True) -> None:
        super().__init__()
        self._text, self._tone, self._dot = text, tone, dot
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.set_tag(text, tone)

    def set_tag(self, text: str, tone: str | None = None) -> None:
        self._text = text
        if tone is not None:
            self._tone = tone
        self.setAccessibleName(text)
        self.setVisible(bool(text))
        self.updateGeometry()
        self.update()

    def text(self) -> str:
        return self._text

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API
        return tag_size(self._text, dot=self._dot)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt API
        return self.sizeHint()

    def paintEvent(self, _event: object) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        paint_tag(painter, QRectF(self.rect()), self._text, self._tone, dot=self._dot)
        painter.end()


class SpotMeter(QWidget):
    """How full a shift is: one segment per spot, with the count in words beside it."""

    def __init__(self, *, show_text: bool = True, bar_width: int = 120) -> None:
        super().__init__()
        self._filled, self._capacity = 0, 1
        self._show_text = show_text
        self._bar_width = bar_width
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setAccessibleName(tr("Spots filled"))

    def set_spots(self, filled: int, capacity: int) -> None:
        self._filled, self._capacity = filled, max(capacity, 1)
        self.setAccessibleDescription(self._text())
        self.updateGeometry()
        self.update()

    def _text(self) -> str:
        return tr("{filled} of {capacity} filled", filled=self._filled, capacity=self._capacity)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API
        metrics = QFontMetricsF(ui_font(0.93, 500, tabular=True))
        text = metrics.horizontalAdvance(self._text()) + px(10) if self._show_text else 0
        return QSize(round(px(self._bar_width) + text), round(max(metrics.height(), px(10))))

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt API
        return self.sizeHint()

    def paintEvent(self, _event: object) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        height = px(8)
        bar = QRectF(0, (self.height() - height) / 2, px(self._bar_width), height)
        paint_meter(painter, bar, self._filled, self._capacity)
        if self._show_text:
            painter.setFont(ui_font(0.93, 500, tabular=True))
            painter.setPen(QColor(current_palette().text_muted))
            painter.drawText(
                QRectF(bar.right() + px(10), 0, self.width() - bar.right() - px(10), self.height()),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                self._text(),
            )
        painter.end()


class ScoreRing(QWidget):
    """A score out of 100 as part of a circle, with the number in the middle."""

    def __init__(self, score: int = 0, size: int = 48) -> None:
        super().__init__()
        self._score = score
        self.setFixedSize(px(size), px(size))
        self.set_score(score)

    def set_score(self, score: int) -> None:
        self._score = max(0, min(int(score), 100))
        self.setAccessibleName(tr("Match score {score} out of 100", score=self._score))
        self.setToolTip(tr("Match score out of 100"))
        self.update()

    def paintEvent(self, _event: object) -> None:  # noqa: N802 - Qt API
        palette = current_palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        stroke = max(self.width() * 0.09, 3.0)
        rect = QRectF(self.rect()).adjusted(stroke / 2 + 1, stroke / 2 + 1, -stroke / 2 - 1, -stroke / 2 - 1)
        painter.setPen(QPen(QColor(palette.line_control), stroke))
        painter.drawEllipse(rect)
        if self._score:
            pen = QPen(QColor(palette.success_fill), stroke)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawArc(rect, 90 * 16, round(-360 * 16 * self._score / 100))
        font = ui_font(1.0, 700, tabular=True)
        font.setPixelSize(max(round(self.height() * 0.32), 9))
        painter.setFont(font)
        painter.setPen(QColor(palette.text))
        painter.drawText(QRectF(self.rect()), Qt.AlignmentFlag.AlignCenter, str(self._score))
        painter.end()


class IconBadge(QLabel):
    """An icon centered on a tinted, rounded square."""

    def __init__(self, icon_name: str, tone: str = INFO, size: int = 32) -> None:
        super().__init__()
        self._icon_name, self._tone, self._size = icon_name, tone, size
        self.setFixedSize(px(size), px(size))
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def set_icon(self, icon_name: str, tone: str | None = None) -> None:
        self._icon_name = icon_name
        if tone is not None:
            self._tone = tone
        self.update()

    def paintEvent(self, _event: object) -> None:  # noqa: N802 - Qt API
        palette = current_palette()
        if self._tone == PLAIN:  # for use on a tinted background: a white tile with a blue icon
            background, foreground = palette.surface, palette.primary
        else:
            background, foreground = palette.tone(self._tone)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(background))
        radius = self.width() * 0.28
        painter.drawRoundedRect(QRectF(self.rect()), radius, radius)
        glyph = round(self.width() * 0.52)
        icon = assets.pixmap(self._icon_name, foreground, glyph)
        offset = (self.width() - glyph) / 2
        painter.drawPixmap(QRectF(offset, offset, glyph, glyph), icon, QRectF(icon.rect()))
        painter.end()


class Dot(QWidget):
    """A small filled circle in a theme color (a marker beside a line of text)."""

    def __init__(self, token: str = "attention_fill", size: int = 8) -> None:
        super().__init__()
        self._token = token
        self.setFixedSize(px(size), px(size))

    def paintEvent(self, _event: object) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(getattr(current_palette(), self._token)))
        painter.drawEllipse(QRectF(self.rect()))
        painter.end()


class Glyph(QWidget):
    """An icon drawn in a theme color; it follows the theme without being rebuilt."""

    def __init__(self, icon_name: str, token: str = "text_muted", size: int = 16) -> None:
        super().__init__()
        self._icon_name, self._token = icon_name, token
        self.setFixedSize(px(size), px(size))
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def set_icon(self, icon_name: str, token: str | None = None) -> None:
        self._icon_name = icon_name
        if token is not None:
            self._token = token
        self.update()

    def paintEvent(self, _event: object) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        image = assets.pixmap(self._icon_name, getattr(current_palette(), self._token), self.width())
        painter.drawPixmap(QRectF(self.rect()), image, QRectF(image.rect()))
        painter.end()


def divider() -> QFrame:
    line = QFrame()
    line.setProperty("divider", True)
    line.setFixedHeight(1)
    return line


class StatTile(QFrame):
    """
    One key figure: the number, what it counts, and an icon.

    A figure that needs action gets an amber bar down its left edge and an amber
    icon, and says "needs attention" to screen readers, so it stands out by
    shape and words as well as color.
    """

    def __init__(self, icon_name: str = "", tone: str = INFO) -> None:
        super().__init__()
        self.setProperty("kpi", True)
        self._attention = False
        self._tone = tone
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 16, 16, 16)
        layout.setSpacing(12)
        text = QVBoxLayout()
        text.setSpacing(2)
        self.value = QLabel("-")
        self.value.setProperty("role", "figure")
        self.label = QLabel("")
        self.label.setProperty("role", "figure-label")
        self.label.setWordWrap(True)
        self.note = QLabel("")
        self.note.setProperty("role", "hint")
        self.note.setWordWrap(True)
        self.note.hide()
        text.addWidget(self.value)
        text.addWidget(self.label)
        text.addWidget(self.note)
        text.addStretch(1)
        layout.addLayout(text, 1)
        self.badge = IconBadge(icon_name or "activity", tone, 36)
        self.badge.setVisible(bool(icon_name))
        layout.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignTop)

    def set_figure(self, value: str, label: str, attention: bool = False, note: str = "") -> None:
        from servesync.ui.widgets.common import set_prop  # local: common imports this module

        self.value.setText(value)
        self.label.setText(label)
        self.note.setText(note)
        self.note.setVisible(bool(note))
        self._attention = attention
        set_prop(self, "attention", attention)
        set_prop(self.value, "role", "figure-attention" if attention else "figure")
        self.badge.set_icon(self.badge._icon_name, ATTENTION if attention else self._tone)
        spoken = f"{label}: {value}" + (f", {note}" if note else "")
        self.value.setAccessibleName(
            tr("{label}: {value} (needs attention)", label=label, value=value) if attention else spoken
        )
        self.setAccessibleName(spoken)
        self.update()

    def paintEvent(self, event: object) -> None:  # noqa: N802 - Qt API
        super().paintEvent(event)  # type: ignore[arg-type]
        if not self._attention:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(current_palette().attention_fill))
        painter.drawRoundedRect(QRectF(7, 16, 4, self.height() - 32), 2, 2)
        painter.end()


class TagFlow(QWidget):
    """A run of small tags that wraps onto as many lines as it needs (skills, access needs)."""

    def __init__(self, tone: str = NEUTRAL) -> None:
        super().__init__()
        self._tags: list[str] = []
        self._tone = tone
        policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def set_tags(self, tags: Sequence[str]) -> None:
        self._tags = [tag for tag in tags if tag]
        self.setAccessibleName(", ".join(self._tags))
        self.updateGeometry()
        self.update()

    def _place(self, width: int) -> tuple[list[tuple[QRectF, str]], int]:
        gap = px(6)
        x, y, row_height = 0.0, 0.0, 0.0
        placed: list[tuple[QRectF, str]] = []
        for tag in self._tags:
            size = tag_size(tag, dot=False)
            if x > 0 and x + size.width() > width:
                x, y = 0.0, y + row_height + gap
            placed.append((QRectF(x, y, size.width(), size.height()), tag))
            x += size.width() + gap
            row_height = max(row_height, size.height())
        return placed, round(y + row_height)

    def hasHeightForWidth(self) -> bool:  # noqa: N802 - Qt API
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 - Qt API
        return self._place(max(width, 1))[1]

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API
        width = self.width() if self.width() > 0 else px(240)
        return QSize(width, self.heightForWidth(width))

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt API
        return QSize(px(80), self.heightForWidth(max(self.width(), px(80))))

    def resizeEvent(self, event: object) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)  # type: ignore[arg-type]
        self.updateGeometry()

    def paintEvent(self, _event: object) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        for rect, tag in self._place(self.width())[0]:
            paint_tag(painter, rect, tag, self._tone, dot=False)
        painter.end()


class FactList(QWidget):
    """Label and value pairs in two aligned columns (a profile's details, a shift's facts)."""

    def __init__(self, *, label_width: int = 0) -> None:
        super().__init__()
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(16)
        self._grid.setVerticalSpacing(10)
        self._grid.setColumnStretch(1, 1)
        if label_width:
            self._grid.setColumnMinimumWidth(0, px(label_width))
        self._facts: list[tuple[str, str]] = []

    def set_facts(self, facts: Sequence[tuple[str, str | Sequence[str]]]) -> None:
        """
        ``facts``: (label, value) pairs; pairs with an empty value are left out.
        A value that is a list of words is drawn as a run of tags.
        """
        from servesync.ui.widgets.common import clear_layout

        clear_layout(self._grid)
        self._facts = []
        row = 0
        for label, value in facts:
            if not value:
                continue
            name = QLabel(label)
            name.setProperty("role", "label")
            name.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
            self._grid.addWidget(name, row, 0)
            if isinstance(value, str):
                text = QLabel(value)
                text.setWordWrap(True)
                text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                text.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
                text.setAccessibleName(f"{label}: {value}")
                self._grid.addWidget(text, row, 1)
                self._facts.append((label, value))
            else:
                flow = TagFlow()
                flow.set_tags(value)
                flow.setAccessibleName(f"{label}: {', '.join(value)}")
                self._grid.addWidget(flow, row, 1)
                self._facts.append((label, ", ".join(value)))
            row += 1

    def text(self) -> str:
        """Everything shown, one 'Label: value' per line (for tests and screen readers)."""
        return "\n".join(f"{label}: {value}" for label, value in self._facts)


class EmptyState(QWidget):
    """What to show when a list has nothing in it: an icon and a sentence saying what to do."""

    def __init__(self, message: str, icon_name: str = "inbox") -> None:
        super().__init__()
        column = QVBoxLayout(self)
        column.setContentsMargins(24, 24, 24, 24)
        column.setSpacing(12)
        column.addStretch(1)
        badge = IconBadge(icon_name, NEUTRAL, 44)
        column.addWidget(badge, 0, Qt.AlignmentFlag.AlignHCenter)
        self.label = QLabel(message)
        self.label.setProperty("role", "muted")
        self.label.setWordWrap(True)
        self.label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        column.addWidget(self.label)
        column.addStretch(1)

    def setText(self, message: str) -> None:  # noqa: N802 - mirrors QLabel
        self.label.setText(message)

    def text(self) -> str:
        return self.label.text()


def rounded_clip(rect: QRectF, radius: float) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    return path
