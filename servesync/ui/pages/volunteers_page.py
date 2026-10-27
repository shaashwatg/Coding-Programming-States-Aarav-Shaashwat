"""
Volunteers: search, review applicants, and keep records current.

Master-detail layout: the list on the left stays put while the right side
shows everything about the selected person, so coordinators never lose
their place.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLineEdit, QSplitter, QVBoxLayout, QWidget

from servesync.models import AccessNeed, AssignmentStatus, Volunteer, VolunteerParticipation, VolunteerStatus
from servesync.services import Permission
from servesync.ui.context import AppContext
from servesync.ui.dialogs.volunteer_dialog import VolunteerDialog
from servesync.ui.pages.base import Page
from servesync.ui.theme import current_palette
from servesync.ui.widgets.common import (
    EnumComboBox,
    PageHeader,
    Panel,
    confirm,
    format_date,
    format_hours,
    format_when,
    guarded,
    make_button,
    make_label,
)
from servesync.ui.widgets.table import Column, RecordTable


def status_color(status: VolunteerStatus) -> str | None:
    palette = current_palette()
    return {VolunteerStatus.APPLICANT: palette.attention, VolunteerStatus.INACTIVE: palette.text_muted}.get(status)


def describe_availability(volunteer: Volunteer) -> str:
    slots = volunteer.sorted_availability()
    return ", ".join(slot.label for slot in slots) if slots else "Not listed yet"


def describe_participation(stats: VolunteerParticipation | None) -> str:
    if stats is None or (stats.shifts_attended == 0 and stats.no_shows == 0 and stats.upcoming_shifts == 0):
        return "No shifts yet."
    reliability = (
        f"showed up {stats.reliability:.0%} of the time" if stats.reliability is not None else "no completed shifts yet"
    )
    shifts = f"{stats.shifts_attended} shift{'s' if stats.shifts_attended != 1 else ''}"
    return f"{format_hours(stats.total_hours)} over {shifts}, {reliability}, {stats.upcoming_shifts} upcoming."


class VolunteerProfileCard(Panel):
    """Everything about one volunteer, as short labeled lines (easy to scan)."""

    def __init__(self, *, show_notes: bool) -> None:
        super().__init__()
        self._show_notes = show_notes
        self.name = make_label("", "name", wrap=True)
        self.status = make_label("", "muted", wrap=True)
        self.lines = make_label("", wrap=True, selectable=True)
        for widget in (self.name, self.status, self.lines):
            self.body.addWidget(widget)

    def show_volunteer(self, volunteer: Volunteer, stats: VolunteerParticipation | None) -> None:
        self.name.setText(volunteer.name_with_pronouns)
        age = volunteer.age()
        minor = " (minor; guardian contact on file)" if volunteer.is_minor() else ""
        self.status.setText(
            f"{volunteer.status.label} volunteer since {format_date(volunteer.joined_on)}. Age {age}{minor}."
        )
        emergency = (
            f"{volunteer.emergency_contact_name}, {volunteer.display_emergency_phone}"
            if volunteer.emergency_contact_name
            else "None listed"
        )
        lines = [
            f"• Email: {volunteer.email}",
            f"• Phone: {volunteer.display_phone}",
            f"• Emergency contact: {emergency}",
            f"• Skills: {', '.join(volunteer.sorted_skills()) or 'None listed yet'}",
            f"• Usually free: {describe_availability(volunteer)}",
            f"• Service: {describe_participation(stats)}",
        ]
        if volunteer.preferred_name:
            lines.insert(0, f"• Legal name (for safety records): {volunteer.legal_name}")
        if volunteer.access_needs:
            needs = ", ".join(need.label for need in AccessNeed if need in volunteer.access_needs)
            lines.append(f"• What helps: {needs}")
        if self._show_notes:
            lines.append(f"• Heard about us: {volunteer.recruitment_source.label}")
            if volunteer.notes:
                lines.append(f"• Notes: {volunteer.notes}")
        self.lines.setText("\n".join(lines))
        self.setAccessibleName(f"Profile of {volunteer.full_name}")


class VolunteersPage(Page):
    key = "volunteers"
    title = "Volunteers"
    icon_name = "users"

    def __init__(self, ctx: AppContext) -> None:
        super().__init__(ctx)
        self._stats: dict[int, VolunteerParticipation] = {}
        self.layout_.addWidget(
            PageHeader(
                "Volunteers",
                "Search everyone, approve applicants, and keep contact details current. "
                "Double-click a person to edit their profile.",
            )
        )
        filters = QHBoxLayout()
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search by name, email, or phone")
        self.search_box.setAccessibleName("Search volunteers")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.textChanged.connect(lambda _text: self.reload())
        self.status_filter: EnumComboBox[VolunteerStatus] = EnumComboBox(
            VolunteerStatus, all_label="Everyone", label=lambda status: f"{status.label}s"
        )
        self.status_filter.setAccessibleName("Filter by status")
        self.status_filter.currentIndexChanged.connect(lambda _index: self.reload())
        self.skill_filter = QComboBox()
        self.skill_filter.setAccessibleName("Filter by skill")
        self.skill_filter.currentIndexChanged.connect(lambda _index: self.reload())
        filters.addWidget(self.search_box, 2)
        filters.addWidget(self.status_filter, 1)
        filters.addWidget(self.skill_filter, 1)
        self.layout_.addLayout(filters)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.table: RecordTable[Volunteer] = RecordTable(
            [
                Column("Name", lambda v: f"{v.last_name}, {v.given_name}", stretch=True),
                Column("Status", lambda v: v.status.label, color=lambda v: status_color(v.status)),
                Column("Phone", lambda v: v.display_phone),
                Column(
                    "Hours",
                    lambda v: format_hours(self._hours(v)),
                    sort=lambda v: self._hours(v),
                    align_right=True,
                ),
            ],
            empty_message="No volunteers match. Try clearing the search or filters.",
            accessible_name="Volunteer list",
        )
        self.table.selection_changed.connect(lambda _v: self._show_selected())
        self.table.activated.connect(lambda _v: self._edit())
        splitter.addWidget(self.table)

        right = QWidget()
        right_column = QVBoxLayout(right)
        right_column.setContentsMargins(12, 0, 0, 0)
        self.card = VolunteerProfileCard(show_notes=True)
        right_column.addWidget(self.card)
        actions = QHBoxLayout()
        self.edit_button = make_button("Edit profile", on_click=self._edit)
        self.approve_button = make_button(
            "Approve", kind="primary", on_click=lambda: self._change(VolunteerStatus.ACTIVE)
        )
        self.archive_button = make_button("Archive", on_click=lambda: self._change(VolunteerStatus.INACTIVE))
        self.delete_button = make_button("Delete", kind="danger", on_click=self._delete)
        for button in (self.edit_button, self.approve_button, self.archive_button, self.delete_button):
            actions.addWidget(button)
        actions.addStretch(1)
        right_column.addLayout(actions)
        self.history = Panel("Recent service")
        self.history_text = make_label("", wrap=True)
        self.history.body.addWidget(self.history_text)
        right_column.addWidget(self.history)
        right_column.addStretch(1)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        self.layout_.addWidget(splitter, 1)
        self._show_selected()

    def _hours(self, volunteer: Volunteer) -> float:
        stats = self._stats.get(volunteer.volunteer_id or 0)
        return stats.total_hours if stats else 0.0

    def apply_options(self, **options: Any) -> None:
        status = options.get("status")
        if status:
            self.status_filter.set_value(VolunteerStatus(status))

    def refresh(self) -> None:
        services, session = self.ctx.services, self.ctx.session
        current_skill = self.skill_filter.currentData()
        self.skill_filter.blockSignals(True)
        self.skill_filter.clear()
        self.skill_filter.addItem("Any skill", None)
        for name in services.volunteers.skill_names():
            self.skill_filter.addItem(name, name)
        self.skill_filter.setCurrentIndex(max(self.skill_filter.findData(current_skill), 0))
        self.skill_filter.blockSignals(False)

        self._stats = {p.volunteer_id: p for p in services.volunteers.participation_all(session)}
        volunteers = services.volunteers.search(
            session,
            status=self.status_filter.value(),
            search=self.search_box.text() if self.search_box else "",
            skill=self.skill_filter.currentData(),
        )
        self.table.set_records(volunteers, keep_selection=lambda v: v.volunteer_id)
        if self.table.selected() is None:
            self.table.select_first()
        self._show_selected()

    def _show_selected(self) -> None:
        volunteer = self.table.selected()
        has = volunteer is not None
        for widget in (self.card, self.history, self.edit_button):
            widget.setVisible(has)
        self.approve_button.setVisible(False)
        self.archive_button.setVisible(False)
        self.delete_button.setVisible(False)
        if volunteer is None:
            return
        stats = self._stats.get(volunteer.volunteer_id or 0)
        self.card.show_volunteer(volunteer, stats)
        status = volunteer.status
        self.approve_button.setVisible(status is not VolunteerStatus.ACTIVE)
        self.approve_button.setText("Approve" if status is VolunteerStatus.APPLICANT else "Reactivate")
        self.archive_button.setVisible(status is not VolunteerStatus.INACTIVE)
        self.archive_button.setText("Decline" if status is VolunteerStatus.APPLICANT else "Archive")
        can_delete = self.ctx.session.can(Permission.DELETE_RECORDS) and (stats is None or stats.total_hours == 0)
        self.delete_button.setVisible(can_delete)
        records = self.ctx.services.volunteers.history(self.ctx.session, volunteer.volunteer_id or 0)[:5]
        if records:
            self.history_text.setText(
                "\n".join(
                    f"• {format_when(r.starts_at)}: {r.opportunity_title} ({r.assignment.status.label.lower()}"
                    + (
                        f", {format_hours(r.assignment.counted_hours)})"
                        if r.assignment.status is AssignmentStatus.ATTENDED
                        else ")"
                    )
                    for r in records
                )
            )
        else:
            self.history_text.setText("No shifts yet. Use Smart Match from any shift to find them a good first fit.")

    @guarded
    def _edit(self) -> None:
        volunteer = self.table.selected()
        if volunteer is None:
            return
        dialog = VolunteerDialog(self.ctx, volunteer, self)
        if dialog.exec() and dialog.saved is not None:
            self.ctx.changed(f"Saved {dialog.saved.full_name}'s profile.")

    @guarded
    def _change(self, status: VolunteerStatus) -> None:
        volunteer = self.table.selected()
        if volunteer is None:
            return
        verb = {
            VolunteerStatus.ACTIVE: "approve" if volunteer.status is VolunteerStatus.APPLICANT else "reactivate"
        }.get(status, "archive")
        detail = (
            " Their upcoming sign-ups will be cancelled so others can take those spots. Their history is kept."
            if status is VolunteerStatus.INACTIVE and volunteer.status is VolunteerStatus.ACTIVE
            else ""
        )
        if not confirm(
            self, f"{verb.title()} volunteer", f"{verb.title()} {volunteer.full_name}?{detail}", verb.title()
        ):
            return
        result = self.ctx.services.volunteers.change_status(self.ctx.session, volunteer.volunteer_id or 0, status)
        extra = f" Cancelled {result.cancelled_signups} upcoming sign-up(s)." if result.cancelled_signups else ""
        self.ctx.changed(f"{volunteer.full_name} is now {status.label}.{extra}")

    @guarded
    def _delete(self) -> None:
        volunteer = self.table.selected()
        if volunteer is None or not confirm(
            self,
            "Delete volunteer",
            f"Permanently delete {volunteer.full_name}? This can't be undone. "
            "(People with service history can only be archived.)",
            "Delete permanently",
        ):
            return
        self.ctx.services.volunteers.delete(self.ctx.session, volunteer.volunteer_id or 0)
        self.ctx.changed(f"Deleted {volunteer.full_name}.")
