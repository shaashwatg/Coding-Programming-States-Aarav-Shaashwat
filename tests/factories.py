"""Factory helpers that build valid sample records; tests override only what they need."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from servesync.core.security import hash_password
from servesync.models import (
    AvailabilitySlot,
    DayPart,
    Opportunity,
    OpportunityCategory,
    OpportunityStatus,
    Shift,
    UserRole,
    Volunteer,
    VolunteerStatus,
    Weekday,
)
from servesync.services import Session

FAST_ITERATIONS = 1_000  # keeps password tests fast; production uses 600,000


def make_volunteer(**overrides: object) -> Volunteer:
    fields: dict[str, object] = {
        "first_name": "Ana",
        "last_name": "Lopez",
        "email": "ana.lopez@example.org",
        "phone": "(312) 555-0142",
        "birth_date": date(1998, 4, 12),
        "joined_on": date(2025, 1, 15),
        "status": VolunteerStatus.ACTIVE,
        "skills": frozenset({"Tutoring", "Spanish"}),
        "availability": frozenset({AvailabilitySlot(Weekday.SATURDAY, DayPart.MORNING)}),
    }
    fields.update(overrides)
    return Volunteer(**fields)  # type: ignore[arg-type]


def make_opportunity(**overrides: object) -> Opportunity:
    fields: dict[str, object] = {
        "title": "Food Pantry",
        "description": "Sort and distribute groceries to local families.",
        "category": OpportunityCategory.FOOD_SECURITY,
        "location": "Community Center",
        "coordinator_name": "Dana Whitfield",
        "status": OpportunityStatus.OPEN,
        "required_skills": frozenset({"Food Handling"}),
    }
    fields.update(overrides)
    return Opportunity(**fields)  # type: ignore[arg-type]


def make_shift(opportunity_id: int, start: datetime, hours: float = 3, capacity: int = 5) -> Shift:
    return Shift(opportunity_id, start, start + timedelta(hours=hours), capacity)


def fast_hash(password: str = "Volunteer2026") -> str:
    return hash_password(password, iterations=FAST_ITERATIONS)


# ------------------------------------------------------------ service tests

ADMIN = Session(account_id=1, username="admin", role=UserRole.ADMIN)
COORDINATOR = Session(account_id=2, username="coordinator", role=UserRole.COORDINATOR)


def volunteer_session(volunteer_id: int) -> Session:
    """A signed-in volunteer acting on their own behalf."""
    return Session(
        account_id=100 + volunteer_id, username=f"vol{volunteer_id}", role=UserRole.VOLUNTEER, volunteer_id=volunteer_id
    )
