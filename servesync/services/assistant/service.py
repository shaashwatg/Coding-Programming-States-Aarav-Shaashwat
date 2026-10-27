"""
Ask ServeSync — an offline, role-aware question-and-answer assistant.

Leaders can ask about people, programs, availability, staffing and impact;
volunteers can ask about their own hours, upcoming shifts and what to sign
up for. Anyone can ask how to do something. Every answer:

* is computed from live records (no canned numbers),
* respects privacy — a volunteer can never learn another person's details,
* says what the question was understood to mean, and
* offers buttons that open the right page, plus follow-up questions.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from types import MappingProxyType

from servesync.core.validators import InvalidInputError, clean_text
from servesync.data import DataStore
from servesync.models import AssignmentStatus, AvailabilitySlot, DayPart, OpportunityStatus, VolunteerStatus, Weekday
from servesync.services.assistant.knowledge import HelpArticle, search_help
from servesync.services.assistant.language import (
    Intent,
    NamedThing,
    ParsedQuestion,
    Period,
    Slot,
    classify,
    is_leader_only,
    person_keys,
    program_keys,
)
from servesync.services.base import Service
from servesync.services.clock import Clock
from servesync.services.matching_service import MatchingService
from servesync.services.reports import ReportFilters, ReportKind, ReportService
from servesync.services.session import Session

MAX_QUESTION_LENGTH = 300
#: Help articles must score at least this to be offered as the answer.
HELP_CONFIDENCE = 2.0
LIST_LIMIT = 6


@dataclass(frozen=True, slots=True)
class AnswerAction:
    """A button under an answer: opens ``page`` with optional navigation options."""

    label: str
    page: str
    options: Mapping[str, object] = field(default_factory=lambda: MappingProxyType({}))


@dataclass(frozen=True, slots=True)
class Answer:
    text: str
    understood: str = ""
    actions: tuple[AnswerAction, ...] = ()
    follow_ups: tuple[str, ...] = ()


def _when(moment: datetime) -> str:
    return f"{moment:%a, %b} {moment.day}, {moment.hour % 12 or 12}:{moment:%M} {'AM' if moment.hour < 12 else 'PM'}"


def _hours(value: float) -> str:
    text = f"{value:,.1f}" if value % 1 else f"{value:,.0f}"
    return f"{text} hour{'' if value == 1 else 's'}"


def _names(names: list[str], limit: int = LIST_LIMIT) -> str:
    if len(names) <= limit:
        return ", ".join(names[:-1]) + (" and " if len(names) > 1 else "") + names[-1] if names else ""
    return ", ".join(names[:limit]) + f" and {len(names) - limit} more"


def _period_text(period: Period) -> str:
    return period.label


def subject_has(pronouns: str, given_name: str) -> str:
    """
    "She has" / "He has" / "They have" from the pronouns a person shared;
    their name otherwise. ServeSync never assumes anyone's pronouns.
    """
    first = pronouns.lower().replace(",", "/").split("/")[0].strip()
    return {"she": "She has", "he": "He has", "they": "They have"}.get(first, f"{given_name} has")


def _days(count: int) -> str:
    return f"{count} day{'' if count == 1 else 's'}"


def _number(row: Mapping[str, object], key: str) -> float:
    """A numeric report cell (missing or blank counts as zero)."""
    value = row.get(key)
    return float(value) if isinstance(value, (int, float)) else 0.0


class AssistantService(Service):
    def __init__(self, store: DataStore, clock: Clock, *, matching: MatchingService, reports: ReportService) -> None:
        super().__init__(store, clock)
        self._matching = matching
        self._reports = reports

    # ------------------------------------------------------------ public

    def suggestions(self, session: Session) -> tuple[str, ...]:
        """Starter questions, shown as one-click chips."""
        if session.is_leader:
            return (
                "Which shifts need volunteers this week?",
                "Who is free Saturday morning?",
                "How many hours did we serve this month?",
                "Who is waiting for approval?",
                "How do I export a report?",
            )
        return (
            "What should I sign up for?",
            "When is my next shift?",
            "How many hours do I have this school year?",
            "How do I get a service hours record?",
        )

    def ask(self, session: Session, question: object) -> Answer:
        try:
            text = clean_text(question, "Question", max_length=MAX_QUESTION_LENGTH)
        except InvalidInputError as error:
            if "required" in str(error):
                return Answer("Type a question, or pick one of the suggestions.", follow_ups=self.suggestions(session))
            return Answer(
                f"That's a long question. Try asking in under {MAX_QUESTION_LENGTH} characters, one thing at a time."
            )

        today = self._clock.now().date()
        parsed = classify(
            text,
            today=today,
            people=self._people(),
            programs=self._programs(session),
            is_leader=session.is_leader,
        )
        intent = parsed.intent
        asks_about_someone_else = any(person.record_id != session.volunteer_id for person in parsed.people)
        if not session.is_leader and (
            (intent is not None and is_leader_only(intent))
            or (asks_about_someone_else and intent in (Intent.MY_HOURS, Intent.PERSON_HOURS, Intent.MY_NEXT_SHIFT))
        ):
            return Answer(
                "That's information only coordinators can see, to protect everyone's privacy. "
                "I can tell you about your own hours, your upcoming shifts, or shifts you could join.",
                follow_ups=self.suggestions(session),
            )
        if intent in (None, Intent.HOW_TO):
            return self._help_answer(session, text)
        handler = {
            Intent.GREETING: self._greeting,
            Intent.THANKS: lambda s, _p: Answer("You're welcome! Anything else?", follow_ups=self.suggestions(s)),
            Intent.MY_HOURS: self._my_hours,
            Intent.MY_NEXT_SHIFT: self._my_next_shift,
            Intent.RECOMMEND_SHIFTS: self._recommend,
            Intent.PERSON_HOURS: self._person_hours,
            Intent.ORG_HOURS: self._org_hours,
            Intent.WHO_IS_FREE: self._who_is_free,
            Intent.SHIFTS_NEEDING_PEOPLE: self._shifts_needing_people,
            Intent.TOP_VOLUNTEERS: self._top_volunteers,
            Intent.VOLUNTEER_COUNTS: self._volunteer_counts,
            Intent.APPLICANTS: self._applicants,
            Intent.PROGRAM_STATUS: self._program_status,
            Intent.TOP_PROGRAMS: self._top_programs,
        }[intent]
        return handler(session, parsed)

    # ------------------------------------------------------------ lookup tables

    def _people(self) -> list[NamedThing]:
        return [
            NamedThing(v.volunteer_id or 0, v.full_name, person_keys(v.first_name, v.last_name, v.preferred_name))
            for v in self._store.volunteers.find_all()
        ]

    def _programs(self, session: Session) -> list[NamedThing]:
        programs = self._store.opportunities.find_all()
        if not session.is_leader:
            programs = [p for p in programs if p.status is OpportunityStatus.OPEN]
        return [NamedThing(p.opportunity_id or 0, p.title, program_keys(p.title)) for p in programs]

    # ------------------------------------------------------------ answers: everyone

    def _help_answer(self, session: Session, text: str) -> Answer:
        results = search_help(text, is_leader=session.is_leader)
        if results and results[0][0] >= HELP_CONFIDENCE:
            article = results[0][1]
            return self._article_answer(article, [a.title for _, a in results[1:]])
        return Answer(
            "I'm not sure I understood that. I can answer questions about "
            + (
                "volunteers, shifts, programs, hours, and how to use ServeSync."
                if session.is_leader
                else "your hours, your shifts, and how to use ServeSync."
            )
            + " Try one of these:",
            follow_ups=self.suggestions(session),
        )

    @staticmethod
    def _article_answer(article: HelpArticle, related: list[str]) -> Answer:
        steps = "\n".join(f"• {step}" for step in article.steps)
        actions = (AnswerAction(article.action_label or "Show me", article.page),) if article.page else ()
        return Answer(
            f"{article.title}\n{steps}",
            understood="a how-to question",
            actions=actions,
            follow_ups=tuple(f"{title}?" if not title.endswith("?") else title for title in related),
        )

    def _greeting(self, session: Session, _parsed: ParsedQuestion) -> Answer:
        name = session.username
        if session.volunteer_id is not None:
            name = self._store.volunteers.get(session.volunteer_id).given_name
        return Answer(f"Hi {name}! Ask me anything about ServeSync. A few ideas:", follow_ups=self.suggestions(session))

    # ------------------------------------------------------------ answers: volunteers

    def _my_hours(self, session: Session, parsed: ParsedQuestion) -> Answer:
        volunteer_id = session.volunteer_id
        if volunteer_id is None:
            return Answer(
                "Your account isn't linked to a volunteer record, so there are no hours to show. "
                "Ask about a volunteer by name instead, for example 'How many hours has Priya served?'"
            )
        period = parsed.period
        hours = self._store.assignments.total_hours(
            volunteer_id=volunteer_id, start=period.start if period else None, end=period.end if period else None
        )
        participation = self._store.volunteers.get_participation(volunteer_id)
        value = hours * self._store.settings.volunteer_hour_value()
        when = f" {_period_text(period)}" if period else " in total"
        text = f"You've served {_hours(hours)}{when}"
        text += f" — worth about ${value:,.0f} to the community." if hours else "."
        if not period:
            text += f" That's {participation.shifts_attended} shifts so far."
        return Answer(
            text,
            understood=f"your hours{when}",
            actions=(AnswerAction("Open My hours", "hours"),),
            follow_ups=("When is my next shift?", "How do I get a service hours record?"),
        )

    def _my_next_shift(self, session: Session, _parsed: ParsedQuestion) -> Answer:
        volunteer_id = session.volunteer_id
        if volunteer_id is None:
            return Answer(
                "Your account isn't linked to a volunteer record. Try 'Which shifts need volunteers this week?'"
            )
        upcoming = self._store.assignments.upcoming_scheduled(after=self._clock.now(), volunteer_id=volunteer_id)
        records = {r.assignment.assignment_id: r for r in self._store.assignments.history(volunteer_id)}
        lines = [
            f"• {_when(records[a.assignment_id].starts_at)} — {records[a.assignment_id].opportunity_title}"
            for a in upcoming[:3]
            if a.assignment_id in records
        ]
        if not lines:
            return Answer(
                "You don't have any upcoming shifts yet.",
                understood="your upcoming shifts",
                actions=(AnswerAction("Find a shift", "find"),),
                follow_ups=("What should I sign up for?",),
            )
        more = f"\n…and {len(upcoming) - 3} more." if len(upcoming) > 3 else ""
        return Answer(
            "Your next shift" + ("s are:\n" if len(lines) > 1 else " is:\n") + "\n".join(lines) + more,
            understood="your upcoming shifts",
            actions=(AnswerAction("Open Home", "home"),),
            follow_ups=("How do I cancel a sign-up?", "What should I sign up for?"),
        )

    def _recommend(self, session: Session, parsed: ParsedQuestion) -> Answer:
        volunteer_id = session.volunteer_id
        if volunteer_id is None:
            return self._shifts_needing_people(session, parsed)
        matches = self._matching.recommend_shifts(session, volunteer_id, limit=50, diversify=parsed.slot is None)
        if parsed.slot is not None:
            slot = parsed.slot
            matches = [
                m
                for m in matches
                if (not slot.weekdays or m.overview.shift.weekday in slot.weekdays)
                and (slot.day_part is None or m.overview.shift.day_part is slot.day_part)
            ]
        if parsed.period is not None:
            period = parsed.period
            matches = [m for m in matches if period.start <= m.overview.shift.starts_at.date() <= period.end]
        picks = matches[:3]
        scope = " for " + parsed.slot.label if parsed.slot else (f" {parsed.period.label}" if parsed.period else "")
        if not picks:
            return Answer(
                f"I couldn't find open shifts{scope} that you can join right now.",
                understood=f"shifts that suit you{scope}",
                actions=(AnswerAction("Browse all shifts", "find"),),
            )
        lines = [
            f"• {m.overview.opportunity_title}, {_when(m.overview.shift.starts_at)} — Fit {m.score}"
            + (f" ({m.strengths[0][:1].lower()}{m.strengths[0][1:]})" if m.strengths else "")
            for m in picks
        ]
        return Answer(
            "These fit you best:\n" + "\n".join(lines),
            understood=f"shifts that suit you{scope}",
            actions=(AnswerAction("Find a shift", "find"),),
            follow_ups=("What should I sign up for this weekend?", "When is my next shift?"),
        )

    # ------------------------------------------------------------ answers: leaders

    def _person_hours(self, session: Session, parsed: ParsedQuestion) -> Answer:
        if len(parsed.people) > 1:
            names = [p.display for p in parsed.people[:LIST_LIMIT]]
            return Answer(
                "I found more than one person with that name. Which one did you mean?",
                understood="a volunteer's hours",
                follow_ups=tuple(f"How many hours has {name} served?" for name in names),
            )
        person = parsed.people[0]
        period = parsed.period
        hours = self._store.assignments.total_hours(
            volunteer_id=person.record_id, start=period.start if period else None, end=period.end if period else None
        )
        participation = self._store.volunteers.get_participation(person.record_id)
        when = f" {_period_text(period)}" if period else " in total"
        text = f"{person.display} has served {_hours(hours)}{when}"
        if not period:
            text += f" across {participation.shifts_attended} shifts"
            if participation.reliability is not None:
                text += f", showing up for {participation.reliability:.0%} of commitments"
        text += "."
        if participation.upcoming_shifts:
            count = participation.upcoming_shifts
            volunteer = self._store.volunteers.get(person.record_id)
            plural = "s" if count != 1 else ""
            text += f" {subject_has(volunteer.pronouns, volunteer.given_name)} {count} upcoming shift{plural}."
        return Answer(
            text,
            understood=f"hours for {person.display}{when}",
            actions=(
                AnswerAction(
                    "Open service record",
                    "reports",
                    MappingProxyType({"kind": ReportKind.SERVICE_RECORD.value, "volunteer_id": person.record_id}),
                ),
            ),
            follow_ups=(
                f"How many hours has {person.display} served this month?",
                "Who volunteered the most this month?",
            ),
        )

    def _org_hours(self, session: Session, parsed: ParsedQuestion) -> Answer:
        today = self._clock.now().date()
        period = parsed.period or Period(today.replace(day=1), today, "this month")
        report = self._reports.build(
            session, ReportKind.PROGRAM_IMPACT, ReportFilters(period.start, min(period.end, today))
        )
        hours = sum(_number(row, "hours") for row in report.rows)
        people = len(
            {
                f.volunteer_id
                for f in self._store.assignments.service_facts(start=period.start, end=min(period.end, today))
                if f.status is AssignmentStatus.ATTENDED
            }
        )
        value = hours * self._store.settings.volunteer_hour_value()
        text = f"Volunteers served {_hours(hours)} {period.label}"
        programs = sum(1 for row in report.rows if _number(row, "hours"))
        text += f" — {people} people across {programs} programs, worth about ${value:,.0f}." if hours else "."
        return Answer(
            text,
            understood=f"total hours served {period.label}",
            actions=(
                AnswerAction(
                    "Open Program impact report", "reports", MappingProxyType({"kind": ReportKind.PROGRAM_IMPACT.value})
                ),
            ),
            follow_ups=("Who volunteered the most this month?", "Which program delivered the most hours this year?"),
        )

    def _who_is_free(self, session: Session, parsed: ParsedQuestion) -> Answer:
        slot = parsed.slot
        weekdays = list(slot.weekdays) if slot else []
        if not weekdays and parsed.period and parsed.period.start == parsed.period.end:
            weekdays = [Weekday(parsed.period.start.weekday())]
        if not weekdays:
            return Answer(
                "Which day? For example: 'Who is free Saturday morning?' or 'Who is available on weekday evenings?'",
                understood="who is available",
                follow_ups=("Who is free Saturday morning?", "Who is available on weekday evenings?"),
            )
        parts = [slot.day_part] if slot and slot.day_part else list(DayPart)
        people: dict[int, str] = {}
        for weekday in weekdays:
            for part in parts:
                for volunteer in self._store.volunteers.find_all(
                    status=VolunteerStatus.ACTIVE, available_in=AvailabilitySlot(weekday, part)
                ):
                    people[volunteer.volunteer_id or 0] = volunteer.full_name
        label = Slot(tuple(weekdays), slot.day_part if slot else None).label
        if not people:
            return Answer(
                f"No active volunteers list {label} as a usual free time.", understood=f"who is free on {label}"
            )
        names = sorted(people.values(), key=lambda n: n.split()[-1])
        return Answer(
            f"{len(names)} active volunteer{'s are' if len(names) != 1 else ' is'} usually "
            f"free on {label}: {_names(names)}.\nOpen a shift's Smart Match tab to rank them for that shift.",
            understood=f"who is free on {label}",
            actions=(AnswerAction("Open Calendar", "calendar"),),
            follow_ups=("Which shifts need volunteers this week?",),
        )

    def _shifts_needing_people(self, session: Session, parsed: ParsedQuestion) -> Answer:
        now = self._clock.now()
        period = parsed.period
        start = max(now, datetime.combine(period.start, time.min)) if period else now
        end = datetime.combine(period.end + timedelta(days=1), time.min) if period else now + timedelta(days=7)
        label = period.label if period else "in the next 7 days"
        shifts = self._store.shifts.overviews(
            starts_after=start, starts_before=end, opportunity_status=OpportunityStatus.OPEN, only_with_openings=True
        )
        if parsed.program is not None:
            shifts = [s for s in shifts if s.shift.opportunity_id == parsed.program.record_id]
            label += f" for '{parsed.program.display}'"
        if not shifts:
            return Answer(
                f"Good news: every open shift {label} is fully staffed.", understood=f"shifts that need people {label}"
            )
        lines = [
            f"• {_when(s.shift.starts_at)} — {s.opportunity_title}: {s.open_spots} of {s.shift.capacity} spots open"
            for s in shifts[:5]
        ]
        spots = sum(s.open_spots for s in shifts)
        more = f"\n…and {len(shifts) - 5} more shifts." if len(shifts) > 5 else ""
        first_day: date = shifts[0].shift.starts_at.date()
        return Answer(
            f"{len(shifts)} shift{'s' if len(shifts) != 1 else ''} {label} still need people ({spots} open spots):\n"
            + "\n".join(lines)
            + more,
            understood=f"shifts that need people {label}",
            actions=(AnswerAction("Open the first one in Calendar", "calendar", MappingProxyType({"day": first_day})),),
            follow_ups=("Who is free Saturday morning?", "How do I use Smart Match?"),
        )

    def _top_volunteers(self, session: Session, parsed: ParsedQuestion) -> Answer:
        today = self._clock.now().date()
        period = parsed.period or Period(today.replace(day=1), today, "this month")
        hours = self._store.assignments.hours_by_volunteer(start=period.start, end=period.end)
        if not hours:
            return Answer(
                f"No hours have been recorded {period.label} yet.", understood=f"top volunteers {period.label}"
            )
        names = {p.record_id: p.display for p in self._people()}
        top = sorted(hours.items(), key=lambda item: (-item[1], names.get(item[0], "")))[:3]
        lines = [f"{index}. {names.get(vid, 'Unknown')} — {_hours(h)}" for index, (vid, h) in enumerate(top, start=1)]
        return Answer(
            f"Most hours {period.label}:\n" + "\n".join(lines),
            understood=f"top volunteers {period.label}",
            actions=(
                AnswerAction(
                    "Open Volunteer hours report",
                    "reports",
                    MappingProxyType({"kind": ReportKind.VOLUNTEER_HOURS.value}),
                ),
            ),
            follow_ups=(
                f"How many hours has {names.get(top[0][0], 'them')} served?",
                "How many hours did we serve this month?",
            ),
        )

    def _volunteer_counts(self, session: Session, _parsed: ParsedQuestion) -> Answer:
        counts = self._store.volunteers.count_by_status()
        return Answer(
            f"You have {counts[VolunteerStatus.ACTIVE]} active volunteers, {counts[VolunteerStatus.APPLICANT]} "
            f"applicant{'s' if counts[VolunteerStatus.APPLICANT] != 1 else ''} waiting for review, and "
            f"{counts[VolunteerStatus.INACTIVE]} archived.",
            understood="volunteer counts",
            actions=(AnswerAction("Open Volunteers", "volunteers"),),
            follow_ups=("Who is waiting for approval?", "Where do new volunteers come from?"),
        )

    def _applicants(self, session: Session, _parsed: ParsedQuestion) -> Answer:
        today = self._clock.now().date()
        waiting = sorted(self._store.volunteers.find_all(status=VolunteerStatus.APPLICANT), key=lambda v: v.joined_on)
        if not waiting:
            return Answer("No one is waiting for approval right now.", understood="applicants waiting for review")
        lines = [f"• {v.full_name} — waiting {_days((today - v.joined_on).days)}" for v in waiting[:LIST_LIMIT]]
        return Answer(
            f"{len(waiting)} applicant{'s are' if len(waiting) != 1 else ' is'} waiting, longest first:\n"
            + "\n".join(lines),
            understood="applicants waiting for review",
            actions=(
                AnswerAction(
                    "Review applicants", "volunteers", MappingProxyType({"status": VolunteerStatus.APPLICANT.value})
                ),
            ),
            follow_ups=("How do I approve an applicant?",),
        )

    def _program_status(self, session: Session, parsed: ParsedQuestion) -> Answer:
        program = parsed.program
        if program is None:
            return Answer(
                "Which program? Try naming it, for example 'How is the food pantry doing?'",
                understood="how a program is doing",
                follow_ups=tuple(f"How is {p.display} doing?" for p in self._programs(session)[:3]),
            )
        today = self._clock.now().date()
        period = parsed.period or Period(today - timedelta(days=29), today, "in the last 30 days")
        report = self._reports.build(
            session,
            ReportKind.PROGRAM_IMPACT,
            ReportFilters(period.start, min(period.end, today), opportunity_id=program.record_id),
        )
        upcoming = self._store.shifts.overviews(
            starts_after=self._clock.now(), opportunity_id=program.record_id, limit=1
        )
        if not report.rows:
            text = f"'{program.display}' has no shifts {period.label}."
        else:
            row = report.rows[0]
            text = (
                f"'{program.display}' {period.label}: {_hours(_number(row, 'hours'))} from "
                f"{row['volunteers']} volunteers; {_number(row, 'fill_rate'):.0f}% of spots filled"
            )
            if row["show_up_rate"] is not None:
                text += f"; {100 - _number(row, 'show_up_rate'):.0f}% no-shows"
            text += "."
        if upcoming:
            nxt = upcoming[0]
            text += f"\nNext shift: {_when(nxt.shift.starts_at)} ({nxt.open_spots} of {nxt.shift.capacity} spots open)."
        return Answer(
            text,
            understood=f"how '{program.display}' is doing {period.label}",
            actions=(
                AnswerAction(
                    "Open program report",
                    "reports",
                    MappingProxyType({"kind": ReportKind.PROGRAM_IMPACT.value, "opportunity_id": program.record_id}),
                ),
            ),
            follow_ups=(f"Which shifts need volunteers for {program.display}?",),
        )

    def _top_programs(self, session: Session, parsed: ParsedQuestion) -> Answer:
        today = self._clock.now().date()
        period = parsed.period or Period(today - timedelta(days=29), today, "in the last 30 days")
        filters = ReportFilters(period.start, min(period.end, today))
        report = self._reports.build(session, ReportKind.PROGRAM_IMPACT, filters)
        ranked = [row for row in report.rows if _number(row, "hours")][:3]
        if not ranked:
            return Answer(f"No hours have been recorded {period.label} yet.", understood=f"top programs {period.label}")
        lines = [
            f"{index}. {row['program']} — {_hours(_number(row, 'hours'))}, "
            f"{_number(row, 'fill_rate'):.0f}% of spots filled"
            for index, row in enumerate(ranked, start=1)
        ]
        return Answer(
            f"Programs with the most hours {period.label}:\n" + "\n".join(lines),
            understood=f"programs with the most impact {period.label}",
            actions=(
                AnswerAction(
                    "Open Program impact report", "reports", MappingProxyType({"kind": ReportKind.PROGRAM_IMPACT.value})
                ),
            ),
            follow_ups=(f"How is {ranked[0]['program']} doing?",),
        )
