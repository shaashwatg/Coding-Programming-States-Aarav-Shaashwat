"""Announcements, tomorrow's reminders, calendar files, and the paper sign-in sheet."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from servesync.core.errors import BusinessRuleError, PermissionDeniedError, ValidationError
from servesync.data import DataStore
from servesync.models import OpportunityStatus
from servesync.services import Services
from servesync.services.coordination_service import (
    ICS_LINE_OCTETS,
    ReminderRow,
    _ics_fold,
    reminders_csv,
    shift_ics,
)
from tests.conftest import SATURDAY_9AM, World
from tests.factories import COORDINATOR, make_shift, volunteer_session

# ------------------------------------------------------------- announcements


def test_people_signed_up_see_a_shift_announcement(services: Services, world: World) -> None:
    services.scheduling.sign_up(COORDINATOR, world.shift_id, world.ana_id)
    services.coordination.post_announcement(COORDINATOR, "  Parking is in the north lot.  ", shift_id=world.shift_id)
    (note,) = services.coordination.my_announcements(volunteer_session(world.ana_id), world.ana_id)
    assert note.body == "Parking is in the north lot." and note.shift_starts_at == SATURDAY_9AM
    assert services.coordination.my_announcements(volunteer_session(world.ben_id), world.ben_id) == []


def test_a_program_announcement_reaches_everyone_signed_up_for_it(
    services: Services, store: DataStore, world: World
) -> None:
    later = store.shifts.add(make_shift(world.opportunity_id, SATURDAY_9AM + timedelta(days=7)))
    services.scheduling.sign_up(COORDINATOR, later.shift_id or 0, world.ben_id)
    services.coordination.post_announcement(COORDINATOR, "Bring gloves.", opportunity_id=world.opportunity_id)
    assert [n.body for n in services.coordination.my_announcements(COORDINATOR, world.ben_id)] == ["Bring gloves."]


@pytest.mark.parametrize("text", ["", "   ", "x" * 501])
def test_announcement_text_is_checked(services: Services, world: World, text: str) -> None:
    with pytest.raises(ValidationError):
        services.coordination.post_announcement(COORDINATOR, text, shift_id=world.shift_id)


def test_an_announcement_needs_exactly_one_open_target(services: Services, store: DataStore, world: World) -> None:
    with pytest.raises(BusinessRuleError, match="either a program or a shift"):
        services.coordination.post_announcement(COORDINATOR, "Hi")
    with pytest.raises(BusinessRuleError, match="either a program or a shift"):
        services.coordination.post_announcement(
            COORDINATOR, "Hi", opportunity_id=world.opportunity_id, shift_id=world.shift_id
        )
    store.opportunities.set_status(world.opportunity_id, OpportunityStatus.CLOSED)
    with pytest.raises(BusinessRuleError, match="Publish the program"):
        services.coordination.post_announcement(COORDINATOR, "Hi", opportunity_id=world.opportunity_id)


def test_only_leaders_post_announcements(services: Services, world: World) -> None:
    with pytest.raises(PermissionDeniedError):
        services.coordination.post_announcement(volunteer_session(world.ana_id), "Hi", shift_id=world.shift_id)
    with pytest.raises(PermissionDeniedError):
        services.coordination.my_announcements(volunteer_session(world.ana_id), world.ben_id)


# ---------------------------------------------------------------- reminders


def test_reminders_list_everyone_on_the_chosen_day(services: Services, world: World) -> None:
    services.scheduling.sign_up(COORDINATOR, world.shift_id, world.ana_id)
    services.scheduling.sign_up(COORDINATOR, world.shift_id, world.teen_id)
    rows = services.coordination.reminders(COORDINATOR, SATURDAY_9AM.date())
    assert [r.volunteer_name.split()[0] for r in rows] == ["Ana", "Tess"]
    assert rows[0].phone == "(312) 555-0142" and rows[0].role == "General"
    assert services.coordination.reminders(COORDINATOR) == []  # tomorrow (Tuesday) has nothing


def test_reminder_csv_has_headers_and_never_runs_a_formula() -> None:
    start = datetime(2026, 11, 7, 9)
    row = ReminderRow("=HYPERLINK(1)", "(312) 555-0142", "a@example.org", "Pantry", start, start, "Gym", "General")
    text = reminders_csv([row])
    lines = text.split("\r\n")
    assert lines[0].startswith("Volunteer,Phone,Email")
    assert lines[1].startswith("'=HYPERLINK(1)")


# ------------------------------------------------------------ calendar file


def test_calendar_file_is_a_valid_event(services: Services, world: World) -> None:
    name, text = services.coordination.calendar_file(volunteer_session(world.ana_id), world.shift_id)
    assert name.endswith("2026-11-07.ics")
    assert text.startswith("BEGIN:VCALENDAR\r\n") and text.endswith("END:VCALENDAR\r\n")
    assert "DTSTART:20261107T090000\r\n" in text and "DTEND:20261107T120000\r\n" in text
    assert all(len(line.encode("utf-8")) <= ICS_LINE_OCTETS for line in text.split("\r\n"))


def test_calendar_text_is_escaped_and_folded(services: Services, world: World) -> None:
    overview = services.opportunities.shift_overview(COORDINATOR, world.shift_id)
    text = shift_ics(
        overview,
        description="Bring gloves; wear boots, please.\nThanks",
        coordinator="Dana",
        organization="Riverbend",
        now=datetime(2026, 11, 2, 8),
    )
    unfolded = text.replace("\r\n ", "")
    assert "Bring gloves\\; wear boots\\, please.\\nThanks" in unfolded
    folded = _ics_fold("DESCRIPTION:" + "é" * 80)
    assert all(len(piece.encode("utf-8")) <= ICS_LINE_OCTETS for piece in folded.split("\r\n"))
    assert folded.replace("\r\n ", "") == "DESCRIPTION:" + "é" * 80


# ---------------------------------------------------------- sign-in sheet


def test_sign_in_sheet_lists_people_and_blank_rows(services: Services, world: World) -> None:
    services.scheduling.sign_up(COORDINATOR, world.shift_id, world.ana_id)
    html = services.coordination.sign_in_sheet(COORDINATOR, world.shift_id)
    assert "Ana Lopez" in html and "Signature" in html and "Time in" in html
    assert html.count("&nbsp;") >= 6 * 6  # six empty rows for walk-ins
    with pytest.raises(PermissionDeniedError):
        services.coordination.sign_in_sheet(volunteer_session(world.ana_id), world.shift_id)


def test_names_in_the_sheet_are_escaped(services: Services, store: DataStore, world: World) -> None:
    volunteer = store.volunteers.get(world.ana_id)
    volunteer.preferred_name = "Ana"
    services.scheduling.sign_up(COORDINATOR, world.shift_id, world.ana_id)
    html = services.coordination.sign_in_sheet(COORDINATOR, world.shift_id)
    assert "<script" not in html
