"""
Check-in kiosk: a full-screen welcome desk for a shared laptop.

A leader opens it and walks away, so it is locked down: it shows only a first
name and last initial, and only the leader's password closes it (Esc does
nothing). Volunteers type the start of their name, tap it to check in, and tap
it again to check out; hours come from the two times. Name buttons are large,
for touch screens and unsteady hands.
"""

from __future__ import annotations

from functools import partial

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from servesync.core.errors import AuthenticationError, ServeSyncError
from servesync.core.i18n import format_clock, tr
from servesync.services import KioskPerson, KioskResult, KioskState
from servesync.ui import assets
from servesync.ui.context import AppContext
from servesync.ui.theme import current_palette
from servesync.ui.widgets.common import clear_layout, format_hours, format_when, make_button, make_label
from servesync.ui.widgets.elements import avatar_icon

CONTENT_WIDTH = 760
LOGO_SIZE = 72


class KioskDialog(QDialog):
    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self._unlocked = False
        self.setWindowTitle(tr("Check-in kiosk"))
        self.setModal(True)

        outer = QHBoxLayout(self)
        outer.addStretch(1)
        holder = QWidget()
        holder.setMaximumWidth(CONTENT_WIDTH)
        column = QVBoxLayout(holder)
        column.setSpacing(16)
        column.addStretch(1)
        logo = make_label()
        logo.setPixmap(assets.logo_pixmap(current_palette().brand, LOGO_SIZE))
        logo.setAccessibleName(tr("ServeSync logo"))
        column.addWidget(logo, 0, Qt.AlignmentFlag.AlignHCenter)
        heading = make_label(tr("Welcome! Thanks for coming."), "display", wrap=True)
        heading.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        column.addWidget(heading)

        self.shift_box = QComboBox()
        self.shift_box.setAccessibleName(tr("Shift"))
        column.addWidget(self.shift_box)
        self.prompt = make_label(
            tr("Find your name and tap it to check in. Tap it again when you leave to check out."),
            "subtitle",
            wrap=True,
        )
        self.prompt.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        column.addWidget(self.prompt)
        self.search = QLineEdit()
        self.search.setObjectName("KioskSearch")
        self.search.setPlaceholderText(tr("Type your name"))
        self.search.setAccessibleName(tr("Type your name to find it"))
        self.search.setMaxLength(40)
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _text: self.show_people())
        column.addWidget(self.search)

        # Big name buttons in two columns: easy to hit on a touch screen, quick to scan.
        names_holder = QWidget()
        self.names = QGridLayout(names_holder)
        self.names.setContentsMargins(0, 0, 0, 0)
        self.names.setSpacing(16)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(names_holder)
        scroll.setMinimumHeight(280)
        column.addWidget(scroll, 3)
        self.message = make_label("", "lead", wrap=True)
        self.message.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        column.addWidget(self.message)
        self.problem = make_label("", "banner-error", wrap=True)
        self.problem.hide()
        column.addWidget(self.problem)
        column.addStretch(1)

        exit_row = QHBoxLayout()
        self.exit_password = QLineEdit()
        self.exit_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.exit_password.setPlaceholderText(tr("Leader password"))
        self.exit_password.setAccessibleName(tr("Leader password, to leave the kiosk"))
        self.exit_password.setMaxLength(128)
        self.exit_password.returnPressed.connect(self.unlock)
        self.exit_button = make_button(tr("Exit kiosk"), on_click=self.unlock)
        exit_row.addWidget(self.exit_password, 1)
        exit_row.addWidget(self.exit_button)
        column.addLayout(exit_row)
        outer.addWidget(holder, 3)
        outer.addStretch(1)

        self.shift_box.currentIndexChanged.connect(lambda _index: self.show_people())
        self._load_shifts()
        self.search.setFocus()

    def _load_shifts(self) -> None:
        self.shift_box.clear()
        for overview in self._ctx.services.attendance.kiosk_shifts(self._ctx.session):
            shift = overview.shift
            self.shift_box.addItem(
                f"{overview.opportunity_title}, {format_when(shift.starts_at, shift.ends_at)}", shift.shift_id
            )
        has_shift = self.shift_box.count() > 0
        self.shift_box.setVisible(self.shift_box.count() > 1)
        self.search.setEnabled(has_shift)
        if not has_shift:
            self._say(tr("No shifts are open for check-in right now. Check-in opens 30 minutes before a shift."))
        self.show_people()

    # ------------------------------------------------------------- checking in

    def show_people(self) -> None:
        """Fill the grid with the names on the chosen shift that match what was typed."""
        clear_layout(self.names)
        shift_id = self.shift_box.currentData()
        if not shift_id:
            return
        try:
            people = self._ctx.services.attendance.kiosk_people(self._ctx.session, shift_id, self.search.text())
        except ServeSyncError as error:
            self._say(error.message, problem=True)
            return
        if not people:
            self.names.addWidget(
                make_label(
                    tr("We couldn't find that name on this shift. Please see a coordinator."), "lead", wrap=True
                ),
                0,
                0,
                1,
                2,
            )
        for index, person in enumerate(people):
            button = make_button(f"{person.short_name}\n{_state_text(person)}", kind="kiosk")
            button.setAccessibleName(f"{person.short_name}. {_state_text(person)}")
            button.setIcon(avatar_icon(person.short_name, 44))  # a face for each name, easy to spot
            button.setIconSize(QSize(44, 44))
            button.setEnabled(person.state is not KioskState.DONE)
            button.clicked.connect(partial(self.tap, person))
            self.names.addWidget(button, index // 2, index % 2)

    def tap(self, person: KioskPerson, _checked: bool = False) -> None:
        try:
            result = self._ctx.services.attendance.kiosk_tap(self._ctx.session, person.assignment_id)
        except ServeSyncError as error:
            self._say(error.message, problem=True)
            return
        self.search.clear()  # the next person starts from the full list
        self.search.setFocus()
        self._say(_thank_you(result))
        self.show_people()

    def _say(self, text: str, *, problem: bool = False) -> None:
        self.message.setVisible(not problem)
        self.problem.setVisible(problem)
        (self.problem if problem else self.message).setText(text)
        self._ctx.announce(text)

    # ----------------------------------------------------------------- leaving

    def unlock(self) -> None:
        """Only the leader who opened the kiosk can close it."""
        try:
            self._ctx.services.auth.sign_in(self._ctx.session.username, self.exit_password.text())
        except AuthenticationError as error:
            self.exit_password.clear()
            self._say(error.message, problem=True)
            return
        self._unlocked = True
        self.accept()

    def reject(self) -> None:  # Esc
        if self._unlocked:
            super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt API
        if self._unlocked:
            super().closeEvent(event)
        else:
            event.ignore()


def _state_text(person: KioskPerson) -> str:
    if person.state is KioskState.HERE and person.checked_in_at is not None:
        return tr("Here since {time}. Tap to check out.", time=format_clock(person.checked_in_at))
    if person.state is KioskState.DONE:
        return tr("Done for today. Thank you!")
    return tr("Tap to check in.")


def _thank_you(result: KioskResult) -> str:
    if not result.checked_out:
        return tr("Welcome, {name}! You're checked in. Tap your name again when you leave.", name=result.given_name)
    text = tr(
        "Thanks, {name}! You served {hours} today.", name=result.given_name, hours=format_hours(result.hours or 0)
    )
    goal = result.goal
    if goal is None:
        return text
    if goal.reached:
        return text + " " + tr("You've reached your goal of {goal} hours!", goal=goal.goal)
    return (
        text + " " + tr("That's {served} of your {goal}-hour goal.", served=format_hours(goal.served), goal=goal.goal)
    )
