"""
Distinctive visual components.

* :class:`ScoreAnatomyBar` — the signature element. A Smart Match score drawn
  as five colored segments, one per factor, so the algorithm explains itself.
* :class:`MatchCard` — a recommendation with its bar, reasons, and an action.
* :class:`ProgramArt` — the organization's own program photo, or consistent
  category artwork when no photo has been added.
* :class:`FeaturedBanner` — the "Happening next" spotlight (one event, never a carousel).
* :class:`Callout` — the quiet panel at the bottom of a home screen.
* :class:`ActivityFeed` — the newest sign-ups, service, and applications.
* :class:`ShiftCalendar` — a month calendar that marks days with shifts.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from datetime import date, datetime

from PySide6.QtCore import QDate, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPixmap, QTextCharFormat
from PySide6.QtWidgets import (
    QCalendarWidget,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from servesync.models import ActivityItem, ActivityKind, OpportunityCategory, ShiftOverview
from servesync.services import ScoreFactor
from servesync.ui import assets
from servesync.ui.theme import current_palette
from servesync.ui.widgets.common import format_hours, format_when, make_button, make_label


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
        lines = [f"{f.name}: {f.points:.0f} of {f.max_points:.0f}" for f in self._factors]
        self.setToolTip("\n".join(lines))
        self.setAccessibleName("Score breakdown")
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
        painter.fillRect(rect, QColor(palette.surface_alt))
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

    NAMES = ("Availability", "Skills", "Reliability", "Experience", "Fair share")

    def __init__(self) -> None:
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(14)
        for name, color in zip(self.NAMES, current_palette().factors, strict=True):
            swatch = QLabel()
            swatch.setFixedSize(12, 12)
            swatch.setStyleSheet(f"background: {color}; border-radius: 3px;")
            row.addWidget(swatch)
            row.addWidget(make_label(name, "hint"))
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
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        top = QHBoxLayout()
        names = QVBoxLayout()
        names.setSpacing(0)
        names.addWidget(make_label(title, "name"))
        if subtitle:
            names.addWidget(make_label(subtitle, "muted"))
        top.addLayout(names, 1)
        score_label = make_label(f"{score}", "score")
        score_label.setAccessibleName(f"Match score {score} out of 100")
        score_label.setToolTip("Match score out of 100")
        top.addWidget(score_label, 0, Qt.AlignmentFlag.AlignTop)
        action = make_button(action_text, kind="primary", on_click=on_action)
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
            line.setAccessibleName(("Concern: " if factor.is_concern else "Strength: ") + factor.explanation)
            layout.addWidget(line)
        for note in access_notes:
            line = make_label(f"!  {note} — check before confirming", "concern", wrap=True)
            line.setAccessibleName(f"Access note: {note}")
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
        path.addRoundedRect(frame, 10, 10)
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
            self.setAccessibleName(f"Photo of {title}")
        else:
            painter.fillRect(frame, QColor(palette.banner))
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
            self.setAccessibleName(f"{category.label} artwork for {title}")


class FeaturedBanner(QFrame):
    """'Happening next': one upcoming event that still needs people, with a clear action."""

    def __init__(self) -> None:
        super().__init__()
        self.setProperty("banner", True)
        row = QHBoxLayout(self)
        row.setContentsMargins(16, 16, 20, 16)
        row.setSpacing(20)
        self.art = ProgramArt(200, 128)
        row.addWidget(self.art)
        text = QVBoxLayout()
        text.setSpacing(4)
        self.eyebrow = make_label("Happening next", "eyebrow")
        self.title = make_label("", "display", wrap=True)
        self.when = make_label("", "subtitle", wrap=True)
        self.description = make_label("", wrap=True)
        text.addWidget(self.eyebrow)
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
        self.title.setText(overview.opportunity_title)
        spots = overview.open_spots
        self.when.setText(
            f"{format_when(shift.starts_at, shift.ends_at)} at {overview.location}. "
            f"{spots} of {shift.capacity} spot{'s' if shift.capacity != 1 else ''} still open."
        )
        self.description.setText(description)
        self.setAccessibleName(f"Happening next: {overview.opportunity_title}, {self.when.text()}")

    def set_actions(self, buttons: Iterable[QPushButton]) -> None:
        for old in self._buttons:
            old.deleteLater()
        self._buttons = list(buttons)
        for button in self._buttons:
            self._action_column.addWidget(button)
        self._action_column.addStretch(1)


class Callout(QFrame):
    """A calm panel near the bottom of a home screen — an invitation, never a pop-up."""

    def __init__(self, icon_name: str) -> None:
        super().__init__()
        self.setProperty("callout", True)
        row = QHBoxLayout(self)
        row.setContentsMargins(18, 14, 18, 14)
        row.setSpacing(14)
        self.icon = QLabel()
        self.icon.setPixmap(assets.pixmap(icon_name, current_palette().info, 28))
        row.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(2)
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
        return f"{item.volunteer_name} signed up for {item.opportunity_title} on {format_when(item.shift_starts_at)}"
    if item.kind is ActivityKind.SERVED:
        return f"{item.volunteer_name} served {format_hours(item.hours or 0)} at {item.opportunity_title}"
    return f"{item.volunteer_name} applied to volunteer"


def relative_time(moment: datetime, now: datetime) -> str:
    delta = now - moment
    minutes = int(delta.total_seconds() // 60)
    if minutes < 60:
        return "just now" if minutes < 2 else f"{minutes} minutes ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = hours // 24
    if days < 7:
        return "yesterday" if days == 1 else f"{days} days ago"
    return f"{moment:%b} {moment.day}"


class ActivityFeed(QListWidget):
    """Newest-first list of what volunteers have been doing (the app's live news feed)."""

    def __init__(self) -> None:
        super().__init__()
        self.setAccessibleName("Recent activity")
        self.setWordWrap(True)
        self.setSpacing(2)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def set_items(self, items: Sequence[ActivityItem], now: datetime) -> None:
        self.clear()
        color = current_palette().info
        if not items:
            self.addItem(QListWidgetItem("Nothing yet. Sign-ups and attendance will appear here."))
            return
        for item in items:
            text = f"{describe_activity(item)}\n{relative_time(item.occurred_at, now)}"
            entry = QListWidgetItem(assets.icon(_ACTIVITY_ICONS[item.kind], color, 18), text)
            entry.setData(Qt.ItemDataRole.AccessibleTextRole, text.replace("\n", ", "))
            self.addItem(entry)


class ShiftCalendar(QCalendarWidget):
    """
    Month calendar that dots each day with shifts: marigold if spots are still
    open, green if every shift is full, gray for days already past.
    """

    def __init__(self) -> None:
        super().__init__()
        self.setGridVisible(False)
        self.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        self.setAccessibleName("Shift calendar")
        self._days: dict[date, tuple[int, int]] = {}  # day -> (shift count, open spots)
        self._today = date.today()
        self.restyle()

    def restyle(self) -> None:
        """Weekends in normal text color: red reads as an error, not a weekend."""
        text_format = QTextCharFormat()
        text_format.setForeground(QColor(current_palette().text))
        for day in (Qt.DayOfWeek.Saturday, Qt.DayOfWeek.Sunday):
            self.setWeekdayTextFormat(day, text_format)

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
        color = palette.text_muted if past else (palette.attention if spots else palette.primary)
        painter.setBrush(QColor(color))
        radius = 3.5
        dots = min(count, 3)
        start = rect.center().x() - (dots - 1) * 5
        for index in range(dots):
            painter.drawEllipse(QRectF(start + index * 10 - radius, rect.bottom() - 9 - radius, radius * 2, radius * 2))
        painter.restore()
