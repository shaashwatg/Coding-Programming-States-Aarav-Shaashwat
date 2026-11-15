"""
Coordinating people around a shift: announcements, tomorrow's reminders, calendar
files, and the paper sign-in sheet.

ServeSync works offline and never sends messages itself. Instead it gives a
coordinator what they need to reach people their own way (a call list with phone
numbers, a CSV for a texting or email service) and gives volunteers a standard
calendar file. The text formats are built by pure functions, so each is tested
without a database or a screen.
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from html import escape

from servesync.core.errors import BusinessRuleError, ValidationError
from servesync.core.i18n import format_clock, format_long_day, tr
from servesync.core.validators import InvalidInputError, clean_text, format_phone
from servesync.models import Announcement, AssignmentStatus, OpportunityStatus, RosterEntry, ShiftOverview
from servesync.services.base import Service
from servesync.services.reports.export import PRINT_MUTED, PRINT_RULE_STRONG, PRINT_TEXT
from servesync.services.session import Permission, Session

ANNOUNCEMENT_MAX_LENGTH = 500
#: Volunteers see notes posted in the last 30 days for shifts they are still signed up for.
ANNOUNCEMENT_DAYS = 30
#: Empty lines at the bottom of a paper sign-in sheet, for walk-ins.
SIGN_IN_SHEET_BLANK_ROWS = 6
#: iCalendar (RFC 5545) lines longer than this many bytes must be folded.
ICS_LINE_OCTETS = 75
_FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")


@dataclass(frozen=True, slots=True)
class ReminderRow:
    """One person to remind about one shift tomorrow."""

    volunteer_name: str
    phone: str  # formatted for reading aloud or dialing
    email: str
    program: str
    starts_at: datetime
    ends_at: datetime
    location: str
    role: str


class CoordinationService(Service):
    # ----------------------------------------------------------- announcements

    def post_announcement(
        self, session: Session, text: object, *, opportunity_id: int | None = None, shift_id: int | None = None
    ) -> Announcement:
        """
        Post a note that everyone signed up for the program (or the one shift) sees on
        Home. Checks: exactly one target; the text is 1 to 500 characters; the program
        is taking sign-ups (a closed program has nobody to tell); the shift isn't over.
        """
        session.require(Permission.MANAGE_SCHEDULE)
        if (opportunity_id is None) == (shift_id is None):
            raise BusinessRuleError(tr("Choose either a program or a shift for this announcement."))
        try:
            body = clean_text(text, tr("Announcement"), max_length=ANNOUNCEMENT_MAX_LENGTH, multiline=True)
        except InvalidInputError as error:
            raise ValidationError.single("body", str(error)) from error
        now = self._clock.now()
        if shift_id is not None:
            overview = self._store.shifts.get_overview(shift_id)
            if overview.shift.ends_at <= now:
                raise BusinessRuleError(tr("This shift is over, so there's nobody left to tell."))
            status = overview.opportunity_status
        else:
            status = self._store.opportunities.get(opportunity_id or 0).status
        if status is not OpportunityStatus.OPEN:
            raise BusinessRuleError(tr("Publish the program first: only open programs have volunteers to tell."))
        return self._store.announcements.add(
            body=body, posted_by=session.username, posted_at=now, opportunity_id=opportunity_id, shift_id=shift_id
        )

    def delete_announcement(self, session: Session, announcement_id: int) -> None:
        session.require(Permission.MANAGE_SCHEDULE)
        self._store.announcements.delete(announcement_id)

    def announcements(
        self, session: Session, *, opportunity_id: int | None = None, shift_id: int | None = None
    ) -> list[Announcement]:
        """Notes posted to one program or one shift (leaders), newest first."""
        session.require(Permission.MANAGE_SCHEDULE)
        return self._store.announcements.for_target(opportunity_id=opportunity_id, shift_id=shift_id)

    def my_announcements(self, session: Session, volunteer_id: int) -> list[Announcement]:
        """Notes for the shifts a volunteer is signed up for, and those shifts' programs."""
        session.require_self_or(Permission.MANAGE_SCHEDULE, volunteer_id)
        now = self._clock.now()
        return self._store.announcements.for_volunteer(
            volunteer_id, now=now, since=now - timedelta(days=ANNOUNCEMENT_DAYS)
        )

    # --------------------------------------------------------------- reminders

    def reminders(self, session: Session, day: date | None = None) -> list[ReminderRow]:
        """Everyone signed up for a shift on ``day`` (tomorrow by default), by start time then name."""
        session.require(Permission.MANAGE_SCHEDULE)
        day = day or self._clock.now().date() + timedelta(days=1)
        rows: list[ReminderRow] = []
        shifts = self._store.shifts.overviews(
            starts_after=datetime.combine(day, time.min),
            starts_before=datetime.combine(day + timedelta(days=1), time.min),
            opportunity_status=OpportunityStatus.OPEN,
        )
        for overview in shifts:
            for entry in self._store.assignments.roster(overview.shift.shift_id or 0):
                if entry.assignment.status is AssignmentStatus.SCHEDULED:
                    rows.append(_reminder_row(overview, entry))
        rows.sort(key=lambda row: (row.starts_at, row.volunteer_name.casefold()))
        return rows

    # --------------------------------------------------- calendar and paper

    def calendar_file(self, session: Session, shift_id: int) -> tuple[str, str]:
        """A standard .ics calendar event for one shift: (suggested file name, file text)."""
        del session  # any signed-in person may add a shift they can see to their calendar
        overview = self._store.shifts.get_overview(shift_id)
        opportunity = self._store.opportunities.get(overview.shift.opportunity_id)
        text = shift_ics(
            overview,
            description=opportunity.description,
            coordinator=opportunity.coordinator_name,
            organization=self._store.settings.organization_name(),
            now=self._clock.now(),
        )
        return ics_filename(overview), text

    def sign_in_sheet(self, session: Session, shift_id: int) -> str:
        """The printable paper sign-in sheet for a shift, as HTML ready to print to PDF."""
        session.require(Permission.RECORD_ATTENDANCE)
        overview = self._store.shifts.get_overview(shift_id)
        entries = [
            entry
            for entry in self._store.assignments.roster(shift_id)
            if entry.assignment.status is not AssignmentStatus.CANCELLED
        ]
        return sign_in_sheet_html(self._store.settings.organization_name(), overview, entries)


# --------------------------------------------------------------- pure helpers


def _reminder_row(overview: ShiftOverview, entry: RosterEntry) -> ReminderRow:
    return ReminderRow(
        volunteer_name=entry.volunteer_name,
        phone=entry.display_phone,
        email=entry.volunteer_email,
        program=overview.opportunity_title,
        starts_at=overview.shift.starts_at,
        ends_at=overview.shift.ends_at,
        location=overview.location,
        role=entry.role_display,
    )


def _safe_cell(text: str) -> str:
    """A spreadsheet must never run a cell as a formula (OWASP: CSV injection)."""
    return f"'{text}" if text.startswith(_FORMULA_STARTS) else text


def reminders_csv(rows: Sequence[ReminderRow]) -> str:
    """The reminder list as CSV, with headers in the interface language."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow([tr("Volunteer"), tr("Phone"), tr("Email"), tr("Program"), tr("Role"), tr("Time"), tr("Place")])
    for row in rows:
        when = f"{format_clock(row.starts_at)} – {format_clock(row.ends_at)}"
        writer.writerow(
            [_safe_cell(value) for value in (row.volunteer_name, row.phone, row.email, row.program, row.role, when)]
            + [_safe_cell(row.location)]
        )
    return out.getvalue()


def _ics_escape(text: str) -> str:
    """RFC 5545 text: backslash, semicolon and comma are escaped; line breaks become \\n."""
    text = text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
    return re.sub(r"\r\n|\r|\n", "\\\\n", text)


def _ics_fold(line: str) -> str:
    """Fold a content line at 75 bytes (never splitting a character), continuing with a space."""
    pieces: list[str] = []
    current = ""
    for char in line:
        limit = ICS_LINE_OCTETS if not pieces else ICS_LINE_OCTETS - 1  # continuation lines start with a space
        if len((current + char).encode("utf-8")) > limit:
            pieces.append(current)
            current = char
        else:
            current += char
    pieces.append(current)
    return "\r\n ".join(pieces)


def _ics_time(moment: datetime) -> str:
    return moment.strftime("%Y%m%dT%H%M%S")


def shift_ics(overview: ShiftOverview, *, description: str, coordinator: str, organization: str, now: datetime) -> str:
    """
    One shift as an iCalendar (RFC 5545) event that Apple, Google and Outlook calendars
    all import. Times are "floating" local times: the shift is at 9:00 where it happens,
    whatever time zone the phone is set to.
    """
    shift = overview.shift
    stamp = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    details = f"{description}\n{tr('Coordinator: {name}', name=coordinator)}"
    summary = tr("{program} ({organization})", program=overview.opportunity_title, organization=organization)
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//ServeSync//Volunteer shifts//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:shift-{shift.shift_id}@servesync.invalid",
        f"DTSTAMP:{stamp}",
        f"DTSTART:{_ics_time(shift.starts_at)}",
        f"DTEND:{_ics_time(shift.ends_at)}",
        f"SUMMARY:{_ics_escape(summary)}",
        f"LOCATION:{_ics_escape(overview.location)}",
        f"DESCRIPTION:{_ics_escape(details)}",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    return "\r\n".join(_ics_fold(line) for line in lines) + "\r\n"


def ics_filename(overview: ShiftOverview) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", overview.opportunity_title.casefold()).strip("-") or "shift"
    return f"{slug}-{overview.shift.starts_at:%Y-%m-%d}.ics"


def sign_in_sheet_html(organization: str, overview: ShiftOverview, entries: Sequence[RosterEntry]) -> str:
    """
    A paper fallback for when the laptop can't come: everyone signed up (grouped by
    role, as the roster is), with blank columns for time in, time out and a signature,
    plus empty rows for walk-ins.
    """
    e = escape
    shift = overview.shift
    when = f"{format_long_day(shift.starts_at.date())}, {format_clock(shift.starts_at)} – {format_clock(shift.ends_at)}"
    cell = f"style='border:1px solid {PRINT_RULE_STRONG}; padding:10px 6px'"
    heads = (tr("Name"), tr("Role"), tr("Phone"), tr("Time in"), tr("Time out"), tr("Signature"))
    header = "".join(f"<th align='left' {cell}>{e(text)}</th>" for text in heads)
    body = [
        f"<tr><td {cell}>{e(entry.volunteer_name)}</td><td {cell}>{e(entry.role_display)}</td>"
        f"<td {cell}>{e(format_phone(entry.volunteer_phone))}</td><td {cell}></td><td {cell}></td><td {cell}></td></tr>"
        for entry in entries
    ]
    body += [f"<tr>{''.join(f'<td {cell}>&nbsp;</td>' for _ in heads)}</tr>"] * SIGN_IN_SHEET_BLANK_ROWS
    return (
        f"<html><body style='font-family: sans-serif; color: {PRINT_TEXT};'>"
        f"<p style='color:{PRINT_MUTED}; margin:0'>{e(organization)}</p>"
        f"<h1 style='margin:4px 0'>{e(tr('Sign-in sheet'))}: {e(overview.opportunity_title)}</h1>"
        f"<p style='margin:0 0 4px 0'>{e(when)}. {e(overview.location)}.</p>"
        f"<p style='color:{PRINT_MUTED}; margin:0 0 12px 0'>"
        f"{e(tr('Please write the time you arrive and leave, and sign. Walk-ins: use an empty row.'))}</p>"
        f"<table cellspacing='0' width='100%'><tr>{header}</tr>{''.join(body)}</table>"
        f"<p style='margin-top:18px; color:{PRINT_MUTED}'>"
        f"{e(tr('A coordinator enters these times in ServeSync afterward.'))}</p>"
        "</body></html>"
    )
