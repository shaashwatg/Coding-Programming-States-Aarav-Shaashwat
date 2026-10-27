"""
Details of one shift for the browse and calendar screens.

Volunteers see the program, what they'll do, and either a Sign up button or a
plain-language list of reasons they can't — never a mystery error. Leaders see
buttons to open the roster or run Smart Match instead.
"""

from __future__ import annotations

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from servesync.models import AccessNeed, ShiftOverview
from servesync.services import Permission
from servesync.services.rules import describe_access_gaps
from servesync.ui.context import AppContext
from servesync.ui.dialogs.shift_detail import open_shift
from servesync.ui.widgets.common import Panel, format_hours, format_when, guarded, make_button, make_label, set_prop
from servesync.ui.widgets.visuals import ProgramArt


class ShiftInfoPanel(Panel):
    changed = Signal()

    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self._ctx = ctx
        self._overview: ShiftOverview | None = None
        self._story_url = ""
        self.art = ProgramArt(260, 150)
        self.body.addWidget(self.art)
        self.title = make_label("Select a shift", "name", wrap=True)
        self.when = make_label("Choose a shift from the list to see the details here.", "muted", wrap=True)
        self.facts = make_label("", wrap=True)
        self.description = make_label("", wrap=True)
        for widget in (self.title, self.when, self.facts, self.description):
            self.body.addWidget(widget)
        self.story_button = make_button("Watch the story video", kind="link", on_click=self._open_story)
        self.story_button.setToolTip("Opens in your web browser")
        self.body.addWidget(self.story_button)
        self.verdict = make_label("", wrap=True)
        self.body.addWidget(self.verdict)

        actions = QHBoxLayout()
        self.primary = make_button("Sign up", kind="primary", on_click=self._primary)
        self.secondary = make_button("Smart Match", on_click=self._secondary)
        actions.addWidget(self.primary)
        actions.addWidget(self.secondary)
        actions.addStretch(1)
        self.body.addLayout(actions)
        self.body.addStretch(1)
        self._is_leader = ctx.session.can(Permission.MANAGE_SCHEDULE)
        self.primary.setText("Open roster" if self._is_leader else "Sign up")
        self.secondary.setVisible(self._is_leader)
        self.show_shift(None)

    def show_shift(self, overview: ShiftOverview | None) -> None:
        self._overview = overview
        has = overview is not None
        for widget in (self.art, self.facts, self.description, self.primary, self.verdict):
            widget.setVisible(has)
        self.secondary.setVisible(has and self._is_leader)
        self.story_button.setVisible(False)
        if overview is None:
            self.title.setText("Select a shift")
            self.when.setText("Choose a shift from the list to see the details here.")
            return
        services, session = self._ctx.services, self._ctx.session
        shift = overview.shift
        opportunity = services.opportunities.get(session, shift.opportunity_id)
        self.art.show_program(
            overview.category, services.opportunities.photo(session, shift.opportunity_id), opportunity.title
        )
        self.title.setText(opportunity.title)
        self.when.setText(f"{format_when(shift.starts_at, shift.ends_at)} ({format_hours(shift.duration_hours)})")
        skills = ", ".join(sorted(opportunity.required_skills, key=str.casefold)) or "None needed"
        self.facts.setText(
            f"• Where: {opportunity.location}\n"
            f"• Coordinator: {opportunity.coordinator_name}\n"
            f"• Ages {opportunity.min_age}+\n"
            f"• Helpful skills: {skills}\n"
            f"• Spots open: {overview.open_spots} of {shift.capacity}"
            + (f"\n• Access: {access}" if (access := _access_text(opportunity.access_features)) else "")
            + (f"\n• Note: {shift.notes}" if shift.notes else "")
        )
        self.description.setText(opportunity.description)
        self._story_url = opportunity.story_video_url
        self.story_button.setVisible(bool(self._story_url))
        if self._is_leader:
            self.verdict.setText("")
            self.verdict.hide()
            return
        volunteer_id = session.volunteer_id or 0
        reasons = services.scheduling.why_not_eligible(session, shift.shift_id or 0, volunteer_id)
        if reasons:
            set_prop(self.verdict, "role", "concern")
            self.verdict.setText("You can't sign up for this one:\n" + "\n".join(f"• {r}" for r in reasons))
        else:
            volunteer = services.volunteers.get(session, volunteer_id)
            gaps = describe_access_gaps(volunteer.access_needs, opportunity.access_features, opportunity.title)
            set_prop(self.verdict, "role", "ok")
            text = "✓ You can sign up for this shift."
            if gaps:
                text += "\nGood to know: " + "; ".join(g.split(": ", 1)[-1] for g in gaps) + ". Ask the coordinator."
            self.verdict.setText(text)
        self.primary.setEnabled(not reasons)
        self.primary.setToolTip("" if not reasons else "See the reasons above")

    @guarded
    def _primary(self) -> None:
        overview = self._overview
        if overview is None:
            return
        if self._is_leader:
            open_shift(self._ctx, overview.shift.shift_id or 0, self)
        else:
            self._ctx.services.scheduling.sign_up(
                self._ctx.session, overview.shift.shift_id or 0, self._ctx.session.volunteer_id or 0
            )
            self._ctx.changed(
                f"You're signed up for {overview.opportunity_title}, {format_when(overview.shift.starts_at)}."
            )
        self.changed.emit()

    @guarded
    def _secondary(self) -> None:
        if self._overview is not None:
            open_shift(self._ctx, self._overview.shift.shift_id or 0, self, smart_match=True)
            self.changed.emit()

    def _open_story(self) -> None:
        if self._story_url:
            QDesktopServices.openUrl(QUrl(self._story_url))


def _access_text(features: frozenset[AccessNeed]) -> str:
    return ", ".join(need.offer_label for need in AccessNeed if need in features)


def stacked(*widgets: QWidget) -> QWidget:
    holder = QWidget()
    column = QVBoxLayout(holder)
    column.setContentsMargins(0, 0, 0, 0)
    for widget in widgets:
        column.addWidget(widget)
    return holder
