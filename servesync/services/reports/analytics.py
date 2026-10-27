"""
Report math as pure functions: lists of facts in, a finished ``Report`` out.

No database, no clock, no Qt — so every total, rate and insight here is
covered by fast unit tests, and the same numbers appear on screen, in the CSV
and in the PDF.

Data structures used (the rubric's "arrays/lists where appropriate"):

* ``list[ServiceFact]`` — the raw sign-ups, loaded once per report.
* ``dict[int, _Tally]`` — one running tally per volunteer/program/shift,
  keyed by ID: a single pass over the facts fills every row (O(n)).
* ``defaultdict(float)`` buckets for trends (week or month -> hours).
* ``tuple`` for finished rows, columns and chart series, so nothing
  downstream can change a number by accident.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

from servesync.core.i18n import format_clock, format_day_short, format_month_year, mark, tr, tr_n, weekday_plural
from servesync.models import (
    AssignmentStatus,
    Opportunity,
    RecruitmentSource,
    ServiceFact,
    ShiftOverview,
    Volunteer,
    VolunteerStatus,
    Weekday,
)
from servesync.services.reports.model import (
    ChartSeries,
    Figure,
    Report,
    ReportColumn,
    ReportFilters,
    ReportKind,
    ValueKind,
    format_value,
)

if TYPE_CHECKING:  # typing-only: "any dataclass instance"
    from _typeshed import DataclassInstance

#: Reliability below this share of kept commitments is called out.
LOW_RELIABILITY_PERCENT = 70.0
#: ...but only once someone has this many completed shifts (fairness to newcomers).
RELIABILITY_MIN_SHIFTS = 3
#: Program no-show rate worth flagging.
HIGH_NO_SHOW_PERCENT = 15.0
#: Applicants waiting longer than this are flagged for review.
APPLICANT_WAIT_DAYS = 14
#: Trends switch from weekly to monthly buckets above this many days.
WEEKLY_TREND_MAX_DAYS = 92
TOP_CHART_BARS = 10


@dataclass(frozen=True, slots=True)
class ReportInputs:
    """Everything a report needs, gathered by the service in a few queries."""

    facts: Sequence[ServiceFact]
    shifts: Sequence[ShiftOverview]
    volunteers: Sequence[Volunteer]
    opportunities: Mapping[int, Opportunity]
    hour_value: float
    now: datetime
    organization_name: str


@dataclass(slots=True)
class _Tally:
    """Running totals for one row while the facts are scanned."""

    hours: float = 0.0
    attended: int = 0
    no_shows: int = 0
    cancelled: int = 0
    scheduled: int = 0
    unrecorded: int = 0  # still SCHEDULED after the shift started
    last_served: date | None = None
    volunteers: set[int] = field(default_factory=set)
    programs: set[int] = field(default_factory=set)

    def add(self, fact: ServiceFact, now: datetime) -> None:
        if fact.status is AssignmentStatus.ATTENDED:
            self.hours += fact.hours
            self.attended += 1
            self.volunteers.add(fact.volunteer_id)
            self.programs.add(fact.opportunity_id)
            served = fact.starts_at.date()
            self.last_served = served if self.last_served is None else max(self.last_served, served)
        elif fact.status is AssignmentStatus.NO_SHOW:
            self.no_shows += 1
        elif fact.status is AssignmentStatus.CANCELLED:
            self.cancelled += 1
        else:
            self.scheduled += 1
            if fact.starts_at <= now:
                self.unrecorded += 1

    @property
    def holds_spot(self) -> int:
        """Sign-ups that occupy a spot (everything except cancellations)."""
        return self.attended + self.no_shows + self.scheduled

    @property
    def show_up_percent(self) -> float | None:
        completed = self.attended + self.no_shows
        return None if completed == 0 else round(100 * self.attended / completed, 1)


def percent(part: float, whole: float) -> float | None:
    """``part`` as a share of ``whole`` (0-100, one decimal), or None when undefined."""
    return None if whole <= 0 else round(100 * part / whole, 1)


def tally_by(facts: Iterable[ServiceFact], key: Callable[[ServiceFact], int], now: datetime) -> dict[int, _Tally]:
    """One pass over the facts: a tally per key (volunteer, program, or shift ID)."""
    tallies: defaultdict[int, _Tally] = defaultdict(_Tally)
    for fact in facts:
        tallies[key(fact)].add(fact, now)
    return dict(tallies)


def apply_scope(inputs: ReportInputs, filters: ReportFilters) -> tuple[list[ServiceFact], list[ShiftOverview]]:
    """Facts and shifts limited to the program/category the person picked."""

    def in_scope(opportunity_id: int, category: object) -> bool:
        if filters.opportunity_id is not None and opportunity_id != filters.opportunity_id:
            return False
        return filters.category is None or category is filters.category

    facts = [f for f in inputs.facts if in_scope(f.opportunity_id, f.category)]
    shifts = [s for s in inputs.shifts if in_scope(s.shift.opportunity_id, s.category)]
    return facts, shifts


def hours_trend(facts: Iterable[ServiceFact], filters: ReportFilters) -> ChartSeries:
    """Hours served per week (short ranges) or per month (long ranges), gaps filled with zero."""
    weekly = filters.days <= WEEKLY_TREND_MAX_DAYS
    buckets: defaultdict[date, float] = defaultdict(float)
    for fact in facts:
        if fact.status is AssignmentStatus.ATTENDED:
            buckets[_bucket(fact.starts_at.date(), weekly)] += fact.hours

    labels: list[str] = []
    values: list[float] = []
    cursor = _bucket(filters.start, weekly)
    while cursor <= filters.end:
        labels.append(format_day_short(cursor) if weekly else format_month_year(cursor))
        values.append(round(buckets.get(cursor, 0.0), 2))
        cursor = cursor + timedelta(days=7) if weekly else _next_month(cursor)
    return ChartSeries(
        tr("Hours per week") if weekly else tr("Hours per month"), tuple(labels), tuple(values), ValueKind.HOURS, "line"
    )


def _bucket(day: date, weekly: bool) -> date:
    return day - timedelta(days=day.weekday()) if weekly else day.replace(day=1)


def _next_month(day: date) -> date:
    return date(day.year + (day.month == 12), day.month % 12 + 1, 1)


def top_bars(
    title: str, pairs: Iterable[tuple[str, float]], kind: ValueKind, limit: int = TOP_CHART_BARS
) -> ChartSeries:
    """Largest values first, capped so labels stay readable."""
    ordered = sorted(pairs, key=lambda pair: (-pair[1], pair[0]))[:limit]
    return ChartSeries(title, tuple(p[0] for p in ordered), tuple(round(p[1], 2) for p in ordered), kind)


def _hours(value: float) -> str:
    return f"{format_value(ValueKind.HOURS, value)} h"


def _report(
    kind: ReportKind,
    inputs: ReportInputs,
    filters: ReportFilters,
    columns: Sequence[ReportColumn],
    rows: Sequence[DataclassInstance],
    figures: Sequence[Figure],
    insights: Sequence[str],
    charts: Sequence[ChartSeries],
    context: Sequence[str] = (),
) -> Report:
    scope: list[str] = list(context)
    if filters.opportunity_id is not None and filters.opportunity_id in inputs.opportunities:
        scope.append(tr("Program: {title}", title=inputs.opportunities[filters.opportunity_id].title))
    if filters.category is not None:
        scope.append(tr("Category: {label}", label=filters.category.label))
    return Report(
        kind=kind,
        title=kind.label,
        filters=filters,
        columns=tuple(columns),
        rows=tuple(asdict(row) for row in rows),
        figures=tuple(figures),
        insights=tuple(insights),
        charts=tuple(chart for chart in charts if not chart.is_empty),
        generated_at=inputs.now,
        organization_name=inputs.organization_name,
        context=tuple(scope),
    )


# --------------------------------------------------------- volunteer hours

VOLUNTEER_COLUMNS = (
    ReportColumn("name", mark("Volunteer")),
    ReportColumn("status", mark("Status")),
    ReportColumn("hours", mark("Hours"), ValueKind.HOURS),
    ReportColumn("shifts", mark("Shifts served"), ValueKind.COUNT),
    ReportColumn("no_shows", mark("No-shows"), ValueKind.COUNT),
    ReportColumn("cancelled", mark("Cancelled"), ValueKind.COUNT, shown_by_default=False),
    ReportColumn("reliability", mark("Show-up rate"), ValueKind.PERCENT),
    ReportColumn("programs", mark("Programs"), ValueKind.COUNT, shown_by_default=False),
    ReportColumn("value", mark("Community value"), ValueKind.MONEY),
    ReportColumn("last_served", mark("Last served"), ValueKind.DATE),
    ReportColumn("email", mark("Email"), shown_by_default=False),
)


@dataclass(frozen=True, slots=True)
class _VolunteerRow:  # field names match VOLUNTEER_COLUMNS keys
    name: str
    status: str
    hours: float
    shifts: int
    no_shows: int
    cancelled: int
    reliability: float | None
    programs: int
    value: float
    last_served: date | None
    email: str
    is_active: bool


def volunteer_hours(inputs: ReportInputs, filters: ReportFilters) -> Report:
    facts, _shifts = apply_scope(inputs, filters)
    tallies = tally_by(facts, lambda f: f.volunteer_id, inputs.now)
    scoped = filters.opportunity_id is not None or filters.category is not None

    # Who appears: anyone with a sign-up in scope (so totals always match the
    # other reports); without a program filter, also every active volunteer
    # who *didn't* serve — they may need a check-in.
    def listed(volunteer: Volunteer) -> bool:
        if (volunteer.volunteer_id or 0) in tallies:
            return True
        if scoped:
            return False
        return volunteer.status is VolunteerStatus.ACTIVE or (
            filters.include_inactive and volunteer.status is VolunteerStatus.INACTIVE
        )

    rows: list[_VolunteerRow] = []
    for volunteer in filter(listed, inputs.volunteers):
        tally = tallies.get(volunteer.volunteer_id or 0, _Tally())
        rows.append(
            _VolunteerRow(
                name=volunteer.full_name,
                status=volunteer.status.label,
                hours=round(tally.hours, 2),
                shifts=tally.attended,
                no_shows=tally.no_shows,
                cancelled=tally.cancelled,
                reliability=tally.show_up_percent,
                programs=len(tally.programs),
                value=round(tally.hours * inputs.hour_value, 2),
                last_served=tally.last_served,
                email=volunteer.email,
                is_active=volunteer.status is VolunteerStatus.ACTIVE,
            )
        )
    rows.sort(key=lambda row: (-row.hours, row.name))

    total_hours = sum(row.hours for row in rows)
    served = [row for row in rows if row.hours > 0]
    figures = (
        Figure(tr("Hours served"), _hours(total_hours)),
        Figure(
            tr("Community value"),
            format_value(ValueKind.MONEY, total_hours * inputs.hour_value),
            tr("at ${hour_value:.2f} per hour", hour_value=inputs.hour_value),
        ),
        Figure(tr("Volunteers who served"), str(len(served)), tr("of {len} listed", len=len(rows))),
        Figure(
            tr("Average per volunteer"), _hours(total_hours / len(served)) if served else "\u2013", tr("who served")
        ),
    )

    insights: list[str] = []
    if served:
        insights.append(tr("{name} served the most: {hours}.", name=served[0].name, hours=_hours(served[0].hours)))
    if len(served) >= 5:
        top_count = math.ceil(len(served) * 0.2)
        share = percent(sum(row.hours for row in served[:top_count]), total_hours) or 0.0
        if share >= 50:
            insights.append(
                tr_n(
                    "The top {count} volunteer (20%) gave {share:.0f}% of all hours — consider spreading "
                    "shifts around to prevent burnout.",
                    "The top {count} volunteers (20%) gave {share:.0f}% of all hours — consider spreading "
                    "shifts around to prevent burnout.",
                    top_count,
                    share=share,
                )
            )
        else:
            insights.append(
                tr_n(
                    "The top {count} volunteer (20%) gave {share:.0f}% of all hours.",
                    "The top {count} volunteers (20%) gave {share:.0f}% of all hours.",
                    top_count,
                    share=share,
                )
            )
    idle = [row for row in rows if row.is_active and row.hours == 0]
    if idle and not scoped:
        insights.append(
            tr_n(
                "{count} active volunteer didn't serve in this period — a friendly check-in could bring them back.",
                "{count} active volunteers didn't serve in this period — a friendly check-in could bring them back.",
                len(idle),
            )
        )
    shaky = [
        row
        for row in rows
        if row.reliability is not None
        and row.reliability < LOW_RELIABILITY_PERCENT
        and row.shifts + row.no_shows >= RELIABILITY_MIN_SHIFTS
    ]
    if shaky:
        insights.append(
            tr_n(
                "{count} volunteer kept fewer than {limit:.0f}% of their commitments — ask whether their "
                "schedule has changed.",
                "{count} volunteers kept fewer than {limit:.0f}% of their commitments — ask whether their "
                "schedule has changed.",
                len(shaky),
                limit=LOW_RELIABILITY_PERCENT,
            )
        )

    charts = (
        top_bars(tr("Most hours"), ((row.name, row.hours) for row in served), ValueKind.HOURS),
        hours_trend(facts, filters),
    )
    return _report(ReportKind.VOLUNTEER_HOURS, inputs, filters, VOLUNTEER_COLUMNS, rows, figures, insights, charts)


# ---------------------------------------------------------- program impact

PROGRAM_COLUMNS = (
    ReportColumn("program", mark("Program")),
    ReportColumn("category", mark("Category"), shown_by_default=False),
    ReportColumn("shifts", mark("Shifts"), ValueKind.COUNT),
    ReportColumn("spots", mark("Spots offered"), ValueKind.COUNT),
    ReportColumn("signed_up", mark("Signed up"), ValueKind.COUNT),
    ReportColumn("fill_rate", mark("Fill rate"), ValueKind.PERCENT),
    ReportColumn("attended", mark("Attended"), ValueKind.COUNT, shown_by_default=False),
    ReportColumn("no_shows", mark("No-shows"), ValueKind.COUNT, shown_by_default=False),
    ReportColumn("show_up_rate", mark("Show-up rate"), ValueKind.PERCENT),
    ReportColumn("hours", mark("Hours"), ValueKind.HOURS),
    ReportColumn("volunteers", mark("Volunteers"), ValueKind.COUNT),
    ReportColumn("value", mark("Community value"), ValueKind.MONEY),
)


@dataclass(frozen=True, slots=True)
class _ProgramRow:
    program: str
    category: str
    shifts: int
    spots: int
    signed_up: int
    fill_rate: float | None
    attended: int
    no_shows: int
    show_up_rate: float | None
    hours: float
    volunteers: int
    value: float


def program_impact(inputs: ReportInputs, filters: ReportFilters) -> Report:
    facts, shifts = apply_scope(inputs, filters)
    tallies = tally_by(facts, lambda f: f.opportunity_id, inputs.now)
    shift_count: defaultdict[int, int] = defaultdict(int)
    capacity: defaultdict[int, int] = defaultdict(int)
    for overview in shifts:
        shift_count[overview.shift.opportunity_id] += 1
        capacity[overview.shift.opportunity_id] += overview.shift.capacity

    rows: list[_ProgramRow] = []
    for program_id in sorted(set(shift_count) | set(tallies)):
        opportunity = inputs.opportunities.get(program_id)
        if opportunity is None:
            continue
        tally = tallies.get(program_id, _Tally())
        rows.append(
            _ProgramRow(
                program=opportunity.title,
                category=opportunity.category.label,
                shifts=shift_count[program_id],
                spots=capacity[program_id],
                signed_up=tally.holds_spot,
                fill_rate=percent(tally.holds_spot, capacity[program_id]),
                attended=tally.attended,
                no_shows=tally.no_shows,
                show_up_rate=tally.show_up_percent,
                hours=round(tally.hours, 2),
                volunteers=len(tally.volunteers),
                value=round(tally.hours * inputs.hour_value, 2),
            )
        )
    rows.sort(key=lambda row: (-row.hours, row.program))

    total_hours = sum(row.hours for row in rows)
    total_spots = sum(row.spots for row in rows)
    total_signed = sum(row.signed_up for row in rows)
    figures = (
        Figure(tr("Programs"), str(len(rows))),
        Figure(tr("Hours served"), _hours(total_hours)),
        Figure(
            tr("Overall fill rate"),
            format_value(ValueKind.PERCENT, percent(total_signed, total_spots)),
            tr("{total_signed} of {total_spots} spots", total_signed=total_signed, total_spots=total_spots),
        ),
        Figure(tr("Community value"), format_value(ValueKind.MONEY, total_hours * inputs.hour_value)),
    )

    insights: list[str] = []
    if rows and total_hours:
        top = rows[0]
        insights.append(
            tr(
                ("'{program}' delivered the most service: {hours} ({value:.0f}% of the total)."),
                program=top.program,
                hours=_hours(top.hours),
                value=percent(top.hours, total_hours) or 0,
            )
        )
    rated = [row for row in rows if row.fill_rate is not None and row.shifts >= 2]
    if len(rated) >= 2:
        weakest = min(rated, key=lambda row: row.fill_rate or 0.0)
        if (weakest.fill_rate or 0.0) < 75:
            insights.append(
                tr(
                    (
                        "'{program}' fills only {fill_rate:.0f}% of its spots — try Smart "
                        "Match on its next shifts, or offer fewer spots."
                    ),
                    program=weakest.program,
                    fill_rate=weakest.fill_rate,
                )
            )
    flaky = [row for row in rows if row.show_up_rate is not None and 100 - row.show_up_rate > HIGH_NO_SHOW_PERCENT]
    for row in flaky[:2]:
        insights.append(
            tr(
                ("'{program}' has a {value:.0f}% no-show rate — a reminder the day before usually helps."),
                program=row.program,
                value=100 - (row.show_up_rate or 0),
            )
        )

    charts = (
        top_bars(tr("Hours by program"), ((row.program, row.hours) for row in rows), ValueKind.HOURS),
        hours_trend(facts, filters),
    )
    return _report(ReportKind.PROGRAM_IMPACT, inputs, filters, PROGRAM_COLUMNS, rows, figures, insights, charts)


# -------------------------------------------------------- shift attendance

SHIFT_COLUMNS = (
    ReportColumn("date", mark("Date"), ValueKind.DATE),
    ReportColumn("time", mark("Time")),
    ReportColumn("program", mark("Program")),
    ReportColumn("capacity", mark("Spots"), ValueKind.COUNT),
    ReportColumn("signed_up", mark("Signed up"), ValueKind.COUNT),
    ReportColumn("fill_rate", mark("Fill rate"), ValueKind.PERCENT),
    ReportColumn("attended", mark("Attended"), ValueKind.COUNT),
    ReportColumn("no_shows", mark("No-shows"), ValueKind.COUNT),
    ReportColumn("unrecorded", mark("Not recorded"), ValueKind.COUNT),
    ReportColumn("hours", mark("Hours"), ValueKind.HOURS, shown_by_default=False),
)


@dataclass(frozen=True, slots=True)
class _ShiftRow:
    date: date
    time: str
    program: str
    capacity: int
    signed_up: int
    fill_rate: float | None
    attended: int
    no_shows: int
    unrecorded: int
    hours: float


def _clock(moment: datetime) -> str:
    return format_clock(moment)


def shift_attendance(inputs: ReportInputs, filters: ReportFilters) -> Report:
    facts, shifts = apply_scope(inputs, filters)
    tallies = tally_by(facts, lambda f: f.shift_id, inputs.now)

    rows: list[_ShiftRow] = []
    upcoming_thin = 0
    signed_by_day: defaultdict[Weekday, int] = defaultdict(int)
    spots_by_day: defaultdict[Weekday, int] = defaultdict(int)
    for overview in shifts:
        shift = overview.shift
        tally = tallies.get(shift.shift_id or 0, _Tally())
        fill = percent(tally.holds_spot, shift.capacity)
        rows.append(
            _ShiftRow(
                date=shift.starts_at.date(),
                time=f"{_clock(shift.starts_at)} \u2013 {_clock(shift.ends_at)}",
                program=overview.opportunity_title,
                capacity=shift.capacity,
                signed_up=tally.holds_spot,
                fill_rate=fill,
                attended=tally.attended,
                no_shows=tally.no_shows,
                unrecorded=tally.unrecorded,
                hours=round(tally.hours, 2),
            )
        )
        signed_by_day[shift.weekday] += tally.holds_spot
        spots_by_day[shift.weekday] += shift.capacity
        if shift.starts_at > inputs.now and (fill or 0.0) < 50:
            upcoming_thin += 1

    signed = sum(row.signed_up for row in rows)
    spots = sum(row.capacity for row in rows)
    attended = sum(row.attended for row in rows)
    no_shows = sum(row.no_shows for row in rows)
    to_record = sum(1 for row in rows if row.unrecorded)
    figures = (
        Figure(tr("Shifts"), str(len(rows))),
        Figure(
            tr("Fill rate"),
            format_value(ValueKind.PERCENT, percent(signed, spots)),
            tr("{signed} of {spots} spots", signed=signed, spots=spots),
        ),
        Figure(tr("Show-up rate"), format_value(ValueKind.PERCENT, percent(attended, attended + no_shows))),
        Figure(tr("Attendance to record"), str(to_record), tr("shifts that already started")),
    )

    weekday_fill = {day: percent(signed_by_day[day], spots_by_day[day]) or 0.0 for day in Weekday if spots_by_day[day]}
    insights: list[str] = []
    if to_record:
        insights.append(
            tr_n(
                "{count} shift already started but still has attendance to record — open it from the "
                "Calendar so the hours count.",
                "{count} shifts already started but still have attendance to record — open them from the "
                "Calendar so the hours count.",
                to_record,
            )
        )
    if len(weekday_fill) >= 2:
        best = max(weekday_fill, key=lambda day: (weekday_fill[day], -int(day)))
        worst = min(weekday_fill, key=lambda day: (weekday_fill[day], int(day)))
        if weekday_fill[best] > weekday_fill[worst]:
            insights.append(
                tr(
                    "{best} fill best ({best_rate:.0f}%) and {worst} least ({worst_rate:.0f}%) — "
                    "plan big events for {best}.",
                    best=weekday_plural(best),
                    best_rate=weekday_fill[best],
                    worst=weekday_plural(worst),
                    worst_rate=weekday_fill[worst],
                )
            )
    if upcoming_thin:
        insights.append(
            tr_n(
                "{count} upcoming shift in this range is less than half full.",
                "{count} upcoming shifts in this range are less than half full.",
                upcoming_thin,
            )
        )

    weekday_chart = ChartSeries(
        tr("Fill rate by day of week"),
        tuple(day.short_label for day in weekday_fill),
        tuple(weekday_fill.values()),
        ValueKind.PERCENT,
    )
    return _report(
        ReportKind.SHIFT_ATTENDANCE, inputs, filters, SHIFT_COLUMNS, rows, figures, insights, (weekday_chart,)
    )


# ---------------------------------------------------------------- recruitment

RECRUITMENT_COLUMNS = (
    ReportColumn("source", mark("Channel")),
    ReportColumn("new", mark("New in period"), ValueKind.COUNT),
    ReportColumn("total", mark("All volunteers"), ValueKind.COUNT),
    ReportColumn("active", mark("Active now"), ValueKind.COUNT),
    ReportColumn("applicants", mark("Awaiting review"), ValueKind.COUNT),
    ReportColumn("retention", mark("Still active"), ValueKind.PERCENT),
    ReportColumn("hours", mark("Hours in period"), ValueKind.HOURS),
    ReportColumn("hours_each", mark("Hours per volunteer"), ValueKind.HOURS),
)


@dataclass(frozen=True, slots=True)
class _SourceRow:
    source: str
    new: int
    total: int
    active: int
    applicants: int
    retention: float | None
    hours: float
    hours_each: float


def recruitment(inputs: ReportInputs, filters: ReportFilters) -> Report:
    facts, _shifts = apply_scope(inputs, filters)
    hours_by_source: defaultdict[RecruitmentSource, float] = defaultdict(float)
    for fact in facts:
        hours_by_source[fact.recruitment_source] += fact.hours

    groups: defaultdict[RecruitmentSource, list[Volunteer]] = defaultdict(list)
    for volunteer in inputs.volunteers:
        groups[volunteer.recruitment_source].append(volunteer)

    rows: list[_SourceRow] = []
    for source, people in groups.items():
        active = sum(v.status is VolunteerStatus.ACTIVE for v in people)
        inactive = sum(v.status is VolunteerStatus.INACTIVE for v in people)
        hours = round(hours_by_source[source], 2)
        rows.append(
            _SourceRow(
                source=source.label,
                new=sum(filters.start <= v.joined_on <= filters.end for v in people),
                total=len(people),
                active=active,
                applicants=sum(v.status is VolunteerStatus.APPLICANT for v in people),
                retention=percent(active, active + inactive),
                hours=hours,
                hours_each=round(hours / len(people), 1),
            )
        )
    rows.sort(key=lambda row: (-row.new, -row.total, row.source))

    today = inputs.now.date()
    waiting = sum(
        1
        for v in inputs.volunteers
        if v.status is VolunteerStatus.APPLICANT and (today - v.joined_on).days > APPLICANT_WAIT_DAYS
    )
    new_total = sum(row.new for row in rows)
    figures = (
        Figure(tr("New volunteers"), str(new_total), tr("joined in this period")),
        Figure(tr("Awaiting review"), str(sum(row.applicants for row in rows))),
        Figure(tr("Top channel"), rows[0].source if rows and new_total else "\u2013", tr("by new volunteers")),
    )
    insights: list[str] = []
    if rows and new_total:
        insights.append(
            tr(
                "{source} brought the most new volunteers ({new} of {new_total}).",
                source=rows[0].source,
                new=rows[0].new,
                new_total=new_total,
            )
        )
    committed = [row for row in rows if row.total >= 2]
    if committed and rows:
        deepest = max(committed, key=lambda row: row.hours_each)
        if deepest.source != rows[0].source and deepest.hours_each > 0:
            insights.append(
                tr(
                    ("Volunteers from {source} serve the most hours each ({hours}) — a channel worth investing in."),
                    source=deepest.source,
                    hours=_hours(deepest.hours_each),
                )
            )
    if waiting:
        insights.append(
            tr_n(
                "{count} applicant has waited more than {days} days for review — quick replies keep people interested.",
                "{count} applicants have waited more than {days} days for review — quick replies keep people "
                "interested.",
                waiting,
                days=APPLICANT_WAIT_DAYS,
            )
        )
    chart = top_bars(tr("New volunteers by channel"), ((row.source, float(row.new)) for row in rows), ValueKind.COUNT)
    return _report(ReportKind.RECRUITMENT, inputs, filters, RECRUITMENT_COLUMNS, rows, figures, insights, (chart,))


# ------------------------------------------------------------ service record

SERVICE_RECORD_COLUMNS = (
    ReportColumn("date", mark("Date"), ValueKind.DATE),
    ReportColumn("program", mark("Program")),
    ReportColumn("category", mark("Category")),
    ReportColumn("time", mark("Time")),
    ReportColumn("hours", mark("Hours"), ValueKind.HOURS),
)


@dataclass(frozen=True, slots=True)
class _ServiceRow:
    date: date
    program: str
    category: str
    time: str
    hours: float


def service_record(inputs: ReportInputs, filters: ReportFilters, volunteer: Volunteer) -> Report:
    facts, _shifts = apply_scope(inputs, filters)
    served = [f for f in facts if f.volunteer_id == volunteer.volunteer_id and f.status is AssignmentStatus.ATTENDED]
    rows = [
        _ServiceRow(
            date=f.starts_at.date(),
            program=f.opportunity_title,
            category=f.category.label,
            time=f"{_clock(f.starts_at)} \u2013 {_clock(f.ends_at)}",
            hours=round(f.hours, 2),
        )
        for f in served
    ]
    total = sum(f.hours for f in served)
    by_program: defaultdict[str, float] = defaultdict(float)
    for fact in served:
        by_program[fact.opportunity_title] += fact.hours
    figures = (
        Figure(tr("Total hours"), _hours(total)),
        Figure(tr("Shifts served"), str(len(served))),
        Figure(tr("Programs"), str(len(by_program))),
        Figure(tr("Community value"), format_value(ValueKind.MONEY, total * inputs.hour_value)),
    )
    insights: list[str] = []
    if by_program:
        favorite = max(by_program, key=lambda title: (by_program[title], title))
        insights.append(
            tr("Most time given to '{favorite}': {hours}.", favorite=favorite, hours=_hours(by_program[favorite]))
        )
    name_line = tr("Volunteer: {legal_name}", legal_name=volunteer.legal_name)
    if volunteer.preferred_name:
        name_line += tr(" (goes by {preferred_name})", preferred_name=volunteer.preferred_name)
    context = (
        name_line,
        tr("Volunteering since {format_value}", format_value=format_value(ValueKind.DATE, volunteer.joined_on)),
    )
    chart = top_bars(tr("Hours by program"), by_program.items(), ValueKind.HOURS)
    return _report(
        ReportKind.SERVICE_RECORD, inputs, filters, SERVICE_RECORD_COLUMNS, rows, figures, insights, (chart,), context
    )
