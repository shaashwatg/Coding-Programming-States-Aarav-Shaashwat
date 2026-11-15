"""
Demo data generator.

Judges should see a living organization, not empty tables. This module builds
a realistic, fictional nonprofit — "Riverbend Community Alliance" — with
about 40 volunteers, eight programs, roughly four months of service history
and six weeks of upcoming shifts.

Two design choices make the demo dependable on competition day:

* **Deterministic** — a fixed random seed means the same data every reset, so
  the presentation script never meets a surprise.
* **Date-relative** — every date is computed from "today", so whether the app
  runs at a state conference in March or at nationals in June there is always
  recent history *and* upcoming shifts to show.

All people, organizations and places are fictional. Email addresses use the
reserved ``example.org`` domain and phone numbers use the 555-0100 to
555-0199 block set aside for fiction, so no real person can be contacted.
"""

from __future__ import annotations

import dataclasses
import logging
import random
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from servesync.config import MINIMUM_VOLUNTEER_AGE
from servesync.core.errors import BusinessRuleError
from servesync.core.security import DEFAULT_ITERATIONS, hash_password
from servesync.core.validators import calculate_age
from servesync.data.store import DataStore
from servesync.models import (
    AccessNeed,
    Assignment,
    AssignmentStatus,
    AvailabilitySlot,
    Certification,
    CredentialKind,
    DayPart,
    NoticeKind,
    Opportunity,
    OpportunityCategory,
    OpportunityStatus,
    RecruitmentSource,
    Shift,
    ShiftRole,
    UserAccount,
    UserRole,
    Volunteer,
    VolunteerStatus,
    Weekday,
)

logger = logging.getLogger(__name__)

DEMO_ORGANIZATION_NAME = "Riverbend Community Alliance"
DEMO_MISSION = (
    "Riverbend Community Alliance connects neighbors with practical ways to help: "
    "feeding families, tutoring kids, caring for our parks, and checking in on seniors."
)
DEMO_PASSWORD = "ServeSync2026!"  # documented in README; demo use only
#: A community partner (not a volunteer) who invites people; shows referrals outside the Referral channel.
DEMO_PARTNER_REFERRER = "Ruth Alvarez"
HISTORY_DAYS = 119
UPCOMING_DAYS = 42
GENERATED_VOLUNTEERS = 38

SKILL_POOL: tuple[str, ...] = (
    "Food Handling",
    "Customer Service",
    "Tutoring",
    "Spanish",
    "First Aid/CPR",
    "Event Setup",
    "Data Entry",
    "Gardening",
    "Construction",
    "Animal Care",
    "Photography",
    "Driving",
)

_FIRST_NAMES: tuple[str, ...] = (
    "Aaliyah",
    "Ben",
    "Camila",
    "Darius",
    "Elena",
    "Felix",
    "Grace",
    "Hiro",
    "Imani",
    "Jamal",
    "Keira",
    "Liam",
    "Mei",
    "Nadia",
    "Omar",
    "Paige",
    "Quinn",
    "Rosa",
    "Samir",
    "Tessa",
    "Uriel",
    "Valerie",
    "Wes",
    "Ximena",
    "Yusuf",
    "Zoe",
    "Andre",
    "Bianca",
    "Caleb",
    "Daniela",
    "Ethan",
    "Fatima",
    "Gabriel",
    "Hannah",
    "Isaac",
    "Julia",
    "Kofi",
    "Lena",
)
_LAST_NAMES: tuple[str, ...] = (
    "Abernathy",
    "Brooks",
    "Castillo",
    "Dang",
    "Ellison",
    "Fujita",
    "Gallagher",
    "Haddad",
    "Iverson",
    "Jovanovic",
    "Kowalski",
    "Lindqvist",
    "Mbeki",
    "Nakamura",
    "O'Connell",
    "Petrov",
    "Quintero",
    "Ramirez",
    "Sato",
    "Thornton",
    "Underwood",
    "Vasquez",
    "Whitaker",
    "Xu",
    "Yilmaz",
    "Zimmerman",
)
_AREA_CODES: tuple[str, ...] = ("312", "404", "512", "614", "720", "919")
_SOURCE_WEIGHTS: dict[RecruitmentSource, int] = {
    RecruitmentSource.WEBSITE: 25,
    RecruitmentSource.REFERRAL: 22,
    RecruitmentSource.SOCIAL_MEDIA: 18,
    RecruitmentSource.SCHOOL: 15,
    RecruitmentSource.COMMUNITY_EVENT: 10,
    RecruitmentSource.PARTNER_ORG: 6,
    RecruitmentSource.OTHER: 4,
}


#: Personal goals for the two volunteer logins, due June 1 (the end of a school year).
DEMO_GOAL_MONTH, DEMO_STUDENT_GOAL_HOURS, DEMO_ADULT_GOAL_HOURS = 6, 40, 80
#: Back-to-back shifts today, so the check-in kiosk can be shown from 7 AM to 7 PM.
DEMO_CHECKIN_START_HOURS = (7, 11, 15)
DEMO_CHECKIN_SHIFT_HOURS, DEMO_CHECKIN_CAPACITY, DEMO_CHECKIN_ROSTER, DEMO_SIGNUP_LEAD = 4, 8, 6, 3

#: What each program measures, and a typical result per person attending (results come from attendance).
DEMO_IMPACT = {
    "Weekend Food Pantry Distribution": ("families served", 6),
    "After-School Reading Buddies": ("students tutored", 2),
    "Senior Wellness Phone Calls": ("calls made", 8),
    "Animal Shelter Care Team": ("animals cared for", 4),
    "Riverside Park Cleanup": ("bags of litter collected", 3),
}
DEMO_IMPACT_BLANK_EVERY = 25  # one shift in this many has no result yet
#: The program that requires a certification (it works with children).
DEMO_CERTIFIED_PROGRAM, DEMO_CERTIFICATION = "After-School Reading Buddies", "Background Check"
DEMO_CERTIFIED_SHARE, DEMO_RENEW_SOON_EVERY = 2, 7  # every 2nd person holds one; every 7th renews soon
DEMO_CERTIFICATION_DAYS, DEMO_RENEW_SOON_DAYS = 300, 20

#: How long a background check is valid; issue dates are worked back from the expiry date.
DEMO_CREDENTIAL_VALID_DAYS = 365
#: The one-time event that requires a signed waiver, and has roles.
DEMO_EVENT_PROGRAM, DEMO_WAIVER, DEMO_FOOD_CARD = "Community 5K Fun Run", "Liability waiver", "Food Handler Card"
DEMO_WAIVER_SOON_DAYS = 10
DEMO_WAITLIST_SIZE = 2
#: Fixed verification codes for the demo (documented in the README), so "Verify a record" can be shown.
DEMO_RECORD_CODE, DEMO_CERTIFICATE_CODE, DEMO_CERTIFICATE_HOURS = "RVBD7K2M", "HQ5MTZPA", 50
DEMO_EVENT_ANNOUNCEMENT = (
    "Thank you for helping with the 5K! Please arrive 30 minutes early for a short briefing at the "
    "registration tent. Parking is in the north lot."
)
DEMO_SHIFT_ANNOUNCEMENT = "We're short on reusable bags this week. If you have spares, please bring them along."
DEMO_WAITLIST_LEAD_DAYS = 3  # the full shift is a few days out, so the demo has time to show it
#: Roles for upcoming shifts: (name, people, required skill). Totals match each program's capacity.
DEMO_ROLES: dict[str, tuple[tuple[str, int, str], ...]] = {
    "Community 5K Fun Run": (
        ("Registration", 4, "Customer Service"),
        ("Water station", 12, ""),
        ("Course marshal", 8, ""),
        ("Finish line", 4, ""),
        ("First aid", 2, "First Aid/CPR"),
    ),
    "Weekend Food Pantry Distribution": (
        ("Greeter", 2, "Customer Service"),
        ("Sorting and packing", 6, ""),
    ),
}

#: Which active volunteers stop coming in the demo (fixed positions, so every reset matches).
LAPSED_START, LAPSED_STEP, LAPSED_COUNT = 5, 9, 3


@dataclass(frozen=True, slots=True)
class SeedSummary:
    volunteers: int
    opportunities: int
    shifts: int
    assignments: int
    accounts: int
    hours_served: float


@dataclass(frozen=True, slots=True)
class _ProgramPlan:
    """Blueprint for one opportunity and its recurring schedule."""

    opportunity: Opportunity
    weekdays: tuple[Weekday, ...]
    start: time
    hours: float
    capacity: int
    every_other_week: bool = False
    first_day: int = -HISTORY_DAYS  # offset from today
    last_day: int = UPCOMING_DAYS
    one_time_offset: int | None = None  # single event N days from today


def _days_until(today: date, weekday: Weekday, *, at_least: int) -> int:
    """Days from ``today`` to the first ``weekday`` that is at least ``at_least`` days away."""
    first = today + timedelta(days=at_least)
    return at_least + (int(weekday) - first.weekday()) % 7


def _saved_id(record_id: int | None) -> int:
    """Narrow ``int | None`` to ``int`` for records that were just saved."""
    if record_id is None:
        raise RuntimeError("Seed record was not saved.")
    return record_id


class _PhoneBook:
    """Hands out unique fictional phone numbers (555-0100 to 555-0199)."""

    def __init__(self) -> None:
        self._counter = 0

    def next(self) -> str:
        area = _AREA_CODES[self._counter // 100 % len(_AREA_CODES)]
        line = 100 + self._counter % 100
        self._counter += 1
        return f"{area}5550{line:03d}"


def seed_demo_data(
    store: DataStore,
    *,
    today: date | None = None,
    random_seed: int = 2026,
    password_iterations: int = DEFAULT_ITERATIONS,
) -> SeedSummary:
    """
    Fill an **empty** database with the demo organization (all-or-nothing).

    ``password_iterations`` exists only so automated tests can hash quickly.
    """
    if not store.is_empty():
        raise BusinessRuleError("Demo data can only be loaded into an empty database. Reset it first.")

    today = today or date.today()
    rng = random.Random(random_seed)
    phones = _PhoneBook()

    with store.transaction():
        store.settings.set_organization_name(DEMO_ORGANIZATION_NAME)
        store.settings.set_mission_statement(DEMO_MISSION)
        volunteers = _create_volunteers(store, rng, phones, today)
        plans = _program_plans(today)
        shifts = _create_shifts(store, plans, today)
        assignment_count, hours = _create_assignments(store, rng, volunteers, shifts, today)
        account_count = _create_accounts(store, volunteers, password_iterations)
        _add_referrals_and_goals(store, volunteers, today)
        _add_impact_results(store, shifts, today)
        _add_certifications(store, volunteers, shifts, today)
        _add_waivers_and_cards(store, volunteers, shifts, today)
        _add_roles(store, shifts, today)
        checkin_shifts = _create_todays_checkin_shifts(store, volunteers, shifts, today)
        _add_waitlists_and_notices(store, volunteers, today)
        _add_announcements_and_kiosk_times(store, volunteers, today)
        _add_issued_documents(store, volunteers, today)

    summary = SeedSummary(
        volunteers=len(volunteers),
        opportunities=len(plans) + 1,  # +1 draft program with no shifts yet
        shifts=len(shifts) + checkin_shifts,
        assignments=assignment_count,
        accounts=account_count,
        hours_served=round(hours, 2),
    )
    logger.info("Demo data loaded: %s", summary)
    return summary


# --------------------------------------------------------------- volunteers


def _birth_date_for_age(rng: random.Random, today: date, age: int) -> date:
    """A birth date that makes someone exactly ``age`` today."""
    days_past_birthday = rng.randint(1, 360)
    return today.replace(year=today.year - age) - timedelta(days=days_past_birthday)


def _random_slots(rng: random.Random) -> frozenset[AvailabilitySlot]:
    """3-7 random weekly slots, with weekend mornings more common (as in real volunteer pools)."""
    all_slots = [AvailabilitySlot(day, part) for day in Weekday for part in DayPart]
    slots = set(rng.sample(all_slots, rng.randint(3, 7)))
    if rng.random() < 0.5:
        slots.add(AvailabilitySlot(Weekday.SATURDAY, DayPart.MORNING))
    if rng.random() < 0.4:
        slots.add(AvailabilitySlot(Weekday.SUNDAY, DayPart.MORNING))
    return frozenset(slots)


#: Some people share pronouns, most don't — as in real life.
_DEMO_PRONOUNS = ("", "she/her", "he/him", "", "she/her", "", "he/him", "they/them", "", "she/they")


def _demo_access_needs(index: int) -> frozenset[AccessNeed]:
    needs = set()
    if index % 9 == 2:
        needs.add(AccessNeed.STEP_FREE)
    if index % 11 == 5:
        needs.add(AccessNeed.QUIET)
    if index % 13 == 4:
        needs.add(AccessNeed.NO_COST)
    if index % 10 == 8:
        needs.add(AccessNeed.TRANSIT)
    return frozenset(needs)


def _create_volunteers(store: DataStore, rng: random.Random, phones: _PhoneBook, today: date) -> list[Volunteer]:
    volunteers = [
        # Persona 1: a high-school student (shows minor safeguards + age rules).
        Volunteer(
            first_name="Jordan",
            last_name="Rivera",
            email="jordan.rivera@example.org",
            phone=phones.next(),
            birth_date=_birth_date_for_age(rng, today, 16),
            joined_on=today - timedelta(days=200),
            status=VolunteerStatus.ACTIVE,
            recruitment_source=RecruitmentSource.SCHOOL,
            skills=frozenset({"Tutoring", "Spanish", "Event Setup"}),
            availability=frozenset(
                {
                    AvailabilitySlot(Weekday.TUESDAY, DayPart.AFTERNOON),
                    AvailabilitySlot(Weekday.THURSDAY, DayPart.AFTERNOON),
                    AvailabilitySlot(Weekday.SATURDAY, DayPart.MORNING),
                    AvailabilitySlot(Weekday.SUNDAY, DayPart.AFTERNOON),
                }
            ),
            emergency_contact_name="Maria Rivera (parent)",
            emergency_contact_phone=phones.next(),
            notes="Earning service hours for the school's community service award.",
            pronouns="they/them",
        ),
        # Persona 2: a working adult who volunteers evenings and weekends.
        Volunteer(
            first_name="Priya",
            last_name="Patel",
            email="priya.patel@example.org",
            phone=phones.next(),
            birth_date=_birth_date_for_age(rng, today, 34),
            joined_on=today - timedelta(days=410),
            status=VolunteerStatus.ACTIVE,
            recruitment_source=RecruitmentSource.REFERRAL,
            skills=frozenset({"First Aid/CPR", "Customer Service", "Data Entry"}),
            availability=frozenset(
                {
                    AvailabilitySlot(Weekday.MONDAY, DayPart.EVENING),
                    AvailabilitySlot(Weekday.WEDNESDAY, DayPart.EVENING),
                    AvailabilitySlot(Weekday.SATURDAY, DayPart.MORNING),
                }
            ),
            emergency_contact_name="Arjun Patel",
            emergency_contact_phone=phones.next(),
            pronouns="she/her",
            # Relies on the bus: shows access-aware matching in Find a shift.
            access_needs=frozenset({AccessNeed.TRANSIT}),
        ),
    ]

    used_names = {("Jordan", "Rivera"), ("Priya", "Patel")}
    sources = list(_SOURCE_WEIGHTS)
    weights = list(_SOURCE_WEIGHTS.values())
    for index in range(GENERATED_VOLUNTEERS):
        first, last = rng.choice(_FIRST_NAMES), rng.choice(_LAST_NAMES)
        while (first, last) in used_names:
            first, last = rng.choice(_FIRST_NAMES), rng.choice(_LAST_NAMES)
        used_names.add((first, last))

        # Fixed mix so the recruitment pipeline always has applicants to review.
        if index % 8 == 3:
            status, joined = VolunteerStatus.APPLICANT, today - timedelta(days=rng.randint(1, 25))
        elif index % 8 == 6:
            status, joined = VolunteerStatus.INACTIVE, today - timedelta(days=rng.randint(200, 700))
        else:
            status, joined = VolunteerStatus.ACTIVE, today - timedelta(days=rng.randint(130, 700))

        age = rng.randint(14, 17) if index % 7 == 0 else rng.randint(18, 74)
        birth = _birth_date_for_age(rng, today, age)
        while calculate_age(birth, joined) < MINIMUM_VOLUNTEER_AGE:  # old enough when they joined
            birth -= timedelta(days=365)
        is_minor_at_join = calculate_age(birth, joined) < 18
        needs_contact = is_minor_at_join or rng.random() < 0.6

        email_local = f"{first}.{last}".lower().replace("'", "")
        volunteers.append(
            Volunteer(
                first_name=first,
                last_name=last,
                email=f"{email_local}@example.org",
                phone=phones.next(),
                birth_date=birth,
                joined_on=joined,
                status=status,
                recruitment_source=rng.choices(sources, weights)[0],
                skills=frozenset(rng.sample(SKILL_POOL, rng.randint(1, 4))),
                availability=_random_slots(rng),
                emergency_contact_name=(
                    f"{rng.choice(_FIRST_NAMES)} {last}{' (guardian)' if is_minor_at_join else ''}"
                    if needs_contact
                    else ""
                ),
                emergency_contact_phone=phones.next() if needs_contact else "",
                # Index-based (no extra random draws), so the rest of the demo stays identical.
                pronouns=_DEMO_PRONOUNS[index % len(_DEMO_PRONOUNS)],
                access_needs=_demo_access_needs(index),
            )
        )

    return [store.volunteers.add(volunteer) for volunteer in volunteers]


# ------------------------------------------------------------ opportunities


def _program_plans(today: date) -> list[_ProgramPlan]:
    def program(
        title: str,
        description: str,
        category: OpportunityCategory,
        location: str,
        coordinator: str,
        skills: set[str],
        *,
        min_age: int = MINIMUM_VOLUNTEER_AGE,
        status: OpportunityStatus = OpportunityStatus.OPEN,
        story: str = "",
        access: frozenset[AccessNeed] = frozenset(),
    ) -> Opportunity:
        return Opportunity(
            title=title,
            description=description,
            category=category,
            location=location,
            coordinator_name=coordinator,
            min_age=min_age,
            status=status,
            required_skills=frozenset(skills),
            story_video_url=story,
            access_features=access,
        )

    step_free, seated, transit, quiet, no_cost, remote = (
        AccessNeed.STEP_FREE,
        AccessNeed.SEATED,
        AccessNeed.TRANSIT,
        AccessNeed.QUIET,
        AccessNeed.NO_COST,
        AccessNeed.REMOTE,
    )
    return [
        _ProgramPlan(
            program(
                "Weekend Food Pantry Distribution",
                "Sort donated groceries, pack family boxes, and greet neighbors at our weekly pantry.",
                OpportunityCategory.FOOD_SECURITY,
                "Riverbend Community Center - Gym",
                "Dana Whitfield",
                {"Food Handling", "Customer Service"},
                story="https://www.example.org/stories/weekend-pantry",
                access=frozenset({step_free, seated, transit, no_cost}),
            ),
            weekdays=(Weekday.SATURDAY,),
            start=time(9, 0),
            hours=3,
            capacity=8,
        ),
        _ProgramPlan(
            program(
                "After-School Reading Buddies",
                "Read one-on-one with elementary students and help with homework in a supervised library room.",
                OpportunityCategory.EDUCATION,
                "Eastgate Public Library - Room B",
                "Marcus Bell",
                {"Tutoring"},
                min_age=16,
                access=frozenset({step_free, transit, quiet, no_cost}),
            ),
            weekdays=(Weekday.TUESDAY, Weekday.THURSDAY),
            start=time(15, 30),
            hours=2,
            capacity=6,
        ),
        _ProgramPlan(
            program(
                "Riverside Park Cleanup",
                "Remove litter and invasive plants along the river trail. Gloves and tools provided.",
                OpportunityCategory.ENVIRONMENT,
                "Riverside Park - North Pavilion",
                "Elena Ruiz",
                {"Gardening"},
                access=frozenset({no_cost}),
            ),
            weekdays=(Weekday.SUNDAY,),
            start=time(13, 0),
            hours=3,
            capacity=15,
            every_other_week=True,
        ),
        _ProgramPlan(
            program(
                "Senior Wellness Phone Calls",
                "Make friendly check-in calls to older adults living alone and flag any urgent needs to staff.",
                OpportunityCategory.HEALTH,
                "Riverbend Office - Call Room",
                "Grace Okafor",
                {"Customer Service"},
                min_age=18,
                access=frozenset({step_free, seated, transit, quiet, remote, no_cost}),
            ),
            weekdays=(Weekday.MONDAY, Weekday.WEDNESDAY),
            start=time(18, 0),
            hours=2,
            capacity=4,
        ),
        _ProgramPlan(
            program(
                "Animal Shelter Care Team",
                "Walk dogs, socialize cats, and help clean kennels at our partner animal shelter.",
                OpportunityCategory.ANIMAL_WELFARE,
                "Second Chance Animal Shelter",
                "Tom Becker",
                {"Animal Care"},
                min_age=16,
            ),
            weekdays=(Weekday.FRIDAY,),
            start=time(16, 0),
            hours=3,
            capacity=5,
        ),
        _ProgramPlan(
            program(
                "Habitat Home Build Day",
                "Help frame walls, paint, and landscape an affordable home alongside skilled crew leaders.",
                OpportunityCategory.HOUSING,
                "1420 Maple Street Build Site",
                "Luis Ortega",
                {"Construction", "First Aid/CPR"},
                min_age=18,
                access=frozenset({no_cost}),
            ),
            weekdays=(Weekday.SATURDAY,),
            start=time(8, 0),
            hours=6,
            capacity=10,
            every_other_week=True,
        ),
        _ProgramPlan(
            program(
                "Community 5K Fun Run",
                "Staff registration, water stations, and the finish line at our annual fundraising 5K.",
                OpportunityCategory.COMMUNITY_EVENTS,
                "Lakeview Park",
                "Dana Whitfield",
                {"Event Setup", "First Aid/CPR"},
                access=frozenset({step_free, seated, no_cost}),
            ),
            weekdays=(),
            start=time(7, 0),
            hours=5,
            capacity=30,
            one_time_offset=_days_until(today, Weekday.SUNDAY, at_least=21),
        ),
        _ProgramPlan(
            program(
                "Volunteer Office Support",
                "Answer phones, update records, and prepare mailings at the front desk. "
                "Program paused for renovations.",
                OpportunityCategory.ADMINISTRATIVE,
                "Riverbend Office - Front Desk",
                "Grace Okafor",
                {"Data Entry"},
                min_age=16,
                status=OpportunityStatus.CLOSED,
                access=frozenset({step_free, seated, transit, quiet}),
            ),
            weekdays=(Weekday.WEDNESDAY,),
            start=time(10, 0),
            hours=3,
            capacity=3,
            last_day=-30,
        ),
    ]


def _create_shifts(store: DataStore, plans: list[_ProgramPlan], today: date) -> list[tuple[Shift, Opportunity]]:
    # A program still being planned: shows the DRAFT stage, no shifts yet.
    store.opportunities.add(
        Opportunity(
            title="Holiday Meal Packing",
            description="Pack and deliver holiday meal kits to families referred by local schools.",
            category=OpportunityCategory.FOOD_SECURITY,
            location="Riverbend Community Center - Kitchen",
            coordinator_name="Dana Whitfield",
            status=OpportunityStatus.DRAFT,
            required_skills=frozenset({"Food Handling", "Driving"}),
            access_features=frozenset({AccessNeed.STEP_FREE, AccessNeed.TRANSIT}),
        )
    )

    created: list[tuple[Shift, Opportunity]] = []
    for plan in plans:
        opportunity = store.opportunities.add(plan.opportunity)
        opportunity_id = _saved_id(opportunity.opportunity_id)
        if plan.one_time_offset is not None:
            dates = [today + timedelta(days=plan.one_time_offset)]
        else:
            dates = [
                today + timedelta(days=offset)
                for offset in range(plan.first_day, plan.last_day + 1)
                if Weekday((today + timedelta(days=offset)).weekday()) in plan.weekdays
                and (not plan.every_other_week or (today + timedelta(days=offset)).isocalendar().week % 2 == 0)
            ]
        for day in dates:
            starts = datetime.combine(day, plan.start)
            shift = store.shifts.add(
                Shift(
                    opportunity_id=opportunity_id,
                    starts_at=starts,
                    ends_at=starts + timedelta(hours=plan.hours),
                    capacity=plan.capacity,
                )
            )
            created.append((shift, opportunity))
    created.sort(key=lambda pair: pair[0].starts_at)
    return created


# -------------------------------------------------------------- assignments


def _create_assignments(
    store: DataStore,
    rng: random.Random,
    volunteers: list[Volunteer],
    shifts: list[tuple[Shift, Opportunity]],
    today: date,
) -> tuple[int, float]:
    """Sign volunteers up realistically: by availability, skills, age, and no double-booking."""
    start_of_today = datetime.combine(today, time.min)
    inactive_since = start_of_today - timedelta(days=45)
    # Each volunteer gets a personal reliability so attendance reports vary.
    reliability = {v.volunteer_id: rng.choice((0.97, 0.95, 0.92, 0.9, 0.85, 0.7)) for v in volunteers}
    reliability[volunteers[0].volunteer_id] = 0.96  # personas are dependable demo subjects
    reliability[volunteers[1].volunteer_id] = 0.98
    booked: dict[int | None, list[Shift]] = {v.volunteer_id: [] for v in volunteers}
    # A few active regulars who stopped coming, so Staffing Studio has people to re-engage.
    active = [v for v in volunteers[2:] if v.status is VolunteerStatus.ACTIVE]
    lapsed = {v.volunteer_id for v in active[LAPSED_START::LAPSED_STEP][:LAPSED_COUNT]}

    count = 0
    hours_total = 0.0
    for shift, opportunity in shifts:
        is_past = shift.starts_at < start_of_today
        days_ahead = (shift.starts_at - start_of_today).days

        candidates: list[tuple[float, Volunteer]] = []
        for volunteer in volunteers:
            if volunteer.status is VolunteerStatus.APPLICANT:
                continue
            if volunteer.status is VolunteerStatus.INACTIVE and shift.starts_at >= inactive_since:
                continue
            if volunteer.joined_on > shift.starts_at.date():
                continue
            if calculate_age(volunteer.birth_date, shift.starts_at.date()) < opportunity.min_age:
                continue
            if any(other.overlaps(shift.starts_at, shift.ends_at) for other in booked[volunteer.volunteer_id]):
                continue
            weight = 1.0
            if volunteer.is_available_at(shift.starts_at):
                weight += 3.0
            weight += 1.5 * len(
                {s.casefold() for s in volunteer.skills} & {s.casefold() for s in opportunity.required_skills}
            )
            candidates.append((weight * rng.random(), volunteer))

        if is_past:
            target_fill = rng.uniform(0.6, 1.0)
        elif opportunity.category is OpportunityCategory.COMMUNITY_EVENTS:
            target_fill = 0.35  # big upcoming event with open spots — perfect for Smart Match demos
        else:
            target_fill = max(0.15, 0.9 - days_ahead * 0.02)
        wanted = min(len(candidates), max(1, round(shift.capacity * target_fill)))

        candidates.sort(key=lambda pair: pair[0], reverse=True)
        for _, volunteer in candidates[:wanted]:
            signed_up = shift.starts_at - timedelta(days=rng.randint(2, 21), hours=rng.randint(0, 9))
            signed_up = max(signed_up, datetime.combine(volunteer.joined_on, time(9, 0)))
            signed_up = min(signed_up, start_of_today - timedelta(hours=1))

            status = AssignmentStatus.SCHEDULED
            hours: float | None = None
            if is_past:
                roll = rng.random()
                if roll < 0.06:
                    status = AssignmentStatus.CANCELLED
                elif roll < 0.06 + 0.94 * reliability[volunteer.volunteer_id]:
                    status = AssignmentStatus.ATTENDED
                    hours = shift.duration_hours - (0.5 if rng.random() < 0.1 and shift.duration_hours > 1 else 0)
                    hours_total += hours
                else:
                    status = AssignmentStatus.NO_SHOW

            if volunteer.volunteer_id in lapsed and shift.starts_at >= inactive_since:
                # Leave the record out, but count them as booked and draw the same random numbers,
                # so everyone else's demo history stays exactly the same.
                hours_total -= hours or 0.0
                booked[volunteer.volunteer_id].append(shift)
                continue

            store.assignments.add(
                Assignment(
                    shift_id=_saved_id(shift.shift_id),
                    volunteer_id=_saved_id(volunteer.volunteer_id),
                    status=status,
                    hours_served=hours,
                    signed_up_at=signed_up,
                )
            )
            if status is not AssignmentStatus.CANCELLED:
                booked[volunteer.volunteer_id].append(shift)
            count += 1
    return count, hours_total


def _add_referrals_and_goals(store: DataStore, volunteers: list[Volunteer], today: date) -> None:
    """Named referrers and two personal goals. Drawn without random numbers, so the demo history is untouched."""
    jordan, priya = volunteers[0], volunteers[1]
    referred = [v for v in volunteers[2:] if v.recruitment_source is RecruitmentSource.REFERRAL]
    for index, volunteer in enumerate(referred):
        # Priya invited two of every three, so the recruiting report has a clear person to thank.
        referrer = jordan if index % 3 == 2 else priya
        store.volunteers.update(dataclasses.replace(volunteer, referred_by=referrer.full_name))
    # A community partner who isn't a volunteer also sends people, through other channels. One
    # applicant typed the name in lowercase, which the report still counts as the same person.
    others = [v for v in volunteers[2:] if v.recruitment_source is RecruitmentSource.COMMUNITY_EVENT][:2]
    for volunteer, typed in zip(others, (DEMO_PARTNER_REFERRER, DEMO_PARTNER_REFERRER.lower()), strict=False):
        store.volunteers.update(dataclasses.replace(volunteer, referred_by=typed))
    due = date(today.year + (today.month >= DEMO_GOAL_MONTH), DEMO_GOAL_MONTH, 1)
    for person, hours in ((jordan, DEMO_STUDENT_GOAL_HOURS), (priya, DEMO_ADULT_GOAL_HOURS)):
        store.volunteers.update(
            dataclasses.replace(store.volunteers.get(person.volunteer_id or 0), hour_goal=hours, hour_goal_due=due)
        )


def _add_impact_results(store: DataStore, shifts: list[tuple[Shift, Opportunity]], today: date) -> None:
    """What each program measures, and results for past shifts: a steady rate per person who attended."""
    units = {o.opportunity_id: o for _, o in shifts}
    for opportunity in units.values():
        unit, _ = DEMO_IMPACT.get(opportunity.title, ("", 0))
        store.opportunities.update(dataclasses.replace(opportunity, impact_unit=unit))
    for position, (shift, opportunity) in enumerate(shifts):
        _, per_person = DEMO_IMPACT.get(opportunity.title, ("", 0))
        # A few recent shifts stay blank, so the report can show its "results missing" note.
        if not per_person or shift.starts_at.date() >= today or position % DEMO_IMPACT_BLANK_EVERY == 0:
            continue
        attended = sum(
            entry.assignment.status is AssignmentStatus.ATTENDED
            for entry in store.assignments.roster(_saved_id(shift.shift_id))
        )
        store.shifts.set_impact(_saved_id(shift.shift_id), attended * per_person)


def _add_certifications(
    store: DataStore, volunteers: list[Volunteer], shifts: list[tuple[Shift, Opportunity]], today: date
) -> None:
    """One program requires a background check. Everyone on its roster holds one; a few need renewing soon."""
    program = next(o for _, o in shifts if o.title == DEMO_CERTIFIED_PROGRAM)
    store.opportunities.update(
        dataclasses.replace(
            store.opportunities.get(_saved_id(program.opportunity_id)),
            required_certifications=frozenset({DEMO_CERTIFICATION}),
        )
    )
    on_roster = {
        entry.assignment.volunteer_id
        for shift, opportunity in shifts
        if opportunity.opportunity_id == program.opportunity_id and shift.starts_at.date() >= today
        for entry in store.assignments.roster(_saved_id(shift.shift_id))
    }
    active = [v for v in volunteers if v.status is VolunteerStatus.ACTIVE]
    for position, volunteer in enumerate(active):
        volunteer_id = _saved_id(volunteer.volunteer_id)
        if volunteer_id not in on_roster and position % DEMO_CERTIFIED_SHARE != 0:
            continue
        renew_soon = position % DEMO_RENEW_SOON_EVERY == 0
        days = DEMO_RENEW_SOON_DAYS if renew_soon else DEMO_CERTIFICATION_DAYS
        expires = today + timedelta(days=days)
        store.volunteers.save_certification(
            volunteer_id,
            Certification(
                DEMO_CERTIFICATION,
                expires,
                CredentialKind.CERTIFICATION,
                expires - timedelta(days=DEMO_CREDENTIAL_VALID_DAYS),
            ),
        )


def _add_waivers_and_cards(
    store: DataStore, volunteers: list[Volunteer], shifts: list[tuple[Shift, Opportunity]], today: date
) -> None:
    """
    The 5K (a Sunday morning race) requires a signed liability waiver. Everyone already on
    its roster has one, as does everyone usually free on Sunday mornings and every third
    other active volunteer; two run out within the dashboard's 30 days.
    Some volunteers also hold a food handler card, and two of those have already expired,
    so the Certification expiry report has something to show in each group.
    """
    event = next(o for _, o in shifts if o.title == DEMO_EVENT_PROGRAM)
    store.opportunities.update(
        dataclasses.replace(
            store.opportunities.get(_saved_id(event.opportunity_id)),
            required_certifications=frozenset({DEMO_WAIVER}),
        )
    )
    on_event = {
        entry.assignment.volunteer_id
        for shift, opportunity in shifts
        if opportunity.opportunity_id == event.opportunity_id
        for entry in store.assignments.roster(_saved_id(shift.shift_id))
    }
    active = [v for v in volunteers if v.status is VolunteerStatus.ACTIVE]
    soon = 0
    for position, volunteer in enumerate(active):
        volunteer_id = _saved_id(volunteer.volunteer_id)
        sunday_morning = AvailabilitySlot(Weekday.SUNDAY, DayPart.MORNING) in volunteer.availability
        if volunteer_id in on_event or sunday_morning or position % 3 == 0:
            days = DEMO_WAIVER_SOON_DAYS + soon * 3 if soon < 2 and volunteer_id not in on_event else 300
            soon += days != 300
            expires = today + timedelta(days=days)
            store.volunteers.save_certification(
                volunteer_id,
                Certification(DEMO_WAIVER, expires, CredentialKind.WAIVER, expires - timedelta(days=365)),
            )
    with_cards = [v for v in active if "Food Handling" in v.skills]
    for position, volunteer in enumerate(with_cards):
        offset = -15 - position if position < 2 else 120 + position * 20  # the first two have lapsed
        expires = today + timedelta(days=offset)
        store.volunteers.save_certification(
            _saved_id(volunteer.volunteer_id),
            Certification(DEMO_FOOD_CARD, expires, CredentialKind.CERTIFICATION, expires - timedelta(days=3 * 365)),
        )


def _add_roles(store: DataStore, shifts: list[tuple[Shift, Opportunity]], today: date) -> None:
    """
    Upcoming 5K and food pantry shifts are split into roles. Past shifts keep their one
    general role, as they would have before roles existed. Sign-ups already made move
    into the role that uses their skills, as Smart Match would have placed them.
    """
    for shift, opportunity in shifts:
        if shift.starts_at.date() < today or opportunity.title not in DEMO_ROLES:
            continue
        shift_id = _saved_id(shift.shift_id)
        (general,) = store.shifts.roles(shift_id)
        plan = DEMO_ROLES[opportunity.title]
        # The general role becomes the first unskilled role, so it keeps everyone already in it.
        roles: list[ShiftRole] = []
        for position, (name, capacity, skill) in enumerate(plan):
            is_first_open = not skill and not any(not r.required_skill for r in roles)
            roles.append(
                ShiftRole(
                    name=name,
                    capacity=max(capacity, general.filled) if is_first_open else capacity,
                    required_skill=skill,
                    shift_id=shift_id,
                    position=position,
                    role_id=general.role.role_id if is_first_open else None,
                )
            )
        saved = store.shifts.replace_roles(shift_id, roles)
        skilled = [role for role in saved if role.role.required_skill]
        for entry in store.assignments.roster(shift_id):
            volunteer = store.volunteers.get(entry.assignment.volunteer_id)
            for role in skilled:
                current = store.shifts.get_role(_saved_id(role.role.role_id))
                if not current.is_full and role.role.fits(volunteer.skills):
                    store.assignments.update(dataclasses.replace(entry.assignment, role_id=role.role.role_id))
                    break


def _add_waitlists_and_notices(store: DataStore, volunteers: list[Volunteer], today: date) -> None:
    """
    Two people wait for a full upcoming shift, and Priya (a demo sign-in) finds a note on
    Home saying she was moved off a waitlist into one of her shifts.
    """
    now = datetime.combine(today, time(8))
    priya = volunteers[1]
    upcoming = store.shifts.overviews(
        starts_after=now + timedelta(days=DEMO_WAITLIST_LEAD_DAYS), opportunity_status=OpportunityStatus.OPEN
    )
    # The smallest upcoming shift of a program anyone may join (no certification needed) fills up.
    candidates = [
        o
        for o in upcoming
        if not store.opportunities.get(o.shift.opportunity_id).required_certifications
        and len(store.shifts.roles(_saved_id(o.shift.shift_id))) == 1
    ]
    if candidates:
        target = min(candidates, key=lambda o: (o.shift.capacity, o.shift.starts_at))
        shift = target.shift
        shift_id = _saved_id(shift.shift_id)
        min_age = store.opportunities.get(shift.opportunity_id).min_age
        people = [v for v in volunteers[2:] if v.status is VolunteerStatus.ACTIVE]
        waiting = 0
        for offset, volunteer in enumerate(people):
            volunteer_id = _saved_id(volunteer.volunteer_id)
            if (
                volunteer_id in store.assignments.volunteer_ids_on_shift(shift_id)
                or calculate_age(volunteer.birth_date, shift.starts_at.date()) < min_age
                or store.assignments.conflicting_shifts(volunteer_id, shift.starts_at, shift.ends_at)
            ):
                continue
            if not store.shifts.get_overview(shift_id).is_full:
                store.assignments.add(Assignment(shift_id, volunteer_id, signed_up_at=now - timedelta(days=5)))
            elif waiting < DEMO_WAITLIST_SIZE:
                store.waitlist.add(shift_id, volunteer_id, now - timedelta(days=3, hours=offset))
                waiting += 1
            else:
                break
    mine = store.assignments.upcoming_scheduled(after=now, volunteer_id=_saved_id(priya.volunteer_id))
    if mine:
        store.notices.add(
            _saved_id(priya.volunteer_id), NoticeKind.WAITLIST_PROMOTED, mine[-1].shift_id, now - timedelta(days=1)
        )


def _add_announcements_and_kiosk_times(store: DataStore, volunteers: list[Volunteer], today: date) -> None:
    """
    Two notes from coordinators (one for the whole 5K, one for a shift Priya is on), and
    kiosk arrival and departure times for the most recent finished shift, consistent with
    the hours already recorded for it.
    """
    now = datetime.combine(today, time(8))
    event = next(o for o in store.opportunities.find_all() if o.title == DEMO_EVENT_PROGRAM)
    store.announcements.add(
        body=DEMO_EVENT_ANNOUNCEMENT,
        posted_by="coordinator",
        posted_at=now - timedelta(days=2),
        opportunity_id=event.opportunity_id,
        shift_id=None,
    )
    mine = store.assignments.upcoming_scheduled(after=now, volunteer_id=_saved_id(volunteers[1].volunteer_id))
    if mine:
        store.announcements.add(
            body=DEMO_SHIFT_ANNOUNCEMENT,
            posted_by="coordinator",
            posted_at=now - timedelta(days=1),
            opportunity_id=None,
            shift_id=mine[0].shift_id,
        )
    finished = [o for o in store.shifts.overviews(starts_before=now) if o.shift.ends_at <= now and o.filled]
    if finished:
        shift = finished[-1].shift
        for index, entry in enumerate(store.assignments.roster(_saved_id(shift.shift_id))):
            served = entry.assignment.hours_served
            if entry.assignment.status is not AssignmentStatus.ATTENDED or served is None:
                continue
            arrived = shift.starts_at - timedelta(minutes=5) + timedelta(minutes=3 * index)
            left = max(arrived, shift.starts_at) + timedelta(hours=served)
            store.assignments.update(dataclasses.replace(entry.assignment, checked_in_at=arrived, checked_out_at=left))


def _add_issued_documents(store: DataStore, volunteers: list[Volunteer], today: date) -> None:
    """
    Two documents Priya has already saved, with fixed codes so the demo of *Verify a record*
    always works: her service record for this school year, and her 50-hour certificate.
    """
    priya_id = _saved_id(volunteers[1].volunteer_id)
    start = date(today.year if today.month >= 8 else today.year - 1, 8, 1)
    issued_at = datetime.combine(today - timedelta(days=3), time(16))
    store.documents.add(
        code=DEMO_RECORD_CODE,
        kind="SERVICE_RECORD",
        volunteer_id=priya_id,
        hours=round(store.assignments.total_hours(volunteer_id=priya_id, start=start, end=issued_at.date()), 2),
        issued_at=issued_at,
        issued_by="priya.patel",
        period_start=start,
        period_end=issued_at.date(),
    )
    if store.assignments.total_hours(volunteer_id=priya_id) >= DEMO_CERTIFICATE_HOURS:
        store.documents.add(
            code=DEMO_CERTIFICATE_CODE,
            kind="MILESTONE",
            volunteer_id=priya_id,
            hours=float(DEMO_CERTIFICATE_HOURS),
            issued_at=issued_at,
            issued_by="priya.patel",
            milestone=DEMO_CERTIFICATE_HOURS,
        )


def _create_todays_checkin_shifts(
    store: DataStore, volunteers: list[Volunteer], shifts: list[tuple[Shift, Opportunity]], today: date
) -> int:
    """Shifts throughout today, so the check-in kiosk has someone to welcome whenever the demo happens."""
    open_programs = (o for _, o in shifts if o.status is OpportunityStatus.OPEN and o.title != DEMO_CERTIFIED_PROGRAM)
    opportunity = min(open_programs, key=lambda o: o.min_age)
    count = 0
    for start_hour in DEMO_CHECKIN_START_HOURS:
        starts_at = datetime.combine(today, time(start_hour))
        ends_at = starts_at + timedelta(hours=DEMO_CHECKIN_SHIFT_HOURS)
        shift = store.shifts.add(
            Shift(_saved_id(opportunity.opportunity_id), starts_at, ends_at, DEMO_CHECKIN_CAPACITY)
        )
        count += 1
        roster = 0
        for volunteer in (v for v in volunteers if v.status is VolunteerStatus.ACTIVE):
            volunteer_id = _saved_id(volunteer.volunteer_id)
            if roster == DEMO_CHECKIN_ROSTER or store.assignments.conflicting_shifts(volunteer_id, starts_at, ends_at):
                continue
            store.assignments.add(
                Assignment(
                    _saved_id(shift.shift_id), volunteer_id, signed_up_at=starts_at - timedelta(days=DEMO_SIGNUP_LEAD)
                )
            )
            roster += 1
    return count


# ----------------------------------------------------------------- accounts


def _create_accounts(store: DataStore, volunteers: list[Volunteer], iterations: int) -> int:
    jordan, priya = volunteers[0], volunteers[1]
    logins: list[tuple[str, UserRole, int | None]] = [
        ("admin", UserRole.ADMIN, None),
        ("coordinator", UserRole.COORDINATOR, None),
        ("jordan.rivera", UserRole.VOLUNTEER, jordan.volunteer_id),
        ("priya.patel", UserRole.VOLUNTEER, priya.volunteer_id),
    ]
    for username, role, volunteer_id in logins:
        store.accounts.add(
            UserAccount(
                username=username,
                # Hashed separately so every account gets its own random salt.
                password_hash=hash_password(DEMO_PASSWORD, iterations=iterations),
                role=role,
                volunteer_id=volunteer_id,
            )
        )
    return len(logins)
