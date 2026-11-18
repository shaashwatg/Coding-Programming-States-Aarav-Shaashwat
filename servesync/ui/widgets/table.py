"""
Generic record tables (Qt model/view architecture).

A screen describes its columns once as :class:`Column` objects (header, how
to get the value, how to sort it, and how to draw it) and :class:`RecordTable`
does the rest: sorting by clicking headers, keyboard navigation, an empty
state instead of a blank grid, and screen-reader text for each cell. One
tested component replaces a dozen hand-built tables.

Cells are drawn by one delegate so every table looks the same:

* ``kind="person"``: initials avatar, the name, and an optional second line.
* ``kind="icon"``: an icon on a tinted tile, then the text (a program and its area).
* ``kind="tag"``: a status in words on a tinted background.
* ``kind="meter"``: how full a shift is, one segment per spot, then the words.
* plain text otherwise; ``strong`` for the column that names the row, ``muted``
  for supporting details. Right-aligned numbers use same-width digits.

Rows have no stripes or grid: a hairline separates them, the row under the
pointer gets a soft tint, and the selected row a blue tint.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Generic, TypeVar

from PySide6.QtCore import (
    QAbstractTableModel,
    QEvent,
    QModelIndex,
    QPersistentModelIndex,
    QRectF,
    QSize,
    QSortFilterProxyModel,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QFontMetricsF, QMouseEvent, QPainter, QResizeEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from servesync.ui import assets
from servesync.ui.theme import current_palette, px, ui_font
from servesync.ui.widgets.elements import EmptyState, paint_avatar, paint_meter, paint_tag, tag_size

T = TypeVar("T")
SORT_ROLE = int(Qt.ItemDataRole.UserRole) + 1

AnyIndex = QModelIndex | QPersistentModelIndex

TEXT, PERSON, TAG, METER, ICON = "text", "person", "tag", "meter", "icon"
#: Space between a cell's edge and its content; the first and last columns use the table's ``edge``.
CELL_PAD = 12
AVATAR = 28
METER_WIDTH = 64
#: A stretch column may be narrowed to this (its text ends in "...") before the table scrolls sideways.
STRETCH_MIN = 180


@dataclass(frozen=True)
class Column(Generic[T]):
    header: str
    value: Callable[[T], object]
    sort: Callable[[T], object] | None = None
    color: Callable[[T], str | None] | None = None
    tooltip: Callable[[T], str] | None = None
    align_right: bool = False
    stretch: bool = False
    #: How the cell is drawn: "text", "person", "tag" or "meter".
    kind: str = TEXT
    #: For tags: the tone name (neutral, info, attention, success, danger) for this record.
    tone: Callable[[T], str] | None = None
    #: For meters: (filled, capacity) for this record.
    meter: Callable[[T], tuple[int, int]] | None = None
    #: For people (and text): a second, quieter line under the main one.
    secondary: Callable[[T], str] | None = None
    #: The column that names the row is drawn a little heavier.
    strong: bool = False
    #: Supporting details are drawn in the secondary text color.
    muted: bool = False
    #: For people: the name the initials (and their tint) come from, when the cell shows it differently.
    avatar: Callable[[T], str] | None = None
    #: For ``kind="icon"``: the icon's name for this record.
    icon: Callable[[T], str] | None = None


def _sortable(value: object) -> object:
    """Normalize sort keys so Qt can compare them (dates as ISO text, None first)."""
    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


class RecordTableModel(QAbstractTableModel, Generic[T]):
    def __init__(self, columns: Sequence[Column[T]]) -> None:
        super().__init__()
        self._columns = list(columns)
        self._records: list[T] = []

    def set_records(self, records: Sequence[T]) -> None:
        self.beginResetModel()
        self._records = list(records)
        self.endResetModel()

    def record(self, row: int) -> T | None:
        return self._records[row] if 0 <= row < len(self._records) else None

    @property
    def records(self) -> list[T]:
        return list(self._records)

    @property
    def columns(self) -> list[Column[T]]:
        return self._columns

    # Qt model interface -------------------------------------------------

    def rowCount(self, parent: AnyIndex = QModelIndex()) -> int:  # noqa: B008, N802 - Qt API
        return 0 if parent.isValid() else len(self._records)

    def columnCount(self, parent: AnyIndex = QModelIndex()) -> int:  # noqa: B008, N802 - Qt API
        return 0 if parent.isValid() else len(self._columns)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole) -> Any:  # noqa: N802
        if orientation != Qt.Orientation.Horizontal:
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return self._columns[section].header
        if role == Qt.ItemDataRole.TextAlignmentRole:
            horizontal = (
                Qt.AlignmentFlag.AlignRight if self._columns[section].align_right else Qt.AlignmentFlag.AlignLeft
            )
            return int(horizontal | Qt.AlignmentFlag.AlignVCenter)
        return None

    def data(self, index: AnyIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        record = self._records[index.row()]
        column = self._columns[index.column()]
        if role == Qt.ItemDataRole.DisplayRole:
            value = column.value(record)
            return "" if value is None else str(value)
        if role == Qt.ItemDataRole.AccessibleTextRole:
            value = column.value(record)
            text = "" if value is None else str(value)
            extra = column.secondary(record) if column.secondary is not None else ""
            return f"{text}, {extra}" if extra else text
        if role == SORT_ROLE:
            return _sortable((column.sort or column.value)(record))
        if role == Qt.ItemDataRole.ForegroundRole and column.color is not None:
            color = column.color(record)
            return QColor(color) if color else None
        if role == Qt.ItemDataRole.ToolTipRole and column.tooltip is not None:
            return column.tooltip(record)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            horizontal = Qt.AlignmentFlag.AlignRight if column.align_right else Qt.AlignmentFlag.AlignLeft
            return int(horizontal | Qt.AlignmentFlag.AlignVCenter)
        return None


class _RecordView(QTableView):
    """A table view that knows which row the pointer is over, so the whole row can be tinted."""

    def __init__(self) -> None:
        super().__init__()
        self.hover_row = -1
        self.setMouseTracking(True)

    def _set_hover(self, row: int) -> None:
        if row != self.hover_row:
            self.hover_row = row
            self.viewport().update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt API
        self._set_hover(self.indexAt(event.position().toPoint()).row())
        super().mouseMoveEvent(event)

    def leaveEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt API
        self._set_hover(-1)
        super().leaveEvent(event)


class RecordDelegate(QStyledItemDelegate, Generic[T]):
    """Draws every cell of a :class:`RecordTable` (see the module docstring for the cell kinds)."""

    def __init__(self, table: RecordTable[T]) -> None:
        super().__init__(table)
        self._table = table

    # ------------------------------------------------------------- helpers

    def _cell(self, index: AnyIndex) -> tuple[Column[T], T | None]:
        table = self._table
        source = table._proxy.mapToSource(index)
        return table._model.columns[source.column()], table._model.record(source.row())

    def _padding(self, index: AnyIndex) -> tuple[int, int]:
        """Left and right padding: the table's edge inset for the outer columns, a smaller gap between columns."""
        header = self._table.view.horizontalHeader()
        visual = header.visualIndex(index.column())
        edge = self._table.edge
        left = edge if visual == 0 else CELL_PAD
        right = edge if visual == header.count() - 1 else CELL_PAD
        return left, right

    @staticmethod
    def _fonts(column: Column[T]) -> tuple[Any, Any]:
        weight = 500 if column.strong or column.kind in (PERSON, ICON) else 400
        return ui_font(1.0, weight, tabular=column.align_right), ui_font(0.86, 400)

    # ------------------------------------------------------------ Qt hooks

    def sizeHint(self, option: QStyleOptionViewItem, index: AnyIndex) -> QSize:  # noqa: N802 - Qt API
        column, record = self._cell(index)
        left, right = self._padding(index)
        main_font, small_font = self._fonts(column)
        text = str(index.data() or "")
        width = QFontMetricsF(main_font).horizontalAdvance(text)
        if column.secondary is not None and record is not None:
            width = max(width, QFontMetricsF(small_font).horizontalAdvance(column.secondary(record)))
        if column.kind in (PERSON, ICON):
            width += px(AVATAR) + px(10)
        elif column.kind == TAG:
            width = tag_size(text).width()
        elif column.kind == METER:
            width += px(METER_WIDTH) + px(10)
        return QSize(round(width + left + right + 2), self._table.row_height())

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: AnyIndex) -> None:
        palette = current_palette()
        column, record = self._cell(index)
        rect = QRectF(option.rect)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = index.row() == self._table.view.hover_row
        painter.save()
        if selected:
            painter.fillRect(rect, QColor(palette.selection))
        elif hovered:
            painter.fillRect(rect, QColor(palette.surface_hover))
        painter.fillRect(QRectF(rect.left(), rect.bottom(), rect.width(), 1), QColor(palette.line))
        if record is None:
            painter.restore()
            return

        left, right = self._padding(index)
        area = rect.adjusted(left, 0, -right, 0)
        text = str(index.data() or "")
        main_font, small_font = self._fonts(column)
        if selected:
            color = QColor(palette.on_selection)
        elif column.color is not None and column.color(record):
            color = QColor(column.color(record))
        else:
            color = QColor(palette.text_muted if column.muted else palette.text)
        secondary = column.secondary(record) if column.secondary is not None else ""

        if column.kind == TAG:
            if text:
                size = tag_size(text)
                box = QRectF(area.left(), area.center().y() - size.height() / 2, size.width(), size.height())
                paint_tag(painter, box, text, column.tone(record) if column.tone else "neutral")
            painter.restore()
            return
        if column.kind == PERSON:
            diameter = float(px(AVATAR))
            name = column.avatar(record) if column.avatar is not None else text
            paint_avatar(painter, QRectF(area.left(), area.center().y() - diameter / 2, diameter, diameter), name)
            area.setLeft(area.left() + diameter + px(10))
        elif column.kind == ICON and column.icon is not None:
            edge = float(px(AVATAR))
            tile = QRectF(area.left(), area.center().y() - edge / 2, edge, edge)
            background, foreground = palette.tone(column.tone(record) if column.tone else "info")
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(background))
            painter.drawRoundedRect(tile, edge * 0.28, edge * 0.28)
            glyph = round(edge * 0.55)
            image = assets.pixmap(column.icon(record), foreground, glyph)
            painter.drawPixmap(
                QRectF(tile.center().x() - glyph / 2, tile.center().y() - glyph / 2, glyph, glyph),
                image,
                QRectF(image.rect()),
            )
            area.setLeft(area.left() + edge + px(10))
        elif column.kind == METER and column.meter is not None:
            filled, capacity = column.meter(record)
            height = px(6)
            bar = QRectF(area.left(), area.center().y() - height / 2, px(METER_WIDTH), height)
            paint_meter(painter, bar, filled, capacity)
            area.setLeft(bar.right() + px(10))

        horizontal = Qt.AlignmentFlag.AlignRight if column.align_right else Qt.AlignmentFlag.AlignLeft
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        if secondary:
            main_metrics, small_metrics = QFontMetricsF(main_font), QFontMetricsF(small_font)
            block = main_metrics.height() + small_metrics.height()
            top = area.center().y() - block / 2
            painter.setFont(main_font)
            painter.setPen(color)
            line = QRectF(area.left(), top, area.width(), main_metrics.height())
            painter.drawText(
                line,
                horizontal | Qt.AlignmentFlag.AlignVCenter,
                main_metrics.elidedText(text, Qt.TextElideMode.ElideRight, area.width()),
            )
            painter.setFont(small_font)
            painter.setPen(QColor(palette.on_selection if selected else palette.text_muted))
            line = QRectF(area.left(), top + main_metrics.height(), area.width(), small_metrics.height())
            painter.drawText(
                line,
                horizontal | Qt.AlignmentFlag.AlignVCenter,
                small_metrics.elidedText(secondary, Qt.TextElideMode.ElideRight, area.width()),
            )
        else:
            metrics = QFontMetricsF(main_font)
            painter.setFont(main_font)
            painter.setPen(color)
            painter.drawText(
                area,
                horizontal | Qt.AlignmentFlag.AlignVCenter,
                metrics.elidedText(text, Qt.TextElideMode.ElideRight, area.width()),
            )
        painter.restore()


class RecordTable(QWidget, Generic[T]):
    """A sortable table with an empty state and record-level signals."""

    selection_changed = Signal(object)  # the selected record, or None
    activated = Signal(object)  # double-click or Enter on a record

    def __init__(
        self,
        columns: Sequence[Column[T]],
        *,
        empty_message: str,
        accessible_name: str,
        sort_column: int = 0,
        descending: bool = False,
        edge: int = 18,
        empty_icon: str = "inbox",
    ) -> None:
        super().__init__()
        #: Left padding of the first column and right padding of the last, so rows line up with a card's title.
        self.edge = edge
        self._two_lines = any(column.secondary is not None for column in columns)
        self._model: RecordTableModel[T] = RecordTableModel(columns)
        self._proxy = QSortFilterProxyModel(self)
        self._proxy.setSourceModel(self._model)
        self._proxy.setSortRole(SORT_ROLE)
        self._proxy.setSortCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

        self.view = _RecordView()
        self.view.setModel(self._proxy)
        self.view.setProperty("flat", True)
        self.view.setProperty("edge", edge > CELL_PAD)
        self.view.setItemDelegate(RecordDelegate(self))
        self.view.setAccessibleName(accessible_name)
        self.view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.view.setAlternatingRowColors(False)  # hairlines, not stripes, separate rows
        self.view.setShowGrid(False)
        self.view.setSortingEnabled(True)
        self.view.setWordWrap(False)
        self.view.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.view.verticalHeader().setVisible(False)
        self.view.verticalHeader().setMinimumSectionSize(px(40))
        self.view.verticalHeader().setDefaultSectionSize(self.row_height())  # also a full touch target
        header = self.view.horizontalHeader()
        header.setHighlightSections(False)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setMinimumSectionSize(px(48))
        self._stretch = [position for position, column in enumerate(columns) if column.stretch]
        self._stretching = False
        header.setStretchLastSection(not self._stretch)
        self.sort_by(sort_column, descending)  # Qt would otherwise start with a descending sort
        self.view.selectionModel().selectionChanged.connect(lambda *_: self.selection_changed.emit(self.selected()))
        self.view.doubleClicked.connect(lambda index: self._activate(index))
        self.view.activated.connect(lambda index: self._activate(index))

        self._empty = EmptyState(empty_message, empty_icon)
        self._stack = QStackedWidget()
        self._stack.addWidget(self.view)
        self._stack.addWidget(self._empty)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._stack)

    def row_height(self) -> int:
        """Tall enough for the text at any size, and never less than a 44 px target."""
        main = QFontMetricsF(ui_font(1.0, 500)).height()
        if self._two_lines:
            return round(max(px(56), main + QFontMetricsF(ui_font(0.86)).height() + px(18)))
        return round(max(px(48), main + px(22)))

    def set_records(self, records: Sequence[T], *, keep_selection: Callable[[T], object] | None = None) -> None:
        """Replace the rows; optionally re-select the record with the same key afterwards."""
        previous = self.selected()
        key = keep_selection(previous) if keep_selection and previous is not None else None
        self.view.verticalHeader().setDefaultSectionSize(self.row_height())
        self._model.set_records(records)
        self._fit_columns()
        self._stack.setCurrentWidget(self.view if records else self._empty)
        if keep_selection and key is not None:
            for row, record in enumerate(self._model.records):
                if keep_selection(record) == key:
                    self.select_source_row(row)
                    break
        self.selection_changed.emit(self.selected())

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self._fit_columns()

    def _fit_columns(self) -> None:
        """
        Let the main text column (a "stretch" column) fill spare width. It may give
        up some of its own width so the other columns stay on screen, but never
        below a readable minimum: Qt would otherwise squeeze it to a few letters
        at large text sizes. Past that point the table scrolls sideways instead.
        """
        header = self.view.horizontalHeader()
        if self._stretching:  # measure natural widths first
            for position in self._stretch:
                header.setSectionResizeMode(position, QHeaderView.ResizeMode.Interactive)
        self.view.resizeColumnsToContents()
        metrics = QFontMetricsF(ui_font(0.93, 500))
        for position, column in enumerate(self._model.columns):  # headers need room for the sort arrow
            wanted = round(metrics.horizontalAdvance(column.header) + 2 * CELL_PAD + px(22))
            if position in (0, header.count() - 1):
                wanted += max(self.edge - CELL_PAD, 0)
            if header.sectionSize(position) < wanted:
                header.resizeSection(position, wanted)
        natural = [header.sectionSize(i) for i in range(header.count())]
        floor = px(STRETCH_MIN)
        needed = sum(min(width, floor) if i in self._stretch else width for i, width in enumerate(natural))
        self._stretching = bool(self._stretch) and needed <= self.view.viewport().width()
        if self._stretching:
            for position in self._stretch:
                header.setSectionResizeMode(position, QHeaderView.ResizeMode.Stretch)

    def set_empty_message(self, message: str) -> None:
        self._empty.setText(message)

    def selected(self) -> T | None:
        rows = self.view.selectionModel().selectedRows()
        if not rows:
            return None
        return self._model.record(self._proxy.mapToSource(rows[0]).row())

    def select_source_row(self, row: int) -> None:
        index = self._proxy.mapFromSource(self._model.index(row, 0))
        if index.isValid():
            self.view.selectRow(index.row())
            self.view.scrollTo(index)

    def select_first(self) -> None:
        if self._proxy.rowCount() > 0:
            self.view.selectRow(0)

    def records(self) -> list[T]:
        return self._model.records

    def sort_by(self, column: int, descending: bool = False) -> None:
        order = Qt.SortOrder.DescendingOrder if descending else Qt.SortOrder.AscendingOrder
        self.view.sortByColumn(column, order)

    def fit_height(self, rows: int, *, minimum: int = 3) -> None:
        """Size the table to show ``rows`` rows without scrolling (short lists on a dashboard)."""
        shown = max(rows, minimum)
        header = self.view.horizontalHeader().sizeHint().height()
        self.setMinimumHeight(header + shown * self.row_height() + 4)

    def _activate(self, index: QModelIndex) -> None:
        record = self._model.record(self._proxy.mapToSource(index).row())
        if record is not None:
            self.activated.emit(record)
