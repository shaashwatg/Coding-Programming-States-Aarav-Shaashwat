"""
Sign-ups, cancellations, roles within a shift, and waitlists: where volunteers and shifts meet.

Every sign-up runs inside one database transaction that starts with
``BEGIN IMMEDIATE`` (a write lock). The capacity check and the insert happen
under that lock, so two coordinators clicking "sign up" for the last spot at
the same moment can never overbook the shift or one of its roles.

Waitlist: when a shift is full, an eligible volunteer can join its waitlist.
When a spot opens (someone cancels, a volunteer is archived, or a leader adds
room), the longest-waiting person who still qualifies is signed up
automatically and finds a notice on their Home page. Someone who no longer
qualifies (for example, they booked another shift at that time) is skipped
but stays on the list, so they aren't silently dropped.
"""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Iterable, Sequence

from servesync.core.errors import BusinessRuleError
from servesync.core.i18n import tr
from servesync.models import (
    Assignment,
    AssignmentStatus,
    Notice,
    NoticeKind,
    RoleOverview,
    ShiftOverview,
    ShiftRole,
    Volunteer,
    WaitlistEntry,
)
from servesync.services.base import WAITLIST, Service
from servesync.services.rules import (
    best_role,
    check_roles,
    no_fitting_role_message,
    role_problems,
    signup_blockers,
    waitlist_blockers,
)
from servesync.services.session import Permission, Session

logger = logging.getLogger(__name__)


class SchedulingService(Service):
    # ------------------------------------------------------------ sign-ups

    def why_not_eligible(
        self, session: Session, shift_id: int, volunteer_id: int, role_id: int | None = None
    ) -> list[str]:
        """Reasons the volunteer can't sign up for the shift, or for one role of it (empty list = they can)."""
        session.require_self_or(Permission.MANAGE_SCHEDULE, volunteer_id)
        volunteer = self._store.volunteers.get(volunteer_id)
        overview = self._store.shifts.get_overview(shift_id)
        return self._blockers(volunteer, overview, self._store.shifts.roles(shift_id), role_id)

    def roles(self, session: Session, shift_id: int) -> list[RoleOverview]:
        """The shift's roles with how many spots each has taken (anyone signed in may see them)."""
        del session  # every signed-in person may see a shift's roles
        return self._store.shifts.roles(shift_id)

    def suggested_role(self, session: Session, shift_id: int, volunteer_id: int) -> RoleOverview | None:
        """The role ServeSync would pick for this person, or None if no open role fits."""
        session.require_self_or(Permission.MANAGE_SCHEDULE, volunteer_id)
        volunteer = self._store.volunteers.get(volunteer_id)
        return best_role(self._store.shifts.roles(shift_id), volunteer.skills)

    def sign_up(self, session: Session, shift_id: int, volunteer_id: int, role_id: int | None = None) -> Assignment:
        """
        Sign a volunteer up for a shift, in the chosen role or the best one for their skills.
        Volunteers may sign themselves up; leaders may sign up anyone. A previously
        cancelled sign-up is reused, so the history stays one row per person per shift.
        """
        session.require_self_or(Permission.MANAGE_SCHEDULE, volunteer_id)
        with self._store.transaction():  # write lock held from check to insert
            saved = self._sign_up_locked(shift_id, volunteer_id, role_id)
            self._log(session.username, "ADDED", "SIGN_UP", saved.assignment_id, self._signup_label(saved))
        logger.info("Volunteer #%s signed up for shift #%s by account #%s", volunteer_id, shift_id, session.account_id)
        return saved

    def cancel(self, session: Session, assignment_id: int) -> Assignment:
        """Cancel an upcoming sign-up. The spot goes to the next person waiting, if anyone."""
        signup = self._store.assignments.get(assignment_id)
        session.require_self_or(Permission.MANAGE_SCHEDULE, signup.volunteer_id)
        if signup.status is not AssignmentStatus.SCHEDULED:
            raise BusinessRuleError(
                tr("Only scheduled sign-ups can be cancelled (this one is {label}).", label=signup.status.label)
            )
        shift = self._store.shifts.get(signup.shift_id)
        if shift.has_started(self._clock.now()):
            raise BusinessRuleError(tr("This shift has already started. A coordinator can record a no-show instead."))
        with self._store.transaction():
            cancelled = self._store.assignments.update(
                dataclasses.replace(signup, status=AssignmentStatus.CANCELLED, hours_served=None)
            )
            self._log(
                session.username, "STATUS", "SIGN_UP", assignment_id, self._signup_label(signup), "SCHEDULED>CANCELLED"
            )
            self.fill_from_waitlist(signup.shift_id)
        logger.info("Sign-up #%s cancelled by account #%s", assignment_id, session.account_id)
        return cancelled

    def change_role(self, session: Session, assignment_id: int, role_id: int) -> Assignment:
        """Move someone to another role on the same shift (leaders only, before the shift starts)."""
        session.require(Permission.MANAGE_SCHEDULE)
        with self._store.transaction():
            signup = self._store.assignments.get(assignment_id)
            if signup.status is not AssignmentStatus.SCHEDULED:
                raise BusinessRuleError(tr("Only scheduled sign-ups can change role."))
            if self._store.shifts.get(signup.shift_id).has_started(self._clock.now()):
                raise BusinessRuleError(tr("This shift has already started."))
            role = self._role_on_shift(signup.shift_id, role_id)
            if role.role.role_id == signup.role_id:
                return signup
            problems = role_problems(role, self._store.volunteers.get(signup.volunteer_id))
            if problems:
                raise BusinessRuleError(" ".join(problems))
            saved = self._store.assignments.update(dataclasses.replace(signup, role_id=role_id))
            self._log(session.username, "CHANGED", "SIGN_UP", assignment_id, self._signup_label(saved), "role")
            return saved

    # --------------------------------------------------------------- roles

    def set_roles(self, session: Session, shift_id: int, roles: Sequence[ShiftRole]) -> list[RoleOverview]:
        """
        Replace a shift's roles (leaders only, before it starts). The shift's capacity
        becomes the roles' total; if that adds room, people on the waitlist move up.
        """
        session.require(Permission.MANAGE_SCHEDULE)
        with self._store.transaction():
            if self._store.shifts.get(shift_id).has_started(self._clock.now()):
                raise BusinessRuleError(tr("This shift has already started, so its roles can't change."))
            current = self._store.shifts.roles(shift_id)
            check_roles(roles, current)
            saved = self._store.shifts.replace_roles(shift_id, list(roles))
            label = self._store.shifts.get_overview(shift_id).opportunity_title
            self._log(session.username, "CHANGED", "SHIFT", shift_id, label, "roles")
            self.fill_from_waitlist(shift_id)
        logger.info("Roles for shift #%s set by account #%s", shift_id, session.account_id)
        return saved

    # ------------------------------------------------------------ waitlist

    def join_waitlist(self, session: Session, shift_id: int, volunteer_id: int) -> int:
        """Join a full shift's waitlist. Returns the person's place in line (1 = next)."""
        session.require_self_or(Permission.MANAGE_SCHEDULE, volunteer_id)
        with self._store.transaction():
            problems = self._waitlist_problems(shift_id, volunteer_id)
            if problems:
                raise BusinessRuleError(" ".join(problems))
            self._store.waitlist.add(shift_id, volunteer_id, self._clock.now())
        logger.info("Volunteer #%s joined the waitlist for shift #%s", volunteer_id, shift_id)
        return self.waitlist_position(session, shift_id, volunteer_id) or 1

    def why_not_waitlist(self, session: Session, shift_id: int, volunteer_id: int) -> list[str]:
        """Reasons the volunteer can't join this shift's waitlist (empty list = they can)."""
        session.require_self_or(Permission.MANAGE_SCHEDULE, volunteer_id)
        return self._waitlist_problems(shift_id, volunteer_id)

    def leave_waitlist(self, session: Session, shift_id: int, volunteer_id: int) -> None:
        session.require_self_or(Permission.MANAGE_SCHEDULE, volunteer_id)
        if not self._store.waitlist.remove(shift_id, volunteer_id):
            raise BusinessRuleError(tr("You're not on the waitlist for this shift."))

    def waitlist_position(self, session: Session, shift_id: int, volunteer_id: int) -> int | None:
        """The person's place in line (1 = next), or None if they aren't waiting."""
        session.require_self_or(Permission.MANAGE_SCHEDULE, volunteer_id)
        for place, entry in enumerate(self._store.waitlist.entries(shift_id), start=1):
            if entry.volunteer_id == volunteer_id:
                return place
        return None

    def waitlist(self, session: Session, shift_id: int) -> list[WaitlistEntry]:
        """Everyone waiting for a shift, in order (leaders only: it lists names)."""
        session.require(Permission.MANAGE_SCHEDULE)
        return self._store.waitlist.entries(shift_id)

    def fill_from_waitlist(self, shift_id: int) -> list[Assignment]:
        """
        Give open spots to the people waiting longest who still qualify, and leave each
        a notice. Called after anything that frees room. Runs inside the caller's
        transaction, so the freed spot can't be taken by someone else in between.
        """
        overview = self._store.shifts.get_overview(shift_id)
        now = self._clock.now()
        if overview.shift.has_started(now) or not overview.opportunity_status.accepts_signups:
            return []
        promoted: list[Assignment] = []
        for entry in self._store.waitlist.entries(shift_id):
            if self._store.shifts.get_overview(shift_id).is_full:
                break
            volunteer = self._store.volunteers.get(entry.volunteer_id)
            current = self._store.shifts.get_overview(shift_id)
            if self._blockers(volunteer, current, self._store.shifts.roles(shift_id), None):
                continue  # can't take this spot (e.g. no fitting role, or now busy then); keeps their place
            promoted.append(self._sign_up_locked(shift_id, entry.volunteer_id, None))
            self._log(WAITLIST, "ADDED", "SIGN_UP", promoted[-1].assignment_id, self._signup_label(promoted[-1]))
            self._store.waitlist.remove(shift_id, entry.volunteer_id)
            self._store.notices.add(entry.volunteer_id, NoticeKind.WAITLIST_PROMOTED, shift_id, now)
            logger.info("Volunteer #%s moved from the waitlist into shift #%s", entry.volunteer_id, shift_id)
        return promoted

    def fill_from_waitlists(self, shift_ids: Iterable[int]) -> None:
        for shift_id in sorted(set(shift_ids)):
            self.fill_from_waitlist(shift_id)

    # ------------------------------------------------------------- notices

    def notices(self, session: Session, volunteer_id: int) -> list[Notice]:
        """Messages waiting on a volunteer's Home page, newest first."""
        session.require_self_or(Permission.MANAGE_SCHEDULE, volunteer_id)
        return self._store.notices.for_volunteer(volunteer_id)

    def dismiss_notice(self, session: Session, notice_id: int) -> None:
        owner = self._store.notices.owner(notice_id)
        if owner is None:
            raise BusinessRuleError(tr("That message was already removed."))
        session.require_self_or(Permission.MANAGE_SCHEDULE, owner)
        self._store.notices.dismiss(notice_id)

    # ---------------------------------------------------------------- helpers

    def _sign_up_locked(self, shift_id: int, volunteer_id: int, role_id: int | None) -> Assignment:
        """The sign-up itself; the caller holds the write lock."""
        now = self._clock.now()
        volunteer = self._store.volunteers.get(volunteer_id)
        overview = self._store.shifts.get_overview(shift_id)
        roles = self._store.shifts.roles(shift_id)
        blockers = self._blockers(volunteer, overview, roles, role_id)
        if blockers:
            raise BusinessRuleError(" ".join(blockers))
        role = self._role_on_shift(shift_id, role_id) if role_id is not None else best_role(roles, volunteer.skills)
        assert role is not None  # _blockers explains the case where no role fits
        chosen = role.role.role_id

        existing = self._store.assignments.find(shift_id, volunteer_id)
        if existing is not None:  # was cancelled earlier: reactivate it
            saved = self._store.assignments.update(
                dataclasses.replace(
                    existing, status=AssignmentStatus.SCHEDULED, hours_served=None, signed_up_at=now, role_id=chosen
                )
            )
        else:
            saved = self._store.assignments.add(Assignment(shift_id, volunteer_id, signed_up_at=now, role_id=chosen))
        self._store.waitlist.remove(shift_id, volunteer_id)  # signed up another way: no longer waiting
        return saved

    def _waitlist_problems(self, shift_id: int, volunteer_id: int) -> list[str]:
        volunteer = self._store.volunteers.get(volunteer_id)
        overview = self._store.shifts.get_overview(shift_id)
        roles = self._store.shifts.roles(shift_id)
        if volunteer_id in {entry.volunteer_id for entry in self._store.waitlist.entries(shift_id)}:
            return [tr("You're already on the waitlist for this shift.")]
        # Ask "what would stop them if there were room?" by pretending every spot were free.
        if_room = self._blockers(
            volunteer,
            dataclasses.replace(overview, filled=0),
            [dataclasses.replace(role, filled=0) for role in roles],
            None,
        )
        open_to_them = not overview.is_full and best_role(roles, volunteer.skills) is not None
        return waitlist_blockers(if_room, shift_is_open_to_them=open_to_them)

    def _role_on_shift(self, shift_id: int, role_id: int) -> RoleOverview:
        for role in self._store.shifts.roles(shift_id):
            if role.role.role_id == role_id:
                return role
        raise BusinessRuleError(tr("That role isn't part of this shift. Please choose again."))

    def _blockers(
        self,
        volunteer: Volunteer,
        overview: ShiftOverview,
        roles: Sequence[RoleOverview],
        role_id: int | None,
    ) -> list[str]:
        volunteer_id = volunteer.volunteer_id or 0
        shift = overview.shift
        shift_id = shift.shift_id or 0
        existing = self._store.assignments.find(shift_id, volunteer_id)
        opportunity = self._store.opportunities.get(shift.opportunity_id)
        if role_id is not None:
            chosen = next((role for role in roles if role.role.role_id == role_id), None)
            role_reasons = (
                role_problems(chosen, volunteer)
                if chosen is not None
                else [tr("That role isn't part of this shift. Please choose again.")]
            )
        elif best_role(roles, volunteer.skills) is None:
            role_reasons = [no_fitting_role_message(volunteer, roles)]
        else:
            role_reasons = []
        return signup_blockers(
            volunteer=volunteer,
            overview=overview,
            min_age=opportunity.min_age,
            now=self._clock.now(),
            already_signed_up=existing is not None and existing.status.holds_a_spot,
            has_conflict=bool(
                self._store.assignments.conflicting_shifts(
                    volunteer_id, shift.starts_at, shift.ends_at, exclude_shift_id=shift_id
                )
            ),
            required_certifications=opportunity.required_certifications,
            role_reasons=role_reasons,
        )
