"""Dashboard, settings, and first-launch setup services."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from servesync.core.errors import BusinessRuleError, PermissionDeniedError, ValidationError
from servesync.data import DataStore
from servesync.models import Theme, UserRole
from servesync.services import FixedClock, Services
from tests.conftest import SATURDAY_9AM, World
from tests.factories import ADMIN, COORDINATOR, volunteer_session

# ---------------------------------------------------------------- dashboard


def test_leader_summary(services: Services, clock: FixedClock, world: World) -> None:
    summary = services.dashboard.leader_summary(COORDINATOR)
    assert summary.active_volunteers == 3
    assert [v.full_name for v in summary.applicants] == ["Ivy Newman"]
    assert [o.shift.shift_id for o in summary.understaffed] == [world.shift_id]
    assert summary.open_spots == 2

    services.scheduling.sign_up(COORDINATOR, world.shift_id, world.ana_id)
    clock.set(SATURDAY_9AM + timedelta(hours=4))
    services.attendance.check_in_everyone(COORDINATOR, world.shift_id)
    after = services.dashboard.leader_summary(COORDINATOR)
    assert after.hours_this_month == 3.0
    assert after.value_this_month == round(3.0 * after.hour_value, 2)


def test_volunteers_cannot_see_leader_dashboard(services: Services, world: World) -> None:
    with pytest.raises(PermissionDeniedError):
        services.dashboard.leader_summary(volunteer_session(world.ana_id))


def test_volunteer_summary(services: Services, world: World) -> None:
    me = volunteer_session(world.ana_id)
    services.scheduling.sign_up(me, world.shift_id, world.ana_id)
    summary = services.dashboard.volunteer_summary(me, world.ana_id)
    assert summary.volunteer.first_name == "Ana"
    assert [r.assignment.shift_id for r in summary.upcoming] == [world.shift_id]
    assert summary.community_value == 0.0
    with pytest.raises(PermissionDeniedError):
        services.dashboard.volunteer_summary(me, world.ben_id)


# ----------------------------------------------------------------- settings


def test_anyone_can_change_accessibility(services: Services, world: World) -> None:
    result = services.settings.set_appearance(volunteer_session(world.ana_id), theme=Theme.DARK, font_scale=1.3)
    assert (result.theme, result.font_scale) == (Theme.DARK, 1.3)
    assert services.settings.appearance() == result


def test_only_admins_change_organization(services: Services) -> None:
    with pytest.raises(PermissionDeniedError):
        services.settings.update_organization(COORDINATOR, name="New Name", hour_value="40")
    with pytest.raises(ValidationError):
        services.settings.update_organization(ADMIN, name="New Name", hour_value="free")
    assert services.settings.organization_name() == "My Nonprofit"  # nothing half-saved
    services.settings.update_organization(ADMIN, name="Harbor Lights", hour_value="$34.67")
    assert (services.settings.organization_name(), services.settings.volunteer_hour_value()) == ("Harbor Lights", 34.67)


# -------------------------------------------------------------------- setup


def test_first_admin_setup(services: Services) -> None:
    assert services.setup.needs_setup()
    with pytest.raises(ValidationError) as caught:
        services.setup.create_first_admin(
            organization_name="Harbor Lights", username="director", password="weak", confirm="weak"
        )
    assert "password" in caught.value.errors
    session = services.setup.create_first_admin(
        organization_name="Harbor Lights", username="Director", password="Harbor2026!", confirm="Harbor2026!"
    )
    assert session.role is UserRole.ADMIN and session.username == "director"
    assert services.auth.sign_in("director", "Harbor2026!").account_id == session.account_id
    with pytest.raises(BusinessRuleError, match="already set up"):
        services.setup.create_first_admin(
            organization_name="Takeover", username="mallory", password="Takeover2026!", confirm="Takeover2026!"
        )


def test_demo_data_only_on_brand_new_database(services: Services, store: DataStore, clock: FixedClock) -> None:
    clock.set(datetime(2026, 10, 1, 8, 0))  # demo dates are relative to "today"; keep it in the real past
    summary = services.setup.load_demo_data()
    assert summary.volunteers == 40 and not services.setup.needs_setup()
    with pytest.raises(BusinessRuleError):
        services.setup.load_demo_data()


# ------------------------------------------------- featured, feed, insight


def test_featured_event_is_the_biggest_open_shift(services: Services, store: DataStore, world: World) -> None:
    from tests.factories import make_shift

    big = store.shifts.add(make_shift(world.opportunity_id, SATURDAY_9AM + timedelta(days=8), capacity=25))
    featured = services.dashboard.featured_event(volunteer_session(world.ana_id))
    assert featured is not None and featured.overview.shift.shift_id == big.shift_id
    assert featured.opportunity.title == "Food Pantry"


def test_activity_feed_newest_first(services: Services, clock: FixedClock, world: World) -> None:
    services.scheduling.sign_up(COORDINATOR, world.shift_id, world.ana_id)
    clock.set(SATURDAY_9AM + timedelta(hours=4))
    services.attendance.check_in_everyone(COORDINATOR, world.shift_id)
    feed = services.dashboard.activity_feed(COORDINATOR)
    kinds = [item.kind.value for item in feed]
    assert kinds[0] == "SERVED" and "SIGNED_UP" in kinds and "APPLIED" in kinds
    assert feed[0].volunteer_name == "Ana Lopez" and feed[0].hours == 3.0
    assert [i.occurred_at for i in feed] == sorted((i.occurred_at for i in feed), reverse=True)
    with pytest.raises(PermissionDeniedError):
        services.dashboard.activity_feed(volunteer_session(world.ana_id))


def test_recruitment_insight(services: Services, world: World) -> None:
    insight = services.dashboard.recruitment_insight(COORDINATOR)
    assert insight is not None and insight.total == 4 and insight.top_count == 4  # factory default: OTHER
    assert insight.share == 1.0


def test_mission_statement_round_trip(services: Services) -> None:
    services.settings.update_organization(ADMIN, name="Harbor Lights", hour_value="36.14", mission="We feed families.")
    assert services.settings.mission_statement() == "We feed families."


def test_program_photos(services: Services, world: World) -> None:
    jpeg = b"\xff\xd8\xff\xe0" + b"0" * 1000
    services.opportunities.set_photo(COORDINATOR, world.opportunity_id, jpeg)
    assert services.opportunities.photo(volunteer_session(world.ana_id), world.opportunity_id) == jpeg
    with pytest.raises(ValidationError, match="JPEG"):
        services.opportunities.set_photo(COORDINATOR, world.opportunity_id, b"GIF89a")
    with pytest.raises(ValidationError, match="300 kB"):
        services.opportunities.set_photo(COORDINATOR, world.opportunity_id, b"\xff\xd8\xff" + b"0" * 400_000)
    with pytest.raises(PermissionDeniedError):
        services.opportunities.set_photo(volunteer_session(world.ana_id), world.opportunity_id, jpeg)
    services.opportunities.remove_photo(COORDINATOR, world.opportunity_id)
    assert services.opportunities.photo(COORDINATOR, world.opportunity_id) is None
