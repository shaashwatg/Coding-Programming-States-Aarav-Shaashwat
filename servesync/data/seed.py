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
    DayPart,
    Opportunity,
    OpportunityCategory,
    OpportunityStatus,
    RecruitmentSource,
    Shift,
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

    summary = SeedSummary(
        volunteers=len(volunteers),
        opportunities=len(plans) + 1,  # +1 draft program with no shifts yet
        shifts=len(shifts),
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
