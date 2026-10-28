"""
Generic record tables (Qt model/view architecture).

A screen describes its columns once as :class:`Column` objects — header,
how to get the value, how to sort it, an optional color and tooltip — and
:class:`RecordTable` does the rest: sorting by clicking headers, keyboard
navigation, an empty-state message instead of a blank grid, and screen-reader
text for each cell. One tested component replaces a dozen hand-built tables.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Generic, TypeVar

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QPersistentModelIndex,
    QSortFilterProxyModel,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QStackedWidget, QTableView, QVBoxLayout, QWidget

from servesync.ui.widgets.common import make_label

T = TypeVar("T")
SORT_ROLE = int(Qt.ItemDataRole.UserRole) + 1

AnyIndex = QModelIndex | QPersistentModelIndex


@dataclass(frozen=True)
class Column(Generic[T]):
    header: str
    value: Callable[[T], object]
    sort: Callable[[T], object] | None = None
    color: Callable[[T], str | None] | None = None
    tooltip: Callable[[T], str] | None = None
    align_right: bool = False
    stretch: bool = False


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
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.AccessibleTextRole):
            value = column.value(record)
            return "" if value is None else str(value)
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


class RecordTable(QWidget, Generic[T]):
    """A sortable table with an empty-state message and record-level signals."""

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
    ) -> None:
        super().__init__()
        self._model: RecordTableModel[T] = RecordTableModel(columns)
        self._proxy = QSortFilterProxyModel(self)
        self._proxy.setSourceModel(self._model)
        self._proxy.setSortRole(SORT_ROLE)
        self._proxy.setSortCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

        self.view = QTableView()
        self.view.setModel(self._proxy)
        self.view.setAccessibleName(accessible_name)
        self.view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.view.setAlternatingRowColors(True)
        self.view.setShowGrid(False)
        self.view.setSortingEnabled(True)
        self.view.setWordWrap(False)
        self.view.verticalHeader().setVisible(False)
        self.view.verticalHeader().setDefaultSectionSize(38)
        header = self.view.horizontalHeader()
        header.setHighlightSections(False)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for position, column in enumerate(columns):
            if column.stretch:
                header.setSectionResizeMode(position, QHeaderView.ResizeMode.Stretch)
        header.setStretchLastSection(not any(column.stretch for column in columns))
        self.sort_by(sort_column, descending)  # Qt would otherwise start with a descending sort
        self.view.selectionModel().selectionChanged.connect(lambda *_: self.selection_changed.emit(self.selected()))
        self.view.doubleClicked.connect(lambda index: self._activate(index))
        self.view.activated.connect(lambda index: self._activate(index))

        self._empty = make_label(empty_message, "muted", wrap=True)
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._stack = QStackedWidget()
        self._stack.addWidget(self.view)
        self._stack.addWidget(self._empty)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._stack)

    def set_records(self, records: Sequence[T], *, keep_selection: Callable[[T], object] | None = None) -> None:
        """Replace the rows; optionally re-select the record with the same key afterwards."""
        previous = self.selected()
        key = keep_selection(previous) if keep_selection and previous is not None else None
        self._model.set_records(records)
        self.view.resizeColumnsToContents()
        self._stack.setCurrentWidget(self.view if records else self._empty)
        if keep_selection and key is not None:
            for row, record in enumerate(self._model.records):
                if keep_selection(record) == key:
                    self.select_source_row(row)
                    break
        self.selection_changed.emit(self.selected())

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

    def _activate(self, index: QModelIndex) -> None:
        record = self._model.record(self._proxy.mapToSource(index).row())
        if record is not None:
            self.activated.emit(record)
