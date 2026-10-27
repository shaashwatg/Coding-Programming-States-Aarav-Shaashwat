"""
The shift workspace: who's coming, attendance, and Smart Match — in one place.

Buttons enable themselves only when the action makes sense (sign-ups before a
shift starts, attendance after), and each disabled button's tooltip says why,
so coordinators never hit a dead end.
"""

from __future__ import annotations

from functools import partial

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from servesync.models import AssignmentStatus, OpportunityStatus, RosterEntry, Shift, VolunteerStatus
from servesync.services import Permission
from servesync.ui.context import AppContext
from servesync.ui.theme import current_palette
from servesync.ui.widgets.common import (
    clear_layout,
    confirm,
    format_hours,
    format_when,
    guarded,
    make_button,
    make_label,
)
from servesync.ui.widgets.table import Column, RecordTable
from servesync.ui.widgets.visuals import FactorLegend, MatchCard

ROSTER_TAB, MATCH_TAB = 0, 1


def status_color(status: AssignmentStatus) -> str | None:
    palette = current_palette()
    return {
        AssignmentStatus.ATTENDED: palette.success,
        AssignmentStatus.NO_SHOW: palette.danger,
        AssignmentStatus.CANCELLED: palette.text_muted,
    }.get(status)


class HoursDialog(QDialog):
    """Ask how many hours someone served (defaults to the full shift, can't exceed it)."""

    def __init__(self, name: str, shift: Shift, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Record hours")
        column = QVBoxLayout(self)
        column.setContentsMargins(20, 18, 20, 18)
        column.addWidget(make_label(f"How many hours did {name} serve?", "section", wrap=True))
        column.addWidget(make_label(f"The shift lasted {format_hours(shift.duration_hours)}.", "muted"))
        self.hours = QDoubleSpinBox()
        self.hours.setRange(0.25, shift.duration_hours)
        self.hours.setSingleStep(0.25)
        self.hours.setDecimals(2)
        self.hours.setSuffix(" hours")
        self.hours.setValue(shift.duration_hours)
        self.hours.setAccessibleName("Hours served")
        column.addWidget(self.hours)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setText("Mark attended")
        ok.setProperty("kind", "primary")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        column.addWidget(buttons)


class VolunteerPickerDialog(QDialog):
    """Choose a volunteer for a shift; explains right away why someone can't be chosen."""

    def __init__(self, ctx: AppContext, shift_id: int, *, walk_in: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self._shift_id = shift_id
        self._walk_in = walk_in
        self.volunteer_id: int | None = None
        self.setWindowTitle("Record a walk-in" if walk_in else "Sign up a volunteer")
        self.resize(560, 560)

        column = QVBoxLayout(self)
        column.setContentsMargins(20, 18, 20, 18)
        column.setSpacing(10)
        column.addWidget(make_label(self.windowTitle(), "title"))
        column.addWidget(
            make_label(
                "Choose someone who served without signing up first."
                if walk_in
                else "Search for an active volunteer. ServeSync checks age, schedule clashes, and space as you pick.",
                "subtitle",
                wrap=True,
            )
        )
        self.search = QLineEdit()
        self.search.setPlaceholderText("Type a name")
        self.search.setAccessibleName("Search volunteers")
        self.search.textChanged.connect(self._fill)
        column.addWidget(self.search)
        self.list = QListWidget()
        self.list.setAccessibleName("Active volunteers")
        self.list.currentItemChanged.connect(lambda *_: self._explain())
        self.list.itemDoubleClicked.connect(lambda *_: self._choose())
        column.addWidget(self.list, 1)
        self.verdict = make_label("", wrap=True)
        column.addWidget(self.verdict)

        buttons = QDialogButtonBox()
        self.choose_button = QPushButton("Record walk-in" if walk_in else "Sign up")
        self.choose_button.setProperty("kind", "primary")
        self.choose_button.setEnabled(False)
        buttons.addButton(self.choose_button, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._choose)
        buttons.rejected.connect(self.reject)
        column.addWidget(buttons)

        self._volunteers = ctx.services.volunteers.search(ctx.session, status=VolunteerStatus.ACTIVE)
        self._fill()
        self.search.setFocus()

    def _fill(self) -> None:
        text = self.search.text().strip().casefold()
        self.list.clear()
        for volunteer in self._volunteers:
            if text and text not in volunteer.full_name.casefold():
                continue
            item = QListWidgetItem(f"{volunteer.full_name}  ({volunteer.email})")
            item.setData(Qt.ItemDataRole.UserRole, volunteer.volunteer_id)
            self.list.addItem(item)

    def _explain(self) -> None:
        item = self.list.currentItem()
        if item is None:
            self.verdict.setText("")
            self.choose_button.setEnabled(False)
            return
        volunteer_id = int(item.data(Qt.ItemDataRole.UserRole))
        if self._walk_in:
            self.verdict.setText("")
            self.choose_button.setEnabled(True)
            return
        reasons = self._ctx.services.scheduling.why_not_eligible(self._ctx.session, self._shift_id, volunteer_id)
        if reasons:
            self.verdict.setProperty("role", "concern")
            self.verdict.setText("Can't sign up: " + " ".join(reasons))
        else:
            self.verdict.setProperty("role", "ok")
            self.verdict.setText("✓ Eligible for this shift.")
        self.verdict.style().unpolish(self.verdict)
        self.verdict.style().polish(self.verdict)
        self.choose_button.setEnabled(not reasons)

    def _choose(self) -> None:
        item = self.list.currentItem()
        if item is not None and self.choose_button.isEnabled():
            self.volunteer_id = int(item.data(Qt.ItemDataRole.UserRole))
            self.accept()


class ShiftDetailDialog(QDialog):
    def __init__(
        self, ctx: AppContext, shift_id: int, *, start_tab: int = ROSTER_TAB, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self._shift_id = shift_id
        self.setWindowTitle("Shift")
        self.resize(940, 700)

        column = QVBoxLayout(self)
        column.setContentsMargins(24, 20, 24, 16)
        column.setSpacing(10)
        self.title = make_label("", "title", wrap=True)
        self.when = make_label("", "subtitle", wrap=True)
        self.state = make_label("", "muted", wrap=True)
        column.addWidget(self.title)
        column.addWidget(self.when)
        fill_row = QHBoxLayout()
        self.fill = QProgressBar()
        self.fill.setAccessibleName("Spots filled")
        self.fill.setMaximumWidth(320)
        self.fill.setTextVisible(False)
        fill_row.addWidget(self.fill)
        fill_row.addWidget(self.state, 1)
        column.addLayout(fill_row)

        self.tabs = QTabWidget()
        column.addWidget(self.tabs, 1)

        # Roster tab -------------------------------------------------------
        roster_page = QWidget()
        roster_layout = QVBoxLayout(roster_page)
        roster_layout.setContentsMargins(12, 12, 12, 12)
        self.roster: RecordTable[RosterEntry] = RecordTable(
            [
                Column(
                    "Volunteer",
                    lambda e: e.volunteer_name,
                    sort=lambda e: f"{e.volunteer_name.split()[-1]} {e.volunteer_name}".casefold(),
                    stretch=True,
                ),
                Column(
                    "Status",
                    lambda e: e.assignment.status.label,
                    color=lambda e: status_color(e.assignment.status),
                ),
                Column(
                    "Hours",
                    lambda e: format_hours(e.assignment.hours_served) if e.assignment.hours_served else "",
                    sort=lambda e: e.assignment.counted_hours,
                    align_right=True,
                ),
                Column("Phone", lambda e: e.display_phone),
                Column("Email", lambda e: e.volunteer_email),
            ],
            empty_message="Nobody has signed up yet. Use Smart Match or Sign up a volunteer to fill this shift.",
            accessible_name="Roster",
        )
        self.roster.selection_changed.connect(lambda _record: self._update_buttons())
        roster_layout.addWidget(self.roster, 1)

        actions = QHBoxLayout()
        self.sign_up_button = make_button("Sign up a volunteer...", kind="primary", on_click=self._sign_up)
        self.cancel_button = make_button("Cancel sign-up", on_click=self._cancel)
        self.attended_button = make_button("Mark attended...", on_click=self._attended)
        self.no_show_button = make_button("Mark no-show", on_click=self._no_show)
        self.everyone_button = make_button("Check in everyone", on_click=self._check_in_everyone)
        self.walk_in_button = make_button("Record walk-in...", on_click=self._walk_in)
        for button in (self.sign_up_button, self.cancel_button):
            actions.addWidget(button)
        actions.addStretch(1)
        for button in (self.attended_button, self.no_show_button, self.everyone_button, self.walk_in_button):
            actions.addWidget(button)
        roster_layout.addLayout(actions)
        self.tabs.addTab(roster_page, "Roster and attendance")

        # Smart Match tab ----------------------------------------------------
        match_page = QWidget()
        match_layout = QVBoxLayout(match_page)
        match_layout.setContentsMargins(12, 12, 12, 12)
        match_layout.addWidget(
            make_label(
                "Smart Match ranks every eligible volunteer from 0 to 100. Each bar shows where the points came from; "
                "point at a bar to see the numbers. Volunteers who are too young, double-booked, or not yet approved "
                "are never shown.",
                "subtitle",
                wrap=True,
            )
        )
        match_layout.addWidget(FactorLegend())
        self.match_message = make_label("", "muted", wrap=True)
        match_layout.addWidget(self.match_message)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        holder = QWidget()
        self.match_list = QVBoxLayout(holder)
        self.match_list.setSpacing(10)
        scroll.setWidget(holder)
        match_layout.addWidget(scroll, 1)
        self.tabs.addTab(match_page, "Smart Match")

        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        column.addWidget(close)

        self._refresh()
        self.tabs.setCurrentIndex(start_tab)

    # ------------------------------------------------------------- refreshing

    def _refresh(self) -> None:
        services, session = self._ctx.services, self._ctx.session
        overview = services.opportunities.shift_overview(session, self._shift_id)
        self._overview = overview
        shift = overview.shift
        now = services.clock.now()
        self._started = shift.has_started(now)
        self.title.setText(overview.opportunity_title)
        self.setWindowTitle(f"{overview.opportunity_title} - {format_when(shift.starts_at)}")
        notes = f"  Note: {shift.notes}" if shift.notes else ""
        self.when.setText(f"{format_when(shift.starts_at, shift.ends_at)} at {overview.location}.{notes}")
        self.fill.setRange(0, shift.capacity)
        self.fill.setValue(min(overview.filled, shift.capacity))
        filled = f"{overview.filled} of {shift.capacity} filled. "
        self.fill.setAccessibleDescription(filled)
        if shift.ends_at <= now:
            self.state.setText(filled + "This shift is over. Record who attended and how long they served.")
        elif self._started:
            self.state.setText(filled + "This shift is under way. You can record attendance now.")
        else:
            self.state.setText(filled + f"{overview.open_spots} spot{'s' if overview.open_spots != 1 else ''} open.")
        self.roster.set_records(
            services.attendance.roster(session, self._shift_id, include_cancelled=True),
            keep_selection=lambda e: e.assignment.assignment_id,
        )
        self._update_buttons()
        self._refresh_matches()

    def _refresh_matches(self) -> None:
        clear_layout(self.match_list)
        overview = self._overview
        if self._started:
            self.match_message.setText("Smart Match is for upcoming shifts. This one has already started.")
            return
        if overview.opportunity_status is not OpportunityStatus.OPEN:
            self.match_message.setText("Publish this program (set it to Open) to use Smart Match.")
            return
        if overview.is_full:
            self.match_message.setText("This shift is full. Nice work!")
            return
        matches = self._ctx.services.matching.recommend_volunteers(self._ctx.session, self._shift_id, limit=8)
        self.match_message.setText(
            f"Top {len(matches)} of the eligible volunteers."
            if matches
            else "No eligible volunteers are free at this time."
        )
        for match in matches:
            volunteer = match.volunteer
            subtitle = ", ".join(volunteer.sorted_skills()[:4]) or "No skills listed yet"
            self.match_list.addWidget(
                MatchCard(
                    title=volunteer.full_name,
                    subtitle=subtitle,
                    score=match.score,
                    factors=match.factors,
                    action_text="Sign up",
                    on_action=partial(self._sign_up_id, volunteer.volunteer_id or 0),
                    access_notes=match.access_gaps,
                )
            )
        self.match_list.addStretch(1)

    def _update_buttons(self) -> None:
        entry = self.roster.selected()
        status = entry.assignment.status if entry else None
        before, after = not self._started, self._started
        waiting = "Available once the shift starts."
        self._enable(self.sign_up_button, before, "Sign-ups close when the shift starts. Use Record walk-in instead.")
        self._enable(
            self.cancel_button,
            before and status is AssignmentStatus.SCHEDULED,
            "Select a scheduled volunteer before the shift starts.",
        )
        self._enable(
            self.attended_button, after and entry is not None, waiting if before else "Select a volunteer first."
        )
        self._enable(
            self.no_show_button,
            after and status in (AssignmentStatus.SCHEDULED, AssignmentStatus.ATTENDED),
            waiting if before else "Select a scheduled volunteer first.",
        )
        anyone_waiting = any(e.assignment.status is AssignmentStatus.SCHEDULED for e in self.roster.records())
        self._enable(
            self.everyone_button, after and anyone_waiting, waiting if before else "Everyone is already checked in."
        )
        self._enable(self.walk_in_button, after, waiting)

    @staticmethod
    def _enable(button: QPushButton, enabled: bool, reason_when_disabled: str) -> None:
        button.setEnabled(enabled)
        button.setToolTip("" if enabled else reason_when_disabled)

    # ---------------------------------------------------------------- actions

    def _done(self, message: str) -> None:
        self._ctx.changed(message)
        self._refresh()

    @guarded
    def _sign_up(self) -> None:
        picker = VolunteerPickerDialog(self._ctx, self._shift_id, walk_in=False, parent=self)
        if picker.exec() and picker.volunteer_id is not None:
            self._sign_up_id(picker.volunteer_id)

    @guarded
    def _sign_up_id(self, volunteer_id: int) -> None:
        self._ctx.services.scheduling.sign_up(self._ctx.session, self._shift_id, volunteer_id)
        name = self._ctx.services.volunteers.get(self._ctx.session, volunteer_id).full_name
        self._done(f"Signed up {name}.")

    @guarded
    def _cancel(self) -> None:
        entry = self.roster.selected()
        if entry is None or not confirm(
            self,
            "Cancel sign-up",
            f"Cancel {entry.volunteer_name}'s sign-up? Their spot will open for others.",
            "Cancel sign-up",
        ):
            return
        self._ctx.services.scheduling.cancel(self._ctx.session, entry.assignment.assignment_id or 0)
        self._done(f"Cancelled {entry.volunteer_name}'s sign-up.")

    @guarded
    def _attended(self) -> None:
        entry = self.roster.selected()
        if entry is None:
            return
        dialog = HoursDialog(entry.volunteer_name, self._overview.shift, self)
        if dialog.exec():
            self._ctx.services.attendance.record_attendance(
                self._ctx.session, entry.assignment.assignment_id or 0, dialog.hours.value()
            )
            self._done(f"Recorded {format_hours(dialog.hours.value())} for {entry.volunteer_name}.")

    @guarded
    def _no_show(self) -> None:
        entry = self.roster.selected()
        if entry is None:
            return
        self._ctx.services.attendance.mark_no_show(self._ctx.session, entry.assignment.assignment_id or 0)
        self._done(f"Marked {entry.volunteer_name} as a no-show.")

    @guarded
    def _check_in_everyone(self) -> None:
        count = self._ctx.services.attendance.check_in_everyone(self._ctx.session, self._shift_id)
        self._done(f"Checked in {count} volunteer{'s' if count != 1 else ''} for the full shift.")

    @guarded
    def _walk_in(self) -> None:
        picker = VolunteerPickerDialog(self._ctx, self._shift_id, walk_in=True, parent=self)
        if not picker.exec() or picker.volunteer_id is None:
            return
        name = self._ctx.services.volunteers.get(self._ctx.session, picker.volunteer_id).full_name
        dialog = HoursDialog(name, self._overview.shift, self)
        if dialog.exec():
            self._ctx.services.attendance.record_walk_in(
                self._ctx.session, self._shift_id, picker.volunteer_id, dialog.hours.value()
            )
            self._done(f"Recorded a walk-in for {name}.")


def open_shift(ctx: AppContext, shift_id: int, parent: QWidget | None, *, smart_match: bool = False) -> None:
    """Open the shift workspace (leaders only)."""
    if not ctx.session.can(Permission.RECORD_ATTENDANCE):
        return
    dialog = ShiftDetailDialog(ctx, shift_id, start_tab=MATCH_TAB if smart_match else ROSTER_TAB, parent=parent)
    dialog.exec()
