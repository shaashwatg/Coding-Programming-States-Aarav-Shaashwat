"""
Report vocabulary: what a person can ask for (filters) and what they get back.

Everything here is an immutable value object. A ``Report`` is plain data, so
the same object feeds the on-screen table, the chart, the CSV file and the PDF
without any of them recomputing a number — one source of truth per figure.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum

from servesync.core.validators import ErrorCollector, parse_date
from servesync.models import OpportunityCategory

#: Longest range one report may cover. Keeps a mistyped year (2062) from
#: silently producing an empty or enormous report.
MAX_RANGE_DAYS = 366 * 5


class ReportKind(Enum):
    """The reports ServeSync can produce. Each answers one leadership question."""

    VOLUNTEER_HOURS = "VOLUNTEER_HOURS"
    PROGRAM_IMPACT = "PROGRAM_IMPACT"
    SHIFT_ATTENDANCE = "SHIFT_ATTENDANCE"
    RECRUITMENT = "RECRUITMENT"
    SERVICE_RECORD = "SERVICE_RECORD"

    @property
    def label(self) -> str:
        return _KIND_TEXT[self][0]

    @property
    def question(self) -> str:
        """The question this report answers (shown under the report picker)."""
        return _KIND_TEXT[self][1]

    @property
    def for_leaders(self) -> bool:
        return self is not ReportKind.SERVICE_RECORD


_KIND_TEXT: dict[ReportKind, tuple[str, str]] = {
    ReportKind.VOLUNTEER_HOURS: (
        "Volunteer hours",
        "Who served, how much, and who might need a check-in?",
    ),
    ReportKind.PROGRAM_IMPACT: (
        "Program impact",
        "Which programs fill their shifts and deliver the most hours?",
    ),
    ReportKind.SHIFT_ATTENDANCE: (
        "Shift attendance",
        "Which shifts were full or short, and which still need attendance recorded?",
    ),
    ReportKind.RECRUITMENT: (
        "Recruitment channels",
        "Where do new volunteers come from, and which channels bring people who stay?",
    ),
    ReportKind.SERVICE_RECORD: (
        "Service hours record",
        "A verified list of one volunteer's service, for school, scholarships, or employers.",
    ),
}


class DatePreset(Enum):
    """Common reporting periods, resolved against "today"."""

    LAST_30_DAYS = "Last 30 days"
    THIS_MONTH = "This month"
    LAST_MONTH = "Last month"
    LAST_90_DAYS = "Last 90 days"
    SCHOOL_YEAR = "This school year (Aug-Jul)"
    THIS_YEAR = "This calendar year"
    CUSTOM = "Custom dates"

    def resolve(self, today: date) -> tuple[date, date]:
        """Inclusive (start, end) for this preset. CUSTOM returns the last 30 days as a starting point."""
        if self is DatePreset.THIS_MONTH:
            return today.replace(day=1), today
        if self is DatePreset.LAST_MONTH:
            last_day = today.replace(day=1) - timedelta(days=1)
            return last_day.replace(day=1), last_day
        if self is DatePreset.LAST_90_DAYS:
            return today - timedelta(days=89), today
        if self is DatePreset.SCHOOL_YEAR:
            year = today.year if today.month >= 8 else today.year - 1
            return date(year, 8, 1), today
        if self is DatePreset.THIS_YEAR:
            return date(today.year, 1, 1), today
        return today - timedelta(days=29), today


class ValueKind(Enum):
    """How a column's values are displayed (stored values stay raw numbers)."""

    TEXT = "text"
    COUNT = "count"
    HOURS = "hours"
    PERCENT = "percent"  # stored 0-100
    MONEY = "money"
    DATE = "date"

    @property
    def is_numeric(self) -> bool:
        return self in (ValueKind.COUNT, ValueKind.HOURS, ValueKind.PERCENT, ValueKind.MONEY)


def format_value(kind: ValueKind, value: object) -> str:
    """Human-readable text for one cell. ``None`` (no data) shows as an en dash."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "–"
    if kind is ValueKind.COUNT and isinstance(value, (int, float)):
        return f"{value:,.0f}"
    if kind is ValueKind.HOURS and isinstance(value, (int, float)):
        return f"{value:,.1f}" if value % 1 else f"{value:,.0f}"
    if kind is ValueKind.PERCENT and isinstance(value, (int, float)):
        return f"{value:.0f}%"
    if kind is ValueKind.MONEY and isinstance(value, (int, float)):
        return f"${value:,.0f}" if abs(value) >= 1000 else f"${value:,.2f}"
    if kind is ValueKind.DATE and isinstance(value, (date, datetime)):
        return f"{value:%b} {value.day}, {value.year}"
    return str(value)


@dataclass(frozen=True, slots=True)
class ReportColumn:
    key: str
    label: str
    kind: ValueKind = ValueKind.TEXT
    #: Hidden columns can be switched on in the report's column chooser.
    shown_by_default: bool = True


@dataclass(frozen=True, slots=True)
class ReportFilters:
    """
    What the person asked for. Validated on creation:

    * Syntactic — dates parse (``MM/DD/YYYY`` text is accepted too).
    * Semantic — start is not after end; the range is at most five years;
      a service record names a volunteer.
    """

    start: date
    end: date
    opportunity_id: int | None = None
    category: OpportunityCategory | None = None
    include_inactive: bool = False
    volunteer_id: int | None = None  # SERVICE_RECORD only

    def __post_init__(self) -> None:
        errors = ErrorCollector()
        start = errors.check("start", parse_date, self.start, "Start date")
        end = errors.check("end", parse_date, self.end, "End date")
        if isinstance(start, date) and isinstance(end, date):
            if start > end:
                errors.add("end", "End date must be on or after the start date.")
            elif (end - start).days > MAX_RANGE_DAYS:
                errors.add("end", "Choose a range of five years or less.")
        errors.raise_if_any()
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def describe(self) -> str:
        return f"{format_value(ValueKind.DATE, self.start)} – {format_value(ValueKind.DATE, self.end)}"


@dataclass(frozen=True, slots=True)
class Figure:
    """One headline number at the top of a report."""

    label: str
    value: str
    note: str = ""


@dataclass(frozen=True, slots=True)
class ChartSeries:
    """One bar or line series, already in display order."""

    title: str
    labels: tuple[str, ...]
    values: tuple[float, ...]
    kind: ValueKind
    #: "bar" for comparing categories, "line" for change over time.
    style: str = "bar"

    @property
    def is_empty(self) -> bool:
        return not self.values or all(value == 0 for value in self.values)


@dataclass(frozen=True, slots=True)
class Report:
    kind: ReportKind
    title: str
    filters: ReportFilters
    columns: tuple[ReportColumn, ...]
    rows: tuple[dict[str, object], ...]
    figures: tuple[Figure, ...]
    insights: tuple[str, ...]
    charts: tuple[ChartSeries, ...]
    generated_at: datetime
    organization_name: str
    #: Extra lines printed under the title (who the report is about, filters in use).
    context: tuple[str, ...] = field(default=())

    @property
    def is_empty(self) -> bool:
        return not self.rows

    def column(self, key: str) -> ReportColumn:
        for column in self.columns:
            if column.key == key:
                return column
        raise KeyError(key)
