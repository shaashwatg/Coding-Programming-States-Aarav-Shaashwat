"""
Programs: plan the work, publish it, and schedule its shifts.

Lifecycle buttons change with the program's state (Publish a draft, Close an
open program, Reopen a closed one), so only valid next steps are offered.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLineEdit, QSplitter, QVBoxLayout, QWidget

from servesync.models import Opportunity, OpportunityStatus, ShiftOverview
from servesync.services import Permission
from servesync.ui.context import AppContext
from servesync.ui.dialogs.program_dialogs import OpportunityDialog, ShiftDialog
from servesync.ui.dialogs.shift_detail import open_shift
from servesync.ui.pages.base import Page
from servesync.ui.theme import current_palette
from servesync.ui.widgets.common import (
    EnumComboBox,
    PageHeader,
    Panel,
    confirm,
    format_when,
    guarded,
    make_button,
    make_label,
)
from servesync.ui.widgets.table import Column, RecordTable
from servesync.ui.widgets.visuals import ProgramArt


def program_status_color(status: OpportunityStatus) -> str | None:
    palette = current_palette()
    return {OpportunityStatus.DRAFT: palette.attention, OpportunityStatus.CLOSED: palette.text_muted}.get(status)


class ProgramsPage(Page):
    key = "programs"
    title = "Programs"
    icon_name = "clipboard-list"

    def __init__(self, ctx: AppContext) -> None:
        super().__init__(ctx)
        self._story_url = ""
        self.layout_.addWidget(
            PageHeader(
                "Programs and shifts",
                "Pick a program to see its shifts. Open a shift to manage its roster, take attendance, "
                "or find volunteers with Smart Match.",
                [make_button("New program", kind="primary", on_click=self._new_program)],
            )
        )
        splitter = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        left_column = QVBoxLayout(left)
        left_column.setContentsMargins(0, 0, 12, 0)
        filters = QHBoxLayout()
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search programs")
        self.search_box.setAccessibleName("Search programs")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.textChanged.connect(lambda _t: self.reload())
        self.status_filter: EnumComboBox[OpportunityStatus] = EnumComboBox(OpportunityStatus, all_label="All programs")
        self.status_filter.setAccessibleName("Filter programs by status")
        self.status_filter.currentIndexChanged.connect(lambda _i: self.reload())
        filters.addWidget(self.search_box, 2)
        filters.addWidget(self.status_filter, 1)
        left_column.addLayout(filters)
        self.programs: RecordTable[Opportunity] = RecordTable(
            [
                Column("Program", lambda o: o.title, stretch=True),
                Column("Status", lambda o: o.status.label, color=lambda o: program_status_color(o.status)),
            ],
            empty_message="No programs match. Choose New program to create one.",
            accessible_name="Programs",
        )
        self.programs.selection_changed.connect(lambda _o: self._show_program())
        self.programs.activated.connect(lambda _o: self._edit_program())
        left_column.addWidget(self.programs, 1)
        splitter.addWidget(left)

        right = QWidget()
        right_column = QVBoxLayout(right)
        right_column.setContentsMargins(12, 0, 0, 0)
        right_column.setSpacing(12)
        detail = Panel()
        top = QHBoxLayout()
        self.art = ProgramArt(200, 128)
        top.addWidget(self.art)
        text = QVBoxLayout()
        self.program_title = make_label("", "name", wrap=True)
        self.program_meta = make_label("", "muted", wrap=True)
        self.program_description = make_label("", wrap=True)
        self.story_button = make_button("Watch the story video", kind="link", on_click=self._open_story)
        self.story_button.setToolTip("Opens in your web browser")
        for widget in (self.program_title, self.program_meta, self.program_description, self.story_button):
            text.addWidget(widget)
        text.addStretch(1)
        top.addLayout(text, 1)
        detail.body.addLayout(top)
        lifecycle = QHBoxLayout()
        self.edit_button = make_button("Edit program", on_click=self._edit_program)
        self.publish_button = make_button("Publish", kind="primary", on_click=self._publish)
        self.close_button = make_button("Close program", on_click=self._close)
        for button in (self.edit_button, self.publish_button, self.close_button):
            lifecycle.addWidget(button)
        lifecycle.addStretch(1)
        detail.body.addLayout(lifecycle)
        right_column.addWidget(detail)

        shifts = Panel("Shifts")
        shift_filters = QHBoxLayout()
        self.when_filter = QComboBox()
        self.when_filter.setAccessibleName("Which shifts to show")
        for label, value in (("Upcoming", "upcoming"), ("Past", "past"), ("All", "all")):
            self.when_filter.addItem(label, value)
        self.when_filter.currentIndexChanged.connect(lambda _i: self._show_shifts())
        shift_filters.addWidget(self.when_filter)
        shift_filters.addStretch(1)
        self.add_shift_button = make_button("Add shifts", kind="primary", on_click=self._add_shifts)
        shift_filters.addWidget(self.add_shift_button)
        shifts.body.addLayout(shift_filters)
        self.shifts: RecordTable[ShiftOverview] = RecordTable(
            [
                Column(
                    "When",
                    lambda o: format_when(o.shift.starts_at, o.shift.ends_at),
                    sort=lambda o: o.shift.starts_at,
                    stretch=True,
                ),
                Column(
                    "Filled",
                    lambda o: f"{o.filled} of {o.shift.capacity}",
                    sort=lambda o: o.fill_ratio,
                    align_right=True,
                ),
                Column(
                    "Open",
                    lambda o: o.open_spots,
                    color=lambda o: current_palette().attention if o.open_spots else None,
                    align_right=True,
                ),
                Column("Notes", lambda o: o.shift.notes),
            ],
            empty_message="No shifts here yet. Choose Add shifts to schedule some.",
            accessible_name="Shifts for the selected program",
        )
        self.shifts.activated.connect(lambda o: self._open_shift(o))
        self.shifts.selection_changed.connect(lambda _o: self._update_shift_buttons())
        shifts.body.addWidget(self.shifts, 1)
        shift_actions = QHBoxLayout()
        self.open_button = make_button("Open roster", on_click=lambda: self._open_shift(self.shifts.selected()))
        self.match_button = make_button(
            "Smart Match", on_click=lambda: self._open_shift(self.shifts.selected(), smart=True)
        )
        self.edit_shift_button = make_button("Edit shift", on_click=self._edit_shift)
        self.delete_shift_button = make_button("Delete shift", kind="danger", on_click=self._delete_shift)
        for button in (self.open_button, self.match_button, self.edit_shift_button, self.delete_shift_button):
            shift_actions.addWidget(button)
        shift_actions.addStretch(1)
        shifts.body.addLayout(shift_actions)
        right_column.addWidget(shifts, 1)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        self.layout_.addWidget(splitter, 1)

    # -------------------------------------------------------------- refresh

    def refresh(self) -> None:
        programs = self.ctx.services.opportunities.find_all(
            self.ctx.session,
            status=self.status_filter.value(),
            search=self.search_box.text() if self.search_box else "",
        )
        self.programs.set_records(programs, keep_selection=lambda o: o.opportunity_id)
        if self.programs.selected() is None:
            self.programs.select_first()
        self._show_program()

    def _show_program(self) -> None:
        program = self.programs.selected()
        services, session = self.ctx.services, self.ctx.session
        enabled = program is not None
        for widget in (self.edit_button, self.add_shift_button):
            widget.setEnabled(enabled)
        if program is None:
            self.program_title.setText("No program selected")
            self.program_meta.setText("")
            self.program_description.setText("")
            self.story_button.hide()
            self.publish_button.hide()
            self.close_button.hide()
            self.shifts.set_records([])
            return
        self.art.show_program(
            program.category, services.opportunities.photo(session, program.opportunity_id or 0), program.title
        )
        self.program_title.setText(program.title)
        skills = ", ".join(sorted(program.required_skills, key=str.casefold)) or "none"
        self.program_meta.setText(
            f"{program.status.label} {program.category.label.lower()} program at {program.location}. "
            f"Coordinator: {program.coordinator_name}. Ages {program.min_age}+. Helpful skills: {skills}."
        )
        self.program_description.setText(program.description)
        self._story_url = program.story_video_url
        self.story_button.setVisible(bool(self._story_url))
        status = program.status
        self.publish_button.setVisible(status is not OpportunityStatus.OPEN)
        self.publish_button.setText("Publish" if status is OpportunityStatus.DRAFT else "Reopen")
        self.close_button.setVisible(status is not OpportunityStatus.CLOSED)
        self.add_shift_button.setEnabled(status is not OpportunityStatus.CLOSED)
        self.add_shift_button.setToolTip(
            "" if status is not OpportunityStatus.CLOSED else "Reopen the program to add shifts."
        )
        self._show_shifts()

    def _show_shifts(self) -> None:
        program = self.programs.selected()
        if program is None:
            self.shifts.set_records([])
            return
        services, session = self.ctx.services, self.ctx.session
        now = services.clock.now()
        overviews = services.opportunities.schedule(session, opportunity_id=program.opportunity_id)
        mode = self.when_filter.currentData()
        if mode == "upcoming":
            overviews = [o for o in overviews if o.shift.ends_at > now]
        elif mode == "past":
            overviews = sorted(
                (o for o in overviews if o.shift.ends_at <= now), key=lambda o: o.shift.starts_at, reverse=True
            )
        self.shifts.set_records(overviews, keep_selection=lambda o: o.shift.shift_id)
        self.shifts.sort_by(0, descending=mode == "past")
        self._update_shift_buttons()

    def _update_shift_buttons(self) -> None:
        overview = self.shifts.selected()
        now = self.ctx.services.clock.now()
        selected = overview is not None
        upcoming = selected and overview is not None and not overview.shift.has_started(now)
        self.open_button.setEnabled(selected)
        self.match_button.setEnabled(bool(upcoming))
        self.edit_shift_button.setEnabled(bool(upcoming))
        self.delete_shift_button.setEnabled(bool(upcoming) and overview is not None and overview.filled == 0)
        self.delete_shift_button.setToolTip("Only empty, upcoming shifts can be deleted.")

    # -------------------------------------------------------------- actions

    @guarded
    def _new_program(self) -> None:
        dialog = OpportunityDialog(self.ctx, None, self)
        if dialog.exec() and dialog.saved is not None:
            self.ctx.changed(f"Created {dialog.saved.title}.")

    @guarded
    def _edit_program(self) -> None:
        program = self.programs.selected()
        if program is None:
            return
        dialog = OpportunityDialog(self.ctx, program, self)
        if dialog.exec() and dialog.saved is not None:
            self.ctx.changed(f"Saved {dialog.saved.title}.")

    @guarded
    def _publish(self) -> None:
        program = self.programs.selected()
        if program is None:
            return
        self.ctx.services.opportunities.change_status(
            self.ctx.session, program.opportunity_id or 0, OpportunityStatus.OPEN
        )
        self.ctx.changed(f"{program.title} is open for sign-ups.")

    @guarded
    def _close(self) -> None:
        program = self.programs.selected()
        if program is None or not confirm(
            self,
            "Close program",
            f"Close {program.title}? Upcoming sign-ups will be cancelled and volunteers won't see it. "
            "Past history is kept, and you can reopen it later.",
            "Close program",
        ):
            return
        cancelled = self.ctx.services.opportunities.change_status(
            self.ctx.session, program.opportunity_id or 0, OpportunityStatus.CLOSED
        )
        self.ctx.changed(f"Closed {program.title}. Cancelled {cancelled} upcoming sign-up(s).")

    @guarded
    def _add_shifts(self) -> None:
        program = self.programs.selected()
        if program is None:
            return
        dialog = ShiftDialog(self.ctx, program, None, self)
        if dialog.exec():
            self.ctx.changed(f"Added {dialog.created} shift{'s' if dialog.created != 1 else ''} to {program.title}.")

    @guarded
    def _edit_shift(self) -> None:
        program, overview = self.programs.selected(), self.shifts.selected()
        if program is None or overview is None:
            return
        if ShiftDialog(self.ctx, program, overview.shift, self).exec():
            self.ctx.changed("Shift updated.")

    @guarded
    def _delete_shift(self) -> None:
        overview = self.shifts.selected()
        if overview is None or not confirm(
            self, "Delete shift", f"Delete the shift on {format_when(overview.shift.starts_at)}?", "Delete shift"
        ):
            return
        self.ctx.services.opportunities.delete_shift(self.ctx.session, overview.shift.shift_id or 0)
        self.ctx.changed("Shift deleted.")

    @guarded
    def _open_shift(self, overview: ShiftOverview | None, smart: bool = False) -> None:
        if overview is not None and self.ctx.session.can(Permission.RECORD_ATTENDANCE):
            open_shift(self.ctx, overview.shift.shift_id or 0, self, smart_match=smart)
            self.reload()

    def _open_story(self) -> None:
        if self._story_url:
            QDesktopServices.openUrl(QUrl(self._story_url))
