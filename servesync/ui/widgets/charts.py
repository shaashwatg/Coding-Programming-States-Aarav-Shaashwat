"""
Charts drawn with QPainter — accessible by keyboard and screen reader.

Why not a chart library? Qt Charts is GPL-licensed (ServeSync uses only LGPL
parts of Qt), and painting our own gives full control over accessibility:

* **Direct labels.** Every bar prints its value; color never carries meaning
  alone, so charts work in grayscale and for color-blind readers.
* **Keyboard.** Tab to a chart, then use the arrow keys (Home/End too) to move
  between bars or points. Each step is announced ("Food Pantry: 231 hours,
  2 of 7"), and a visible outline marks the current item.
* **Text alternative.** The accessible description summarizes the chart
  (highest, lowest, total), and every report also shows the same numbers in
  a sortable table (WCAG 1.1.1).
* **Quiet styling.** Hairline grid, no 3-D, no legends to decode, generous
  whitespace; long names go on horizontal bars so they never rotate.
* **One orchestrated motion.** Bars grow once when a report opens — skipped
  entirely with Reduce motion.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable

from PySide6.QtCore import Property, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFocusEvent,
    QFont,
    QFontMetrics,
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from servesync.services.reports import ChartSeries, ValueKind, format_value
from servesync.ui.motion import DURATION_SLOW, animate
from servesync.ui.theme import LIGHT, Palette, current_palette

BAR_HEIGHT = 22
BAR_GAP = 12
LINE_HEIGHT = 230


def _value_text(series: ChartSeries, value: float) -> str:
    text = format_value(series.kind, value)
    return f"{text} h" if series.kind is ValueKind.HOURS else text


class ChartView(QWidget):
    """Shows one ``ChartSeries`` as horizontal bars (comparisons) or a line (trends)."""

    #: Emitted with a sentence describing the newly focused item (for the screen reader).
    item_focused = Signal(str)

    def __init__(self, series: ChartSeries | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._series: ChartSeries | None = None
        self._progress = 1.0
        self._current = -1
        self._hit_boxes: list[QRectF] = []
        if series is not None:
            self.set_series(series, animated=False)

    # ------------------------------------------------------------ data

    def set_series(self, series: ChartSeries, *, animated: bool = True) -> None:
        self._series = series
        self._current = -1
        self.setAccessibleName(series.title)
        self.setAccessibleDescription(describe_series(series))
        self.setToolTip(f"{series.title}. Use the arrow keys to read each value.")
        self.updateGeometry()
        if animated:
            animate(self, "progress", 1.0, start=0.0, duration=DURATION_SLOW)
        else:
            self._progress = 1.0
        self.update()

    def _get_progress(self) -> float:
        return self._progress

    def _set_progress(self, value: float) -> None:
        self._progress = max(0.0, min(float(value), 1.2))
        self.update()

    progress = Property(float, _get_progress, _set_progress)

    @property
    def series(self) -> ChartSeries | None:
        return self._series

    @property
    def current_index(self) -> int:
        return self._current

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API
        if self._series is None or self._series.style == "line":
            return QSize(480, LINE_HEIGHT)
        rows = max(len(self._series.values), 1)
        return QSize(480, 40 + rows * (BAR_HEIGHT + BAR_GAP))

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt API
        return QSize(320, self.sizeHint().height())

    # ------------------------------------------------------------ keyboard

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt API
        count = len(self._series.values) if self._series else 0
        if not count:
            super().keyPressEvent(event)
            return
        moves: dict[int, Callable[[int], int]] = {
            Qt.Key.Key_Right: lambda i: min(i + 1, count - 1),
            Qt.Key.Key_Down: lambda i: min(i + 1, count - 1),
            Qt.Key.Key_Left: lambda i: max(i - 1, 0),
            Qt.Key.Key_Up: lambda i: max(i - 1, 0),
            Qt.Key.Key_Home: lambda _i: 0,
            Qt.Key.Key_End: lambda _i: count - 1,
        }
        move = moves.get(event.key())
        if move is None:
            super().keyPressEvent(event)
            return
        # The first arrow press lands on the first item; later presses move from there.
        self.select(0 if self._current < 0 else move(self._current))
        event.accept()

    def select(self, index: int) -> None:
        if self._series is None or not 0 <= index < len(self._series.values):
            return
        self._current = index
        self.update()
        self.item_focused.emit(self.describe_item(index))

    def describe_item(self, index: int) -> str:
        assert self._series is not None
        series = self._series
        return (
            f"{series.labels[index]}: {_value_text(series, series.values[index])}, {index + 1} of {len(series.values)}"
        )

    def focusInEvent(self, event: QFocusEvent) -> None:  # noqa: N802 - Qt API
        super().focusInEvent(event)
        self.update()

    def focusOutEvent(self, event: QFocusEvent) -> None:  # noqa: N802 - Qt API
        super().focusOutEvent(event)
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt API
        for index, box in enumerate(self._hit_boxes):
            if box.contains(event.position()):
                QToolTip.showText(event.globalPosition().toPoint(), self.describe_item(index), self)
                return
        QToolTip.hideText()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt API
        for index, box in enumerate(self._hit_boxes):
            if box.contains(event.position()):
                self.setFocus(Qt.FocusReason.MouseFocusReason)
                self.select(index)
                return
        super().mousePressEvent(event)

    # ------------------------------------------------------------ painting

    def paintEvent(self, _event: object) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        try:
            self._hit_boxes = paint_series(
                painter,
                QRectF(self.rect()),
                self._series,
                current_palette(),
                self.font(),
                progress=self._progress,
                highlight=self._current,
                focused=self.hasFocus(),
            )
        finally:
            painter.end()

    def render_image(self, width: int = 1240) -> QImage:
        """A print-quality picture on white (for the PDF), independent of the screen theme."""
        height = max(int(self.sizeHint().height() * width / 620), 200)
        image = QImage(width, height, QImage.Format.Format_ARGB32)
        image.fill(QColor("#FFFFFF"))
        painter = QPainter(image)
        try:
            font = QFont(self.font())
            font.setPointSizeF(max(font.pointSizeF(), 11.0) * width / 620 * 0.75)
            paint_series(painter, QRectF(0, 0, width, height), self._series, LIGHT, font, progress=1.0)
        finally:
            painter.end()
        return image


def describe_series(series: ChartSeries) -> str:
    """A one-sentence text alternative for the whole chart."""
    if series.is_empty:
        return f"{series.title}: no data for this period."
    pairs = list(zip(series.labels, series.values, strict=True))
    high = max(pairs, key=lambda pair: pair[1])
    low = min(pairs, key=lambda pair: pair[1])
    if series.style == "line":
        return (
            f"{series.title}, {len(pairs)} periods from {pairs[0][0]} to {pairs[-1][0]}. "
            f"Highest {high[0]} ({_value_text(series, high[1])}); lowest {low[0]} ({_value_text(series, low[1])})."
        )
    return (
        f"{series.title}, {len(pairs)} items. Highest: {high[0]} ({_value_text(series, high[1])}). "
        f"Lowest: {low[0]} ({_value_text(series, low[1])})."
    )


def paint_series(
    painter: QPainter,
    area: QRectF,
    series: ChartSeries | None,
    palette: Palette,
    font: QFont,
    *,
    progress: float = 1.0,
    highlight: int = -1,
    focused: bool = False,
) -> list[QRectF]:
    """Draw ``series`` into ``area``. Returns each item's hit box (for tooltips and clicks)."""
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setFont(font)
    if focused:
        pen = QPen(QColor(palette.focus), palette.focus_width)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(area.adjusted(1, 1, -1, -1), 8, 8)
    if series is None or series.is_empty:
        painter.setPen(QColor(palette.text_muted))
        painter.drawText(area, Qt.AlignmentFlag.AlignCenter, "No data for this period")
        return []
    if series.style == "line":
        return _paint_line(painter, area, series, palette, progress, highlight)
    return _paint_bars(painter, area, series, palette, progress, highlight)


def _paint_bars(
    painter: QPainter, area: QRectF, series: ChartSeries, palette: Palette, progress: float, highlight: int
) -> list[QRectF]:
    metrics = QFontMetrics(painter.font())
    scale = area.width() / 620 if area.width() > 900 else 1.0
    bar, gap = BAR_HEIGHT * scale, BAR_GAP * scale
    label_width = min(max(metrics.horizontalAdvance(label) for label in series.labels) + 16, area.width() * 0.38)
    value_width = max(metrics.horizontalAdvance(_value_text(series, v)) for v in series.values) + 14
    left = area.left() + 12 + label_width
    right = area.right() - 12 - value_width
    top = area.top() + 16
    peak = max(series.values) or 1.0
    boxes: list[QRectF] = []
    fill = QColor(palette.chart[0])
    for index, (label, value) in enumerate(zip(series.labels, series.values, strict=True)):
        y = top + index * (bar + gap)
        painter.setPen(QColor(palette.text))
        text_rect = QRectF(area.left() + 12, y, label_width - 12, bar)
        painter.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            metrics.elidedText(label, Qt.TextElideMode.ElideRight, int(label_width - 12)),
        )
        # track (very light), then the bar
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(palette.surface_alt))
        painter.drawRoundedRect(QRectF(left, y + bar * 0.2, right - left, bar * 0.6), 3, 3)
        width = max((right - left) * (value / peak) * min(progress, 1.0), 2.0 if value else 0.0)
        painter.setBrush(QColor(palette.primary) if index == highlight else fill)
        bar_rect = QRectF(left, y + bar * 0.1, width, bar * 0.8)
        painter.drawRoundedRect(bar_rect, 4, 4)
        if index == highlight:
            painter.setPen(QPen(QColor(palette.focus), palette.focus_width))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRectF(area.left() + 6, y - 3, area.width() - 12, bar + 6), 6, 6)
        painter.setPen(QColor(palette.text))
        painter.drawText(
            QRectF(left + width + 8, y, value_width, bar), Qt.AlignmentFlag.AlignVCenter, _value_text(series, value)
        )
        boxes.append(QRectF(area.left(), y - gap / 2, area.width(), bar + gap))
    return boxes


def _paint_line(
    painter: QPainter, area: QRectF, series: ChartSeries, palette: Palette, progress: float, highlight: int
) -> list[QRectF]:
    metrics = QFontMetrics(painter.font())
    peak = max(series.values) or 1.0
    nice = _nice_ceiling(peak)
    axis_width = metrics.horizontalAdvance(format_value(series.kind, nice)) + 14
    plot = QRectF(
        area.left() + 12 + axis_width,
        area.top() + 16,
        area.width() - 36 - axis_width,
        area.height() - 16 - metrics.height() * 2 - 8,
    )
    # gridlines: 4 quiet hairlines with values
    for step in range(5):
        value = nice * step / 4
        y = plot.bottom() - plot.height() * step / 4
        painter.setPen(QPen(QColor(palette.line if step else palette.line_strong), 1))
        painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
        painter.setPen(QColor(palette.text_muted))
        painter.drawText(
            QRectF(area.left(), y - 10, axis_width, 20),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            format_value(series.kind, value),
        )
    count = len(series.values)
    step_x = plot.width() / max(count - 1, 1)
    points = [
        QPointF(plot.left() + i * step_x, plot.bottom() - plot.height() * (v / nice) * min(progress, 1.0))
        for i, v in enumerate(series.values)
    ]
    # soft area under the line, then the line itself
    fill = QPainterPath(QPointF(points[0].x(), plot.bottom()))
    for point in points:
        fill.lineTo(point)
    fill.lineTo(QPointF(points[-1].x(), plot.bottom()))
    tint = QColor(palette.chart[0])
    tint.setAlphaF(0.12)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(tint)
    painter.drawPath(fill)
    painter.setPen(QPen(QColor(palette.chart[0]), 2.5))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    for a, b in itertools.pairwise(points):
        painter.drawLine(a, b)
    # x labels, thinned so they never overlap
    widest = max(metrics.horizontalAdvance(label) for label in series.labels) + 12
    every = max(1, int(widest // max(step_x, 1)) + 1)
    painter.setPen(QColor(palette.text_muted))
    for index, label in enumerate(series.labels):
        if index % every == 0 or index == count - 1:
            painter.drawText(
                QRectF(points[index].x() - widest / 2, plot.bottom() + 6, widest, metrics.height() + 4),
                Qt.AlignmentFlag.AlignHCenter,
                label,
            )
    boxes: list[QRectF] = []
    for index, point in enumerate(points):
        radius = 5.5 if index == highlight else 3.5
        painter.setPen(QPen(QColor(palette.surface), 2))
        painter.setBrush(QColor(palette.primary if index == highlight else palette.chart[0]))
        painter.drawEllipse(point, radius, radius)
        if index == highlight:
            painter.setPen(QPen(QColor(palette.focus), palette.focus_width))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(point, radius + 4, radius + 4)
            painter.setPen(QColor(palette.text))
            text = _value_text(series, series.values[index])
            painter.drawText(QRectF(point.x() - 60, point.y() - 30, 120, 20), Qt.AlignmentFlag.AlignCenter, text)
        boxes.append(QRectF(point.x() - step_x / 2, plot.top(), step_x, plot.height()))
    return boxes


def _nice_ceiling(value: float) -> float:
    """Round up to 1, 2, 2.5, or 5 times a power of ten, for tidy gridlines."""
    if value <= 0:
        return 1.0
    magnitude = 10.0 ** int(f"{value:e}".split("e")[1])
    for factor in (1, 2, 2.5, 5, 10):
        if value <= factor * magnitude:
            return factor * magnitude
    return 10 * magnitude


__all__ = ["ChartView", "describe_series", "paint_series"]
