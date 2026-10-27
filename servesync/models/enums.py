"""
Enumerations for every fixed set of choices in the domain.

Using enums instead of loose strings means a typo such as ``"Actve"`` is a
crash in testing rather than a silent bad record in production. Each enum's
``value`` is the stable code stored in the database; ``label`` is the
human-friendly text shown in the interface and on reports.
"""

from __future__ import annotations

from enum import Enum, IntEnum

from servesync.core.i18n import Language, current_language, mark, tr, weekday_name, weekday_plural

# Labels that are not simply the title-cased member name.
_LABEL_OVERRIDES: dict[str, str] = {
    "NO_SHOW": "No-Show",
    "PARTNER_ORG": "Partner Organization",
    "ADMIN": "Administrator",
    "COORDINATOR": "Volunteer Coordinator",
}


class DisplayEnum(str, Enum):
    """
    A string-valued enum whose members carry a display ``label``.

    ``english_label`` is the message ID; ``label`` is it in the current
    language, looked up each time it's shown so a language switch is instant.
    """

    @property
    def english_label(self) -> str:
        return _LABEL_OVERRIDES.get(self.value, self.name.replace("_", " ").title())

    @property
    def label(self) -> str:
        return tr(self.english_label)


class VolunteerStatus(DisplayEnum):
    """Where a person is in the recruitment pipeline."""

    APPLICANT = "APPLICANT"  # applied, awaiting screening/orientation
    ACTIVE = "ACTIVE"  # cleared to be scheduled
    INACTIVE = "INACTIVE"  # archived; history is preserved

    @property
    def can_be_scheduled(self) -> bool:
        return self is VolunteerStatus.ACTIVE


class RecruitmentSource(DisplayEnum):
    """How a volunteer heard about the organization (drives recruiting reports)."""

    WEBSITE = "WEBSITE"
    REFERRAL = "REFERRAL"
    SOCIAL_MEDIA = "SOCIAL_MEDIA"
    SCHOOL = "SCHOOL"
    COMMUNITY_EVENT = "COMMUNITY_EVENT"
    PARTNER_ORG = "PARTNER_ORG"
    OTHER = "OTHER"


class OpportunityCategory(DisplayEnum):
    """Program area of a service opportunity."""

    FOOD_SECURITY = "FOOD_SECURITY"
    EDUCATION = "EDUCATION"
    ENVIRONMENT = "ENVIRONMENT"
    HEALTH = "HEALTH"
    ANIMAL_WELFARE = "ANIMAL_WELFARE"
    HOUSING = "HOUSING"
    COMMUNITY_EVENTS = "COMMUNITY_EVENTS"
    ADMINISTRATIVE = "ADMINISTRATIVE"


class OpportunityStatus(DisplayEnum):
    """Lifecycle of a service opportunity."""

    DRAFT = "DRAFT"  # being planned; hidden from volunteers
    OPEN = "OPEN"  # visible and accepting sign-ups
    CLOSED = "CLOSED"  # finished or paused; history is preserved

    @property
    def accepts_signups(self) -> bool:
        return self is OpportunityStatus.OPEN


class AssignmentStatus(DisplayEnum):
    """Outcome of one volunteer's sign-up for one shift."""

    SCHEDULED = "SCHEDULED"
    ATTENDED = "ATTENDED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"

    @property
    def holds_a_spot(self) -> bool:
        """Cancelled sign-ups free their spot; every other status occupies one."""
        return self is not AssignmentStatus.CANCELLED


class UserRole(DisplayEnum):
    """Who is signed in — decides which screens and actions are available."""

    ADMIN = "ADMIN"  # organization leader: everything, including accounts
    COORDINATOR = "COORDINATOR"  # program staff: volunteers, shifts, reports
    VOLUNTEER = "VOLUNTEER"  # self-service portal: own profile, sign-ups, hours

    @property
    def is_leader(self) -> bool:
        return self is not UserRole.VOLUNTEER


class DayPart(DisplayEnum):
    """Coarse time-of-day block used for volunteer availability."""

    MORNING = "MORNING"  # before 12:00
    AFTERNOON = "AFTERNOON"  # 12:00-16:59
    EVENING = "EVENING"  # 17:00 and later

    @property
    def sort_order(self) -> int:
        return list(DayPart).index(self)

    @classmethod
    def from_hour(cls, hour: int) -> DayPart:
        """Classify a 24-hour clock hour (0-23) into a day part."""
        if not 0 <= hour <= 23:
            raise ValueError(f"hour must be 0-23, got {hour}")
        if hour < 12:
            return cls.MORNING
        if hour < 17:
            return cls.AFTERNOON
        return cls.EVENING


class ActivityKind(DisplayEnum):
    """Kinds of events shown in the dashboard activity feed."""

    SIGNED_UP = "SIGNED_UP"
    SERVED = "SERVED"
    APPLIED = "APPLIED"


class Theme(DisplayEnum):
    """Interface color theme (a comfort preference saved for each account)."""

    SYSTEM = "SYSTEM"  # follow the computer's light/dark setting, live
    LIGHT = "LIGHT"
    DARK = "DARK"
    HIGH_CONTRAST = "HIGH_CONTRAST"


class MessageDuration(DisplayEnum):
    """
    How long confirmation messages stay on screen (WCAG 2.2.1 Timing Adjustable).

    People who read slowly, use a screen magnifier, or look away to the
    keyboard can keep messages up until they choose to close them.
    """

    STANDARD = "STANDARD"  # 6 seconds
    LONG = "LONG"  # 20 seconds
    UNTIL_CLOSED = "UNTIL_CLOSED"

    @property
    def milliseconds(self) -> int | None:
        """Display time, or None when the message waits for the person to close it."""
        return {"STANDARD": 6_000, "LONG": 20_000}.get(self.value)


class AccessNeed(DisplayEnum):
    """
    One kind of access support. The same vocabulary describes what a
    *volunteer needs* and what a *program offers*, so matching the two is a
    simple set difference: ``needs - offers`` = what this program can't meet.

    ServeSync never blocks anyone because of an access need. It informs, ranks,
    and filters; the person decides.
    """

    STEP_FREE = "STEP_FREE"
    SEATED = "SEATED"
    TRANSIT = "TRANSIT"
    QUIET = "QUIET"
    NO_COST = "NO_COST"
    REMOTE = "REMOTE"

    @property
    def english_label(self) -> str:
        return _ACCESS_LABELS[self.value][0]

    @property
    def offer_label(self) -> str:
        """Wording for a program that provides this support."""
        return tr(_ACCESS_LABELS[self.value][1])

    @property
    def gap_text(self) -> str:
        """Wording for a program that does not provide it."""
        return tr(_ACCESS_LABELS[self.value][2])


#: (need label, program offer label, gap explanation)
_ACCESS_LABELS: dict[str, tuple[str, str, str]] = {
    "STEP_FREE": (mark("Step-free access"), mark("Step-free access (no stairs)"), mark("isn't listed as step-free")),
    "SEATED": (mark("Seated tasks"), mark("Seated tasks available"), mark("doesn't list seated tasks")),
    "TRANSIT": (mark("Near public transit"), mark("Near public transit"), mark("isn't listed as near public transit")),
    "QUIET": (mark("Quiet, low-sensory setting"), mark("Quiet, low-sensory space"), mark("doesn't list a quiet space")),
    "NO_COST": (
        mark("No out-of-pocket cost"),
        mark("No cost to volunteer (supplies provided)"),
        mark("may have out-of-pocket costs"),
    ),
    "REMOTE": (mark("Remote, from home"), mark("Can be done remotely"), mark("happens in person")),
}


class Weekday(IntEnum):
    """Day of week, numbered like Python's ``date.weekday()`` (Monday = 0)."""

    MONDAY = 0
    TUESDAY = 1
    WEDNESDAY = 2
    THURSDAY = 3
    FRIDAY = 4
    SATURDAY = 5
    SUNDAY = 6

    @property
    def label(self) -> str:
        return weekday_name(int(self))

    @property
    def short_label(self) -> str:
        return weekday_name(int(self), short=True)


def describe_slot(weekday: Weekday, part: DayPart) -> str:
    """'Saturday mornings' / 'sábados por la mañana' — a regular time someone is free."""
    if current_language() is Language.SPANISH:
        return f"{weekday_plural(int(weekday))} por la {part.label.lower()}"
    return f"{weekday.label} {part.label.lower()}s"
