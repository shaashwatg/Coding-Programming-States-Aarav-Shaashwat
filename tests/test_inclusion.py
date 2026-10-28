"""Inclusive data model: names, pronouns, access needs, and per-person comfort settings."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path

import pytest

from servesync.core.errors import ValidationError
from servesync.core.validators import InvalidInputError, clean_pronouns
from servesync.data import DataStore
from servesync.data.migrations import current_version
from servesync.models import AccessNeed, Appearance, MessageDuration, Theme, UserAccount, UserRole, access_gaps
from servesync.services import Services, Session
from servesync.services.rules import describe_access_gaps
from tests.conftest import SATURDAY_9AM, World
from tests.factories import COORDINATOR, fast_hash, make_opportunity, make_shift, make_volunteer, volunteer_session

# --------------------------------------------------------------- names


def test_preferred_name_is_shown_and_legal_name_kept() -> None:
    volunteer = make_volunteer(first_name="Alexandra", preferred_name="Sasha", pronouns="she / her")
    assert volunteer.full_name == "Sasha Lopez"
    assert volunteer.legal_name == "Alexandra Lopez"
    assert volunteer.given_name == "Sasha"
    assert volunteer.pronouns == "she/her"  # spacing tidied
    assert volunteer.name_with_pronouns == "Sasha Lopez (she/her)"


@pytest.mark.parametrize("text", ["they/them", "he, they", "ze/hir", "any pronouns", "Xe/Xem"])
def test_pronouns_accept_how_people_write_them(text: str) -> None:
    assert clean_pronouns(text)


@pytest.mark.parametrize("text", ["she/", "12", "<b>", "x" * 31])
def test_pronouns_reject_malformed_text(text: str) -> None:
    with pytest.raises(InvalidInputError):
        clean_pronouns(text)


def test_preferred_name_follows_name_rules() -> None:
    with pytest.raises(ValidationError) as caught:
        make_volunteer(preferred_name="R2-D2")
    assert "preferred_name" in caught.value.errors


def test_display_name_used_in_rosters_totals_and_search(services: Services, world: World) -> None:
    store = services.store
    ana = store.volunteers.get(world.ana_id)
    store.volunteers.update(make_volunteer(**{**_fields(ana), "preferred_name": "Annie"}))
    services.scheduling.sign_up(COORDINATOR, world.shift_id, world.ana_id)
    assert [entry.volunteer_name for entry in store.assignments.roster(world.shift_id)] == ["Annie Lopez"]
    assert store.volunteers.get_participation(world.ana_id).full_name == "Annie Lopez"
    assert [v.volunteer_id for v in store.volunteers.find_all(search="annie")] == [world.ana_id]
    assert [v.volunteer_id for v in store.volunteers.find_all(search="ana lopez")] == [world.ana_id]  # legal name too


def _fields(volunteer: object) -> dict[str, object]:
    names = (
        "first_name",
        "last_name",
        "email",
        "phone",
        "birth_date",
        "joined_on",
        "status",
        "recruitment_source",
        "skills",
        "availability",
        "emergency_contact_name",
        "emergency_contact_phone",
        "notes",
        "preferred_name",
        "pronouns",
        "access_needs",
        "volunteer_id",
    )
    return {name: getattr(volunteer, name) for name in names}


# ---------------------------------------------------------- access needs


def test_access_needs_round_trip(store: DataStore) -> None:
    saved = store.volunteers.add(make_volunteer(access_needs={"STEP_FREE", AccessNeed.QUIET}))
    assert store.volunteers.get(saved.volunteer_id or 0).access_needs == {AccessNeed.STEP_FREE, AccessNeed.QUIET}
    program = store.opportunities.add(make_opportunity(access_features={AccessNeed.REMOTE}))
    assert store.opportunities.get(program.opportunity_id or 0).access_features == {AccessNeed.REMOTE}


def test_unknown_access_need_is_rejected() -> None:
    with pytest.raises(ValidationError):
        make_volunteer(access_needs={"JETPACK"})


def test_access_gaps_and_remote_rule() -> None:
    needs = frozenset({AccessNeed.STEP_FREE, AccessNeed.NO_COST})
    assert access_gaps(needs, frozenset({AccessNeed.NO_COST})) == [AccessNeed.STEP_FREE]
    # Remote work satisfies in-person needs, but not cost.
    assert access_gaps(needs, frozenset({AccessNeed.REMOTE})) == [AccessNeed.NO_COST]
    assert describe_access_gaps(needs, frozenset(), "Park Day")[0] == (
        "Needs step-free access: 'Park Day' isn't listed as step-free"
    )


def test_smart_match_lists_access_gaps_last_but_never_hides(services: Services, world: World) -> None:
    store = services.store
    ana = store.volunteers.get(world.ana_id)
    store.volunteers.update(make_volunteer(**{**_fields(ana), "access_needs": frozenset({AccessNeed.STEP_FREE})}))
    matches = services.matching.recommend_volunteers(COORDINATOR, world.shift_id)
    by_id = {m.volunteer.volunteer_id: m for m in matches}
    assert world.ana_id in by_id  # still shown...
    assert not by_id[world.ana_id].fits_access_needs
    assert any("step-free" in concern for concern in by_id[world.ana_id].concerns)
    assert matches[-1].volunteer.volunteer_id == world.ana_id  # ...after everyone without a gap


def test_volunteers_see_fitting_shifts_unless_they_ask_for_all(services: Services, world: World) -> None:
    store = services.store
    ana = store.volunteers.get(world.ana_id)
    store.volunteers.update(make_volunteer(**{**_fields(ana), "access_needs": frozenset({AccessNeed.SEATED})}))
    seated = store.opportunities.add(make_opportunity(title="Phone Bank", access_features={AccessNeed.SEATED}))
    store.shifts.add(make_shift(seated.opportunity_id or 0, SATURDAY_9AM.replace(hour=13)))
    me = volunteer_session(world.ana_id)
    fitting = services.matching.recommend_shifts(me, world.ana_id, diversify=False)
    everything = services.matching.recommend_shifts(me, world.ana_id, diversify=False, only_fitting_access=False)
    assert [m.overview.opportunity_title for m in fitting] == ["Phone Bank"]
    assert len(everything) == 2 and everything[-1].access_gaps


# --------------------------------------------------------- preferences


def test_appearance_validates_and_round_trips() -> None:
    chosen = Appearance(
        Theme.DARK,
        1.5,
        reduce_motion=True,
        text_spacing=True,
        simplified=True,
        message_duration=MessageDuration.UNTIL_CLOSED,
    )
    assert Appearance.from_settings(chosen.to_settings()) == chosen
    with pytest.raises(ValidationError):
        Appearance(font_scale=3.0)
    with pytest.raises(ValidationError):
        Appearance(reduce_motion="yes")  # type: ignore[arg-type]


def test_damaged_preference_values_fall_back_safely() -> None:
    restored = Appearance.from_settings({"theme": "NEON", "font_scale": "huge", "reduce_motion": "1"})
    assert restored.theme is Theme.SYSTEM and restored.font_scale == 1.0 and restored.reduce_motion


def test_preferences_follow_each_account(services: Services, world: World) -> None:
    store = services.store
    ana_account = store.accounts.add(UserAccount("ana", fast_hash(), UserRole.VOLUNTEER, volunteer_id=world.ana_id))
    ben_account = store.accounts.add(UserAccount("ben", fast_hash(), UserRole.VOLUNTEER, volunteer_id=world.ben_id))
    ana = Session(ana_account.account_id or 0, "ana", UserRole.VOLUNTEER, world.ana_id)
    ben = Session(ben_account.account_id or 0, "ben", UserRole.VOLUNTEER, world.ben_id)

    services.settings.set_appearance(ana, theme=Theme.HIGH_CONTRAST, font_scale=1.75, reduce_motion=True)
    assert services.settings.appearance(ana).font_scale == 1.75
    # Ben has never chosen: he starts from this computer's most recent settings...
    assert services.settings.appearance(ben).theme is Theme.HIGH_CONTRAST
    services.settings.set_appearance(ben, theme=Theme.DARK, font_scale=1.0)
    # ...and his choice doesn't change Ana's.
    assert services.settings.appearance(ana).theme is Theme.HIGH_CONTRAST
    assert services.settings.appearance(ben).theme is Theme.DARK
    assert services.settings.appearance().theme is Theme.DARK  # sign-in screen: last used


def test_invalid_preference_change_saves_nothing(services: Services, world: World) -> None:
    before = services.settings.appearance()
    with pytest.raises(ValidationError):
        services.settings.set_appearance(volunteer_session(world.ana_id), font_scale=9.0)
    assert services.settings.appearance() == before


# ------------------------------------------------------------ migration


def test_version_2_file_upgrades_with_inclusion_columns(tmp_path: Path) -> None:
    path = tmp_path / "v2.db"
    with DataStore.open(path) as store:
        volunteer = store.volunteers.add(make_volunteer())
    with closing(sqlite3.connect(path)) as raw:  # rewind the file to look like version 2
        raw.executescript(
            "DROP TABLE account_preferences; DROP TABLE opportunity_access_features; DROP TABLE volunteer_access_needs;"
            "DROP VIEW volunteer_participation;"
            "ALTER TABLE volunteers DROP COLUMN pronouns; ALTER TABLE volunteers DROP COLUMN preferred_name;"
            "CREATE VIEW volunteer_participation AS SELECT 1 AS volunteer_id;"
            "PRAGMA user_version = 2;"
        )
    with DataStore.open(path) as store:
        assert current_version(store.db) == 3
        upgraded = store.volunteers.get(volunteer.volunteer_id or 0)
        assert (upgraded.preferred_name, upgraded.pronouns, upgraded.access_needs) == ("", "", frozenset())
        assert store.volunteers.get_participation(volunteer.volunteer_id or 0).full_name == "Ana Lopez"


def test_database_rejects_unknown_access_codes(store: DataStore, world: World) -> None:
    from servesync.core.errors import DataStoreError

    with pytest.raises(DataStoreError):
        store.db.execute(
            "INSERT INTO volunteer_access_needs (volunteer_id, need) VALUES (?, 'JETPACK')", (world.ana_id,)
        )


def test_birthdays_still_validate_with_new_fields() -> None:
    with pytest.raises(ValidationError):
        make_volunteer(birth_date=date(2020, 1, 1), pronouns="he/him")
