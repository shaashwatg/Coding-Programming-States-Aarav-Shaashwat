"""
Base class for every page.

Pages listen for ``data_changed``. A visible page refreshes immediately; a
hidden page just remembers it is out of date and refreshes the next time it
is shown. That keeps every screen accurate without wasted database work.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import QLineEdit, QScrollArea, QVBoxLayout, QWidget

from servesync.ui.context import AppContext
from servesync.ui.widgets.common import guarded


class Page(QWidget):
    key = ""
    title = ""
    icon_name = ""

    def __init__(self, ctx: AppContext, *, scrollable: bool = False) -> None:
        super().__init__()
        self.ctx = ctx
        self._dirty = True
        self.search_box: QLineEdit | None = None
        self.setAccessibleName(self.title)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)  # page takes focus on navigation, so Tab starts here

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        content = QWidget()
        self.layout_ = QVBoxLayout(content)
        self.layout_.setContentsMargins(32, 24, 32, 24)
        self.layout_.setSpacing(18)
        if scrollable:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QScrollArea.Shape.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setWidget(content)
            outer.addWidget(scroll)
        else:
            outer.addWidget(content)
        ctx.events.data_changed.connect(self._on_data_changed)
        # Comfort settings (e.g. Simplified layout) can change what a page shows.
        ctx.events.appearance_changed.connect(self._on_data_changed)

    # ------------------------------------------------------------ refreshing

    def _on_data_changed(self) -> None:
        if self.isVisible():
            self.reload()
        else:
            self._dirty = True

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 - Qt API
        super().showEvent(event)
        if self._dirty:
            self.reload()

    @guarded
    def reload(self) -> None:
        self._dirty = False
        self.refresh()

    def refresh(self) -> None:
        """Re-read data from the services and update the widgets."""
        raise NotImplementedError

    # ------------------------------------------------------------ navigation

    def apply_options(self, **options: Any) -> None:
        """Handle options passed by another page (for example, a pre-set filter)."""

    def focus_search(self) -> bool:
        if self.search_box is None:
            return False
        self.search_box.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.search_box.selectAll()
        return True
