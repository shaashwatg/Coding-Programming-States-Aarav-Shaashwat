"""
Service opportunities (programs/events) and the shifts that staff them.

An *opportunity* describes the work ("Weekend Food Pantry Distribution");
a *shift* is one dated time block for it with a volunteer capacity. Splitting
them avoids repeating the description, location and coordinator on every
date — a textbook normalization decision we can explain to judges.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from servesync.config import MAX_SHIFT_CAPACITY, MAX_SHIFT_HOURS, MINIMUM_VOLUNTEER_AGE
from servesync.core.validators import (
    ErrorCollector,
    clean_text,
    clean_url,
    parse_datetime,
    parse_enum,
    parse_int,
)
from servesync.models._common import clean_skill_set, validate_optional_id, validate_reference_id
from servesync.models.enums import AccessNeed, DayPart, OpportunityCategory, OpportunityStatus, Weekday
from servesync.models.volunteer import clean_access_needs

MIN_SHIFT_MINUTES = 15


@dataclass(slots=True)
class Opportunity:
    """A volunteer program, project, or event run by the organization."""

    title: str
    description: str
    category: OpportunityCategory
    location: str
    coordinator_name: str
    min_age: int = MINIMUM_VOLUNTEER_AGE
    status: OpportunityStatus = OpportunityStatus.DRAFT
    required_skills: frozenset[str] = frozenset()
    story_video_url: str = ""  # optional link to a video story; opened only when clicked
    access_features: frozenset[AccessNeed] = frozenset()  # supports this program offers
    opportunity_id: int | None = None

    def __post_init__(self) -> None:
        errors = ErrorCollector()
        self.title = errors.check("title", clean_text, self.title, "Title", max_length=80)
        if isinstance(self.title, str) and 0 < len(self.title) < 3:
            errors.add("title", "Title must be at least 3 characters.")
        self.description = errors.check(
            "description", clean_text, self.description, "Description", max_length=1000, multiline=True
        )
        if isinstance(self.description, str) and 0 < len(self.description) < 10:
            errors.add("description", "Description should be at least 10 characters so volunteers know what to expect.")
        self.category = errors.check("category", parse_enum, self.category, OpportunityCategory, "Category")
        self.location = errors.check("location", clean_text, self.location, "Location", max_length=120)
        self.coordinator_name = errors.check(
            "coordinator_name", clean_text, self.coordinator_name, "Coordinator name", max_length=80
        )
        # Semantic: an opportunity may raise the organization's minimum age
        # (e.g. 18+ for driving) but never lower it.
        self.min_age = errors.check(
            "min_age", parse_int, self.min_age, "Minimum age", minimum=MINIMUM_VOLUNTEER_AGE, maximum=99
        )
        self.status = errors.check("status", parse_enum, self.status, OpportunityStatus, "Opportunity status")
        self.required_skills = errors.check("required_skills", clean_skill_set, self.required_skills, "Required skills")
        self.story_video_url = errors.check("story_video_url", clean_url, self.story_video_url, "Story video link")
        self.access_features = errors.check(
            "access_features", clean_access_needs, self.access_features, "Access features"
        )
        self.opportunity_id = errors.check(
            "opportunity_id", validate_optional_id, self.opportunity_id, "Opportunity ID"
        )
        errors.raise_if_any()


@dataclass(slots=True)
class Shift:
    """One scheduled time block for an opportunity, with a volunteer capacity."""

    opportunity_id: int
    starts_at: datetime
    ends_at: datetime
    capacity: int
    notes: str = ""  # e.g. "Wear closed-toe shoes"
    shift_id: int | None = None

    def __post_init__(self) -> None:
        errors = ErrorCollector()
        self.opportunity_id = errors.check("opportunity_id", validate_reference_id, self.opportunity_id, "Opportunity")
        self.starts_at = errors.check("starts_at", parse_datetime, self.starts_at, "Start time")
        self.ends_at = errors.check("ends_at", parse_datetime, self.ends_at, "End time")
        self.capacity = errors.check(
            "capacity", parse_int, self.capacity, "Volunteers needed", minimum=1, maximum=MAX_SHIFT_CAPACITY
        )
        self.notes = errors.check(
            "notes", clean_text, self.notes, "Shift notes", max_length=300, required=False, multiline=True
        )
        self.shift_id = errors.check("shift_id", validate_optional_id, self.shift_id, "Shift ID")

        # Cross-field semantic checks.
        if isinstance(self.starts_at, datetime) and isinstance(self.ends_at, datetime):
            length = self.ends_at - self.starts_at
            if length <= timedelta(0):
                errors.add("ends_at", "End time must be after the start time.")
            elif length < timedelta(minutes=MIN_SHIFT_MINUTES):
                errors.add("ends_at", f"A shift must last at least {MIN_SHIFT_MINUTES} minutes.")
            elif length > timedelta(hours=MAX_SHIFT_HOURS):
                errors.add(
                    "ends_at",
                    f"A shift cannot be longer than {MAX_SHIFT_HOURS} hours — check AM/PM on the end time.",
                )
        errors.raise_if_any()

    @property
    def duration_hours(self) -> float:
        return round((self.ends_at - self.starts_at).total_seconds() / 3600, 2)

    @property
    def weekday(self) -> Weekday:
        return Weekday(self.starts_at.weekday())

    @property
    def day_part(self) -> DayPart:
        return DayPart.from_hour(self.starts_at.hour)

    def overlaps(self, starts_at: datetime, ends_at: datetime) -> bool:
        """True if this shift shares any time with the given interval (touching ends do not count)."""
        return self.starts_at < ends_at and starts_at < self.ends_at

    def has_started(self, now: datetime | None = None) -> bool:
        return self.starts_at <= (now or datetime.now())
