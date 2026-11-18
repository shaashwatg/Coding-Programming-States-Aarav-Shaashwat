"""
Programs: plan the work, publish it, and schedule its shifts.

Lifecycle buttons change with the program's state (Publish a draft, Close an
open program, Reopen a closed one), so only valid next steps are offered.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLineEdit, QSplitter, QVBoxLayout, QWidget

from servesync.core.i18n import mark, tr, tr_n
from servesync.models import Opportunity, OpportunityStatus, ShiftOverview
from servesync.services import Permission
from servesync.ui import assets
from servesync.ui.context import AppContext
from servesync.ui.dialogs.coordination_dialogs import AnnounceDialog
from servesync.ui.dialogs.program_dialogs import OpportunityDialog, ShiftDialog
from servesync.ui.dialogs.shift_detail import open_shift
from servesync.ui.pages.base import Page
from servesync.ui.widgets.common import (
    EnumComboBox,
    PageHeader,
    Panel,
    add_search_icon,
    confirm,
    format_when,
    guarded,
    make_button,
    make_label,
)
from servesync.ui.widgets.elements import NEUTRAL, SUCCESS, FactList, Tag, status_tone
from servesync.ui.widgets.table import ICON, METER, TAG, Column, RecordTable
from servesync.ui.widgets.visuals import ProgramArt


class ProgramsPage(Page):
    key = "programs"
    title = mark("Programs")
    icon_name = "clipboard-list"

    def __init__(self, ctx: AppContext) -> None:
        super().__init__(ctx)
        self._story_url = ""
        self.layout_.addWidget(
            PageHeader(
                tr("Programs and shifts"),
                tr(
                    "Pick a program to see its shifts. Open a shift to manage its roster, "
                    "take attendance, or find volunteers with Smart Match."
                ),
                [make_button(tr("New program"), kind="secondary", on_click=self._new_program, icon="plus")],
            )
        )
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        left = QWidget()
        left_column = QVBoxLayout(left)
        left_column.setContentsMargins(0, 0, 8, 0)
        left_column.setSpacing(12)
        filters = QHBoxLayout()
        filters.setSpacing(8)
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText(tr("Search programs"))
        self.search_box.setAccessibleName(tr("Search programs"))
        self.search_box.setClearButtonEnabled(True)
        add_search_icon(self.search_box)
        self.search_box.textChanged.connect(lambda _t: self.reload())
        self.status_filter: EnumComboBox[OpportunityStatus] = EnumComboBox(
            OpportunityStatus, all_label=tr("All programs")
        )
        self.status_filter.setAccessibleName(tr("Filter programs by status"))
        self.status_filter.currentIndexChanged.connect(lambda _i: self.reload())
        filters.addWidget(self.search_box, 3)
        filters.addWidget(self.status_filter, 2)
        left_column.addLayout(filters)
        self.programs: RecordTable[Opportunity] = RecordTable(
            [
                Column(
                    tr("Program"),
                    lambda o: o.title,
                    stretch=True,
                    kind=ICON,
                    icon=lambda o: assets.CATEGORY_ICONS[o.category],
                    secondary=lambda o: o.category.label,
                ),
                Column(tr("Status"), lambda o: o.status.label, kind=TAG, tone=lambda o: status_tone(o.status)),
            ],
            empty_message=tr("No programs match. Choose New program to create one."),
            accessible_name=tr("Programs"),
            empty_icon="clipboard-list",
        )
        self.programs.selection_changed.connect(lambda _o: self._show_program())
        self.programs.activated.connect(lambda _o: self._edit_program())
        program_list = Panel(card=True, flush=True)
        program_list.body.setContentsMargins(0, 4, 0, 10)
        program_list.body.addWidget(self.programs)
        left_column.addWidget(program_list, 1)
        splitter.addWidget(left)

        right = QWidget()
        right_column = QVBoxLayout(right)
        right_column.setContentsMargins(8, 0, 0, 0)
        right_column.setSpacing(16)
        detail = Panel(card=True)
        top = QHBoxLayout()
        top.setSpacing(20)
        self.art = ProgramArt(200, 132)
        top.addWidget(self.art, 0, Qt.AlignmentFlag.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(6)
        heading = QHBoxLayout()
        heading.setSpacing(10)
        self.program_title = make_label("", "heading", wrap=True)
        self.program_status = Tag()
        heading.addWidget(self.program_title, 1)
        heading.addWidget(self.program_status, 0, Qt.AlignmentFlag.AlignTop)
        text.addLayout(heading)
        self.program_description = make_label("", "muted", wrap=True)
        text.addWidget(self.program_description)
        text.addSpacing(4)
        self.program_facts = FactList(label_width=110)
        text.addWidget(self.program_facts)
        #: The same details as one sentence, for screen readers.
        self.program_meta = make_label("", "muted", wrap=True)
        self.program_meta.hide()
        self.story_button = make_button(
            tr("Watch the story video"), kind="link", on_click=self._open_story, icon="circle-play"
        )
        self.story_button.setToolTip(tr("Opens in your web browser"))
        text.addWidget(self.story_button)
        text.addStretch(1)
        top.addLayout(text, 1)
        detail.body.addLayout(top)
        lifecycle = QHBoxLayout()
        lifecycle.setSpacing(8)
        self.edit_button = make_button(tr("Edit program"), on_click=self._edit_program, icon="pencil")
        self.publish_button = make_button(tr("Publish"), kind="secondary", on_click=self._publish)
        self.close_button = make_button(tr("Close program"), on_click=self._close)
        self.announce_button = make_button(tr("Announce..."), on_click=self._announce, icon="megaphone")
        self.announce_button.setToolTip(tr("Post a note for everyone signed up for this program"))
        for button in (self.edit_button, self.publish_button, self.close_button, self.announce_button):
            lifecycle.addWidget(button)
        lifecycle.addStretch(1)
        detail.body.addLayout(lifecycle)
        right_column.addWidget(detail)

        shifts = Panel(tr("Shifts"), flush=True)
        self.when_filter = QComboBox()
        self.when_filter.setAccessibleName(tr("Which shifts to show"))
        for label, value in ((tr("Upcoming"), "upcoming"), (tr("Past"), "past"), (tr("All"), "all")):
            self.when_filter.addItem(label, value)
        self.when_filter.currentIndexChanged.connect(lambda _i: self._show_shifts())
        self.add_shift_button = make_button(tr("Add shifts"), kind="secondary", on_click=self._add_shifts, icon="plus")
        shifts.add_action(self.when_filter)
        shifts.add_action(self.add_shift_button)
        self.shifts: RecordTable[ShiftOverview] = RecordTable(
            [
                Column(
                    tr("When"),
                    lambda o: format_when(o.shift.starts_at, o.shift.ends_at),
                    sort=lambda o: o.shift.starts_at,
                    stretch=True,
                    strong=True,
                    secondary=lambda o: o.shift.notes,
                ),
                Column(
                    tr("Filled"),
                    lambda o: tr("{filled} of {capacity}", filled=o.filled, capacity=o.shift.capacity),
                    sort=lambda o: o.fill_ratio,
                    kind=METER,
                    meter=lambda o: (o.filled, o.shift.capacity),
                ),
                Column(
                    tr("Open"),
                    # Open spots are the stand-out: an emerald tag, in words, so it never depends on color.
                    lambda o: tr("{count} open", count=o.open_spots) if o.open_spots else tr("Full"),
                    sort=lambda o: o.open_spots,
                    kind=TAG,
                    tone=lambda o: SUCCESS if o.open_spots else NEUTRAL,
                ),
            ],
            empty_message=tr("No shifts here yet. Choose Add shifts to schedule some."),
            accessible_name=tr("Shifts for the selected program"),
            empty_icon="calendar-plus",
        )
        self.shifts.activated.connect(lambda o: self._open_shift(o))
        self.shifts.selection_changed.connect(lambda _o: self._update_shift_buttons())
        shifts.body.addWidget(self.shifts, 1)
        self.open_button = make_button(
            tr("Open roster"), on_click=lambda: self._open_shift(self.shifts.selected()), icon="users"
        )
        self.match_button = make_button(
            tr("Smart Match"),
            on_click=lambda: self._open_shift(self.shifts.selected(), smart=True),
            icon="user-round-check",
        )
        self.edit_shift_button = make_button(tr("Edit shift"), on_click=self._edit_shift)
        self.delete_shift_button = make_button(tr("Delete shift"), kind="danger", on_click=self._delete_shift)
        shifts.add_row(self.open_button, self.match_button, self.edit_shift_button, self.delete_shift_button, top=4)
        right_column.addWidget(shifts, 1)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([400, 660])
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
            self.program_title.setText(tr("No program selected"))
            self.program_status.set_tag("")
            self.program_meta.setText("")
            self.program_facts.set_facts([])
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
        self.program_status.set_tag(program.status.label, status_tone(program.status))
        needed = sorted(program.required_skills, key=str.casefold)
        self.program_facts.set_facts(
            [
                (tr("Program area"), program.category.label),
                (tr("Location"), program.location),
                (tr("Coordinator"), program.coordinator_name),
                (tr("Ages"), tr("{min_age} and up", min_age=program.min_age)),
                (tr("Helpful skills"), needed or tr("None needed")),
            ]
        )
        skills = ", ".join(needed) or "none"
        self.program_meta.setText(
            tr(
                (
                    "{label} {lower} program at {location}. Coordinator: "
                    "{coordinator_name}. Ages {min_age}+. Helpful skills: {skills}."
                ),
                label=program.status.label,
                lower=program.category.label.lower(),
                location=program.location,
                coordinator_name=program.coordinator_name,
                min_age=program.min_age,
                skills=skills,
            )
        )
        self.program_description.setText(program.description)
        self.program_description.setVisible(bool(program.description))
        self.setAccessibleDescription(self.program_meta.text())
        self._story_url = program.story_video_url
        self.story_button.setVisible(bool(self._story_url))
        status = program.status
        self.publish_button.setVisible(status is not OpportunityStatus.OPEN)
        self.publish_button.setText(tr("Publish") if status is OpportunityStatus.DRAFT else tr("Reopen"))
        self.close_button.setVisible(status is not OpportunityStatus.CLOSED)
        self.announce_button.setVisible(status is OpportunityStatus.OPEN)
        self.add_shift_button.setEnabled(status is not OpportunityStatus.CLOSED)
        self.add_shift_button.setToolTip(
            "" if status is not OpportunityStatus.CLOSED else tr("Reopen the program to add shifts.")
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
        self.delete_shift_button.setToolTip(tr("Only empty, upcoming shifts can be deleted."))

    # -------------------------------------------------------------- actions

    @guarded
    def _new_program(self) -> None:
        dialog = OpportunityDialog(self.ctx, None, self)
        if dialog.exec() and dialog.saved is not None:
            self.ctx.changed(tr("Created {title}.", title=dialog.saved.title))

    @guarded
    def _edit_program(self) -> None:
        program = self.programs.selected()
        if program is None:
            return
        dialog = OpportunityDialog(self.ctx, program, self)
        if dialog.exec() and dialog.saved is not None:
            self.ctx.changed(tr("Saved {title}.", title=dialog.saved.title))

    @guarded
    def _announce(self) -> None:
        program = self.programs.selected()
        if program is not None:
            AnnounceDialog(self.ctx, program.title, opportunity_id=program.opportunity_id, parent=self).exec()

    @guarded
    def _publish(self) -> None:
        program = self.programs.selected()
        if program is None:
            return
        self.ctx.services.opportunities.change_status(
            self.ctx.session, program.opportunity_id or 0, OpportunityStatus.OPEN
        )
        self.ctx.changed(tr("{title} is open for sign-ups.", title=program.title))

    @guarded
    def _close(self) -> None:
        program = self.programs.selected()
        if program is None or not confirm(
            self,
            tr("Close program"),
            tr(
                (
                    "Close {title}? Upcoming sign-ups will be cancelled and volunteers "
                    "won't see it. Past history is kept, and you can reopen it later."
                ),
                title=program.title,
            ),
            tr("Close program"),
        ):
            return
        cancelled = self.ctx.services.opportunities.change_status(
            self.ctx.session, program.opportunity_id or 0, OpportunityStatus.CLOSED
        )
        self.ctx.changed(
            tr("Closed {title}. Cancelled {cancelled} upcoming sign-up(s).", title=program.title, cancelled=cancelled)
        )

    @guarded
    def _add_shifts(self) -> None:
        program = self.programs.selected()
        if program is None:
            return
        dialog = ShiftDialog(self.ctx, program, None, self)
        if dialog.exec():
            self.ctx.changed(
                tr_n(
                    "Added {count} shift to {title}.",
                    "Added {count} shifts to {title}.",
                    dialog.created,
                    title=program.title,
                )
            )

    @guarded
    def _edit_shift(self) -> None:
        program, overview = self.programs.selected(), self.shifts.selected()
        if program is None or overview is None:
            return
        if ShiftDialog(self.ctx, program, overview.shift, self).exec():
            self.ctx.changed(tr("Shift updated."))

    @guarded
    def _delete_shift(self) -> None:
        overview = self.shifts.selected()
        if overview is None or not confirm(
            self,
            tr("Delete shift"),
            tr("Delete the shift on {format_when}?", format_when=format_when(overview.shift.starts_at)),
            tr("Delete shift"),
        ):
            return
        self.ctx.services.opportunities.delete_shift(self.ctx.session, overview.shift.shift_id or 0)
        self.ctx.changed(tr("Shift deleted."))

    @guarded
    def _open_shift(self, overview: ShiftOverview | None, smart: bool = False) -> None:
        if overview is not None and self.ctx.session.can(Permission.RECORD_ATTENDANCE):
            open_shift(self.ctx, overview.shift.shift_id or 0, self, smart_match=smart)
            self.reload()

    def _open_story(self) -> None:
        if self._story_url:
            QDesktopServices.openUrl(QUrl(self._story_url))
