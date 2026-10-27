"""
Shared context handed to every page and dialog.

* ``services`` and ``session`` — what the screen may do, and as whom.
* ``events`` — an application-wide signal hub (Observer pattern). After any
  change, a screen emits ``data_changed``; every other screen refreshes
  itself the next time it is shown, so numbers never go stale.
* ``navigate`` — lets a page send the user to another page (for example,
  the dashboard's "Review applicants" button opens the Volunteers page
  already filtered to applicants).
* ``announce`` — speak a short message through the screen reader without
  moving focus (the desktop equivalent of an ARIA live region).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from PySide6.QtCore import QObject, Signal

from servesync.services import Services, Session


class AppEvents(QObject):
    data_changed = Signal()
    appearance_changed = Signal()
    status_message = Signal(str)  # shown as a toast and spoken politely
    announcement = Signal(str)  # spoken only (results counts, chart values, answers)


@dataclass
class AppContext:
    services: Services
    session: Session
    events: AppEvents
    navigate: Callable[..., None] = field(default=lambda *_args, **_kwargs: None)

    def changed(self, message: str | None = None) -> None:
        """Announce that data changed (and optionally show a confirmation in the status bar)."""
        self.events.data_changed.emit()
        if message:
            self.events.status_message.emit(message)

    def go(self, page_key: str, **options: Any) -> None:
        self.navigate(page_key, **options)

    def announce(self, message: str) -> None:
        """Tell screen-reader users about a change they can't see (no visual toast)."""
        self.events.announcement.emit(message)
