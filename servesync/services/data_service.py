"""
Data and trust: importing volunteers, backups, the change history, and privacy.

* **Import** reads a CSV, checks *every* row the same way the volunteer form
  does, and lists exactly what to fix. Nothing is saved until every row is ready,
  and then all rows are saved together (one transaction), so a half-imported
  file never happens.
* **Backup** writes one ``.zip`` holding a consistent snapshot of the database,
  the program photos, and a small manifest. **Restore** checks the file
  thoroughly (a real ServeSync backup, not damaged, not from a newer version,
  with an active administrator to sign in with) before replacing anything.
* **Change history** answers "who changed what, and when?" for administrators.
* **Privacy**: volunteers can download everything ServeSync holds about them,
  and ask for their details to be removed. An administrator completes the
  request: someone with no service history is deleted outright; for someone
  with history, the personal details are removed but the hours stay, because
  the organization's totals and reports must still add up.
"""

from __future__ import annotations

import csv
import dataclasses
import io
import json
import logging
import sqlite3
import tempfile
import zipfile
from collections.abc import Sequence
from contextlib import closing
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from servesync import __version__
from servesync.config import ADULT_AGE
from servesync.core.errors import BusinessRuleError, DataStoreError, ValidationError
from servesync.core.i18n import mark, tr
from servesync.core.validators import InvalidInputError, calculate_age, clean_text
from servesync.data.migrations import LATEST_VERSION
from servesync.models import (
    ChangeEntry,
    DeletionRequest,
    RecruitmentSource,
    Volunteer,
    VolunteerStatus,
)
from servesync.services.base import Service
from servesync.services.session import Permission, Session

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ import

MAX_IMPORT_BYTES = 2_000_000
MAX_IMPORT_ROWS = 2_000
REQUIRED_COLUMNS = ("first_name", "last_name", "email", "phone", "birth_date")
OPTIONAL_TEXT_COLUMNS = ("preferred_name", "pronouns", "emergency_contact_name", "emergency_contact_phone", "notes")
#: Header names people actually use (English and Spanish), matched ignoring case, spaces and accents' absence.
HEADER_NAMES: dict[str, tuple[str, ...]] = {
    "first_name": ("first name", "first", "given name", "nombre"),
    "last_name": ("last name", "last", "surname", "family name", "apellido", "apellidos"),
    "email": ("email", "e-mail", "email address", "correo", "correo electronico", "correo electrónico"),
    "phone": ("phone", "phone number", "telephone", "mobile", "cell", "telefono", "teléfono", "celular"),
    "birth_date": ("birth date", "date of birth", "birthday", "dob", "fecha de nacimiento"),
    "preferred_name": ("name they go by", "preferred name", "nickname", "nombre que usa"),
    "pronouns": ("pronouns", "pronombres"),
    "emergency_contact_name": ("emergency contact", "emergency contact name", "contacto de emergencia"),
    "emergency_contact_phone": (
        "emergency phone",
        "emergency contact phone",
        "telefono de emergencia",
        "teléfono de emergencia",
    ),
    "recruitment_source": ("how they heard", "source", "recruitment source", "como se entero", "cómo se enteró"),
    "skills": ("skills", "habilidades"),
    "notes": ("notes", "staff notes", "notas"),
}
#: Labels for messages about a column (translated when shown).
COLUMN_LABELS = {
    "first_name": mark("First name"),
    "last_name": mark("Last name"),
    "email": mark("Email"),
    "phone": mark("Phone"),
    "birth_date": mark("Birth date"),
    "preferred_name": mark("Name they go by"),
    "pronouns": mark("Pronouns"),
    "emergency_contact_name": mark("Emergency contact"),
    "emergency_contact_phone": mark("Emergency phone"),
    "recruitment_source": mark("How they heard"),
    "skills": mark("Skills"),
    "notes": mark("Notes"),
}
TEMPLATE_ROW = (
    "Ana",
    "Lopez",
    "ana.lopez@example.org",
    "312-555-0142",
    "04/12/1998",
    "",
    "she/her",
    "",
    "",
    "Website",
    "Spanish; Tutoring",
    "",
)


@dataclass(frozen=True, slots=True)
class ImportRow:
    """One data row of the file, with everything wrong with it (empty = ready)."""

    line: int  # line number in the file, as a spreadsheet would show it
    name: str
    email: str
    problems: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return not self.problems


@dataclass(frozen=True, slots=True)
class ImportPreview:
    rows: tuple[ImportRow, ...]
    file_problems: tuple[str, ...] = ()  # problems with the file as a whole (missing columns, ...)
    notes: tuple[str, ...] = ()  # things worth knowing that don't block the import
    volunteers: tuple[Volunteer, ...] = field(default=(), repr=False)  # what will be saved, row by row

    @property
    def ready(self) -> bool:
        return bool(self.rows) and not self.file_problems and all(row.ready for row in self.rows)

    @property
    def problem_count(self) -> int:
        return len(self.file_problems) + sum(len(row.problems) for row in self.rows)


def _header_key(text: str) -> str | None:
    cleaned = " ".join(text.replace("_", " ").replace("﻿", "").split()).casefold()
    for key, names in HEADER_NAMES.items():
        if cleaned == key.replace("_", " ") or cleaned in names:
            return key
    return None


def decode_csv(data: bytes) -> str:
    """Excel saves UTF-8 (often with a byte-order mark) or Windows-1252; accept either."""
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def _source(text: str) -> RecruitmentSource:
    wanted = text.strip().casefold()
    for source in RecruitmentSource:
        if wanted in (source.value.casefold(), source.english_label.casefold(), source.label.casefold()):
            return source
    raise InvalidInputError(
        tr(
            "Use one of: {choices}.",
            choices=", ".join(source.label for source in RecruitmentSource),
        )
    )


def template_csv() -> str:
    """A ready-to-fill file with the expected headings and one example row."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow([tr(COLUMN_LABELS[key]) for key in COLUMN_LABELS])
    writer.writerow(TEMPLATE_ROW)
    return out.getvalue()


# ---------------------------------------------------------------- backups

BACKUP_DATABASE, BACKUP_MANIFEST, BACKUP_PHOTOS = "servesync.db", "manifest.json", "photos/"
MAX_BACKUP_BYTES = 500_000_000
_REQUIRED_TABLES = ("volunteers", "opportunities", "shifts", "assignments", "user_accounts")

# ---------------------------------------------------------------- privacy

FORMER_FIRST, FORMER_LAST = "Former", "Volunteer"
REMOVED_CONTACT = "Removed on request"


class DataService(Service):
    # ------------------------------------------------------------- import

    def preview_import(self, session: Session, data: bytes, *, status: VolunteerStatus) -> ImportPreview:
        """
        Read a CSV and check every row without saving anything. Each row is checked
        exactly like the volunteer form (format and meaning), plus: no two rows share
        an email, and nobody is already on file.
        """
        session.require(Permission.MANAGE_VOLUNTEERS)
        if status is VolunteerStatus.INACTIVE:
            raise BusinessRuleError(tr("Imported volunteers start as Applicant or Active."))
        if len(data) > MAX_IMPORT_BYTES:
            return ImportPreview((), (tr("This file is larger than 2 MB. Split it into smaller files."),))
        try:
            table = list(csv.reader(io.StringIO(decode_csv(data))))
        except csv.Error:
            return ImportPreview((), (tr("This doesn't look like a CSV file. Save it from your spreadsheet as CSV."),))
        table = [row for row in table if any(cell.strip() for cell in row)]
        if not table:
            return ImportPreview((), (tr("The file is empty."),))
        header, body = table[0], table[1:]
        keys = [_header_key(cell) for cell in header]
        notes = []
        unknown = [cell for cell, key in zip(header, keys, strict=True) if key is None and cell.strip()]
        if unknown:
            notes.append(tr("These columns will be skipped: {names}.", names=", ".join(unknown)))
        missing = [tr(COLUMN_LABELS[key]) for key in REQUIRED_COLUMNS if key not in keys]
        if missing:
            return ImportPreview(
                (), (tr("The file needs these columns: {names}.", names=", ".join(missing)),), tuple(notes)
            )
        if not body:
            return ImportPreview((), (tr("The file has headings but no volunteers."),), tuple(notes))
        if len(body) > MAX_IMPORT_ROWS:
            return ImportPreview((), (tr("Import at most 2,000 volunteers at a time."),), tuple(notes))

        today = self._clock.now().date()
        rows: list[ImportRow] = []
        volunteers: list[Volunteer] = []
        first_line_for_email: dict[str, int] = {}
        for offset, cells in enumerate(body):
            line = offset + 2  # line 1 is the heading
            values = {key: (cells[i].strip() if i < len(cells) else "") for i, key in enumerate(keys) if key}
            problems: list[str] = []
            fields: dict[str, Any] = {key: values.get(key, "") for key in (*REQUIRED_COLUMNS, *OPTIONAL_TEXT_COLUMNS)}
            fields["skills"] = frozenset(s.strip() for s in values.get("skills", "").split(";") if s.strip())
            try:
                fields["recruitment_source"] = (
                    _source(values["recruitment_source"])
                    if values.get("recruitment_source")
                    else RecruitmentSource.OTHER
                )
            except InvalidInputError as error:
                problems.append(tr("{column}: {message}", column=tr("How they heard"), message=str(error)))
                fields["recruitment_source"] = RecruitmentSource.OTHER
            volunteer: Volunteer | None = None
            try:
                volunteer = Volunteer(status=status, joined_on=today, **fields)
            except ValidationError as error:
                problems += [
                    tr("{column}: {message}", column=tr(COLUMN_LABELS.get(key, key)), message=message)
                    if key in COLUMN_LABELS
                    else message
                    for key, message in error.errors.items()
                ]
            email = values.get("email", "").casefold()
            if email and email in first_line_for_email:
                problems.append(tr("Same email as line {line}.", line=first_line_for_email[email]))
            elif email:
                first_line_for_email[email] = line
            if volunteer is not None and not problems:
                if self._store.volunteers.find_by_email(volunteer.email) is not None:
                    problems.append(tr("Someone with this email is already on file."))
                else:
                    match = self._store.volunteers.find_possible_duplicates(volunteer)
                    if match:
                        problems.append(tr("May already be on file as {name}.", name=match[0].full_name))
            name = " ".join(part for part in (values.get("first_name", ""), values.get("last_name", "")) if part)
            rows.append(ImportRow(line, name, values.get("email", ""), tuple(problems)))
            if volunteer is not None:
                volunteers.append(volunteer)
        return ImportPreview(tuple(rows), (), tuple(notes), tuple(volunteers))

    def run_import(self, session: Session, preview: ImportPreview) -> int:
        """Save every row of a preview that is fully ready, together. Returns how many were added."""
        session.require(Permission.MANAGE_VOLUNTEERS)
        if not preview.ready or len(preview.volunteers) != len(preview.rows):
            raise BusinessRuleError(tr("Fix every problem in the file first, then preview it again."))
        with self._store.transaction():
            for volunteer in preview.volunteers:
                self._store.volunteers.add(volunteer)  # constraints still guard every row
            count = len(preview.volunteers)
            self._log(session.username, "IMPORTED", "VOLUNTEER", None, tr("{count} volunteers", count=count))
        logger.info("Imported %s volunteers (account #%s)", count, session.account_id)
        return count

    # ------------------------------------------------------------ backups

    def backup(self, session: Session, path: Path) -> None:
        """Save everything (database, photos, a manifest) as one .zip file."""
        session.require(Permission.MANAGE_SETTINGS)
        manifest = {
            "app": "ServeSync",
            "app_version": __version__,
            "schema_version": LATEST_VERSION,
            "organization": self._store.settings.organization_name(),
            "created_at": self._clock.now().isoformat(timespec="seconds"),
        }
        with tempfile.TemporaryDirectory() as folder:
            snapshot = Path(folder) / BACKUP_DATABASE
            self._store.db.backup_to(snapshot)
            staged = Path(folder) / "backup.zip"
            with zipfile.ZipFile(staged, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr(BACKUP_MANIFEST, json.dumps(manifest, indent=2))
                archive.write(snapshot, BACKUP_DATABASE)
                for opportunity_id, data in self._store.photos.all().items():
                    archive.writestr(f"{BACKUP_PHOTOS}program-{opportunity_id}.jpg", data)
            try:
                path.write_bytes(staged.read_bytes())
            except OSError as exc:
                raise DataStoreError(
                    tr("Couldn't save the backup to {name}. Try another folder or drive.", name=path.name)
                ) from exc
        self._log(session.username, "ADDED", "DATA", None, path.name, "backup")
        logger.info("Backup saved by account #%s", session.account_id)

    def restore(self, session: Session, path: Path) -> dict[str, str]:
        """
        Replace everything with a backup, after checking it. Returns the backup's manifest.
        Checks, in order: it's a zip made by ServeSync; its database is intact
        (SQLite's integrity check); it isn't from a newer version; it has the core
        tables; and it has an active administrator, so someone can still sign in.
        """
        session.require(Permission.MANAGE_SETTINGS)
        if not path.exists() or path.stat().st_size > MAX_BACKUP_BYTES:
            raise ValidationError.single("backup", tr("Choose a ServeSync backup file (.zip)."))
        with tempfile.TemporaryDirectory() as folder:
            try:
                with zipfile.ZipFile(path) as archive:
                    names = set(archive.namelist())
                    if BACKUP_MANIFEST not in names or BACKUP_DATABASE not in names:
                        raise ValidationError.single("backup", tr("This isn't a ServeSync backup."))
                    manifest = json.loads(archive.read(BACKUP_MANIFEST))
                    if not isinstance(manifest, dict) or manifest.get("app") != "ServeSync":
                        raise ValidationError.single("backup", tr("This isn't a ServeSync backup."))
                    database = Path(folder) / BACKUP_DATABASE
                    database.write_bytes(archive.read(BACKUP_DATABASE))
                    photos = {
                        int(
                            name.removeprefix(BACKUP_PHOTOS).removeprefix("program-").removesuffix(".jpg")
                        ): archive.read(name)
                        for name in names
                        if name.startswith(f"{BACKUP_PHOTOS}program-")
                        and name.endswith(".jpg")
                        and name.removeprefix(f"{BACKUP_PHOTOS}program-").removesuffix(".jpg").isdecimal()
                    }
            except (zipfile.BadZipFile, ValueError, KeyError) as exc:
                raise ValidationError.single("backup", tr("This backup file is damaged and can't be used.")) from exc
            self._check_backup_database(database)
            self._store.db.restore_from(database)
        from servesync.data.migrations import apply_migrations  # older backups are upgraded in place

        apply_migrations(self._store.db)
        self._store.photos.replace_all(photos)
        self._log(session.username, "RESTORED", "DATA", None, path.name, str(manifest.get("created_at", ""))[:40])
        logger.info("Backup restored by account #%s", session.account_id)
        return {str(k): str(v) for k, v in manifest.items()}

    @staticmethod
    def _check_backup_database(database: Path) -> None:
        try:
            with closing(sqlite3.connect(str(database))) as raw:
                if raw.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValidationError.single("backup", tr("This backup file is damaged and can't be used."))
                version = raw.execute("PRAGMA user_version").fetchone()[0]
                tables = {row[0] for row in raw.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
                if version > LATEST_VERSION:
                    raise ValidationError.single(
                        "backup", tr("This backup is from a newer version of ServeSync. Update the app first.")
                    )
                if not set(_REQUIRED_TABLES) <= tables:
                    raise ValidationError.single("backup", tr("This isn't a ServeSync backup."))
                admins = raw.execute(
                    "SELECT COUNT(*) FROM user_accounts WHERE role = 'ADMIN' AND is_active = 1"
                ).fetchone()[0]
                if not admins:
                    raise ValidationError.single(
                        "backup", tr("This backup has no active administrator, so nobody could sign in to it.")
                    )
        except sqlite3.DatabaseError as exc:
            raise ValidationError.single("backup", tr("This backup file is damaged and can't be used.")) from exc

    # ------------------------------------------------------- change history

    def history(self, session: Session, *, entity: str | None = None, search: str = "") -> list[ChangeEntry]:
        """Who changed what, and when, newest first (administrators only)."""
        session.require(Permission.MANAGE_SETTINGS)
        text = " ".join(str(search).split())
        if len(text) > 80:
            raise ValidationError.single("search", tr("Search for a name or username of 80 characters or fewer."))
        return self._store.changes.recent(entity=entity or None, search=text)

    # ------------------------------------------------------------- privacy

    def export_my_data(self, session: Session, volunteer_id: int) -> dict[str, Any]:
        """Everything ServeSync holds about one volunteer, as plain data (for a JSON file)."""
        session.require_self_or(Permission.MANAGE_VOLUNTEERS, volunteer_id)
        volunteer = self._store.volunteers.get(volunteer_id)
        account = self._store.accounts.find_by_volunteer(volunteer_id)
        history = self._store.assignments.history(volunteer_id)
        latest = self._store.deletion_requests.latest_for(volunteer_id)
        roles = {}
        for record in history:
            if record.assignment.role_id is not None and record.assignment.role_id not in roles:
                roles[record.assignment.role_id] = self._store.shifts.get_role(
                    record.assignment.role_id
                ).role.display_name
        return {
            "exported_at": self._clock.now().isoformat(timespec="seconds"),
            "organization": self._store.settings.organization_name(),
            "profile": {
                "first_name": volunteer.first_name,
                "last_name": volunteer.last_name,
                "name_you_go_by": volunteer.preferred_name,
                "pronouns": volunteer.pronouns,
                "email": volunteer.email,
                "phone": volunteer.display_phone,
                "birth_date": volunteer.birth_date.isoformat(),
                "joined_on": volunteer.joined_on.isoformat(),
                "status": volunteer.status.english_label,
                "how_you_heard": volunteer.recruitment_source.english_label,
                "referred_by": volunteer.referred_by,
                "emergency_contact": {
                    "name": volunteer.emergency_contact_name,
                    "phone": volunteer.emergency_contact_phone,
                },
                "skills": sorted(volunteer.skills, key=str.casefold),
                "usually_available": sorted(f"{s.weekday.name} {s.day_part.name}" for s in volunteer.availability),
                "access_needs": sorted(need.value for need in volunteer.access_needs),
                "hour_goal": (
                    {"hours": volunteer.hour_goal, "by": volunteer.hour_goal_due.isoformat()}
                    if volunteer.hour_goal and volunteer.hour_goal_due
                    else None
                ),
                "notes_by_staff": volunteer.notes,
            },
            "certifications_and_waivers": [
                {
                    "name": item.name,
                    "type": item.kind.english_label,
                    "issued_on": item.issued_on.isoformat() if item.issued_on else None,
                    "expires_on": item.expires_on.isoformat(),
                }
                for item in sorted(volunteer.certifications, key=lambda c: c.name.casefold())
            ],
            "sign_in": ({"username": account.username, "role": account.role.value} if account is not None else None),
            "service": [
                {
                    "program": record.opportunity_title,
                    "starts_at": record.starts_at.isoformat(timespec="minutes"),
                    "ends_at": record.ends_at.isoformat(timespec="minutes"),
                    "role": roles.get(record.assignment.role_id or 0, ""),
                    "status": record.assignment.status.english_label,
                    "hours": record.assignment.hours_served,
                }
                for record in history
            ],
            "deletion_request": (
                {"requested_at": latest.requested_at.isoformat(timespec="minutes"), "status": latest.status}
                if latest is not None
                else None
            ),
        }

    def request_deletion(self, session: Session, volunteer_id: int, reason: object = "") -> DeletionRequest:
        """A volunteer asks for their personal details to be removed (an administrator completes it)."""
        session.require_self_or(Permission.MANAGE_VOLUNTEERS, volunteer_id)
        try:
            text = clean_text(reason, tr("Reason"), max_length=500, required=False, multiline=True)
        except InvalidInputError as error:
            raise ValidationError.single("reason", str(error)) from error
        name = self._store.volunteers.get(volunteer_id).full_name
        request = self._store.deletion_requests.add(volunteer_id, self._clock.now(), text)
        self._log(session.username, "REQUESTED", "VOLUNTEER", volunteer_id, name, "deletion")
        return request

    def my_deletion_request(self, session: Session, volunteer_id: int) -> DeletionRequest | None:
        session.require_self_or(Permission.MANAGE_VOLUNTEERS, volunteer_id)
        return self._store.deletion_requests.latest_for(volunteer_id)

    def deletion_requests(self, session: Session) -> list[DeletionRequest]:
        session.require(Permission.DELETE_RECORDS)
        return self._store.deletion_requests.pending()

    def decline_deletion(self, session: Session, request_id: int, response: object) -> None:
        """Say no (for example, an open safety matter), with a reason the volunteer can read."""
        session.require(Permission.DELETE_RECORDS)
        try:
            text = clean_text(response, tr("Reason"), max_length=500, multiline=True)
        except InvalidInputError as error:
            raise ValidationError.single("response", str(error)) from error
        request = self._store.deletion_requests.get(request_id)
        self._store.deletion_requests.close(
            request_id, status="DECLINED", handled_by=session.username, handled_at=self._clock.now(), response=text
        )
        self._log(
            session.username, "CHANGED", "VOLUNTEER", request.volunteer_id, request.volunteer_name, "deletion declined"
        )

    def complete_deletion(self, session: Session, request_id: int) -> bool:
        """
        Remove a volunteer's personal details. Returns True if the whole record was deleted
        (no service history), False if it was anonymized (hours kept for the totals).
        """
        session.require(Permission.DELETE_RECORDS)
        request = self._store.deletion_requests.get(request_id)
        if request.status != "PENDING":
            raise BusinessRuleError(tr("This request was already handled."))
        volunteer_id = request.volunteer_id
        now = self._clock.now()
        with self._store.transaction():
            volunteer = self._store.volunteers.get(volunteer_id)
            old_names = {volunteer.full_name, volunteer.legal_name}
            self._store.deletion_requests.close(
                request_id, status="COMPLETED", handled_by=session.username, handled_at=now, response=""
            )
            for shift_id in self._store.waitlist.shifts_for(volunteer_id):
                self._store.waitlist.remove(shift_id, volunteer_id)
            upcoming = self._store.assignments.upcoming_scheduled(after=now, volunteer_id=volunteer_id)
            self._cancel_signups(upcoming)
            self._store.notices.delete_for_volunteer(volunteer_id)
            self._store.accounts.delete_for_volunteer(volunteer_id)
            for item in volunteer.certifications:
                self._store.volunteers.remove_certification(volunteer_id, item.name)
            deleted = not self._store.assignments.history(volunteer_id)
            if deleted:
                self._store.volunteers.delete(volunteer_id)
            else:
                self._store.volunteers.update(anonymized(volunteer))
            replacement = f"{FORMER_FIRST} {FORMER_LAST}"
            for name in old_names:
                self._store.changes.remove_name(name, replacement)
            self._log(session.username, "ANONYMIZED", "VOLUNTEER", None if deleted else volunteer_id, replacement)
        logger.info("Deletion request #%s completed (record %s)", request_id, "deleted" if deleted else "anonymized")
        return deleted


def anonymized(volunteer: Volunteer) -> Volunteer:
    """
    The same record with every personal detail removed. Kept: the record number, the
    join date and status (archived), and the birth *year* only, so age-based reports
    still count them correctly. Every value is still valid, so the record loads normally.
    """
    volunteer_id = volunteer.volunteer_id or 0
    # Someone who joined under 18 must keep *a* guardian contact for the record to stay valid;
    # the real one is replaced by a placeholder that says what happened.
    joined_as_minor = calculate_age(volunteer.birth_date, volunteer.joined_on) < ADULT_AGE
    contact = (REMOVED_CONTACT, "2025550101") if joined_as_minor else ("", "")
    return dataclasses.replace(
        volunteer,
        first_name=FORMER_FIRST,
        last_name=FORMER_LAST,
        preferred_name="",
        pronouns="",
        email=f"former-volunteer-{volunteer_id}@example.org",
        phone="2025550100",
        birth_date=date(volunteer.birth_date.year, 1, 1),
        status=VolunteerStatus.INACTIVE,
        skills=frozenset(),
        availability=frozenset(),
        access_needs=frozenset(),
        emergency_contact_name=contact[0],
        emergency_contact_phone=contact[1],
        notes="",
        referred_by="",
        hour_goal=None,
        hour_goal_due=None,
        certifications=frozenset(),
    )


def describe_volunteer_count(rows: Sequence[ImportRow]) -> tuple[int, int]:
    """(ready rows, rows needing a fix): the summary line of the import preview."""
    ready = sum(1 for row in rows if row.ready)
    return ready, len(rows) - ready


def json_text(data: dict[str, Any]) -> str:
    """Readable JSON (indented, accents kept) for "Download my data"."""
    return json.dumps(data, indent=2, ensure_ascii=False, default=str)
