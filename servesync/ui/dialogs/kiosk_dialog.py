"""
Check-in kiosk: a full-screen welcome desk for a shared laptop.

A leader opens it and walks away, so it is locked down: it shows only a first
name and last initial, and only the leader's password closes it (Esc does
nothing). Volunteers type the last 4 digits of their phone. When two people on
a shift share those digits, each gets a button to choose from.
"""

from __future__ import annotations

from functools import partial

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent, QIntValidator
from PySide6.QtWidgets import QComboBox, QDialog, QHBoxLayout, QLineEdit, QVBoxLayout, QWidget

from servesync.core.errors import AuthenticationError, ServeSyncError
from servesync.core.i18n import tr
from servesync.services import KioskPerson, KioskResult
from servesync.ui import assets
from servesync.ui.context import AppContext
from servesync.ui.widgets.common import clear_layout, format_hours, format_when, make_button, make_label, set_prop

CONTENT_WIDTH = 640
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
        logo.setPixmap(assets.logo_pixmap(LOGO_SIZE))
        logo.setAccessibleName(tr("ServeSync logo"))
        column.addWidget(logo, 0, Qt.AlignmentFlag.AlignHCenter)
        heading = make_label(tr("Welcome! Thanks for coming."), "display", wrap=True)
        heading.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        column.addWidget(heading)

        self.shift_box = QComboBox()
        self.shift_box.setAccessibleName(tr("Shift"))
        column.addWidget(self.shift_box)
        self.prompt = make_label(
            tr("Type the last 4 digits of your phone number, then press Enter."), "subtitle", wrap=True
        )
        self.prompt.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        column.addWidget(self.prompt)
        self.digits = QLineEdit()
        self.digits.setObjectName("AskInput")
        self.digits.setMaxLength(4)
        self.digits.setValidator(QIntValidator(0, 9999, self))
        self.digits.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.digits.setAccessibleName(tr("Last 4 digits of your phone number"))
        self.digits.returnPressed.connect(self.look_up)
        column.addWidget(self.digits)
        self.check_in_button = make_button(tr("Check in"), kind="primary", on_click=self.look_up)
        column.addWidget(self.check_in_button)

        self.choices_holder = QWidget()
        self.choices = QVBoxLayout(self.choices_holder)
        self.choices.setContentsMargins(0, 0, 0, 0)
        column.addWidget(self.choices_holder)
        self.message = make_label("", "lead", wrap=True)
        self.message.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        column.addWidget(self.message)
        column.addStretch(2)

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

        self._load_shifts()
        self.digits.setFocus()

    def _load_shifts(self) -> None:
        self.shift_box.clear()
        for overview in self._ctx.services.attendance.kiosk_shifts(self._ctx.session):
            shift = overview.shift
            self.shift_box.addItem(
                f"{overview.opportunity_title}, {format_when(shift.starts_at, shift.ends_at)}", shift.shift_id
            )
        has_shift = self.shift_box.count() > 0
        self.shift_box.setVisible(self.shift_box.count() > 1)
        self.digits.setEnabled(has_shift)
        self.check_in_button.setEnabled(has_shift)
        if not has_shift:
            self._say(tr("No shifts are open for check-in right now. Check-in opens 30 minutes before a shift."))

    # ------------------------------------------------------------- checking in

    def look_up(self) -> None:
        clear_layout(self.choices)
        try:
            people = self._ctx.services.attendance.kiosk_lookup(
                self._ctx.session, self.shift_box.currentData() or 0, self.digits.text()
            )
        except ServeSyncError as error:
            self._say(error.message, problem=True)
            return
        if len(people) == 1:
            self.check_in(people[0])
            return
        self._say(tr("Please choose your name."))
        for person in people:
            self.choices.addWidget(make_button(person.short_name, on_click=partial(self.check_in, person)))

    def check_in(self, person: KioskPerson) -> None:
        clear_layout(self.choices)
        self.digits.clear()
        self.digits.setFocus()
        try:
            result = self._ctx.services.attendance.kiosk_check_in(self._ctx.session, person.assignment_id)
        except ServeSyncError as error:
            self._say(error.message, problem=True)
            return
        self._say(_thank_you(result))

    def _say(self, text: str, *, problem: bool = False) -> None:
        self.message.setText(text)
        set_prop(self.message, "role", "banner-error" if problem else "lead")
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


def _thank_you(result: KioskResult) -> str:
    text = tr(
        "Thanks, {name}! You're checked in for {hours}.", name=result.given_name, hours=format_hours(result.hours)
    )
    goal = result.goal
    if goal is None:
        return text
    if goal.reached:
        return text + " " + tr("You've reached your goal of {goal} hours!", goal=goal.goal)
    return (
        text + " " + tr("That's {served} of your {goal}-hour goal.", served=format_hours(goal.served), goal=goal.goal)
    )
