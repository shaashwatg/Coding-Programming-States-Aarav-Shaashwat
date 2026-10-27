"""Persistence for volunteers, their skills, and their weekly availability."""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from collections.abc import Sequence
from typing import Any

from servesync.core.errors import (
    DuplicateRecordError,
    RecordInUseError,
    RecordNotFoundError,
    ValidationError,
)
from servesync.data.converters import (
    chunked,
    contains_pattern,
    date_from_db,
    date_to_db,
    optional_date_from_db,
    placeholders,
)
from servesync.data.database import Database
from servesync.data.repositories.base import Repository
from servesync.data.repositories.skill_repository import SkillRepository
from servesync.models import (
    AccessNeed,
    AvailabilitySlot,
    DayPart,
    RecruitmentSource,
    Volunteer,
    VolunteerParticipation,
    VolunteerStatus,
    Weekday,
)

_ENTITY = "Volunteer"
_DUPLICATE_EMAIL = "Another volunteer already uses this email address."

_SELECT_VOLUNTEER = """
    SELECT volunteer_id, first_name, last_name, email, phone, birth_date, joined_on,
           status, recruitment_source, emergency_contact_name, emergency_contact_phone, notes,
           preferred_name, pronouns
    FROM volunteers
"""


def display_name_sql(table_alias: str = "") -> str:
    """
    SQL for the name a volunteer goes by: preferred name if given, else first
    name, then last name. ``table_alias`` must be a plain identifier (it is
    code, never user input), which is checked so it can't smuggle in SQL.
    """
    if table_alias and not table_alias.isidentifier():
        raise ValueError(f"Not a table alias: {table_alias!r}")
    t = f"{table_alias}." if table_alias else ""
    return f"COALESCE(NULLIF({t}preferred_name, ''), {t}first_name) || ' ' || {t}last_name"


class VolunteerRepository(Repository):
    def __init__(self, db: Database, skills: SkillRepository) -> None:
        super().__init__(db)
        self._skills = skills

    # ----------------------------------------------------------------- writes

    def add(self, volunteer: Volunteer) -> Volunteer:
        """Insert a new volunteer and return a copy carrying its new ID."""
        self._require_new(volunteer.volunteer_id, _ENTITY)
        with self._db.transaction():
            try:
                cursor = self._db.execute(
                    """
                    INSERT INTO volunteers (
                        first_name, last_name, email, phone, birth_date, joined_on, status,
                        recruitment_source, emergency_contact_name, emergency_contact_phone, notes,
                        preferred_name, pronouns)
                    VALUES (:first_name, :last_name, :email, :phone, :birth_date, :joined_on, :status,
                            :recruitment_source, :emergency_contact_name, :emergency_contact_phone, :notes,
                            :preferred_name, :pronouns)
                    """,
                    self._to_params(volunteer),
                )
            except DuplicateRecordError as exc:
                raise ValidationError.single("email", _DUPLICATE_EMAIL) from exc
            new_id = int(cursor.lastrowid or 0)
            self._write_skills(new_id, volunteer.skills)
            self._write_availability(new_id, volunteer.availability)
            self._write_access_needs(new_id, volunteer.access_needs)
        # Re-read so callers get canonical values (e.g. existing skill spellings).
        return self.get(new_id)

    def update(self, volunteer: Volunteer) -> Volunteer:
        """Save changes to an existing volunteer (skills and availability are replaced)."""
        volunteer_id = self._require_saved(volunteer.volunteer_id, _ENTITY)
        params = self._to_params(volunteer) | {"volunteer_id": volunteer_id}
        with self._db.transaction():
            try:
                cursor = self._db.execute(
                    """
                    UPDATE volunteers
                    SET first_name = :first_name, last_name = :last_name, email = :email,
                        phone = :phone, birth_date = :birth_date, joined_on = :joined_on,
                        status = :status, recruitment_source = :recruitment_source,
                        emergency_contact_name = :emergency_contact_name,
                        emergency_contact_phone = :emergency_contact_phone, notes = :notes,
                        preferred_name = :preferred_name, pronouns = :pronouns,
                        updated_at = strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime')
                    WHERE volunteer_id = :volunteer_id
                    """,
                    params,
                )
            except DuplicateRecordError as exc:
                raise ValidationError.single("email", _DUPLICATE_EMAIL) from exc
            if cursor.rowcount == 0:
                raise RecordNotFoundError(_ENTITY, volunteer_id)
            self._db.execute("DELETE FROM volunteer_skills WHERE volunteer_id = ?", (volunteer_id,))
            self._db.execute("DELETE FROM volunteer_availability WHERE volunteer_id = ?", (volunteer_id,))
            self._db.execute("DELETE FROM volunteer_access_needs WHERE volunteer_id = ?", (volunteer_id,))
            self._write_skills(volunteer_id, volunteer.skills)
            self._write_availability(volunteer_id, volunteer.availability)
            self._write_access_needs(volunteer_id, volunteer.access_needs)
        return self.get(volunteer_id)

    def set_status(self, volunteer_id: int, status: VolunteerStatus) -> None:
        cursor = self._db.execute(
            """
            UPDATE volunteers
            SET status = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime')
            WHERE volunteer_id = ?
            """,
            (status.value, volunteer_id),
        )
        if cursor.rowcount == 0:
            raise RecordNotFoundError(_ENTITY, volunteer_id)

    def delete(self, volunteer_id: int) -> None:
        """
        Permanently remove a volunteer who has **no** service history.

        Anyone with sign-ups is protected by the database (ON DELETE RESTRICT);
        leaders mark them Inactive instead so hour totals stay accurate.
        """
        try:
            cursor = self._db.execute("DELETE FROM volunteers WHERE volunteer_id = ?", (volunteer_id,))
        except RecordInUseError as exc:
            raise RecordInUseError(
                "This volunteer has service history, so the record is kept for reporting. "
                "Mark the volunteer Inactive instead."
            ) from exc
        if cursor.rowcount == 0:
            raise RecordNotFoundError(_ENTITY, volunteer_id)

    # ------------------------------------------------------------------ reads

    def get(self, volunteer_id: int) -> Volunteer:
        row = self._db.query_one(f"{_SELECT_VOLUNTEER} WHERE volunteer_id = ?", (volunteer_id,))
        if row is None:
            raise RecordNotFoundError(_ENTITY, volunteer_id)
        return self._hydrate([row])[0]

    def exists(self, volunteer_id: int) -> bool:
        return self._exists("volunteers", "volunteer_id", volunteer_id)

    def find_by_email(self, email: str) -> Volunteer | None:
        row = self._db.query_one(f"{_SELECT_VOLUNTEER} WHERE email = ?", (email.strip(),))
        return None if row is None else self._hydrate([row])[0]

    def find_all(
        self,
        *,
        status: VolunteerStatus | None = None,
        search: str = "",
        skill: str | None = None,
        available_in: AvailabilitySlot | None = None,
    ) -> list[Volunteer]:
        """
        Volunteers matching every filter given, sorted by last then first name.

        ``search`` matches legal or preferred name, email, or phone digits
        ("contains", case-insensitive).
        """
        clauses: list[str] = []
        params: list[Any] = []
        if status is not None:
            clauses.append("status = ?")
            params.append(status.value)
        text = search.strip()
        if text:
            pattern = contains_pattern(text)
            digits = "".join(ch for ch in text if ch.isdigit())
            clauses.append(
                "(first_name || ' ' || last_name LIKE ? ESCAPE '\\'"
                f" OR {display_name_sql()} LIKE ? ESCAPE '\\' OR email LIKE ? ESCAPE '\\'"
                + (" OR phone LIKE ? ESCAPE '\\'" if digits else "")
                + ")"
            )
            params.extend([pattern, pattern, pattern])
            if digits:
                params.append(contains_pattern(digits))
        if skill:
            clauses.append(
                """EXISTS (SELECT 1 FROM volunteer_skills AS vs
                           JOIN skills AS sk ON sk.skill_id = vs.skill_id
                           WHERE vs.volunteer_id = volunteers.volunteer_id AND sk.name = ?)"""
            )
            params.append(skill.strip())
        if available_in is not None:
            clauses.append(
                """EXISTS (SELECT 1 FROM volunteer_availability AS va
                           WHERE va.volunteer_id = volunteers.volunteer_id
                             AND va.weekday = ? AND va.day_part = ?)"""
            )
            params.extend([int(available_in.weekday), available_in.day_part.value])

        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._db.query_all(
            f"{_SELECT_VOLUNTEER}{where} ORDER BY last_name COLLATE NOCASE, first_name COLLATE NOCASE",
            params,
        )
        return self._hydrate(rows)

    def find_possible_duplicates(self, volunteer: Volunteer) -> list[Volunteer]:
        """
        Existing volunteers who are probably the same person: same phone number,
        or same name and birth date. Used to warn before creating a duplicate.
        """
        rows = self._db.query_all(
            f"""{_SELECT_VOLUNTEER}
            WHERE volunteer_id <> ?
              AND (phone = ?
                   OR (first_name = ? COLLATE NOCASE AND last_name = ? COLLATE NOCASE AND birth_date = ?))
            ORDER BY last_name COLLATE NOCASE, first_name COLLATE NOCASE""",
            (
                volunteer.volunteer_id or 0,
                volunteer.phone,
                volunteer.first_name,
                volunteer.last_name,
                date_to_db(volunteer.birth_date),
            ),
        )
        return self._hydrate(rows)

    def count_by_source(self) -> dict[RecruitmentSource, int]:
        """How many volunteers each recruitment channel brought in (all statuses)."""
        counts = dict.fromkeys(RecruitmentSource, 0)
        for row in self._db.query_all(
            "SELECT recruitment_source, COUNT(*) AS total FROM volunteers GROUP BY recruitment_source"
        ):
            counts[RecruitmentSource(row["recruitment_source"])] = row["total"]
        return counts

    def count_by_status(self) -> dict[VolunteerStatus, int]:
        counts = dict.fromkeys(VolunteerStatus, 0)
        for row in self._db.query_all("SELECT status, COUNT(*) AS total FROM volunteers GROUP BY status"):
            counts[VolunteerStatus(row["status"])] = row["total"]
        return counts

    def participation(self, *, status: VolunteerStatus | None = None) -> list[VolunteerParticipation]:
        """Hours and attendance totals per volunteer, most hours first."""
        sql = "SELECT * FROM volunteer_participation"
        params: tuple[Any, ...] = ()
        if status is not None:
            sql += " WHERE status = ?"
            params = (status.value,)
        sql += " ORDER BY total_hours DESC, full_name COLLATE NOCASE"
        return [self._to_participation(row) for row in self._db.query_all(sql, params)]

    def get_participation(self, volunteer_id: int) -> VolunteerParticipation:
        row = self._db.query_one("SELECT * FROM volunteer_participation WHERE volunteer_id = ?", (volunteer_id,))
        if row is None:
            raise RecordNotFoundError(_ENTITY, volunteer_id)
        return self._to_participation(row)

    # ---------------------------------------------------------------- helpers

    @staticmethod
    def _to_params(volunteer: Volunteer) -> dict[str, Any]:
        return {
            "first_name": volunteer.first_name,
            "last_name": volunteer.last_name,
            "email": volunteer.email,
            "phone": volunteer.phone,
            "birth_date": date_to_db(volunteer.birth_date),
            "joined_on": date_to_db(volunteer.joined_on),
            "status": volunteer.status.value,
            "recruitment_source": volunteer.recruitment_source.value,
            "emergency_contact_name": volunteer.emergency_contact_name,
            "emergency_contact_phone": volunteer.emergency_contact_phone,
            "notes": volunteer.notes,
            "preferred_name": volunteer.preferred_name,
            "pronouns": volunteer.pronouns,
        }

    def _write_skills(self, volunteer_id: int, skills: frozenset[str]) -> None:
        skill_ids = self._skills.ensure_ids(skills)
        self._db.execute_many(
            "INSERT INTO volunteer_skills (volunteer_id, skill_id) VALUES (?, ?)",
            [(volunteer_id, skill_id) for skill_id in skill_ids.values()],
        )

    def _write_access_needs(self, volunteer_id: int, needs: frozenset[AccessNeed]) -> None:
        self._db.execute_many(
            "INSERT INTO volunteer_access_needs (volunteer_id, need) VALUES (?, ?)",
            [(volunteer_id, need.value) for need in needs],
        )

    def _write_availability(self, volunteer_id: int, slots: frozenset[AvailabilitySlot]) -> None:
        self._db.execute_many(
            "INSERT INTO volunteer_availability (volunteer_id, weekday, day_part) VALUES (?, ?, ?)",
            [(volunteer_id, int(slot.weekday), slot.day_part.value) for slot in slots],
        )

    def _hydrate(self, rows: Sequence[sqlite3.Row]) -> list[Volunteer]:
        """
        Build Volunteer objects, loading skills and availability for *all* rows
        in two batched queries (avoids the classic "N+1 queries" slowdown).
        """
        ids = [row["volunteer_id"] for row in rows]
        skills: defaultdict[int, set[str]] = defaultdict(set)
        slots: defaultdict[int, set[AvailabilitySlot]] = defaultdict(set)
        needs: defaultdict[int, set[AccessNeed]] = defaultdict(set)
        for batch in chunked(ids):
            marks = placeholders(batch)
            for skill_row in self._db.query_all(
                f"""SELECT vs.volunteer_id, sk.name FROM volunteer_skills AS vs
                    JOIN skills AS sk ON sk.skill_id = vs.skill_id
                    WHERE vs.volunteer_id IN ({marks})""",
                tuple(batch),
            ):
                skills[skill_row["volunteer_id"]].add(skill_row["name"])
            for slot_row in self._db.query_all(
                f"SELECT volunteer_id, weekday, day_part FROM volunteer_availability WHERE volunteer_id IN ({marks})",
                tuple(batch),
            ):
                slots[slot_row["volunteer_id"]].add(
                    AvailabilitySlot(Weekday(slot_row["weekday"]), DayPart(slot_row["day_part"]))
                )
            for need_row in self._db.query_all(
                f"SELECT volunteer_id, need FROM volunteer_access_needs WHERE volunteer_id IN ({marks})",
                tuple(batch),
            ):
                needs[need_row["volunteer_id"]].add(AccessNeed(need_row["need"]))

        return [
            Volunteer(
                first_name=row["first_name"],
                last_name=row["last_name"],
                email=row["email"],
                phone=row["phone"],
                birth_date=date_from_db(row["birth_date"]),
                joined_on=date_from_db(row["joined_on"]),
                status=VolunteerStatus(row["status"]),
                recruitment_source=RecruitmentSource(row["recruitment_source"]),
                skills=frozenset(skills[row["volunteer_id"]]),
                availability=frozenset(slots[row["volunteer_id"]]),
                emergency_contact_name=row["emergency_contact_name"],
                emergency_contact_phone=row["emergency_contact_phone"],
                notes=row["notes"],
                preferred_name=row["preferred_name"],
                pronouns=row["pronouns"],
                access_needs=frozenset(needs[row["volunteer_id"]]),
                volunteer_id=row["volunteer_id"],
            )
            for row in rows
        ]

    @staticmethod
    def _to_participation(row: sqlite3.Row) -> VolunteerParticipation:
        return VolunteerParticipation(
            volunteer_id=row["volunteer_id"],
            full_name=row["full_name"],
            status=VolunteerStatus(row["status"]),
            total_hours=float(row["total_hours"]),
            shifts_attended=row["shifts_attended"],
            no_shows=row["no_shows"],
            cancellations=row["cancellations"],
            upcoming_shifts=row["upcoming_shifts"],
            last_served_on=optional_date_from_db(row["last_served_on"]),
        )
