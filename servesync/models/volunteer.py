"""
Volunteer domain model and availability slots.

A ``Volunteer`` validates itself the moment it is constructed (and again on
``dataclasses.replace``), so an invalid volunteer object can never exist
anywhere in the program — not in the UI, not in a report, not in the database.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime

from servesync.config import ADULT_AGE, MINIMUM_VOLUNTEER_AGE
from servesync.core.i18n import mark, tr
from servesync.core.validators import (
    ErrorCollector,
    InvalidInputError,
    calculate_age,
    clean_email,
    clean_name,
    clean_optional_name,
    clean_phone,
    clean_pronouns,
    clean_text,
    format_phone,
    parse_date,
    parse_enum,
    validate_birth_date,
)
from servesync.models._common import clean_skill_set, validate_optional_id
from servesync.models.enums import AccessNeed, DayPart, RecruitmentSource, VolunteerStatus, Weekday

NOTES_MAX_LENGTH = 1000


@dataclass(frozen=True, slots=True)
class AvailabilitySlot:
    """One block of time a volunteer is generally free, e.g. Saturday morning."""

    weekday: Weekday
    day_part: DayPart

    def __post_init__(self) -> None:
        if not isinstance(self.weekday, Weekday) or not isinstance(self.day_part, DayPart):
            raise TypeError("AvailabilitySlot needs a Weekday and a DayPart.")

    @property
    def label(self) -> str:
        return f"{self.weekday.short_label} {self.day_part.label}"

    @property
    def sort_key(self) -> tuple[int, int]:
        return (int(self.weekday), self.day_part.sort_order)

    @classmethod
    def for_datetime(cls, moment: datetime) -> AvailabilitySlot:
        """The slot a given moment falls in (used to match volunteers to shifts)."""
        return cls(Weekday(moment.weekday()), DayPart.from_hour(moment.hour))


def clean_access_needs(values: object, label: str = mark("Access needs")) -> frozenset[AccessNeed]:
    """A set of :class:`AccessNeed` members; codes such as "STEP_FREE" are accepted too."""
    if values is None:
        return frozenset()
    if isinstance(values, str) or not isinstance(values, Iterable):
        raise InvalidInputError(tr("{label} must be a list of choices.", label=tr(label)))
    return frozenset(parse_enum(value, AccessNeed, label) for value in values)


def access_gaps(needs: frozenset[AccessNeed], offered: frozenset[AccessNeed]) -> list[AccessNeed]:
    """
    The needs a program does not list as supported, in a stable order.

    REMOTE is special: a remote-capable program also satisfies the needs that
    only matter in person (step-free entry, transit, quiet room), because the
    volunteer stays home.
    """
    effective = set(offered)
    if AccessNeed.REMOTE in offered:
        effective |= {AccessNeed.STEP_FREE, AccessNeed.TRANSIT, AccessNeed.QUIET, AccessNeed.SEATED}
    return [need for need in AccessNeed if need in needs and need not in effective]


def _clean_availability(values: object) -> frozenset[AvailabilitySlot]:
    if values is None:
        return frozenset()
    if not isinstance(values, Iterable):
        raise InvalidInputError(tr("Availability must be a list of time slots."))
    slots = frozenset(values)
    if not all(isinstance(slot, AvailabilitySlot) for slot in slots):
        raise InvalidInputError(tr("Availability contains an unrecognized time slot."))
    return slots


@dataclass(slots=True)
class Volunteer:
    """A person who gives time to the organization."""

    first_name: str
    last_name: str
    email: str
    phone: str  # stored as 10 digits; see ``display_phone``
    birth_date: date
    joined_on: date = field(default_factory=date.today)
    status: VolunteerStatus = VolunteerStatus.APPLICANT
    recruitment_source: RecruitmentSource = RecruitmentSource.OTHER
    skills: frozenset[str] = frozenset()
    availability: frozenset[AvailabilitySlot] = frozenset()
    emergency_contact_name: str = ""
    emergency_contact_phone: str = ""
    notes: str = ""
    preferred_name: str = ""  # the name they go by; shown everywhere instead of first_name
    pronouns: str = ""  # optional, self-described (e.g. "she/her"); never inferred
    access_needs: frozenset[AccessNeed] = frozenset()  # shared by the volunteer, used for matching
    volunteer_id: int | None = None

    def __post_init__(self) -> None:
        errors = ErrorCollector()

        # --- Syntactic + per-field semantic checks --------------------------
        self.first_name = errors.check("first_name", clean_name, self.first_name, tr("First name"))
        self.last_name = errors.check("last_name", clean_name, self.last_name, tr("Last name"))
        self.email = errors.check("email", clean_email, self.email)
        self.phone = errors.check("phone", clean_phone, self.phone)
        self.joined_on = errors.check("joined_on", parse_date, self.joined_on, tr("Join date"))
        self.status = errors.check("status", parse_enum, self.status, VolunteerStatus, tr("Volunteer status"))
        self.recruitment_source = errors.check(
            "recruitment_source", parse_enum, self.recruitment_source, RecruitmentSource, tr("Recruitment source")
        )
        self.skills = errors.check("skills", clean_skill_set, self.skills)
        self.availability = errors.check("availability", _clean_availability, self.availability)
        self.emergency_contact_name = errors.check(
            "emergency_contact_name",
            clean_text,
            self.emergency_contact_name,
            tr("Emergency contact name"),
            max_length=80,
            required=False,
        )
        self.emergency_contact_phone = errors.check(
            "emergency_contact_phone",
            clean_phone,
            self.emergency_contact_phone,
            tr("Emergency contact phone"),
            required=False,
        )
        self.notes = errors.check(
            "notes", clean_text, self.notes, tr("Notes"), max_length=NOTES_MAX_LENGTH, required=False, multiline=True
        )
        self.preferred_name = errors.check(
            "preferred_name", clean_optional_name, self.preferred_name, tr("Name they go by")
        )
        self.pronouns = errors.check("pronouns", clean_pronouns, self.pronouns)
        self.access_needs = errors.check("access_needs", clean_access_needs, self.access_needs)
        self.volunteer_id = errors.check("volunteer_id", validate_optional_id, self.volunteer_id, tr("Volunteer ID"))

        # --- Cross-field semantic checks (need other fields to be valid) ----
        if isinstance(self.joined_on, date):
            if self.joined_on > date.today():
                errors.add("joined_on", tr("Join date cannot be in the future."))
            self.birth_date = errors.check(
                "birth_date",
                validate_birth_date,
                self.birth_date,
                minimum_age=MINIMUM_VOLUNTEER_AGE,
                as_of=self.joined_on,
            )

        has_contact_name = bool(self.emergency_contact_name)
        has_contact_phone = bool(self.emergency_contact_phone)
        if has_contact_name and not has_contact_phone:
            errors.add("emergency_contact_phone", tr("Add a phone number for the emergency contact."))
        if has_contact_phone and not has_contact_name:
            errors.add("emergency_contact_name", tr("Add a name for the emergency contact."))
        if has_contact_phone and self.emergency_contact_phone == self.phone:
            errors.add(
                "emergency_contact_phone",
                tr("Emergency contact phone must be different from the volunteer's own phone."),
            )

        joined_as_minor = (
            isinstance(self.birth_date, date)
            and isinstance(self.joined_on, date)
            and calculate_age(self.birth_date, self.joined_on) < ADULT_AGE
        )
        if joined_as_minor and not (has_contact_name and has_contact_phone):
            errors.add(
                "emergency_contact_name",
                tr(
                    ("Volunteers under {ADULT_AGE} need a parent or guardian listed as their emergency contact."),
                    ADULT_AGE=ADULT_AGE,
                ),
            )

        errors.raise_if_any()

    # --- Convenience properties used by the UI and reports ----------------

    @property
    def full_name(self) -> str:
        """The name to show: the name they go by (if given) plus their last name."""
        return f"{self.preferred_name or self.first_name} {self.last_name}"

    @property
    def given_name(self) -> str:
        """The first name to greet them by."""
        return self.preferred_name or self.first_name

    @property
    def legal_name(self) -> str:
        """First and last name as registered (for safety and emergency records only)."""
        return f"{self.first_name} {self.last_name}"

    @property
    def name_with_pronouns(self) -> str:
        return f"{self.full_name} ({self.pronouns})" if self.pronouns else self.full_name

    @property
    def display_phone(self) -> str:
        return format_phone(self.phone)

    @property
    def display_emergency_phone(self) -> str:
        return format_phone(self.emergency_contact_phone)

    def age(self, on: date | None = None) -> int:
        return calculate_age(self.birth_date, on or date.today())

    def is_minor(self, on: date | None = None) -> bool:
        return self.age(on) < ADULT_AGE

    def is_available_at(self, moment: datetime) -> bool:
        return AvailabilitySlot.for_datetime(moment) in self.availability

    def sorted_skills(self) -> list[str]:
        return sorted(self.skills, key=str.casefold)

    def sorted_availability(self) -> list[AvailabilitySlot]:
        return sorted(self.availability, key=lambda slot: slot.sort_key)
