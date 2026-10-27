"""
Volunteer records and the recruitment pipeline (Applicant → Active → Inactive).

Leaders manage everyone; a volunteer may view and edit only their own
profile, and never the fields a leader controls (status, join date,
recruitment source, staff notes).
"""

from __future__ import annotations

import dataclasses
import logging
from dataclasses import dataclass
from typing import Any

from servesync.core.errors import BusinessRuleError
from servesync.models import (
    AssignmentStatus,
    AvailabilitySlot,
    ServiceRecord,
    Volunteer,
    VolunteerParticipation,
    VolunteerStatus,
)
from servesync.services.base import Service
from servesync.services.rules import check_volunteer_transition
from servesync.services.session import Permission, Session

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class StatusChange:
    """Result of a status change, including side effects the UI should report."""

    volunteer: Volunteer
    cancelled_signups: int


class VolunteerService(Service):
    # ----------------------------------------------------------------- leaders

    def register(self, session: Session, volunteer: Volunteer) -> Volunteer:
        """Add a new volunteer (usually as an Applicant awaiting approval)."""
        session.require(Permission.MANAGE_VOLUNTEERS)
        if volunteer.volunteer_id is not None:
            raise BusinessRuleError("This volunteer is already registered.")
        if volunteer.status is VolunteerStatus.INACTIVE:
            raise BusinessRuleError("New volunteers start as Applicant or Active.")
        saved = self._store.volunteers.add(volunteer)
        logger.info("Volunteer #%s registered by account #%s", saved.volunteer_id, session.account_id)
        return saved

    def possible_duplicates(self, session: Session, volunteer: Volunteer) -> list[Volunteer]:
        """People already on file who look like the same person (same phone, or same name + birthday)."""
        session.require(Permission.MANAGE_VOLUNTEERS)
        return self._store.volunteers.find_possible_duplicates(volunteer)

    def change_status(self, session: Session, volunteer_id: int, new_status: VolunteerStatus) -> StatusChange:
        """
        Move a volunteer through the pipeline.

        Archiving (Inactive) also cancels their upcoming sign-ups so those spots
        reopen for others; their past service history is untouched.
        """
        session.require(Permission.MANAGE_VOLUNTEERS)
        with self._store.transaction():
            volunteer = self._store.volunteers.get(volunteer_id)
            check_volunteer_transition(volunteer.status, new_status)
            self._store.volunteers.set_status(volunteer_id, new_status)
            cancelled = 0
            if new_status is VolunteerStatus.INACTIVE:
                upcoming = self._store.assignments.upcoming_scheduled(
                    after=self._clock.now(), volunteer_id=volunteer_id
                )
                cancelled = self._cancel_signups(upcoming)
        logger.info(
            "Volunteer #%s: %s -> %s (%s sign-ups cancelled)",
            volunteer_id,
            volunteer.status.value,
            new_status.value,
            cancelled,
        )
        return StatusChange(self._store.volunteers.get(volunteer_id), cancelled)

    def search(
        self,
        session: Session,
        *,
        status: VolunteerStatus | None = None,
        search: str = "",
        skill: str | None = None,
        available_in: AvailabilitySlot | None = None,
    ) -> list[Volunteer]:
        session.require(Permission.MANAGE_VOLUNTEERS)
        return self._store.volunteers.find_all(status=status, search=search, skill=skill, available_in=available_in)

    def participation_all(self, session: Session) -> list[VolunteerParticipation]:
        """Hours and attendance for everyone (for lists and leaderboards)."""
        session.require(Permission.MANAGE_VOLUNTEERS)
        return self._store.volunteers.participation()

    def delete(self, session: Session, volunteer_id: int) -> None:
        """Permanently remove a record with no history (administrators only)."""
        session.require(Permission.DELETE_RECORDS)
        self._store.volunteers.delete(volunteer_id)
        logger.info("Volunteer #%s deleted by account #%s", volunteer_id, session.account_id)

    # ------------------------------------------------ leaders or self-service

    def get(self, session: Session, volunteer_id: int) -> Volunteer:
        session.require_self_or(Permission.MANAGE_VOLUNTEERS, volunteer_id)
        return self._store.volunteers.get(volunteer_id)

    def update_profile(self, session: Session, volunteer: Volunteer) -> Volunteer:
        """
        Save profile edits. Status always changes through :meth:`change_status`
        (so pipeline rules and cancellations apply), and volunteers editing
        themselves cannot alter leader-controlled fields.
        """
        if volunteer.volunteer_id is None:
            raise BusinessRuleError("Register the volunteer before editing their profile.")
        session.require_self_or(Permission.MANAGE_VOLUNTEERS, volunteer.volunteer_id)
        existing = self._store.volunteers.get(volunteer.volunteer_id)

        protected: dict[str, Any] = {"status": existing.status}
        if not session.can(Permission.MANAGE_VOLUNTEERS):
            protected |= {
                "joined_on": existing.joined_on,
                "recruitment_source": existing.recruitment_source,
                "notes": existing.notes,
            }
        return self._store.volunteers.update(dataclasses.replace(volunteer, **protected))

    def participation(self, session: Session, volunteer_id: int) -> VolunteerParticipation:
        session.require_self_or(Permission.MANAGE_VOLUNTEERS, volunteer_id)
        return self._store.volunteers.get_participation(volunteer_id)

    def history(self, session: Session, volunteer_id: int) -> list[ServiceRecord]:
        """Every sign-up, newest first."""
        session.require_self_or(Permission.MANAGE_VOLUNTEERS, volunteer_id)
        return self._store.assignments.history(volunteer_id)

    def upcoming(self, session: Session, volunteer_id: int) -> list[ServiceRecord]:
        """Scheduled shifts that haven't started yet, soonest first."""
        now = self._clock.now()
        records = [
            record
            for record in self.history(session, volunteer_id)
            if record.assignment.status is AssignmentStatus.SCHEDULED and record.starts_at > now
        ]
        return sorted(records, key=lambda record: record.starts_at)

    def skill_names(self) -> list[str]:
        """All known skills, for pick lists (not sensitive; any signed-in user)."""
        return self._store.skills.list_names()
