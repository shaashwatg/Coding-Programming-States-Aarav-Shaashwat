"""
Feedback that never interrupts: screen-reader announcements and toasts.

Announcer — the desktop equivalent of an ARIA live region
---------------------------------------------------------
Visual changes (a saved record, a new answer from Ask ServeSync, a filter that
leaves 3 results) are also *spoken* by VoiceOver, Narrator, or NVDA through
Qt's accessibility announcement event, without moving keyboard focus.

* **Politeness** — routine confirmations are *polite* (spoken after the
  current sentence); errors are *assertive* (spoken right away).
* **Coalescing** — messages that arrive within 150 ms are joined into one
  announcement, so a burst of updates isn't read out as chatter.
* **De-duplication** — the same message twice in a row is spoken once.
* **History** — the last 30 messages are kept, so anyone who missed a toast
  can reread it under Help ▸ Recent messages (WCAG 2.2.1).

Toasts
------
Small confirmations in the bottom-right corner that never take focus. They
stay up for the person's chosen time (6 s, 20 s, or until closed — WCAG 2.2.1
Timing Adjustable), pause while the pointer or focus is on them, and can be
closed with their button. At most three are shown; older ones make room.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime

from PySide6.QtCore import QEvent, QObject, QPoint, QTimer, Signal
from PySide6.QtGui import QAccessible, QAccessibleAnnouncementEvent
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QPushButton, QWidget

from servesync.ui.motion import DURATION_BASE, animate
from servesync.ui.theme import current_appearance

COALESCE_MS = 150
HISTORY_SIZE = 30
MAX_TOASTS = 3


class Announcer(QObject):
    """Speaks short messages through the platform screen reader."""

    announced = Signal(str)  # emitted with exactly what was spoken (used by tests and the history)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pending: list[tuple[str, bool]] = []
        self._last_spoken = ""
        self.history: deque[tuple[datetime, str]] = deque(maxlen=HISTORY_SIZE)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(COALESCE_MS)
        self._timer.timeout.connect(self.flush)

    def announce(self, message: str, *, assertive: bool = False) -> None:
        text = " ".join(message.split())
        if not text:
            return
        self._pending.append((text, assertive))
        self.history.append((datetime.now(), text))
        if assertive:
            self.flush()
        else:
            self._timer.start()

    def flush(self) -> None:
        """Speak everything waiting, as one announcement."""
        self._timer.stop()
        if not self._pending:
            return
        assertive = any(flag for _, flag in self._pending)
        unique: list[str] = []
        for text, _ in self._pending:
            if not unique or unique[-1] != text:
                unique.append(text)
        self._pending.clear()
        message = " ".join(t if t.endswith((".", "!", "?")) else f"{t}." for t in unique)
        if message == self._last_spoken and not assertive:
            return
        self._last_spoken = message
        target = QApplication.activeWindow() or QApplication.focusWidget()
        if target is not None:
            event = QAccessibleAnnouncementEvent(target, message)
            event.setPoliteness(
                QAccessible.AnnouncementPoliteness.Assertive if assertive else QAccessible.AnnouncementPoliteness.Polite
            )
            QAccessible.updateAccessibility(event)
        self.announced.emit(message)


class Toast(QFrame):
    """One confirmation message. Never takes focus; pauses while hovered or focused."""

    closed = Signal(object)

    def __init__(self, message: str, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("Toast")
        self.setAccessibleName("Message")
        self.setAccessibleDescription(message)
        row = QHBoxLayout(self)
        row.setContentsMargins(16, 10, 10, 10)
        row.setSpacing(12)
        self.label = QLabel(message)
        self.label.setWordWrap(True)
        self.label.setMaximumWidth(420)
        row.addWidget(self.label, 1)
        close = QPushButton("Close")
        close.setAccessibleName("Close message")
        close.clicked.connect(self.dismiss)
        row.addWidget(close)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.dismiss)
        milliseconds = current_appearance().message_duration.milliseconds
        self._duration = milliseconds
        if milliseconds is not None:
            self._timer.start(milliseconds)
        for child in (self, close):
            child.installEventFilter(self)

    @property
    def is_timed(self) -> bool:
        return self._duration is not None

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt API
        # Pause while someone is reading (pointer over it, or its button focused).
        if self._duration is not None:
            if event.type() in (QEvent.Type.Enter, QEvent.Type.FocusIn):
                self._timer.stop()
            elif event.type() in (QEvent.Type.Leave, QEvent.Type.FocusOut):
                self._timer.start(max(self._duration // 2, 3000))
        return False

    def dismiss(self) -> None:
        self._timer.stop()
        self.hide()
        self.closed.emit(self)
        self.deleteLater()


class ToastHost(QObject):
    """Stacks toasts in the bottom-right corner of a window and keeps them placed on resize."""

    MARGIN = 20
    GAP = 10

    def __init__(self, window: QWidget, announcer: Announcer) -> None:
        super().__init__(window)
        self._window = window
        self._announcer = announcer
        self.toasts: list[Toast] = []
        window.installEventFilter(self)

    def show_message(self, message: str) -> Toast:
        while len(self.toasts) >= MAX_TOASTS:
            self.toasts[0].dismiss()
        toast = Toast(message, self._window)
        toast.closed.connect(self._forget)
        self.toasts.append(toast)
        toast.adjustSize()
        toast.show()
        toast.raise_()
        self._layout(animate_newest=True)
        self._announcer.announce(message)
        return toast

    def _forget(self, toast: object) -> None:
        if isinstance(toast, Toast) and toast in self.toasts:
            self.toasts.remove(toast)
            self._layout()

    def _layout(self, *, animate_newest: bool = False) -> None:
        bottom = self._window.height() - self.MARGIN - 28  # stay clear of the status bar
        for index, toast in enumerate(reversed(self.toasts)):
            toast.adjustSize()
            target = QPoint(self._window.width() - toast.width() - self.MARGIN, bottom - toast.height())
            bottom = target.y() - self.GAP
            if animate_newest and index == 0:
                animate(toast, "pos", target, start=QPoint(target.x(), target.y() + 24), duration=DURATION_BASE)
            else:
                toast.move(target)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt API
        if watched is self._window and event.type() == QEvent.Type.Resize:
            self._layout()
        return False
