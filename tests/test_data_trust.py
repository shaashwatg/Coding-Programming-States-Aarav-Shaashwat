"""CSV import with preview, backup and restore, the change history, and volunteer privacy."""

from __future__ import annotations

import json
import sqlite3
import zipfile
from contextlib import closing
from datetime import date
from pathlib import Path

import pytest

from servesync.core.errors import BusinessRuleError, DuplicateRecordError, PermissionDeniedError, ValidationError
from servesync.data import DataStore
from servesync.models import AssignmentStatus, UserRole, VolunteerStatus
from servesync.services import Services
from servesync.services.data_service import anonymized, decode_csv, template_csv
from tests.conftest import World
from tests.factories import ADMIN, COORDINATOR, make_volunteer, volunteer_session

HEADER = "First name,Last name,Email,Phone,Birth date,Skills,How they heard\n"


def _csv(*rows: str, header: str = HEADER) -> bytes:
    return (header + "\n".join(rows) + "\n").encode("utf-8")


# ------------------------------------------------------------------- import


def test_a_clean_file_previews_ready_and_imports_all_together(services: Services, store: DataStore) -> None:
    data = _csv(
        "Maria,Gomez,maria@example.org,206-555-0170,03/04/1990,Cooking; Spanish,Website",
        "Ben,Ito,ben.ito@example.org,(206) 555-0171,1985-11-20,,Referral",
    )
    preview = services.data.preview_import(COORDINATOR, data, status=VolunteerStatus.ACTIVE)
    assert preview.ready and [row.name for row in preview.rows] == ["Maria Gomez", "Ben Ito"]
    assert services.data.run_import(COORDINATOR, preview) == 2
    maria = store.volunteers.find_by_email("maria@example.org")
    assert maria is not None and maria.skills == {"Cooking", "Spanish"} and maria.status is VolunteerStatus.ACTIVE


def test_every_problem_is_listed_with_its_line_and_nothing_is_saved(services: Services, store: DataStore) -> None:
    data = _csv(
        "Maria,Gomez,maria@example.org,206-555-0170,03/04/1990,,Website",
        "J0rdan,Smith,not-an-email,911-555-0100,02/30/2001,,Billboard",
        "Ana,Lee,MARIA@example.org,206-555-0172,01/01/1992,,",
    )
    preview = services.data.preview_import(COORDINATOR, data, status=VolunteerStatus.APPLICANT)
    assert not preview.ready
    first, second, third = preview.rows
    assert first.ready and first.line == 2
    joined = " ".join(second.problems)
    assert second.line == 3 and "First name" in joined and "Email" in joined and "Phone" in joined
    assert "Birth date" in joined and "How they heard" in joined
    assert third.problems == ("Same email as line 2.",)
    with pytest.raises(BusinessRuleError):
        services.data.run_import(COORDINATOR, preview)
    assert store.volunteers.find_by_email("maria@example.org") is None


def test_people_already_on_file_are_caught(services: Services, world: World) -> None:
    data = _csv("Someone,Else,ana.lopez@example.org,206-555-0173,03/04/1990,,")
    (row,) = services.data.preview_import(COORDINATOR, data, status=VolunteerStatus.ACTIVE).rows
    assert row.problems == ("Someone with this email is already on file.",)


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"", "empty"),
        (b"Name,Email\nAna,ana@example.org\n", "needs these columns"),
        (HEADER.encode(), "no volunteers"),
        (b"x" * 2_000_001, "2 MB"),
    ],
)
def test_file_level_problems_are_explained(services: Services, data: bytes, message: str) -> None:
    preview = services.data.preview_import(COORDINATOR, data, status=VolunteerStatus.ACTIVE)
    assert not preview.ready and message in " ".join(preview.file_problems)


def test_spanish_headings_extra_columns_and_excel_encodings_work(services: Services) -> None:
    header = "Nombre,Apellido,Correo electrónico,Teléfono,Fecha de nacimiento,Favorite color\n"
    data = (header + "José,Núñez,jose@example.org,206-555-0174,03/04/1990,blue\n").encode("cp1252")
    preview = services.data.preview_import(COORDINATOR, data, status=VolunteerStatus.ACTIVE)
    assert preview.ready and preview.rows[0].name == "José Núñez"
    assert any("Favorite color" in note for note in preview.notes)
    assert decode_csv("﻿hola".encode()) == "hola"


def test_the_template_previews_ready(services: Services) -> None:
    preview = services.data.preview_import(COORDINATOR, template_csv().encode(), status=VolunteerStatus.ACTIVE)
    assert preview.ready


def test_volunteers_cannot_import(services: Services, world: World) -> None:
    with pytest.raises(PermissionDeniedError):
        services.data.preview_import(volunteer_session(world.ana_id), _csv(), status=VolunteerStatus.ACTIVE)


# ----------------------------------------------------------------- backups


def _admin(services: Services, store: DataStore) -> None:
    from servesync.models import UserAccount
    from tests.factories import fast_hash

    store.accounts.add(UserAccount(username="admin", password_hash=fast_hash(), role=UserRole.ADMIN))


def test_backup_then_restore_brings_everything_back(services: Services, store: DataStore, tmp_path: Path) -> None:
    _admin(services, store)
    kept = store.volunteers.add(make_volunteer(email="kept@example.org"))
    store.photos.save(1, b"\xff\xd8\xff photo")
    backup = tmp_path / "backup.zip"
    services.data.backup(ADMIN, backup)
    with zipfile.ZipFile(backup) as archive:
        assert {"manifest.json", "servesync.db", "photos/program-1.jpg"} <= set(archive.namelist())

    store.volunteers.add(make_volunteer(email="later@example.org", phone="404-555-0199"))
    store.photos.delete(1)
    manifest = services.data.restore(ADMIN, backup)
    assert manifest["app"] == "ServeSync"
    assert store.volunteers.find_by_email("later@example.org") is None
    assert store.volunteers.get(kept.volunteer_id or 0).email == "kept@example.org"
    assert store.photos.load(1) == b"\xff\xd8\xff photo"
    assert services.data.history(ADMIN)[0].action == "RESTORED"


def test_restore_refuses_files_that_are_not_safe_backups(services: Services, store: DataStore, tmp_path: Path) -> None:
    _admin(services, store)
    not_zip = tmp_path / "notes.zip"
    not_zip.write_text("hello")
    no_manifest = tmp_path / "other.zip"
    with zipfile.ZipFile(no_manifest, "w") as archive:
        archive.writestr("servesync.db", b"")
    for path, message in ((not_zip, "damaged"), (no_manifest, "isn't a ServeSync backup")):
        with pytest.raises(ValidationError) as caught:
            services.data.restore(ADMIN, path)
        assert message in caught.value.errors["backup"]

    good = tmp_path / "good.zip"
    services.data.backup(ADMIN, good)
    newer = tmp_path / "newer.zip"
    with zipfile.ZipFile(good) as src, zipfile.ZipFile(newer, "w") as dst:
        dst.writestr("manifest.json", src.read("manifest.json"))
        db = tmp_path / "db.sqlite"
        db.write_bytes(src.read("servesync.db"))
        with closing(sqlite3.connect(db)) as raw:
            raw.execute("PRAGMA user_version = 999")
        dst.write(db, "servesync.db")
    with pytest.raises(ValidationError, match="newer version"):
        services.data.restore(ADMIN, newer)


def test_only_administrators_back_up_and_see_history(services: Services, tmp_path: Path) -> None:
    with pytest.raises(PermissionDeniedError):
        services.data.backup(COORDINATOR, tmp_path / "b.zip")
    with pytest.raises(PermissionDeniedError):
        services.data.history(COORDINATOR)


# ------------------------------------------------------------ change history


def test_changes_are_recorded_with_who_what_and_which_fields(services: Services, world: World) -> None:
    volunteer = services.volunteers.get(COORDINATOR, world.ana_id)
    volunteer.phone = "404-555-0177"
    volunteer.pronouns = "she/her"
    services.volunteers.update_profile(COORDINATOR, volunteer)
    services.volunteers.change_status(COORDINATOR, world.ben_id, VolunteerStatus.INACTIVE)
    services.scheduling.sign_up(COORDINATOR, world.shift_id, world.ana_id)
    latest, status, changed = services.data.history(ADMIN)[:3]
    assert (latest.action, latest.entity, latest.changed_by) == ("ADDED", "SIGN_UP", "coordinator")
    assert (status.action, status.details) == ("STATUS", "ACTIVE>INACTIVE")
    assert changed.label == "Ana Lopez" and changed.details == "pronouns, phone"
    assert "404-555-0177" not in changed.details  # values are never copied into the history
    assert [e.label for e in services.data.history(ADMIN, search="ben")] == ["Ben Brooks"]
    assert all(e.entity == "SIGN_UP" for e in services.data.history(ADMIN, entity="SIGN_UP"))


# ------------------------------------------------------------------ privacy


def test_download_my_data_includes_everything_and_only_mine(services: Services, world: World) -> None:
    services.scheduling.sign_up(COORDINATOR, world.shift_id, world.ana_id)
    data = services.data.export_my_data(volunteer_session(world.ana_id), world.ana_id)
    assert data["profile"]["email"] == "ana.lopez@example.org" and data["service"][0]["status"] == "Scheduled"
    json.dumps(data)  # it really is plain JSON
    with pytest.raises(PermissionDeniedError):
        services.data.export_my_data(volunteer_session(world.ana_id), world.ben_id)


def test_a_deletion_request_anonymizes_someone_with_history(services: Services, store: DataStore, world: World) -> None:
    signup = services.scheduling.sign_up(COORDINATOR, world.shift_id, world.ana_id)
    store.assignments.update(
        type(signup)(
            signup.shift_id,
            signup.volunteer_id,
            AssignmentStatus.ATTENDED,
            3.0,
            signup.signed_up_at,
            signup.assignment_id,
            signup.role_id,
        )
    )
    request = services.data.request_deletion(volunteer_session(world.ana_id), world.ana_id, "Moving away")
    with pytest.raises(DuplicateRecordError):
        services.data.request_deletion(volunteer_session(world.ana_id), world.ana_id)
    assert [r.request_id for r in services.data.deletion_requests(ADMIN)] == [request.request_id]
    assert services.data.complete_deletion(ADMIN, request.request_id) is False
    former = store.volunteers.get(world.ana_id)
    assert (former.full_name, former.status) == ("Former Volunteer", VolunteerStatus.INACTIVE)
    assert former.skills == frozenset() and "lopez" not in former.email
    assert store.assignments.total_hours(volunteer_id=world.ana_id) == 3.0  # the hours still count
    assert all("Ana Lopez" not in entry.label for entry in services.data.history(ADMIN))


def test_someone_without_history_is_deleted_outright(services: Services, store: DataStore, world: World) -> None:
    request = services.data.request_deletion(volunteer_session(world.ben_id), world.ben_id)
    assert services.data.complete_deletion(ADMIN, request.request_id) is True
    assert not store.volunteers.exists(world.ben_id)
    with pytest.raises(PermissionDeniedError):
        services.data.complete_deletion(COORDINATOR, request.request_id)


def test_a_request_can_be_declined_with_a_reason(services: Services, world: World) -> None:
    request = services.data.request_deletion(volunteer_session(world.ben_id), world.ben_id)
    with pytest.raises(ValidationError):
        services.data.decline_deletion(ADMIN, request.request_id, "   ")
    services.data.decline_deletion(ADMIN, request.request_id, "An incident report is still open.")
    latest = services.data.my_deletion_request(volunteer_session(world.ben_id), world.ben_id)
    assert latest is not None and latest.status == "DECLINED" and "incident" in latest.response


def test_anonymizing_a_minor_keeps_the_record_valid() -> None:
    teen = make_volunteer(
        birth_date=date(2010, 5, 1),
        joined_on=date(2025, 6, 1),
        emergency_contact_name="Rae Young",
        emergency_contact_phone="404-555-0103",
        volunteer_id=7,
    )
    former = anonymized(teen)
    assert former.emergency_contact_name == "Removed on request" and former.birth_date == date(2010, 1, 1)
