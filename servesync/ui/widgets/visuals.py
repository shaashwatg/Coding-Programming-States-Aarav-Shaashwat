"""
Distinctive visual components.

* :class:`ScoreAnatomyBar`: the signature element. A Smart Match score drawn
  as five colored segments, one per factor, so the algorithm explains itself.
* :class:`MatchCard`: a recommendation with its bar, reasons, and an action.
* :class:`ProgramArt`: the organization's own program photo, or consistent
  category artwork when no photo has been added.
* :class:`FeaturedBanner`: the "Happening next" spotlight (one event, never a carousel).
* :class:`Callout`: the quiet section at the bottom of a home screen.
* :class:`ActivityFeed`: the newest sign-ups, service, and applications.
* :class:`ShiftCalendar`: a month calendar that marks days with shifts.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Sequence
from datetime import date, datetime

from PySide6.QtCore import QDate, QPointF, QRect, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QFont,
    QHideEvent,
    QIcon,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QPixmap,
    QShowEvent,
    QTextCharFormat,
    QTransform,
)
from PySide6.QtWidgets import (
    QCalendarWidget,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from servesync.core.i18n import format_day_short, mark, tr, tr_n
from servesync.models import ActivityItem, ActivityKind, OpportunityCategory, ShiftOverview
from servesync.services import ScoreFactor
from servesync.ui import assets
from servesync.ui.theme import current_palette, motion_allowed
from servesync.ui.widgets.common import clear_layout, format_hours, format_when, make_button, make_label


class ScoreAnatomyBar(QWidget):
    """Horizontal bar: each factor's earned points as a colored segment, out of 100."""

    def __init__(self, factors: Sequence[ScoreFactor] = ()) -> None:
        super().__init__()
        self._factors: list[ScoreFactor] = list(factors)
        self.setMinimumHeight(12)
        self.setMaximumHeight(14)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._describe()

    def set_factors(self, factors: Sequence[ScoreFactor]) -> None:
        self._factors = list(factors)
        self._describe()
        self.update()

    def _describe(self) -> None:
        lines = [
            tr("{name}: {points:.0f} of {max_points:.0f}", name=f.name, points=f.points, max_points=f.max_points)
            for f in self._factors
        ]
        self.setToolTip("\n".join(lines))
        self.setAccessibleName(tr("Score breakdown"))
        self.setAccessibleDescription("; ".join(lines))

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API
        return QSize(240, 12)

    def paintEvent(self, _event: object) -> None:  # noqa: N802 - Qt API
        palette = current_palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        clip = QPainterPath()
        clip.addRoundedRect(rect, 5, 5)
        painter.setClipPath(clip)
        painter.fillRect(rect, QColor(palette.line))  # the empty part of the bar, visible on a gray card
        available = sum(f.max_points for f in self._factors) or 1.0
        x = rect.left()
        for factor, color in zip(self._factors, palette.factors, strict=False):
            width = rect.width() * factor.points / available
            painter.fillRect(QRectF(x, rect.top(), width, rect.height()), QColor(color))
            x += width
            if width > 2:  # thin separator keeps adjacent segments distinct
                painter.fillRect(QRectF(x - 1, rect.top(), 1, rect.height()), QColor(palette.surface))
        painter.setClipping(False)
        painter.setPen(QColor(palette.line))
        painter.drawPath(clip)
        painter.end()


class FactorLegend(QWidget):
    """Small key explaining the five colors of the score bar."""

    NAMES = (mark("Availability"), mark("Skills"), mark("Reliability"), mark("Experience"), mark("Fair share"))

    def __init__(self) -> None:
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        for name, color in zip(self.NAMES, current_palette().factors, strict=True):
            swatch = QLabel()
            swatch.setFixedSize(12, 12)
            swatch.setStyleSheet(f"background: {color}; border-radius: 2px;")
            row.addWidget(swatch)
            row.addWidget(make_label(tr(name), "hint"))
        row.addStretch(1)


class MatchCard(QFrame):
    """One recommendation: who or what, the score, why, and an action button."""

    def __init__(
        self,
        *,
        title: str,
        subtitle: str,
        score: int,
        factors: Sequence[ScoreFactor],
        action_text: str,
        on_action: Callable[[], object],
        access_notes: Sequence[str] = (),
    ) -> None:
        super().__init__()
        self.setProperty("card", True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        top = QHBoxLayout()
        names = QVBoxLayout()
        names.setSpacing(0)
        names.addWidget(make_label(title, "name"))
        if subtitle:
            names.addWidget(make_label(subtitle, "muted"))
        top.addLayout(names, 1)
        score_label = make_label(f"{score}", "score")
        score_label.setAccessibleName(tr("Match score {score} out of 100", score=score))
        score_label.setToolTip(tr("Match score out of 100"))
        top.addWidget(score_label, 0, Qt.AlignmentFlag.AlignTop)
        # Outlined: a list of cards would otherwise put several filled buttons on one screen.
        action = make_button(action_text, kind="secondary", on_click=on_action)
        action.setAccessibleName(f"{action_text}: {title}")
        top.addWidget(action, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(top)

        layout.addWidget(ScoreAnatomyBar(factors))
        for factor in factors:
            if factor.points <= 0 and not factor.is_concern:
                continue
            prefix = "!" if factor.is_concern else "✓"
            line = make_label(
                f"{prefix}  {factor.explanation}", "concern" if factor.is_concern else "strength", wrap=True
            )
            line.setAccessibleName((tr("Concern: ") if factor.is_concern else tr("Strength: ")) + factor.explanation)
            layout.addWidget(line)
        for note in access_notes:
            line = make_label(tr("!  {note}. Check before confirming.", note=note), "concern", wrap=True)
            line.setAccessibleName(tr("Access note: {note}", note=note))
            layout.addWidget(line)


class ProgramArt(QLabel):
    """Shows a program's own photo, or category artwork in the same frame when there is none."""

    def __init__(self, width: int = 220, height: int = 140) -> None:
        super().__init__()
        self._size = QSize(width, height)
        self.setFixedSize(self._size)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def show_program(self, category: OpportunityCategory, photo: bytes | None, title: str) -> None:
        ratio = 2.0
        canvas = QPixmap(int(self._size.width() * ratio), int(self._size.height() * ratio))
        canvas.setDevicePixelRatio(ratio)
        canvas.fill(Qt.GlobalColor.transparent)
        painter = QPainter(canvas)
        try:
            self._paint(painter, category, photo, title, ratio)
        finally:
            painter.end()
        self.setPixmap(canvas)

    def _paint(
        self, painter: QPainter, category: OpportunityCategory, photo: bytes | None, title: str, ratio: float
    ) -> None:
        palette = current_palette()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        frame = QRectF(0, 0, self._size.width(), self._size.height())
        path = QPainterPath()
        path.addRoundedRect(frame, 6, 6)
        painter.setClipPath(path)

        image = QPixmap()
        if photo and image.loadFromData(photo):
            scaled = image.scaled(
                self._size * ratio,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            scaled.setDevicePixelRatio(ratio)
            x = (scaled.width() / ratio - frame.width()) / 2
            y = (scaled.height() / ratio - frame.height()) / 2
            painter.drawPixmap(
                QRectF(-x, -y, scaled.width() / ratio, scaled.height() / ratio), scaled, QRectF(scaled.rect())
            )
            self.setAccessibleName(tr("Photo of {title}", title=title))
        else:
            painter.fillRect(frame, QColor(palette.surface))  # a white frame on the gray card
            glyph = assets.pixmap(assets.CATEGORY_ICONS[category], palette.primary, 64)
            painter.drawPixmap(
                QRectF(frame.center().x() - 32, frame.center().y() - 40, 64, 64), glyph, QRectF(glyph.rect())
            )
            painter.setPen(QColor(palette.text_muted))
            font = QFont(self.font())
            font.setPointSizeF(max(font.pointSizeF() * 0.9, 9))
            painter.setFont(font)
            painter.drawText(
                QRectF(0, frame.bottom() - 36, frame.width(), 26), Qt.AlignmentFlag.AlignCenter, category.label
            )
            self.setAccessibleName(tr("{label} artwork for {title}", label=category.label, title=title))


class FeaturedBanner(QFrame):
    """'Happening next': one upcoming event that still needs people, with a clear action."""

    def __init__(self) -> None:
        super().__init__()
        self.setProperty("banner", True)
        row = QHBoxLayout(self)
        row.setContentsMargins(16, 16, 16, 16)
        row.setSpacing(24)
        self.art = ProgramArt(192, 128)
        row.addWidget(self.art)
        text = QVBoxLayout()
        text.setSpacing(8)
        # One heading that says what this is ("Happening next: ..."), not a small label stacked above it.
        self.title = make_label("", "section", wrap=True)
        self.when = make_label("", "subtitle", wrap=True)
        self.description = make_label("", wrap=True)
        text.addWidget(self.title)
        text.addWidget(self.when)
        text.addWidget(self.description)
        text.addStretch(1)
        row.addLayout(text, 1)
        self._action_column = QVBoxLayout()  # not "actions": that name is a QWidget method
        self._action_column.setSpacing(8)
        row.addLayout(self._action_column)
        self._buttons: list[QPushButton] = []

    def show_event(self, overview: ShiftOverview, description: str, photo: bytes | None) -> None:
        shift = overview.shift
        self.art.show_program(overview.category, photo, overview.opportunity_title)
        self.title.setText(tr("Happening next: {title}", title=overview.opportunity_title))
        spots = overview.open_spots
        self.when.setText(
            tr_n(
                "{format_when} at {location}. {spots} of {count} spot still open.",
                "{format_when} at {location}. {spots} of {count} spots still open.",
                shift.capacity,
                format_when=format_when(shift.starts_at, shift.ends_at),
                location=overview.location,
                spots=spots,
            )
        )
        self.description.setText(description)
        self.setAccessibleName(
            tr(
                "Happening next: {opportunity_title}, {text}",
                opportunity_title=overview.opportunity_title,
                text=self.when.text(),
            )
        )

    def set_actions(self, buttons: Iterable[QPushButton]) -> None:
        for old in self._buttons:
            old.deleteLater()
        self._buttons = list(buttons)
        for button in self._buttons:
            self._action_column.addWidget(button)
        self._action_column.addStretch(1)


class Callout(QFrame):
    """A plain section near the bottom of a home screen: an invitation, never a pop-up."""

    def __init__(self, icon_name: str) -> None:
        super().__init__()
        self.setProperty("callout", True)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 24, 0, 8)
        row.setSpacing(16)
        self.icon = QLabel()
        self.icon.setPixmap(assets.pixmap(icon_name, current_palette().primary, 24))
        row.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(4)
        self.heading = make_label("", "section", wrap=True)
        self.body = make_label("", wrap=True)
        text.addWidget(self.heading)
        text.addWidget(self.body)
        row.addLayout(text, 1)
        self.action_slot = QHBoxLayout()
        row.addLayout(self.action_slot)

    def set_text(self, heading: str, body: str) -> None:
        self.heading.setText(heading)
        self.body.setText(body)
        self.setAccessibleName(f"{heading}. {body}")

    def set_action(self, button: QPushButton) -> None:
        self.action_slot.addWidget(button, 0, Qt.AlignmentFlag.AlignVCenter)


_ACTIVITY_ICONS = {
    ActivityKind.SIGNED_UP: "calendar-plus",
    ActivityKind.SERVED: "user-check",
    ActivityKind.APPLIED: "user-plus",
}


def describe_activity(item: ActivityItem) -> str:
    if item.kind is ActivityKind.SIGNED_UP and item.shift_starts_at:
        return tr(
            "{volunteer_name} signed up for {opportunity_title} on {format_when}",
            volunteer_name=item.volunteer_name,
            opportunity_title=item.opportunity_title,
            format_when=format_when(item.shift_starts_at),
        )
    if item.kind is ActivityKind.SERVED:
        return tr(
            "{volunteer_name} served {format_hours} at {opportunity_title}",
            volunteer_name=item.volunteer_name,
            format_hours=format_hours(item.hours or 0),
            opportunity_title=item.opportunity_title,
        )
    return tr("{volunteer_name} applied to volunteer", volunteer_name=item.volunteer_name)


def relative_time(moment: datetime, now: datetime) -> str:
    delta = now - moment
    minutes = int(delta.total_seconds() // 60)
    if minutes < 60:
        return tr("just now") if minutes < 2 else tr("{minutes} minutes ago", minutes=minutes)
    hours = minutes // 60
    if hours < 24:
        return tr_n("{count} hour ago", "{count} hours ago", hours)
    days = hours // 24
    if days < 7:
        return tr("yesterday") if days == 1 else tr("{days} days ago", days=days)
    return format_day_short(moment.date())


class ActivityFeed(QListWidget):
    """Newest-first list of what volunteers have been doing (the app's live news feed)."""

    def __init__(self) -> None:
        super().__init__()
        self.setAccessibleName(tr("Recent activity"))
        self.setWordWrap(True)
        self.setSpacing(2)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def set_items(self, items: Sequence[ActivityItem], now: datetime) -> None:
        self.clear()
        color = current_palette().info
        if not items:
            self.addItem(QListWidgetItem(tr("Nothing yet. Sign-ups and attendance will appear here.")))
            return
        for item in items:
            text = f"{describe_activity(item)}\n{relative_time(item.occurred_at, now)}"
            entry = QListWidgetItem(assets.icon(_ACTIVITY_ICONS[item.kind], color, 18), text)
            entry.setData(Qt.ItemDataRole.AccessibleTextRole, text.replace("\n", ", "))
            self.addItem(entry)


class ShiftCalendar(QCalendarWidget):
    """
    Month calendar that dots each day with shifts: amber (the "look here" color)
    if spots are still open, indigo if every shift is full, gray for days
    already past. The dots are a summary; the day's list says it in words.
    """

    def __init__(self) -> None:
        super().__init__()
        self.setGridVisible(False)
        self.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        self.setAccessibleName(tr("Shift calendar"))
        self._days: dict[date, tuple[int, int]] = {}  # day -> (shift count, open spots)
        self._today = date.today()
        self.restyle()

    def restyle(self) -> None:
        """Weekends in normal text color: red reads as an error, not a weekend."""
        palette = current_palette()
        text_format = QTextCharFormat()
        text_format.setForeground(QColor(palette.text))
        for day in (Qt.DayOfWeek.Saturday, Qt.DayOfWeek.Sunday):
            self.setWeekdayTextFormat(day, text_format)
        # Month arrows: the same thin chevron used everywhere else, instead of Qt's solid triangles.
        down = assets.pixmap("chevron-down", palette.text, 18)
        for name, angle in (("qt_calendar_prevmonth", 90), ("qt_calendar_nextmonth", -90)):
            button = self.findChild(QToolButton, name)
            if button is not None:
                button.setIcon(QIcon(down.transformed(QTransform().rotate(angle))))
                button.setIconSize(QSize(18, 18))

    def set_shifts(self, overviews: Iterable[ShiftOverview], today: date | None = None) -> None:
        self._today = today or date.today()
        days: dict[date, tuple[int, int]] = {}
        for overview in overviews:
            day = overview.shift.starts_at.date()
            count, spots = days.get(day, (0, 0))
            days[day] = (count + 1, spots + overview.open_spots)
        self._days = days
        self.updateCells()

    def paintCell(self, painter: QPainter, rect: QRect, qdate: QDate) -> None:  # noqa: N802 - Qt API
        super().paintCell(painter, rect, qdate)
        day = date(qdate.year(), qdate.month(), qdate.day())
        info = self._days.get(day)
        if not info:
            return
        palette = current_palette()
        count, spots = info
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        past = day < self._today
        color = palette.text_muted if past else (palette.attention_fill if spots else palette.primary)
        painter.setBrush(QColor(color))
        radius = 3.5
        dots = min(count, 3)
        start = rect.center().x() - (dots - 1) * 5
        for index in range(dots):
            painter.drawEllipse(QRectF(start + index * 10 - radius, rect.bottom() - 9 - radius, radius * 2, radius * 2))
        painter.restore()


class UpdatesPanel(QFrame):
    """
    "Updates for you" on a volunteer's Home page: news that concerns them, such as
    being moved off a waitlist into a shift. Each line can be dismissed; the panel
    hides itself when there is nothing to say, so it never adds clutter.
    """

    def __init__(self) -> None:
        super().__init__()
        self.setProperty("card", True)
        self.setAccessibleName(tr("Updates for you"))
        column = QVBoxLayout(self)
        column.setContentsMargins(16, 16, 16, 16)
        column.setSpacing(8)
        column.addWidget(make_label(tr("Updates for you"), "section"))
        self._rows = QVBoxLayout()
        self._rows.setSpacing(8)
        column.addLayout(self._rows)
        self.hide()

    def set_updates(self, updates: Sequence[tuple[str, Callable[[], object] | None]]) -> None:
        """``updates``: (text, dismiss action or None) pairs, newest first."""
        clear_layout(self._rows)
        for text, dismiss in updates:
            row = QHBoxLayout()
            row.setSpacing(16)
            dot = QLabel()
            dot.setFixedSize(8, 8)
            dot.setStyleSheet(f"background: {current_palette().attention_fill}; border-radius: 4px;")
            row.addWidget(dot, 0, Qt.AlignmentFlag.AlignTop)
            label = make_label(text, None, wrap=True, selectable=True)
            row.addWidget(label, 1)
            if dismiss is not None:
                button = make_button(tr("Dismiss"), kind="link", on_click=dismiss)
                button.setAccessibleName(tr("Dismiss: {text}", text=text))
                row.addWidget(button, 0, Qt.AlignmentFlag.AlignTop)
            self._rows.addLayout(row)
        self.setVisible(bool(updates))


class NetworkGlobe(QWidget):
    """
    A slowly turning globe of connected points, drawn in the theme's accent: a
    picture of neighbors linked to one another, for the sign-in screen.

    Purely decorative, so it is hidden from screen readers and takes no focus.
    It turns only while motion is allowed (Reduce motion keeps it still, WCAG
    2.3.3), and it is computed rather than drawn from an image so it stays crisp
    at any size and follows every theme.
    """

    POINTS = 150
    NEIGHBORS = 3

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(240, 240)
        self.setAccessibleName("")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        golden = math.pi * (3 - math.sqrt(5))
        self._points: list[tuple[float, float, float]] = []
        for index in range(self.POINTS):  # evenly spread over the sphere (a Fibonacci lattice)
            y = 1 - 2 * (index + 0.5) / self.POINTS
            radius = math.sqrt(1 - y * y)
            self._points.append((math.cos(golden * index) * radius, y, math.sin(golden * index) * radius))
        edges: set[tuple[int, int]] = set()
        for index, (x, y, z) in enumerate(self._points):

            def distance(i: int, x: float = x, y: float = y, z: float = z) -> float:
                px, py, pz = self._points[i]
                return (px - x) ** 2 + (py - y) ** 2 + (pz - z) ** 2

            nearest = sorted((i for i in range(self.POINTS) if i != index), key=distance)[: self.NEIGHBORS]
            edges.update((min(index, i), max(index, i)) for i in nearest)
        self._edges = sorted(edges)
        self._angle = 0.6
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._turn)

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 - Qt API
        super().showEvent(event)
        if motion_allowed():
            self._timer.start()

    def hideEvent(self, event: QHideEvent) -> None:  # noqa: N802 - Qt API
        self._timer.stop()
        super().hideEvent(event)

    def _turn(self) -> None:
        self._angle = (self._angle + 0.004) % (2 * math.pi)
        self.update()

    def _project(self, size: float, cx: float, cy: float) -> list[tuple[float, float, float]]:
        cos_a, sin_a = math.cos(self._angle), math.sin(self._angle)
        tilt_c, tilt_s = math.cos(0.35), math.sin(0.35)
        projected = []
        for x, y, z in self._points:
            x, z = x * cos_a + z * sin_a, -x * sin_a + z * cos_a  # spin around the vertical axis
            y, z = y * tilt_c - z * tilt_s, y * tilt_s + z * tilt_c  # lean toward the viewer
            projected.append((cx + x * size, cy + y * size, z))
        return projected

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt API
        palette = current_palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        size = min(self.width(), self.height()) / 2 - 8
        points = self._project(size, self.width() / 2, self.height() / 2)
        accent = QColor(palette.primary)
        for a, b in self._edges:
            depth = (points[a][2] + points[b][2]) / 2  # -1 at the back, 1 at the front
            accent.setAlphaF(0.12 + 0.28 * (depth + 1) / 2)
            painter.setPen(QPen(accent, 1))
            painter.drawLine(QPointF(points[a][0], points[a][1]), QPointF(points[b][0], points[b][1]))
        painter.setPen(Qt.PenStyle.NoPen)
        for x, y, z in points:
            accent.setAlphaF(0.3 + 0.7 * (z + 1) / 2)
            painter.setBrush(accent)
            radius = 1.2 + 1.6 * (z + 1) / 2
            painter.drawEllipse(QPointF(x, y), radius, radius)
        painter.end()
