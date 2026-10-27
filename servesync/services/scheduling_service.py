"""
Sign-ups and cancellations — where volunteers and shifts meet.

Every sign-up runs inside one database transaction that starts with
``BEGIN IMMEDIATE`` (a write lock). The capacity check and the insert happen
under that lock, so two coordinators clicking "sign up" for the last spot at
the same moment can never overbook the shift.
"""

from __future__ import annotations

import dataclasses
import logging

from servesync.core.errors import BusinessRuleError
from servesync.models import Assignment, AssignmentStatus, ShiftOverview, Volunteer
from servesync.services.base import Service
from servesync.services.rules import signup_blockers
from servesync.services.session import Permission, Session

logger = logging.getLogger(__name__)


class SchedulingService(Service):
    def why_not_eligible(self, session: Session, shift_id: int, volunteer_id: int) -> list[str]:
        """Reasons the volunteer can't sign up for the shift (empty list = they can)."""
        session.require_self_or(Permission.MANAGE_SCHEDULE, volunteer_id)
        volunteer = self._store.volunteers.get(volunteer_id)
        overview = self._store.shifts.get_overview(shift_id)
        return self._blockers(volunteer, overview)

    def sign_up(self, session: Session, shift_id: int, volunteer_id: int) -> Assignment:
        """
        Sign a volunteer up for a shift. Volunteers may sign themselves up;
        leaders may sign up anyone. A previously cancelled sign-up is reused.
        """
        session.require_self_or(Permission.MANAGE_SCHEDULE, volunteer_id)
        now = self._clock.now()
        with self._store.transaction():  # write lock held from check to insert
            volunteer = self._store.volunteers.get(volunteer_id)
            overview = self._store.shifts.get_overview(shift_id)
            blockers = self._blockers(volunteer, overview)
            if blockers:
                raise BusinessRuleError(" ".join(blockers))

            existing = self._store.assignments.find(shift_id, volunteer_id)
            if existing is not None:  # was cancelled earlier: reactivate it
                saved = self._store.assignments.update(
                    dataclasses.replace(
                        existing, status=AssignmentStatus.SCHEDULED, hours_served=None, signed_up_at=now
                    )
                )
            else:
                saved = self._store.assignments.add(Assignment(shift_id, volunteer_id, signed_up_at=now))
        logger.info("Volunteer #%s signed up for shift #%s by account #%s", volunteer_id, shift_id, session.account_id)
        return saved

    def cancel(self, session: Session, assignment_id: int) -> Assignment:
        """Cancel an upcoming sign-up (frees the spot; the record is kept)."""
        signup = self._store.assignments.get(assignment_id)
        session.require_self_or(Permission.MANAGE_SCHEDULE, signup.volunteer_id)
        if signup.status is not AssignmentStatus.SCHEDULED:
            raise BusinessRuleError(f"Only scheduled sign-ups can be cancelled (this one is {signup.status.label}).")
        shift = self._store.shifts.get(signup.shift_id)
        if shift.has_started(self._clock.now()):
            raise BusinessRuleError("This shift has already started. A coordinator can record a no-show instead.")
        cancelled = self._store.assignments.update(
            dataclasses.replace(signup, status=AssignmentStatus.CANCELLED, hours_served=None)
        )
        logger.info("Sign-up #%s cancelled by account #%s", assignment_id, session.account_id)
        return cancelled

    # ---------------------------------------------------------------- helpers

    def _blockers(self, volunteer: Volunteer, overview: ShiftOverview) -> list[str]:
        volunteer_id = volunteer.volunteer_id or 0
        shift = overview.shift
        shift_id = shift.shift_id or 0
        existing = self._store.assignments.find(shift_id, volunteer_id)
        opportunity = self._store.opportunities.get(shift.opportunity_id)
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
        )
