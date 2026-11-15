"""
Details of one shift for the browse and calendar screens.

Volunteers see the program, what they'll do, and either a Sign up button or a
plain-language list of reasons they can't — never a mystery error. Leaders see
buttons to open the roster or run Smart Match instead.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from servesync.core.i18n import tr, tr_n
from servesync.models import AccessNeed, RoleOverview, ShiftOverview
from servesync.services import Permission
from servesync.services.rules import best_role, describe_access_gaps
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
        self.title = make_label(tr("Select a shift"), "name", wrap=True)
        self.when = make_label(tr("Choose a shift from the list to see the details here."), "muted", wrap=True)
        self.facts = make_label("", wrap=True)
        self.description = make_label("", wrap=True)
        for widget in (self.title, self.when, self.facts, self.description):
            self.body.addWidget(widget)
        self.story_button = make_button(tr("Watch the story video"), kind="link", on_click=self._open_story)
        self.story_button.setToolTip(tr("Opens in your web browser"))
        self.body.addWidget(self.story_button)
        self.verdict = make_label("", wrap=True)
        self.body.addWidget(self.verdict)
        # Volunteers choose a role when a shift has several; ServeSync preselects the best fit for their skills.
        self.role_label = make_label(tr("Role"), "hint")
        self.role_box = QComboBox()
        self.role_box.setAccessibleName(tr("Role"))
        self.body.addWidget(self.role_label)
        self.body.addWidget(self.role_box)
        self._mode = "sign_up"  # or "join" / "leave" the waitlist

        actions = QHBoxLayout()
        self.primary = make_button(tr("Sign up"), kind="secondary", on_click=self._primary)
        self.secondary = make_button(tr("Smart Match"), on_click=self._secondary)
        actions.addWidget(self.primary)
        actions.addWidget(self.secondary)
        actions.addStretch(1)
        self.body.addLayout(actions)
        self.body.addStretch(1)
        self._is_leader = ctx.session.can(Permission.MANAGE_SCHEDULE)
        self.primary.setText(tr("Open roster") if self._is_leader else tr("Sign up"))
        self.secondary.setVisible(self._is_leader)
        self.show_shift(None)

    def show_shift(self, overview: ShiftOverview | None) -> None:
        self._overview = overview
        has = overview is not None
        for widget in (self.art, self.facts, self.description, self.primary, self.verdict):
            widget.setVisible(has)
        self.role_label.hide()
        self.role_box.hide()
        self.secondary.setVisible(has and self._is_leader)
        self.story_button.setVisible(False)
        if overview is None:
            self.title.setText(tr("Select a shift"))
            self.when.setText(tr("Choose a shift from the list to see the details here."))
            return
        services, session = self._ctx.services, self._ctx.session
        shift = overview.shift
        opportunity = services.opportunities.get(session, shift.opportunity_id)
        self.art.show_program(
            overview.category, services.opportunities.photo(session, shift.opportunity_id), opportunity.title
        )
        self.title.setText(opportunity.title)
        self.when.setText(f"{format_when(shift.starts_at, shift.ends_at)} ({format_hours(shift.duration_hours)})")
        roles = services.scheduling.roles(session, shift.shift_id or 0)
        skills = ", ".join(sorted(opportunity.required_skills, key=str.casefold)) or tr("None needed")
        self.facts.setText(
            tr(
                (
                    "• Where: {location}\n• Coordinator: {coordinator_name}\n• Ages "
                    "{min_age}+\n• Helpful skills: {skills}\n• Spots open: {open_spots} of "
                    "{capacity}"
                ),
                location=opportunity.location,
                coordinator_name=opportunity.coordinator_name,
                min_age=opportunity.min_age,
                skills=skills,
                open_spots=overview.open_spots,
                capacity=shift.capacity,
            )
            + (
                "\n" + tr("• Access: {access}", access=access)
                if (access := _access_text(opportunity.access_features))
                else ""
            )
            + ("\n" + tr("• Note: {notes}", notes=shift.notes) if shift.notes else "")
            + ("\n" + tr("• Roles: {roles}", roles=_roles_text(roles)) if len(roles) > 1 else "")
        )
        self.description.setText(opportunity.description)
        self._story_url = opportunity.story_video_url
        self.story_button.setVisible(bool(self._story_url))
        if self._is_leader:
            self.verdict.setText("")
            self.verdict.hide()
            return
        volunteer_id = session.volunteer_id or 0
        shift_id = shift.shift_id or 0
        reasons = services.scheduling.why_not_eligible(session, shift_id, volunteer_id)
        place = services.scheduling.waitlist_position(session, shift_id, volunteer_id)
        self._mode = "sign_up"
        self.primary.setText(tr("Sign up"))
        if place is not None:
            self._mode = "leave"
            set_prop(self.verdict, "role", "lead")
            self.verdict.setText(
                tr(
                    "You're number {place} on the waitlist. If a spot opens, you'll be signed up "
                    "automatically and see a note on Home.",
                    place=place,
                )
            )
            self.primary.setText(tr("Leave waitlist"))
            reasons = []
        elif reasons and not services.scheduling.why_not_waitlist(session, shift_id, volunteer_id):
            self._mode = "join"
            set_prop(self.verdict, "role", "lead")
            self.verdict.setText(tr("This shift is full. Join the waitlist and you'll be signed up if a spot opens."))
            self.primary.setText(tr("Join waitlist"))
            reasons = []
        elif reasons:
            set_prop(self.verdict, "role", "concern")
            self.verdict.setText(tr("You can't sign up for this one:\n") + "\n".join(f"• {r}" for r in reasons))
        else:
            self._show_role_choice(roles, services.volunteers.get(session, volunteer_id).skills)
            volunteer = services.volunteers.get(session, volunteer_id)
            gaps = describe_access_gaps(volunteer.access_needs, opportunity.access_features, opportunity.title)
            set_prop(self.verdict, "role", "ok")
            text = tr("✓ You can sign up for this shift.")
            if gaps:
                text += (
                    tr("\nGood to know: ")
                    + "; ".join(g.split(": ", 1)[-1] for g in gaps)
                    + tr(". Ask the coordinator.")
                )
            self.verdict.setText(text)
        self.primary.setEnabled(not reasons)
        self.primary.setToolTip("" if not reasons else tr("See the reasons above"))

    @guarded
    def _primary(self) -> None:
        overview = self._overview
        if overview is None:
            return
        shift_id, volunteer_id = overview.shift.shift_id or 0, self._ctx.session.volunteer_id or 0
        scheduling = self._ctx.services.scheduling
        if self._is_leader:
            open_shift(self._ctx, shift_id, self)
        elif self._mode == "join":
            place = scheduling.join_waitlist(self._ctx.session, shift_id, volunteer_id)
            self._ctx.changed(tr("You're on the waitlist, number {place}.", place=place))
        elif self._mode == "leave":
            scheduling.leave_waitlist(self._ctx.session, shift_id, volunteer_id)
            self._ctx.changed(tr("You left the waitlist."))
        else:
            role_id = self.role_box.currentData() if self.role_box.isVisible() else None
            scheduling.sign_up(self._ctx.session, shift_id, volunteer_id, role_id)
            self._ctx.changed(
                tr(
                    "You're signed up for {opportunity_title}, {format_when}.",
                    opportunity_title=overview.opportunity_title,
                    format_when=format_when(overview.shift.starts_at),
                )
            )
        self.changed.emit()

    def _show_role_choice(self, roles: list[RoleOverview], skills: frozenset[str]) -> None:
        """List the roles this person can take, best fit first; hidden when there's only one choice."""
        self.role_box.clear()
        suggested = best_role(roles, skills)
        choices = [role for role in roles if not role.is_full and role.role.fits(skills)]
        for role in sorted(choices, key=lambda role: role is not suggested):
            self.role_box.addItem(
                tr_n(
                    "{role} ({count} spot open)",
                    "{role} ({count} spots open)",
                    role.open_spots,
                    role=role.role.display_name,
                ),
                role.role.role_id,
            )
        several = len(choices) > 1
        self.role_label.setVisible(several)
        self.role_box.setVisible(several)

    @guarded
    def _secondary(self) -> None:
        if self._overview is not None:
            open_shift(self._ctx, self._overview.shift.shift_id or 0, self, smart_match=True)
            self.changed.emit()

    def _open_story(self) -> None:
        if self._story_url:
            QDesktopServices.openUrl(QUrl(self._story_url))


def _roles_text(roles: list[RoleOverview]) -> str:
    """'Registration 2 of 2; Water station 4 of 6 (needs First Aid/CPR)'."""
    return "; ".join(
        tr(
            "{role} {filled} of {capacity}",
            role=role.role.display_name,
            filled=role.filled,
            capacity=role.role.capacity,
        )
        + (tr(" (needs {skill})", skill=role.role.required_skill) if role.role.required_skill else "")
        for role in roles
    )


def _access_text(features: frozenset[AccessNeed]) -> str:
    return ", ".join(need.offer_label for need in AccessNeed if need in features)


def stacked(*widgets: QWidget) -> QWidget:
    holder = QWidget()
    column = QVBoxLayout(holder)
    column.setContentsMargins(0, 0, 0, 0)
    for widget in widgets:
        column.addWidget(widget)
    return holder


def scrollable(panel: QWidget) -> QScrollArea:
    """
    Wrap a details panel so it scrolls instead of squeezing. Beside a table in a
    splitter, a long description at large text sizes would otherwise be pressed
    into too little height and its lines would overlap.
    """
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    area.setWidget(panel)
    area.setMinimumWidth(300)
    return area
