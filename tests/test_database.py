"""Database engine tests: migrations, transactions, integrity settings, error translation."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from servesync import config
from servesync.core.errors import DataStoreError
from servesync.data import LATEST_VERSION, Database, DataStore, apply_migrations
from servesync.data import migrations as migrations_module
from servesync.data.migrations import Migration, current_version
from servesync.models import (
    AssignmentStatus,
    DayPart,
    OpportunityCategory,
    OpportunityStatus,
    RecruitmentSource,
    UserRole,
    VolunteerStatus,
)


def _table_sql(store: DataStore, table: str) -> str:
    return str(store.db.query_value("SELECT sql FROM sqlite_master WHERE name = ?", (table,)))


def test_new_database_is_migrated_to_latest(store: DataStore) -> None:
    assert current_version(store.db) == LATEST_VERSION
    assert apply_migrations(store.db) == []  # idempotent: nothing left to apply


def test_migration_versions_are_sequential() -> None:
    versions = [m.version for m in migrations_module.MIGRATIONS]
    assert versions == list(range(1, len(versions) + 1))


def test_foreign_keys_are_enforced(store: DataStore) -> None:
    assert store.db.query_value("PRAGMA foreign_keys") == 1


def test_default_settings_are_seeded(store: DataStore) -> None:
    assert store.settings.volunteer_hour_value() == config.DEFAULT_VOLUNTEER_HOUR_VALUE
    assert store.settings.organization_name() == "My Nonprofit"


@pytest.mark.parametrize(
    ("table", "enum_type"),
    [
        ("volunteers", VolunteerStatus),
        ("volunteers", RecruitmentSource),
        ("opportunities", OpportunityCategory),
        ("opportunities", OpportunityStatus),
        ("assignments", AssignmentStatus),
        ("user_accounts", UserRole),
        ("volunteer_availability", DayPart),
    ],
)
def test_schema_check_constraints_match_python_enums(store: DataStore, table: str, enum_type: type) -> None:
    sql = _table_sql(store, table)
    for member in enum_type:
        assert f"'{member.value}'" in sql, f"{table} CHECK is missing {member.value}"


def test_schema_limits_match_configuration(store: DataStore) -> None:
    assert f"BETWEEN {config.MINIMUM_VOLUNTEER_AGE} AND 99" in _table_sql(store, "opportunities")
    assert f"hours_served <= {config.MAX_SHIFT_HOURS}" in _table_sql(store, "assignments")
    assert f"BETWEEN 1 AND {config.MAX_SHIFT_CAPACITY}" in _table_sql(store, "shifts")


def test_transaction_rolls_back_on_error(store: DataStore) -> None:
    with pytest.raises(RuntimeError), store.transaction():
        store.settings.set_organization_name("Changed")
        raise RuntimeError("boom")
    assert store.settings.organization_name() == "My Nonprofit"


def test_nested_transaction_rolls_back_only_inner_work(store: DataStore) -> None:
    with store.transaction():
        store.settings.set_organization_name("Outer")
        with pytest.raises(RuntimeError), store.transaction():
            store.settings.set_volunteer_hour_value("99")
            raise RuntimeError("inner failure")
    assert store.settings.organization_name() == "Outer"
    assert store.settings.volunteer_hour_value() == config.DEFAULT_VOLUNTEER_HOUR_VALUE


def test_file_database_persists_between_sessions(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "servesync.db"
    with DataStore.open(path) as first:
        first.settings.set_organization_name("Harbor Lights")
    with DataStore.open(path) as second:
        assert second.settings.organization_name() == "Harbor Lights"
        assert second.db.query_value("PRAGMA journal_mode") == "wal"


def test_damaged_file_gives_friendly_error(tmp_path: Path) -> None:
    path = tmp_path / "servesync.db"
    path.write_bytes(b"this is not a sqlite database" * 100)
    with pytest.raises(DataStoreError, match="damaged"):
        DataStore.open(path)


def test_file_from_newer_version_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "servesync.db"
    with Database(path) as db:
        db.execute(f"PRAGMA user_version = {LATEST_VERSION + 1}")
    with pytest.raises(DataStoreError, match="newer version"):
        DataStore.open(path)


def test_failed_migration_changes_nothing(store: DataStore, monkeypatch: pytest.MonkeyPatch) -> None:
    broken = Migration(LATEST_VERSION + 1, "Broken step", "CREATE TABLE half_done (x); SELECT * FROM missing;")
    monkeypatch.setattr(migrations_module, "MIGRATIONS", (*migrations_module.MIGRATIONS, broken))
    with pytest.raises(DataStoreError, match="Broken step"):
        apply_migrations(store.db)
    assert current_version(store.db) == LATEST_VERSION
    assert store.db.query_one("SELECT name FROM sqlite_master WHERE name = 'half_done'") is None


def test_migrations_refuse_to_run_inside_transaction(store: DataStore) -> None:
    with pytest.raises(RuntimeError), store.transaction():
        apply_migrations(store.db)


def test_queries_use_placeholders_not_string_formatting() -> None:
    """Guard rail: no repository builds SQL with user values via % or .format()."""
    source_dir = Path(__file__).resolve().parents[1] / "servesync" / "data" / "repositories"
    for source in source_dir.glob("*.py"):
        text = source.read_text(encoding="utf-8")
        assert not re.search(r"execute\([^)]*%\s*\(", text), source.name
        assert ".format(" not in text, source.name


def test_version_1_file_upgrades_without_losing_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An organization running version 1 keeps every record when the app is updated."""
    from tests.factories import make_opportunity

    path = tmp_path / "servesync.db"
    with monkeypatch.context() as patch:
        patch.setattr(migrations_module, "MIGRATIONS", migrations_module.MIGRATIONS[:1])
        with Database(path) as db:
            apply_migrations(db)
            db.execute(
                "INSERT INTO opportunities (title, description, category, location, coordinator_name, min_age, status)"
                " VALUES ('Old Program', 'Created before the upgrade.', 'EDUCATION', 'Library', 'Sam', 14, 'OPEN')"
            )
            assert current_version(db) == 1

    with DataStore.open(path) as store:
        assert current_version(store.db) == LATEST_VERSION
        (old,) = store.opportunities.find_all()
        assert old.title == "Old Program" and old.story_video_url == ""
        assert store.settings.mission_statement() == ""
        saved = store.opportunities.add(make_opportunity(story_video_url="example.org/story"))
        assert saved.story_video_url == "https://example.org/story"
