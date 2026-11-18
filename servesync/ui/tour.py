"""
The first-run tour: a few short steps that show a new person where things are.

It is a card in the corner of the window, not a modal: the page behind it stays
usable and readable, the control being described gets an outline, and every
step is announced to screen readers. "Skip tour" (or Esc) ends it at once, it
is offered only once per person, and Help > Take the tour replays it.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt
from PySide6.QtGui import QKeyEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QWidget

from servesync.core.i18n import tr
from servesync.ui.help_topics import TourStep
from servesync.ui.widgets.common import make_button, make_label
from servesync.ui.widgets.elements import add_shadow

CARD_WIDTH = 400
CARD_MARGIN = 28
OUTLINE_PADDING = 4


class TourGuide(QFrame):
    """Shows the steps one at a time over ``window``; calls ``on_done`` when finished or skipped."""

    def __init__(
        self,
        window: QWidget,
        steps: Sequence[TourStep],
        *,
        go_to: Callable[[str], None],
        target_for: Callable[[TourStep], QWidget | None],
        announce: Callable[[str], None],
        on_done: Callable[[], None],
    ) -> None:
        super().__init__(window)
        self._window = window
        self._steps = list(steps)
        self._go_to, self._target_for, self._announce, self._on_done = go_to, target_for, announce, on_done
        self._index = 0
        self.setObjectName("TourCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(CARD_WIDTH)
        self.setAccessibleName(tr("Tour"))
        column = QVBoxLayout(self)
        column.setContentsMargins(24, 20, 24, 14)
        column.setSpacing(6)
        self.counter = make_label("", "eyebrow")
        self.title = make_label("", "heading", wrap=True)
        self.text = make_label("", "muted", wrap=True)
        for widget in (self.counter, self.title, self.text):
            column.addWidget(widget)
        row = QHBoxLayout()
        row.setContentsMargins(0, 10, 0, 0)
        row.setSpacing(8)
        self.skip_button = make_button(tr("Skip tour"), kind="link", on_click=lambda: self.finish())
        self.back_button = make_button(tr("Back"), on_click=lambda: self.show_step(self._index - 1))
        self.next_button = make_button(tr("Next"), kind="secondary", on_click=self._next)
        add_shadow(self, blur=40, offset=14, opacity=0.22)
        row.addWidget(self.skip_button)
        row.addStretch(1)
        row.addWidget(self.back_button)
        row.addWidget(self.next_button)
        column.addLayout(row)

        self.outline = QFrame(window)
        self.outline.setObjectName("TourOutline")
        self.outline.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.outline.hide()
        escape_key = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        escape_key.activated.connect(self.finish)
        window.installEventFilter(self)

    # ------------------------------------------------------------- steps

    def start(self) -> None:
        self.show()
        self.show_step(0)

    def show_step(self, index: int) -> None:
        self._index = max(0, min(index, len(self._steps) - 1))
        step = self._steps[self._index]
        self._go_to(step.page)
        self.counter.setText(tr("Step {step} of {total}", step=self._index + 1, total=len(self._steps)))
        self.title.setText(tr(step.title))
        self.text.setText(tr(step.text))
        last = self._index == len(self._steps) - 1
        self.back_button.setEnabled(self._index > 0)
        self.next_button.setText(tr("Finish") if last else tr("Next"))
        self.reposition()
        self.raise_()
        self.next_button.setFocus(Qt.FocusReason.OtherFocusReason)
        self._announce(f"{self.counter.text()}. {self.title.text()}. {self.text.text()}")

    def _next(self) -> None:
        if self._index == len(self._steps) - 1:
            self.finish()
        else:
            self.show_step(self._index + 1)

    def finish(self) -> None:
        """End the tour (finished or skipped); either way it isn't offered again."""
        self._window.removeEventFilter(self)
        self.outline.hide()
        self.outline.deleteLater()
        self.hide()
        self.deleteLater()
        self._on_done()

    # ------------------------------------------------------------ layout

    def reposition(self) -> None:
        """Card in the lower right; outline around the control this step describes."""
        self.adjustSize()
        x = self._window.width() - self.width() - CARD_MARGIN
        y = self._window.height() - self.height() - CARD_MARGIN
        self.move(max(x, 0), max(y, 0))
        target = self._target_for(self._steps[self._index])
        if target is None or not target.isVisible():
            self.outline.hide()
            return
        top_left = target.mapTo(self._window, QPoint(0, 0))
        rect = QRect(top_left, target.size()).adjusted(
            -OUTLINE_PADDING, -OUTLINE_PADDING, OUTLINE_PADDING, OUTLINE_PADDING
        )
        self.outline.setGeometry(rect)
        self.outline.show()
        self.outline.raise_()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt API
        if watched is self._window and event.type() == QEvent.Type.Resize:
            self.reposition()
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt API
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._next()
            return
        super().keyPressEvent(event)
