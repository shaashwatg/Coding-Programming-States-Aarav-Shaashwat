"""
Records that leave the building: service-hours records, milestone certificates,
and the verification codes that let anyone confirm one is genuine.

Every PDF gets a short random code (like ``K7Q2-9XFM``). The code is stored with
what the document said, so a coordinator asked "is this real?" can type it into
*Verify a record* and see the person, the hours as issued, and today's total for
the same period (records are sometimes corrected after printing). Codes are
random, not derived from the data, so nobody can work one out; and they avoid
letters people confuse (0 and O, 1, I and L) because they are read aloud and
typed by hand.
"""

from __future__ import annotations

import secrets
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from html import escape

from servesync.core.errors import BusinessRuleError, ValidationError
from servesync.core.i18n import format_day, tr
from servesync.models import AssignmentStatus, IssuedDocument, ServiceRecord
from servesync.services.base import Service
from servesync.services.reports.export import PRINT_MUTED, PRINT_RULE_STRONG, PRINT_TEXT
from servesync.services.session import Permission, Session

#: Letters and digits that can't be mistaken for one another when read aloud or typed.
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 8
#: Service-hour milestones that earn a certificate.
MILESTONES = (25, 50, 100)
_MAX_CODE_ATTEMPTS = 20


@dataclass(frozen=True, slots=True)
class Milestone:
    hours: int
    reached_on: date


@dataclass(frozen=True, slots=True)
class Verification:
    """The answer to "is this record genuine?"."""

    document: IssuedDocument | None  # None = no such code was ever issued
    current_hours: float | None = None  # the same period's total today, for comparison

    @property
    def genuine(self) -> bool:
        return self.document is not None

    @property
    def changed_since(self) -> bool:
        """True if hours for that period were corrected after the document was issued."""
        return (
            self.document is not None
            and self.current_hours is not None
            and abs(self.current_hours - self.document.hours) >= 0.01
        )


def new_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def display_code(code: str) -> str:
    """'K7Q29XFM' -> 'K7Q2-9XFM' (easier to read aloud)."""
    return f"{code[:4]}-{code[4:]}"


def normalize_code(text: object) -> str:
    """
    Accept a code however it was typed (any case, spaces or dashes) and check its form.
    Raises a plain-language error for anything that can't be a code.
    """
    cleaned = "".join(str(text or "").split()).replace("-", "").upper()
    if not cleaned:
        raise ValidationError.single("code", tr("Type the code printed on the record, like K7Q2-9XFM."))
    if len(cleaned) != CODE_LENGTH or any(char not in CODE_ALPHABET for char in cleaned):
        raise ValidationError.single(
            "code",
            tr("A code has 8 letters and numbers, like K7Q2-9XFM. Codes never use 0, O, 1, I or L."),
        )
    return cleaned


def milestones_reached(records: Iterable[ServiceRecord]) -> list[Milestone]:
    """The milestones a volunteer has passed and the day each was reached (pure)."""
    served = sorted((r for r in records if r.assignment.status is AssignmentStatus.ATTENDED), key=lambda r: r.starts_at)
    reached: list[Milestone] = []
    total = 0.0
    remaining = list(MILESTONES)
    for record in served:
        total += record.assignment.counted_hours
        while remaining and total >= remaining[0]:
            reached.append(Milestone(remaining.pop(0), record.starts_at.date()))
    return reached


class RecordsService(Service):
    def issue_service_record(self, session: Session, volunteer_id: int, start: date, end: date) -> str:
        """Record that a service-hours PDF is being issued for this period; returns its code."""
        session.require_self_or(Permission.VIEW_REPORTS, volunteer_id)
        if start > end:
            raise ValidationError.single("end", tr("The end date must be on or after the start date."))
        hours = self._store.assignments.total_hours(volunteer_id=volunteer_id, start=start, end=end)
        return self._issue(session, kind="SERVICE_RECORD", volunteer_id=volunteer_id, hours=hours, start=start, end=end)

    def milestones(self, session: Session, volunteer_id: int) -> list[Milestone]:
        session.require_self_or(Permission.VIEW_REPORTS, volunteer_id)
        return milestones_reached(self._store.assignments.history(volunteer_id))

    def milestone_certificate(self, session: Session, volunteer_id: int, hours: int) -> tuple[str, str]:
        """Issue a certificate for a reached milestone: (code, printable HTML)."""
        session.require_self_or(Permission.VIEW_REPORTS, volunteer_id)
        reached = {m.hours: m for m in self.milestones(session, volunteer_id)}
        if hours not in MILESTONES:
            raise BusinessRuleError(tr("Certificates are for 25, 50, or 100 hours."))
        if hours not in reached:
            raise BusinessRuleError(tr("This milestone hasn't been reached yet. Keep going!"))
        code = self._issue(session, kind="MILESTONE", volunteer_id=volunteer_id, hours=float(hours), milestone=hours)
        volunteer = self._store.volunteers.get(volunteer_id)
        html = certificate_html(
            organization=self._store.settings.organization_name(),
            legal_name=volunteer.legal_name,
            hours=hours,
            reached_on=reached[hours].reached_on,
            code=code,
        )
        return code, html

    def verify(self, session: Session, code_text: object) -> Verification:
        """Look up a code (leaders only: the answer names a person)."""
        session.require(Permission.VIEW_REPORTS)
        code = normalize_code(code_text)
        document = self._store.documents.find(code)
        if document is None:
            return Verification(None)
        current = None
        if document.kind == "SERVICE_RECORD" and document.period_start and document.period_end:
            current = self._store.assignments.total_hours(
                volunteer_id=document.volunteer_id, start=document.period_start, end=document.period_end
            )
        return Verification(document, current)

    def _issue(
        self,
        session: Session,
        *,
        kind: str,
        volunteer_id: int,
        hours: float,
        start: date | None = None,
        end: date | None = None,
        milestone: int | None = None,
    ) -> str:
        for _ in range(_MAX_CODE_ATTEMPTS):  # a clash is about one in a trillion, but never assume
            code = new_code()
            if self._store.documents.add(
                code=code,
                kind=kind,
                volunteer_id=volunteer_id,
                hours=round(hours, 2),
                issued_at=self._clock.now(),
                issued_by=session.username,
                period_start=start,
                period_end=end,
                milestone=milestone,
            ):
                return code
        raise BusinessRuleError(tr("Couldn't create a verification code. Please try again."))  # pragma: no cover


def certificate_html(*, organization: str, legal_name: str, hours: int, reached_on: date, code: str) -> str:
    """A one-page certificate, calm and printable in black and white."""
    e = escape
    given = tr("has given {hours} hours of volunteer service to our community.", hours=hours)
    return (
        f"<html><body style='font-family: sans-serif; color: {PRINT_TEXT}; text-align: center'>"
        f"<div style='border: 2px solid {PRINT_RULE_STRONG}; padding: 48px 32px'>"
        f"<p style='color:{PRINT_MUTED}; margin:0'>{e(organization)}</p>"
        f"<h1 style='margin:24px 0 8px 0'>{e(tr('Certificate of service'))}</h1>"
        f"<p style='margin:0'>{e(tr('This certifies that'))}</p>"
        f"<h2 style='margin:16px 0'>{e(legal_name)}</h2>"
        f"<p style='margin:0'>{e(given)}</p>"
        f"<p style='margin:8px 0 32px 0'>{e(tr('Reached on {day}.', day=format_day(reached_on)))}</p>"
        f"<p style='margin:0'>{e(tr('Thank you.'))}</p>"
        f"<p style='color:{PRINT_MUTED}; margin-top:48px'>"
        f"{e(tr('Verification code: {code}', code=display_code(code)))}<br>"
        f"{e(tr('The organization can confirm this certificate with this code.'))}</p>"
        "</div></body></html>"
    )
