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
from datetime import date, timedelta
from typing import Any

from servesync.core.errors import BusinessRuleError
from servesync.core.i18n import tr
from servesync.core.validators import ErrorCollector, parse_date, parse_enum, parse_int
from servesync.models import (
    AssignmentStatus,
    AvailabilitySlot,
    Certification,
    CredentialKind,
    ServiceRecord,
    Volunteer,
    VolunteerParticipation,
    VolunteerStatus,
)
from servesync.models.volunteer import clean_certification_name
from servesync.services.base import PUBLIC_FORM, Service, changed_fields
from servesync.services.rules import HourGoalProgress, check_volunteer_transition, hour_goal_progress
from servesync.services.session import Permission, Session

logger = logging.getLogger(__name__)

MAX_HOUR_GOAL = 2000  # about a full-time year; anything higher is a typo
CERTIFICATION_WARNING_DAYS = 45
#: Profile fields named in the change history when they change (values are never logged).
VOLUNTEER_FIELDS = (
    "first_name",
    "last_name",
    "preferred_name",
    "pronouns",
    "email",
    "phone",
    "birth_date",
    "recruitment_source",
    "skills",
    "availability",
    "emergency_contact_name",
    "emergency_contact_phone",
    "notes",
    "access_needs",
    "referred_by",
)
#: An issue date older than this is almost always a typo in the year.
MAX_CREDENTIAL_AGE_DAYS = 3653


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
            raise BusinessRuleError(tr("This volunteer is already registered."))
        if volunteer.status is VolunteerStatus.INACTIVE:
            raise BusinessRuleError(tr("New volunteers start as Applicant or Active."))
        saved = self._store.volunteers.add(volunteer)
        self._log(session.username, "ADDED", "VOLUNTEER", saved.volunteer_id, saved.full_name)
        logger.info("Volunteer #%s registered by account #%s", saved.volunteer_id, session.account_id)
        return saved

    def apply(self, volunteer: Volunteer) -> Volunteer:
        """
        Someone applies from the sign-in screen, with no account yet. They can only ever
        become an Applicant awaiting review, and the answer never says who is already on file.
        """
        if self._store.volunteers.find_possible_duplicates(volunteer):
            raise BusinessRuleError(tr("We may already have you on file. Please ask a coordinator for help."))
        today = self._clock.now().date()
        application = dataclasses.replace(
            volunteer,
            status=VolunteerStatus.APPLICANT,
            joined_on=min(today, date.today()),
            notes="",
            hour_goal=None,
            hour_goal_due=None,
            volunteer_id=None,
        )
        saved = self._store.volunteers.add(application)
        self._log(PUBLIC_FORM, "ADDED", "VOLUNTEER", saved.volunteer_id, saved.full_name)
        logger.info("Volunteer #%s applied from the sign-in screen", saved.volunteer_id)
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
                for shift_id in self._store.waitlist.shifts_for(volunteer_id):  # nor wait for new ones
                    self._store.waitlist.remove(shift_id, volunteer_id)
            details = f"{volunteer.status.value}>{new_status.value}"
            self._log(session.username, "STATUS", "VOLUNTEER", volunteer_id, volunteer.full_name, details)
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
        name = self._store.volunteers.get(volunteer_id).full_name
        self._store.volunteers.delete(volunteer_id)
        self._log(session.username, "REMOVED", "VOLUNTEER", volunteer_id, name)
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
            raise BusinessRuleError(tr("Register the volunteer before editing their profile."))
        session.require_self_or(Permission.MANAGE_VOLUNTEERS, volunteer.volunteer_id)
        existing = self._store.volunteers.get(volunteer.volunteer_id)

        protected: dict[str, Any] = {"status": existing.status}
        if not session.can(Permission.MANAGE_VOLUNTEERS):
            protected |= {
                "joined_on": existing.joined_on,
                "recruitment_source": existing.recruitment_source,
                "notes": existing.notes,
                "referred_by": existing.referred_by,
            }
        saved = self._store.volunteers.update(dataclasses.replace(volunteer, **protected))
        details = changed_fields(existing, saved, VOLUNTEER_FIELDS)
        if details:
            self._log(session.username, "CHANGED", "VOLUNTEER", saved.volunteer_id, saved.full_name, details)
        return saved

    def set_hour_goal(self, session: Session, volunteer_id: int, hours: object, due: object) -> Volunteer:
        """Set a personal hour goal (format: a whole number and a date; meaning: the date is ahead of us)."""
        session.require_self_or(Permission.MANAGE_VOLUNTEERS, volunteer_id)
        errors = ErrorCollector()
        goal = errors.check("hour_goal", parse_int, hours, tr("Hour goal"), minimum=1, maximum=MAX_HOUR_GOAL)
        day = errors.check("hour_goal_due", parse_date, due, tr("Goal date"))
        today = self._clock.now().date()
        if isinstance(day, date) and day <= today:
            errors.add("hour_goal_due", tr("Choose a goal date after today."))
        errors.raise_if_any()
        volunteer = self._store.volunteers.get(volunteer_id)
        return self._store.volunteers.update(dataclasses.replace(volunteer, hour_goal=goal, hour_goal_due=day))

    def clear_hour_goal(self, session: Session, volunteer_id: int) -> Volunteer:
        session.require_self_or(Permission.MANAGE_VOLUNTEERS, volunteer_id)
        volunteer = self._store.volunteers.get(volunteer_id)
        return self._store.volunteers.update(dataclasses.replace(volunteer, hour_goal=None, hour_goal_due=None))

    def hour_goal_progress(self, session: Session, volunteer_id: int) -> HourGoalProgress | None:
        session.require_self_or(Permission.MANAGE_VOLUNTEERS, volunteer_id)
        return hour_goal_progress(
            self._store.volunteers.get(volunteer_id),
            self._store.assignments.history(volunteer_id),
            self._clock.now().date(),
        )

    def add_certification(
        self,
        session: Session,
        volunteer_id: int,
        name: object,
        expires_on: object,
        *,
        kind: object = CredentialKind.CERTIFICATION,
        issued_on: object = None,
    ) -> Volunteer:
        """
        Record or renew a certification or waiver. Leaders only: a volunteer can't vouch
        for their own. Checks: the expiry is after today, the issue date (when given) is
        not in the future and comes before the expiry, and the issue date isn't more than
        ten years ago (almost always a typo in the year).
        """
        session.require(Permission.MANAGE_VOLUNTEERS)
        today = self._clock.now().date()
        errors = ErrorCollector()
        clean_name = errors.check("certification_name", clean_certification_name, name)
        clean_kind = errors.check("certification_kind", parse_enum, kind, CredentialKind, tr("Type"))
        day = errors.check("certification_expires", parse_date, expires_on, tr("Expiry date"))
        issued = (
            None
            if issued_on in (None, "")
            else errors.check("certification_issued", parse_date, issued_on, tr("Issue date"))
        )
        if isinstance(day, date) and day <= today:
            errors.add("certification_expires", tr("This has already expired. Enter a date after today."))
        if isinstance(issued, date):
            if issued > today:
                errors.add("certification_issued", tr("The issue date can't be in the future."))
            elif (today - issued).days > MAX_CREDENTIAL_AGE_DAYS:
                errors.add("certification_issued", tr("The issue date is more than 10 years ago. Check the year."))
            if isinstance(day, date) and issued >= day:
                errors.add("certification_expires", tr("The expiry date must be after the issue date."))
        errors.raise_if_any()
        self._store.volunteers.save_certification(volunteer_id, Certification(clean_name, day, clean_kind, issued))
        person = self._store.volunteers.get(volunteer_id).full_name
        self._log(session.username, "CHANGED", "VOLUNTEER", volunteer_id, person, f"certifications: {clean_name}")
        return self._store.volunteers.get(volunteer_id)

    def remove_certification(self, session: Session, volunteer_id: int, name: str) -> Volunteer:
        session.require(Permission.MANAGE_VOLUNTEERS)
        self._store.volunteers.remove_certification(volunteer_id, name)
        person = self._store.volunteers.get(volunteer_id).full_name
        self._log(session.username, "CHANGED", "VOLUNTEER", volunteer_id, person, f"certifications: {name}")
        return self._store.volunteers.get(volunteer_id)

    def certification_names(self) -> list[str]:
        """All known certification names, for pick lists."""
        return self._store.volunteers.certification_names()

    def expiring_certifications(
        self, session: Session, *, within_days: int = CERTIFICATION_WARNING_DAYS
    ) -> list[tuple[Volunteer, Certification]]:
        """Active volunteers' certifications that have run out or soon will, soonest first."""
        session.require(Permission.MANAGE_VOLUNTEERS)
        cutoff = self._clock.now().date() + timedelta(days=within_days)
        found = [
            (volunteer, certification)
            for volunteer in self._store.volunteers.find_all(status=VolunteerStatus.ACTIVE)
            for certification in volunteer.certifications
            if certification.expires_on <= cutoff
        ]
        return sorted(found, key=lambda pair: (pair[1].expires_on, pair[0].last_name))

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
