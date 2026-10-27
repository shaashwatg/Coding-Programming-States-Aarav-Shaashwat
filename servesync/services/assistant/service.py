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

from servesync.core.i18n import Language, current_language, format_clock, format_weekday_day, tr, tr_n
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
    """'Sat, Nov 7, 9:00 AM' / 'sáb 7 nov, 9:00 a. m.'"""
    return f"{format_weekday_day(moment.date())}, {format_clock(moment)}"


def _hours(value: float) -> str:
    number = f"{value:,.1f}" if value % 1 else f"{value:,.0f}"
    return tr("{number} hour", number=number) if value == 1 else tr("{number} hours", number=number)


def _names(names: list[str], limit: int = LIST_LIMIT) -> str:
    """'Ana, Ben and Cara' or 'Ana, Ben, ... and 3 more' (in the current language)."""
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    if len(names) <= limit:
        return tr("{first} and {last}", first=", ".join(names[:-1]), last=names[-1])
    return tr_n(
        "{names} and {count} more", "{names} and {count} more", len(names) - limit, names=", ".join(names[:limit])
    )


def subject_has(pronouns: str, given_name: str) -> str:
    """
    "She has" / "He has" / "They have" from the pronouns a person shared;
    their name otherwise. ServeSync never assumes anyone's pronouns.
    (Spanish uses "Ella tiene" / "Él tiene", and the person's name otherwise.)
    """
    first = pronouns.lower().replace(",", "/").split("/")[0].strip()
    subjects = {"she": tr("She has"), "he": tr("He has")}
    if current_language() is Language.ENGLISH:
        subjects["they"] = "They have"  # English only; Spanish uses the name
    return subjects.get(first, tr("{name} has", name=given_name))


def _days(count: int) -> str:
    return tr_n("{count} day", "{count} days", count)


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
                tr("Which shifts need volunteers this week?"),
                tr("Who is free Saturday morning?"),
                tr("How many hours did we serve this month?"),
                tr("Who is waiting for approval?"),
                tr("How do I export a report?"),
            )
        return (
            tr("What should I sign up for?"),
            tr("When is my next shift?"),
            tr("How many hours do I have this school year?"),
            tr("How do I get a service hours record?"),
        )

    def ask(self, session: Session, question: object) -> Answer:
        try:
            text = clean_text(question, tr("Question"), max_length=MAX_QUESTION_LENGTH)
        except InvalidInputError as error:
            if "required" in str(error):
                return Answer(
                    tr("Type a question, or pick one of the suggestions."), follow_ups=self.suggestions(session)
                )
            return Answer(
                tr(
                    (
                        "That's a long question. Try asking in under {MAX_QUESTION_LENGTH} "
                        "characters, one thing at a time."
                    ),
                    MAX_QUESTION_LENGTH=MAX_QUESTION_LENGTH,
                )
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
                tr(
                    "That's information only coordinators can see, to protect everyone's "
                    "privacy. I can tell you about your own hours, your upcoming shifts, "
                    "or shifts you could join."
                ),
                follow_ups=self.suggestions(session),
            )
        if intent in (None, Intent.HOW_TO):
            return self._help_answer(session, text)
        handler = {
            Intent.GREETING: self._greeting,
            Intent.THANKS: lambda s, _p: Answer(tr("You're welcome! Anything else?"), follow_ups=self.suggestions(s)),
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
        if session.is_leader:
            text = tr(
                "I'm not sure I understood that. I can answer questions about volunteers, shifts, "
                "programs, hours, and how to use ServeSync. Try one of these:"
            )
        else:
            text = tr(
                "I'm not sure I understood that. I can answer questions about your hours, "
                "your shifts, and how to use ServeSync. Try one of these:"
            )
        return Answer(text, follow_ups=self.suggestions(session))

    @staticmethod
    def _article_answer(article: HelpArticle, related: list[str]) -> Answer:
        steps = "\n".join(f"• {step}" for step in article.steps)
        actions = (AnswerAction(article.action_label or tr("Show me"), article.page),) if article.page else ()
        return Answer(
            f"{article.title}\n{steps}",
            understood=tr("a how-to question"),
            actions=actions,
            follow_ups=tuple(f"{title}?" if not title.endswith("?") else title for title in related),
        )

    def _greeting(self, session: Session, _parsed: ParsedQuestion) -> Answer:
        name = session.username
        if session.volunteer_id is not None:
            name = self._store.volunteers.get(session.volunteer_id).given_name
        return Answer(
            tr("Hi {name}! Ask me anything about ServeSync. A few ideas:", name=name),
            follow_ups=self.suggestions(session),
        )

    # ------------------------------------------------------------ answers: volunteers

    def _my_hours(self, session: Session, parsed: ParsedQuestion) -> Answer:
        volunteer_id = session.volunteer_id
        if volunteer_id is None:
            return Answer(
                tr(
                    "Your account isn't linked to a volunteer record, so there are no "
                    "hours to show. Ask about a volunteer by name instead, for example "
                    "'How many hours has Priya served?'"
                )
            )
        period = parsed.period
        hours = self._store.assignments.total_hours(
            volunteer_id=volunteer_id, start=period.start if period else None, end=period.end if period else None
        )
        participation = self._store.volunteers.get_participation(volunteer_id)
        value = hours * self._store.settings.volunteer_hour_value()
        when = period.label if period else tr("in total")
        if hours:
            text = tr(
                "You've served {hours} {when} — worth about ${value:,.0f} to the community.",
                hours=_hours(hours),
                when=when,
                value=value,
            )
        else:
            text = tr("You've served {hours} {when}.", hours=_hours(hours), when=when)
        if not period:
            text += " " + tr_n(
                "That's {count} shift so far.", "That's {count} shifts so far.", participation.shifts_attended
            )
        return Answer(
            text,
            understood=tr("your hours {when}", when=when),
            actions=(AnswerAction(tr("Open My hours"), "hours"),),
            follow_ups=(tr("When is my next shift?"), tr("How do I get a service hours record?")),
        )

    def _my_next_shift(self, session: Session, _parsed: ParsedQuestion) -> Answer:
        volunteer_id = session.volunteer_id
        if volunteer_id is None:
            return Answer(
                tr("Your account isn't linked to a volunteer record. Try 'Which shifts need volunteers this week?'")
            )
        upcoming = self._store.assignments.upcoming_scheduled(after=self._clock.now(), volunteer_id=volunteer_id)
        records = {r.assignment.assignment_id: r for r in self._store.assignments.history(volunteer_id)}
        lines = [
            f"• {_when(records[a.assignment_id].starts_at)} — {records[a.assignment_id].opportunity_title}"
            for a in upcoming[:3]
            if a.assignment_id in records
        ]  # a date and a program name: nothing to translate
        if not lines:
            return Answer(
                tr("You don't have any upcoming shifts yet."),
                understood=tr("your upcoming shifts"),
                actions=(AnswerAction(tr("Find a shift"), "find"),),
                follow_ups=(tr("What should I sign up for?"),),
            )
        more = "\n" + tr("…and {count} more.", count=len(upcoming) - 3) if len(upcoming) > 3 else ""
        heading = tr("Your next shifts are:") if len(lines) > 1 else tr("Your next shift is:")
        return Answer(
            heading + "\n" + "\n".join(lines) + more,
            understood=tr("your upcoming shifts"),
            actions=(AnswerAction(tr("Open Home"), "home"),),
            follow_ups=(tr("How do I cancel a sign-up?"), tr("What should I sign up for?")),
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
        if parsed.slot:
            scope = tr("for {when}", when=parsed.slot.label)
        else:
            scope = parsed.period.label if parsed.period else tr("anytime")
        if not picks:
            return Answer(
                tr("I couldn't find open shifts {scope} that you can join right now.", scope=scope),
                understood=tr("shifts that suit you {scope}", scope=scope),
                actions=(AnswerAction(tr("Browse all shifts"), "find"),),
            )
        lines = [
            tr(
                "• {program}, {when} — Fit {score}",
                program=m.overview.opportunity_title,
                when=_when(m.overview.shift.starts_at),
                score=m.score,
            )
            + (f" ({m.strengths[0][:1].lower()}{m.strengths[0][1:]})" if m.strengths else "")
            for m in picks
        ]
        return Answer(
            tr("These fit you best:") + "\n" + "\n".join(lines),
            understood=tr("shifts that suit you {scope}", scope=scope),
            actions=(AnswerAction(tr("Find a shift"), "find"),),
            follow_ups=(tr("What should I sign up for this weekend?"), tr("When is my next shift?")),
        )

    # ------------------------------------------------------------ answers: leaders

    def _person_hours(self, session: Session, parsed: ParsedQuestion) -> Answer:
        if len(parsed.people) > 1:
            names = [p.display for p in parsed.people[:LIST_LIMIT]]
            return Answer(
                tr("I found more than one person with that name. Which one did you mean?"),
                understood=tr("a volunteer's hours"),
                follow_ups=tuple(tr("How many hours has {name} served?", name=name) for name in names),
            )
        person = parsed.people[0]
        period = parsed.period
        hours = self._store.assignments.total_hours(
            volunteer_id=person.record_id, start=period.start if period else None, end=period.end if period else None
        )
        participation = self._store.volunteers.get_participation(person.record_id)
        when = period.label if period else tr("in total")
        if period:
            text = tr("{name} has served {hours} {when}.", name=person.display, hours=_hours(hours), when=when)
        elif participation.reliability is not None:
            text = tr_n(
                "{name} has served {hours} in total across {count} shift, showing up for {rate:.0%} of commitments.",
                "{name} has served {hours} in total across {count} shifts, showing up for {rate:.0%} of commitments.",
                participation.shifts_attended,
                name=person.display,
                hours=_hours(hours),
                rate=participation.reliability,
            )
        else:
            text = tr("{name} has served {hours} in total.", name=person.display, hours=_hours(hours))
        if participation.upcoming_shifts:
            volunteer = self._store.volunteers.get(person.record_id)
            text += " " + tr_n(
                "{subject} {count} upcoming shift.",
                "{subject} {count} upcoming shifts.",
                participation.upcoming_shifts,
                subject=subject_has(volunteer.pronouns, volunteer.given_name),
            )
        return Answer(
            text,
            understood=tr("hours for {name} {when}", name=person.display, when=when),
            actions=(
                AnswerAction(
                    tr("Open service record"),
                    "reports",
                    MappingProxyType({"kind": ReportKind.SERVICE_RECORD.value, "volunteer_id": person.record_id}),
                ),
            ),
            follow_ups=(
                tr("How many hours has {display} served this month?", display=person.display),
                tr("Who volunteered the most this month?"),
            ),
        )

    def _org_hours(self, session: Session, parsed: ParsedQuestion) -> Answer:
        today = self._clock.now().date()
        period = parsed.period or Period(today.replace(day=1), today, tr("this month"))
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
        programs = sum(1 for row in report.rows if _number(row, "hours"))
        if hours:
            text = tr(
                "Volunteers served {hours} {when} — {people} people across {programs} programs, "
                "worth about ${value:,.0f}.",
                hours=_hours(hours),
                when=period.label,
                people=people,
                programs=programs,
                value=value,
            )
        else:
            text = tr("Volunteers served {hours} {when}.", hours=_hours(hours), when=period.label)
        return Answer(
            text,
            understood=tr("total hours served {label}", label=period.label),
            actions=(
                AnswerAction(
                    tr("Open Program impact report"),
                    "reports",
                    MappingProxyType({"kind": ReportKind.PROGRAM_IMPACT.value}),
                ),
            ),
            follow_ups=(
                tr("Who volunteered the most this month?"),
                tr("Which program delivered the most hours this year?"),
            ),
        )

    def _who_is_free(self, session: Session, parsed: ParsedQuestion) -> Answer:
        slot = parsed.slot
        weekdays = list(slot.weekdays) if slot else []
        if not weekdays and parsed.period and parsed.period.start == parsed.period.end:
            weekdays = [Weekday(parsed.period.start.weekday())]
        if not weekdays:
            return Answer(
                tr(
                    "Which day? For example: 'Who is free Saturday morning?' or 'Who is available on weekday evenings?'"
                ),
                understood=tr("who is available"),
                follow_ups=(tr("Who is free Saturday morning?"), tr("Who is available on weekday evenings?")),
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
                tr("No active volunteers list {label} as a usual free time.", label=label),
                understood=tr("who is free on {label}", label=label),
            )
        names = sorted(people.values(), key=lambda n: n.split()[-1])
        return Answer(
            tr_n(
                "{count} active volunteer is usually free on {label}: {names}.",
                "{count} active volunteers are usually free on {label}: {names}.",
                len(names),
                label=label,
                names=_names(names),
            )
            + "\n"
            + tr("Open a shift's Smart Match tab to rank them for that shift."),
            understood=tr("who is free on {label}", label=label),
            actions=(AnswerAction(tr("Open Calendar"), "calendar"),),
            follow_ups=(tr("Which shifts need volunteers this week?"),),
        )

    def _shifts_needing_people(self, session: Session, parsed: ParsedQuestion) -> Answer:
        now = self._clock.now()
        period = parsed.period
        start = max(now, datetime.combine(period.start, time.min)) if period else now
        end = datetime.combine(period.end + timedelta(days=1), time.min) if period else now + timedelta(days=7)
        label = period.label if period else tr("in the next 7 days")
        shifts = self._store.shifts.overviews(
            starts_after=start, starts_before=end, opportunity_status=OpportunityStatus.OPEN, only_with_openings=True
        )
        if parsed.program is not None:
            shifts = [s for s in shifts if s.shift.opportunity_id == parsed.program.record_id]
            label = tr("{when} for '{program}'", when=label, program=parsed.program.display)
        if not shifts:
            return Answer(
                tr("Good news: every open shift {label} is fully staffed.", label=label),
                understood=tr("shifts that need people {label}", label=label),
            )
        lines = [
            tr(
                "• {when} — {opportunity_title}: {open_spots} of {capacity} spots open",
                when=_when(s.shift.starts_at),
                opportunity_title=s.opportunity_title,
                open_spots=s.open_spots,
                capacity=s.shift.capacity,
            )
            for s in shifts[:5]
        ]
        spots = sum(s.open_spots for s in shifts)
        more = (
            "\n" + tr_n("…and {count} more shift.", "…and {count} more shifts.", len(shifts) - 5)
            if len(shifts) > 5
            else ""
        )
        first_day: date = shifts[0].shift.starts_at.date()
        return Answer(
            tr_n(
                "{count} shift {label} still needs people ({spots} open spots):",
                "{count} shifts {label} still need people ({spots} open spots):",
                len(shifts),
                label=label,
                spots=spots,
            )
            + "\n"
            + "\n".join(lines)
            + more,
            understood=tr("shifts that need people {label}", label=label),
            actions=(
                AnswerAction(tr("Open the first one in Calendar"), "calendar", MappingProxyType({"day": first_day})),
            ),
            follow_ups=(tr("Who is free Saturday morning?"), tr("How do I use Smart Match?")),
        )

    def _top_volunteers(self, session: Session, parsed: ParsedQuestion) -> Answer:
        today = self._clock.now().date()
        period = parsed.period or Period(today.replace(day=1), today, tr("this month"))
        hours = self._store.assignments.hours_by_volunteer(start=period.start, end=period.end)
        if not hours:
            return Answer(
                tr("No hours have been recorded {label} yet.", label=period.label),
                understood=tr("top volunteers {label}", label=period.label),
            )
        names = {p.record_id: p.display for p in self._people()}
        top = sorted(hours.items(), key=lambda item: (-item[1], names.get(item[0], "")))[:3]
        lines = [
            f"{index}. {names.get(vid, tr('Unknown'))} — {_hours(h)}" for index, (vid, h) in enumerate(top, start=1)
        ]
        return Answer(
            tr("Most hours {label}:", label=period.label) + "\n" + "\n".join(lines),
            understood=tr("top volunteers {label}", label=period.label),
            actions=(
                AnswerAction(
                    tr("Open Volunteer hours report"),
                    "reports",
                    MappingProxyType({"kind": ReportKind.VOLUNTEER_HOURS.value}),
                ),
            ),
            follow_ups=(
                tr("How many hours has {name} served?", name=names.get(top[0][0], "")),
                tr("How many hours did we serve this month?"),
            ),
        )

    def _volunteer_counts(self, session: Session, _parsed: ParsedQuestion) -> Answer:
        counts = self._store.volunteers.count_by_status()
        return Answer(
            tr_n(
                "You have {active} active volunteers, {count} applicant waiting for review, and {archived} archived.",
                "You have {active} active volunteers, {count} applicants waiting for review, and {archived} archived.",
                counts[VolunteerStatus.APPLICANT],
                active=counts[VolunteerStatus.ACTIVE],
                archived=counts[VolunteerStatus.INACTIVE],
            ),
            understood=tr("volunteer counts"),
            actions=(AnswerAction(tr("Open Volunteers"), "volunteers"),),
            follow_ups=(tr("Who is waiting for approval?"), tr("Where do new volunteers come from?")),
        )

    def _applicants(self, session: Session, _parsed: ParsedQuestion) -> Answer:
        today = self._clock.now().date()
        waiting = sorted(self._store.volunteers.find_all(status=VolunteerStatus.APPLICANT), key=lambda v: v.joined_on)
        if not waiting:
            return Answer(
                tr("No one is waiting for approval right now."), understood=tr("applicants waiting for review")
            )
        lines = [
            tr("• {name} — waiting {days}", name=v.full_name, days=_days((today - v.joined_on).days))
            for v in waiting[:LIST_LIMIT]
        ]
        return Answer(
            tr_n("{count} applicant is waiting:", "{count} applicants are waiting, longest first:", len(waiting))
            + "\n"
            + "\n".join(lines),
            understood=tr("applicants waiting for review"),
            actions=(
                AnswerAction(
                    tr("Review applicants"), "volunteers", MappingProxyType({"status": VolunteerStatus.APPLICANT.value})
                ),
            ),
            follow_ups=(tr("How do I approve an applicant?"),),
        )

    def _program_status(self, session: Session, parsed: ParsedQuestion) -> Answer:
        program = parsed.program
        if program is None:
            return Answer(
                tr("Which program? Try naming it, for example 'How is the food pantry doing?'"),
                understood=tr("how a program is doing"),
                follow_ups=tuple(tr("How is {display} doing?", display=p.display) for p in self._programs(session)[:3]),
            )
        today = self._clock.now().date()
        period = parsed.period or Period(today - timedelta(days=29), today, tr("in the last 30 days"))
        report = self._reports.build(
            session,
            ReportKind.PROGRAM_IMPACT,
            ReportFilters(period.start, min(period.end, today), opportunity_id=program.record_id),
        )
        upcoming = self._store.shifts.overviews(
            starts_after=self._clock.now(), opportunity_id=program.record_id, limit=1
        )
        if not report.rows:
            text = tr("'{display}' has no shifts {label}.", display=program.display, label=period.label)
        else:
            row = report.rows[0]
            text = tr(
                "'{display}' {label}: {hours} from {volunteers} volunteers; {number:.0f}% of spots filled",
                display=program.display,
                label=period.label,
                hours=_hours(_number(row, "hours")),
                volunteers=row["volunteers"],
                number=_number(row, "fill_rate"),
            )
            if row["show_up_rate"] is not None:
                text += tr("; {rate:.0f}% no-shows", rate=100 - _number(row, "show_up_rate"))
            text += "."
        if upcoming:
            nxt = upcoming[0]
            text += "\n" + tr(
                "Next shift: {when} ({open_spots} of {capacity} spots open).",
                when=_when(nxt.shift.starts_at),
                open_spots=nxt.open_spots,
                capacity=nxt.shift.capacity,
            )
        return Answer(
            text,
            understood=tr("how '{display}' is doing {label}", display=program.display, label=period.label),
            actions=(
                AnswerAction(
                    tr("Open program report"),
                    "reports",
                    MappingProxyType({"kind": ReportKind.PROGRAM_IMPACT.value, "opportunity_id": program.record_id}),
                ),
            ),
            follow_ups=(tr("Which shifts need volunteers for {display}?", display=program.display),),
        )

    def _top_programs(self, session: Session, parsed: ParsedQuestion) -> Answer:
        today = self._clock.now().date()
        period = parsed.period or Period(today - timedelta(days=29), today, tr("in the last 30 days"))
        filters = ReportFilters(period.start, min(period.end, today))
        report = self._reports.build(session, ReportKind.PROGRAM_IMPACT, filters)
        ranked = [row for row in report.rows if _number(row, "hours")][:3]
        if not ranked:
            return Answer(
                tr("No hours have been recorded {label} yet.", label=period.label),
                understood=tr("top programs {label}", label=period.label),
            )
        lines = [
            tr(
                "{index}. {program} — {hours}, {number:.0f}% of spots filled",
                index=index,
                program=row["program"],
                hours=_hours(_number(row, "hours")),
                number=_number(row, "fill_rate"),
            )
            for index, row in enumerate(ranked, start=1)
        ]
        return Answer(
            tr("Programs with the most hours {label}:", label=period.label) + "\n" + "\n".join(lines),
            understood=tr("programs with the most impact {label}", label=period.label),
            actions=(
                AnswerAction(
                    tr("Open Program impact report"),
                    "reports",
                    MappingProxyType({"kind": ReportKind.PROGRAM_IMPACT.value}),
                ),
            ),
            follow_ups=(tr("How is {program} doing?", program=ranked[0]["program"]),),
        )
