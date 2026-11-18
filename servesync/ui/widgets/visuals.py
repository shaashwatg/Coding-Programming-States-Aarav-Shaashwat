"""
Distinctive visual components.

* :class:`ScoreAnatomyBar`: the signature element. A Smart Match score drawn
  as five colored segments, one per factor, so the algorithm explains itself.
* :class:`MatchCard`: a recommendation with its score ring, bar, reasons, and an action.
* :class:`ProgramArt`: the organization's own program photo, or a brand plate
  with the program area's icon when no photo has been added.
* :class:`FeaturedBanner`: the "Happening next" spotlight (one event, never a carousel).
* :class:`Callout`: the quiet section at the bottom of a home screen.
* :class:`ActivityFeed`: the newest sign-ups, service, and applications.
* :class:`ShiftCalendar`: a month calendar that marks days with shifts.
* :class:`UpdatesPanel`: news that concerns the signed-in volunteer.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from datetime import date, datetime

from PySide6.QtCore import QDate, QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QTextCharFormat, QTransform
from PySide6.QtWidgets import (
    QCalendarWidget,
    QFrame,
    QHBoxLayout,
    QLabel,
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
from servesync.ui.theme import RADIUS_CONTROL, current_palette, px, ui_font
from servesync.ui.widgets.common import clear_layout, format_hours, format_when, make_button, make_label
from servesync.ui.widgets.elements import ATTENTION, PLAIN, Dot, Glyph, IconBadge, ScoreRing, SpotMeter
from servesync.ui.widgets.lists import RowList


class ScoreAnatomyBar(QWidget):
    """Horizontal bar: each factor's earned points as a colored segment, out of 100."""

    def __init__(self, factors: Sequence[ScoreFactor] = ()) -> None:
        super().__init__()
        self._factors: list[ScoreFactor] = list(factors)
        self.setFixedHeight(px(8))
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
        return QSize(240, px(8))

    def paintEvent(self, _event: object) -> None:  # noqa: N802 - Qt API
        palette = current_palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        radius = rect.height() / 2
        clip = QPainterPath()
        clip.addRoundedRect(rect, radius, radius)
        painter.setClipPath(clip)
        painter.fillRect(rect, QColor(palette.surface_alt))
        available = sum(f.max_points for f in self._factors) or 1.0
        x = rect.left()
        for factor, color in zip(self._factors, palette.factors, strict=False):
            width = rect.width() * factor.points / available
            if width <= 0:
                continue
            painter.fillRect(QRectF(x, rect.top(), width, rect.height()), QColor(color))
            x += width
            # A gap in the surface color keeps neighboring segments distinct without relying on hue.
            painter.fillRect(QRectF(x - 2, rect.top(), 2, rect.height()), QColor(palette.surface))
        painter.end()


class _Swatch(QWidget):
    def __init__(self, index: int) -> None:
        super().__init__()
        self._index = index
        self.setFixedSize(px(10), px(10))

    def paintEvent(self, _event: object) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(current_palette().factors[self._index]))
        painter.drawRoundedRect(QRectF(self.rect()), 3, 3)
        painter.end()


class FactorLegend(QWidget):
    """Small key explaining the five colors of the score bar."""

    NAMES = (mark("Availability"), mark("Skills"), mark("Reliability"), mark("Experience"), mark("Fair share"))

    def __init__(self) -> None:
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        for index, name in enumerate(self.NAMES):
            row.addWidget(_Swatch(index))
            row.addWidget(make_label(tr(name), "hint"))
            row.addSpacing(10)
        row.addStretch(1)


def reason_row(text: str, *, concern: bool, accessible: str) -> QWidget:
    """One reason behind a score: a check mark for a strength, a warning mark for a concern, then the words."""
    holder = QWidget()
    row = QHBoxLayout(holder)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(8)
    row.addWidget(
        Glyph("triangle-alert" if concern else "check", "danger" if concern else "success", 16),
        0,
        Qt.AlignmentFlag.AlignTop,
    )
    line = make_label(text, "concern" if concern else "strength", wrap=True)
    line.setAccessibleName(accessible)
    row.addWidget(line, 1)
    return holder


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
        layout.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(12)
        top.addWidget(ScoreRing(score, 44), 0, Qt.AlignmentFlag.AlignTop)
        names = QVBoxLayout()
        names.setSpacing(2)
        names.addWidget(make_label(title, "name", wrap=True))
        if subtitle:
            names.addWidget(make_label(subtitle, "muted", wrap=True))
        top.addLayout(names, 1)
        # Tonal, not filled: a list of cards would otherwise put several filled buttons on one screen.
        action = make_button(action_text, kind="secondary", on_click=on_action)
        action.setAccessibleName(f"{action_text}: {title}")
        top.addWidget(action, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(top)

        layout.addWidget(ScoreAnatomyBar(factors))
        for factor in factors:
            if factor.points <= 0 and not factor.is_concern:
                continue
            layout.addWidget(
                reason_row(
                    factor.explanation,
                    concern=factor.is_concern,
                    accessible=(tr("Concern: ") if factor.is_concern else tr("Strength: ")) + factor.explanation,
                )
            )
        for note in access_notes:
            layout.addWidget(
                reason_row(
                    tr("{note}. Check before confirming.", note=note),
                    concern=True,
                    accessible=tr("Access note: {note}", note=note),
                )
            )


class ProgramArt(QLabel):
    """
    A program's own photo. Without one, a brand plate: deep navy with the logo's
    ring motif and the program area's icon, so every program still has a face.
    """

    def __init__(self, width: int = 220, height: int = 140) -> None:
        super().__init__()
        self._size = QSize(width, height)
        self.setFixedSize(self._size)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._shown: tuple[OpportunityCategory, bytes | None, str] | None = None

    def show_program(self, category: OpportunityCategory, photo: bytes | None, title: str) -> None:
        self._shown = (category, photo, title)
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

    def restyle(self) -> None:
        """Redraw in the current theme's colors."""
        if self._shown is not None:
            self.show_program(*self._shown)

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
            self.setAccessibleName(tr("Photo of {title}", title=title))
            return

        painter.fillRect(frame, QColor(palette.sidebar))
        # The logo's motif: rings spreading from one corner, like service rippling outward.
        center = QPointF(frame.right() - frame.width() * 0.12, frame.bottom() + frame.height() * 0.1)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        step = frame.height() * 0.3
        for index, color in enumerate((palette.sidebar_active, palette.sidebar_active, palette.sidebar_hover)):
            painter.setPen(QPen(QColor(color), 1.5))
            radius = step * (index + 1.6)
            painter.drawEllipse(center, radius, radius)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(palette.sidebar_accent))
        painter.drawEllipse(QPointF(frame.left() + 16, frame.top() + 16), 3.5, 3.5)

        size = min(frame.height() * 0.42, 56.0)
        glyph = assets.pixmap(assets.CATEGORY_ICONS[category], palette.sidebar_text, round(size))
        painter.drawPixmap(
            QRectF(frame.center().x() - size / 2, frame.center().y() - size / 2, size, size),
            glyph,
            QRectF(glyph.rect()),
        )
        painter.setClipping(False)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(palette.sidebar_line), 1))
        painter.drawRoundedRect(frame.adjusted(0.5, 0.5, -0.5, -0.5), 10, 10)
        self.setAccessibleName(tr("{label} artwork for {title}", label=category.label, title=title))


class FeaturedBanner(QFrame):
    """'Happening next': one upcoming event that still needs people, with a clear action."""

    def __init__(self) -> None:
        super().__init__()
        self.setProperty("banner", True)
        row = QHBoxLayout(self)
        row.setContentsMargins(20, 20, 20, 20)
        row.setSpacing(20)
        self.art = ProgramArt(208, 136)
        row.addWidget(self.art, 0, Qt.AlignmentFlag.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(6)
        # One heading that says what this is ("Happening next: ..."), not a small label stacked above it.
        self.title = make_label("", "heading", wrap=True)
        self.when = make_label("", "subtitle", wrap=True)
        self.meter = SpotMeter(show_text=False, bar_width=168)
        self.description = make_label("", wrap=True)
        text.addWidget(self.title)
        text.addWidget(self.when)
        text.addSpacing(4)
        text.addWidget(self.meter)
        text.addSpacing(4)
        text.addWidget(self.description)
        text.addStretch(1)
        self._action_row = QHBoxLayout()  # not "actions": that name is a QWidget method
        self._action_row.setSpacing(8)
        text.addLayout(self._action_row)
        row.addLayout(text, 1)
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
        self.meter.set_spots(shift.capacity - spots, shift.capacity)
        self.description.setText(description)
        self.description.setVisible(bool(description))
        self.setAccessibleName(
            tr(
                "Happening next: {opportunity_title}, {text}",
                opportunity_title=overview.opportunity_title,
                text=self.when.text(),
            )
        )

    def set_actions(self, buttons: Iterable[QPushButton]) -> None:
        clear_layout(self._action_row)
        self._buttons = list(buttons)
        for button in self._buttons:
            self._action_row.addWidget(button)
        self._action_row.addStretch(1)


class Callout(QFrame):
    """A plain section near the bottom of a home screen: an invitation, never a pop-up."""

    def __init__(self, icon_name: str) -> None:
        super().__init__()
        self.setProperty("callout", True)
        row = QHBoxLayout(self)
        row.setContentsMargins(20, 18, 20, 18)
        row.setSpacing(16)
        self.icon = IconBadge(icon_name, PLAIN, 40)
        row.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignVCenter)
        text = QVBoxLayout()
        text.setSpacing(2)
        self.heading = make_label("", "section", wrap=True)
        self.body = make_label("", "muted", wrap=True)
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


class ActivityFeed(RowList):
    """Newest-first list of what volunteers have been doing (the app's live news feed)."""

    def __init__(self) -> None:
        super().__init__(tr("Recent activity"), interactive=False, min_row=56)

    def set_items(self, items: Sequence[ActivityItem], now: datetime) -> None:
        self.clear()
        if not items:
            self.set_empty(tr("Nothing yet. Sign-ups and attendance will appear here."))
            return
        for item in items:
            # Each person's initials lead their line, so the feed reads as people doing things.
            self.add_row(
                describe_activity(item), relative_time(item.occurred_at, now), avatar=item.volunteer_name or "?"
            )


class ShiftCalendar(QCalendarWidget):
    """
    Month calendar that dots each day with shifts: amber (the "look here" color)
    if spots are still open, blue if every shift is full, gray for days already
    past. Today is ringed and the chosen day is filled. The dots are a summary;
    the day's list says it in words.
    """

    def __init__(self) -> None:
        super().__init__()
        self.setGridVisible(False)
        self.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        self.setHorizontalHeaderFormat(QCalendarWidget.HorizontalHeaderFormat.ShortDayNames)
        self.setAccessibleName(tr("Shift calendar"))
        self._days: dict[date, tuple[int, int]] = {}  # day -> (shift count, open spots)
        self._today = date.today()
        self.restyle()

    def restyle(self) -> None:
        """Weekday names in quiet text; weekends in the normal color (red reads as an error, not a weekend)."""
        palette = current_palette()
        header = QTextCharFormat()
        header.setForeground(QColor(palette.text_muted))
        header.setBackground(QColor(palette.surface))
        header.setFont(ui_font(0.86, 500))
        self.setHeaderTextFormat(header)
        text_format = QTextCharFormat()
        text_format.setForeground(QColor(palette.text_muted))
        text_format.setBackground(QColor(palette.surface))
        text_format.setFont(ui_font(0.86, 500))
        for day in (Qt.DayOfWeek.Saturday, Qt.DayOfWeek.Sunday):
            self.setWeekdayTextFormat(day, text_format)
        # Month arrows: the same thin chevron used everywhere else, instead of Qt's solid triangles.
        down = assets.pixmap("chevron-down", palette.text, 18)
        for name, angle in (("qt_calendar_prevmonth", 90), ("qt_calendar_nextmonth", -90)):
            button = self.findChild(QToolButton, name)
            if button is not None:
                button.setIcon(QIcon(down.transformed(QTransform().rotate(angle))))
                button.setIconSize(QSize(18, 18))
        self.updateCells()

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
        palette = current_palette()
        day = date(qdate.year(), qdate.month(), qdate.day())
        in_month = qdate.month() == self.monthShown()
        selected = qdate == self.selectedDate()
        is_today = day == self._today
        info = self._days.get(day)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(rect, QColor(palette.surface))
        cell = QRectF(rect)
        size = min(cell.width() - 6, cell.height() - 14, float(px(34)))
        disc = QRectF(cell.center().x() - size / 2, cell.top() + (cell.height() - 8 - size) / 2, size, size)
        if selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(palette.primary))
            painter.drawEllipse(disc)
        elif is_today:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(palette.primary), 1.5))
            painter.drawEllipse(disc.adjusted(0.75, 0.75, -0.75, -0.75))
        if selected:
            color = palette.on_primary
        elif is_today:
            color = palette.primary
        else:
            color = palette.text if in_month else palette.text_muted
        painter.setFont(ui_font(0.93, 600 if (selected or is_today) else (500 if in_month else 400), tabular=True))
        painter.setPen(QColor(color))
        painter.drawText(disc, Qt.AlignmentFlag.AlignCenter, str(qdate.day()))

        if info:
            count, spots = info
            past = day < self._today
            dot = palette.text_muted if past else (palette.attention_fill if spots else palette.primary)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(dot))
            radius = 2.5
            dots = min(count, 3)
            start = cell.center().x() - (dots - 1) * 4
            for index in range(dots):
                painter.drawEllipse(QPointF(start + index * 8, disc.bottom() + 5.5), radius, radius)
        if self.hasFocus() and selected:  # keyboard focus: a ring just outside the chosen day
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(palette.focus), palette.focus_width))
            painter.drawRoundedRect(cell.adjusted(1.5, 1.5, -1.5, -1.5), RADIUS_CONTROL, RADIUS_CONTROL)
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
        column.setContentsMargins(20, 16, 20, 16)
        column.setSpacing(12)
        heading = QHBoxLayout()
        heading.setSpacing(10)
        heading.addWidget(IconBadge("bell", ATTENTION, 28))
        heading.addWidget(make_label(tr("Updates for you"), "section"), 1)
        column.addLayout(heading)
        self._rows = QVBoxLayout()
        self._rows.setSpacing(10)
        column.addLayout(self._rows)
        self.hide()

    def set_updates(self, updates: Sequence[tuple[str, Callable[[], object] | None]]) -> None:
        """``updates``: (text, dismiss action or None) pairs, newest first."""
        clear_layout(self._rows)
        for text, dismiss in updates:
            # Layouts, not a wrapper widget: clearing hides each label itself, so stale text never lingers.
            row = QHBoxLayout()
            row.setSpacing(12)
            dot_box = QVBoxLayout()
            dot_box.setContentsMargins(10, 7, 0, 0)
            dot_box.addWidget(Dot("attention_fill", 8))
            dot_box.addStretch(1)
            row.addLayout(dot_box)
            label = make_label(text, None, wrap=True, selectable=True)
            row.addWidget(label, 1)
            if dismiss is not None:
                button = make_button(tr("Dismiss"), kind="link", on_click=dismiss)
                button.setAccessibleName(tr("Dismiss: {text}", text=text))
                row.addWidget(button, 0, Qt.AlignmentFlag.AlignTop)
            self._rows.addLayout(row)
        self.setVisible(bool(updates))
