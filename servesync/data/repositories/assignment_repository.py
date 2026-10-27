"""
Persistence for sign-ups and attendance — the organization's service record.

There is deliberately **no delete method**: history is append-only. A
volunteer who drops out is marked CANCELLED, which frees the spot but keeps
an honest record for participation reports.
"""

from __future__ import annotations

import dataclasses
import sqlite3
from datetime import date, datetime
from typing import Any

from servesync.core.errors import DuplicateRecordError, RecordNotFoundError
from servesync.data.converters import date_to_db, datetime_from_db, datetime_to_db
from servesync.data.repositories.base import Repository
from servesync.data.repositories.volunteer_repository import display_name_sql
from servesync.models import (
    ActivityItem,
    ActivityKind,
    Assignment,
    AssignmentStatus,
    OpportunityCategory,
    RecruitmentSource,
    RosterEntry,
    ServiceFact,
    ServiceRecord,
    Shift,
    VolunteerStatus,
)

_ENTITY = "Sign-up"

_V_NAME = display_name_sql("v")

_ASSIGNMENT_COLUMNS = "a.assignment_id, a.shift_id, a.volunteer_id, a.status, a.hours_served, a.signed_up_at"


class AssignmentRepository(Repository):
    # ----------------------------------------------------------------- writes

    def add(self, assignment: Assignment) -> Assignment:
        """Record a new sign-up. Fails if the shift or volunteer is missing or already paired."""
        self._require_new(assignment.assignment_id, _ENTITY)
        with self._db.transaction():
            if not self._exists("shifts", "shift_id", assignment.shift_id):
                raise RecordNotFoundError("Shift", assignment.shift_id)
            if not self._exists("volunteers", "volunteer_id", assignment.volunteer_id):
                raise RecordNotFoundError("Volunteer", assignment.volunteer_id)
            try:
                cursor = self._db.execute(
                    """
                    INSERT INTO assignments (shift_id, volunteer_id, status, hours_served, signed_up_at)
                    VALUES (:shift_id, :volunteer_id, :status, :hours_served, :signed_up_at)
                    """,
                    self._to_params(assignment),
                )
            except DuplicateRecordError as exc:
                raise DuplicateRecordError(
                    "This volunteer is already signed up for this shift.", field="volunteer_id"
                ) from exc
        return dataclasses.replace(assignment, assignment_id=int(cursor.lastrowid or 0))

    def update(self, assignment: Assignment) -> Assignment:
        """Save a status/hours change (e.g. check-in, no-show, cancellation, re-sign-up)."""
        assignment_id = self._require_saved(assignment.assignment_id, _ENTITY)
        cursor = self._db.execute(
            """
            UPDATE assignments
            SET status = :status, hours_served = :hours_served, signed_up_at = :signed_up_at,
                updated_at = strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime')
            WHERE assignment_id = :assignment_id
            """,
            self._to_params(assignment) | {"assignment_id": assignment_id},
        )
        if cursor.rowcount == 0:
            raise RecordNotFoundError(_ENTITY, assignment_id)
        return assignment

    # ------------------------------------------------------------------ reads

    def get(self, assignment_id: int) -> Assignment:
        row = self._db.query_one(
            f"SELECT {_ASSIGNMENT_COLUMNS} FROM assignments AS a WHERE a.assignment_id = ?", (assignment_id,)
        )
        if row is None:
            raise RecordNotFoundError(_ENTITY, assignment_id)
        return self._to_assignment(row)

    def find(self, shift_id: int, volunteer_id: int) -> Assignment | None:
        row = self._db.query_one(
            f"SELECT {_ASSIGNMENT_COLUMNS} FROM assignments AS a WHERE a.shift_id = ? AND a.volunteer_id = ?",
            (shift_id, volunteer_id),
        )
        return None if row is None else self._to_assignment(row)

    def roster(self, shift_id: int, *, include_cancelled: bool = False) -> list[RosterEntry]:
        """Everyone signed up for a shift, alphabetized — the check-in sheet."""
        status_filter = "" if include_cancelled else " AND a.status <> 'CANCELLED'"
        rows = self._db.query_all(
            f"""
            SELECT {_ASSIGNMENT_COLUMNS},
                   {_V_NAME} AS volunteer_name,
                   v.email AS volunteer_email, v.phone AS volunteer_phone
            FROM assignments AS a
            JOIN volunteers AS v ON v.volunteer_id = a.volunteer_id
            WHERE a.shift_id = ?{status_filter}
            ORDER BY v.last_name COLLATE NOCASE, v.first_name COLLATE NOCASE
            """,
            (shift_id,),
        )
        return [
            RosterEntry(
                assignment=self._to_assignment(row),
                volunteer_name=row["volunteer_name"],
                volunteer_email=row["volunteer_email"],
                volunteer_phone=row["volunteer_phone"],
            )
            for row in rows
        ]

    def history(self, volunteer_id: int) -> list[ServiceRecord]:
        """A volunteer's sign-ups with shift details, newest first."""
        rows = self._db.query_all(
            f"""
            SELECT {_ASSIGNMENT_COLUMNS}, s.starts_at, s.ends_at,
                   o.title AS opportunity_title, o.category
            FROM assignments AS a
            JOIN shifts        AS s ON s.shift_id = a.shift_id
            JOIN opportunities AS o ON o.opportunity_id = s.opportunity_id
            WHERE a.volunteer_id = ?
            ORDER BY s.starts_at DESC
            """,
            (volunteer_id,),
        )
        return [
            ServiceRecord(
                assignment=self._to_assignment(row),
                opportunity_title=row["opportunity_title"],
                category=OpportunityCategory(row["category"]),
                starts_at=datetime_from_db(row["starts_at"]),
                ends_at=datetime_from_db(row["ends_at"]),
            )
            for row in rows
        ]

    def conflicting_shifts(
        self,
        volunteer_id: int,
        starts_at: datetime,
        ends_at: datetime,
        *,
        exclude_shift_id: int | None = None,
    ) -> list[Shift]:
        """
        Shifts the volunteer is already committed to that overlap ``starts_at``-``ends_at``.

        Two intervals overlap when each starts before the other ends; shifts that
        merely touch (one ends at 12:00, the next starts at 12:00) do not conflict.
        """
        rows = self._db.query_all(
            """
            SELECT s.shift_id, s.opportunity_id, s.starts_at, s.ends_at, s.capacity, s.notes
            FROM assignments AS a
            JOIN shifts AS s ON s.shift_id = a.shift_id
            WHERE a.volunteer_id = ?
              AND a.status <> 'CANCELLED'
              AND s.starts_at < ? AND ? < s.ends_at
              AND s.shift_id <> ?
            ORDER BY s.starts_at
            """,
            (volunteer_id, datetime_to_db(ends_at), datetime_to_db(starts_at), exclude_shift_id or 0),
        )
        return [
            Shift(
                opportunity_id=row["opportunity_id"],
                starts_at=datetime_from_db(row["starts_at"]),
                ends_at=datetime_from_db(row["ends_at"]),
                capacity=row["capacity"],
                notes=row["notes"],
                shift_id=row["shift_id"],
            )
            for row in rows
        ]

    def total_hours(
        self,
        *,
        volunteer_id: int | None = None,
        start: date | None = None,
        end: date | None = None,
    ) -> float:
        """Attended hours, optionally for one volunteer and/or an inclusive date range."""
        clauses = ["a.status = 'ATTENDED'"]
        params: list[Any] = []
        if volunteer_id is not None:
            clauses.append("a.volunteer_id = ?")
            params.append(volunteer_id)
        if start is not None:
            clauses.append("substr(s.starts_at, 1, 10) >= ?")
            params.append(date_to_db(start))
        if end is not None:
            clauses.append("substr(s.starts_at, 1, 10) <= ?")
            params.append(date_to_db(end))
        total = self._db.query_value(
            f"""
            SELECT ROUND(SUM(a.hours_served), 2)
            FROM assignments AS a JOIN shifts AS s ON s.shift_id = a.shift_id
            WHERE {" AND ".join(clauses)}
            """,
            params,
            default=0.0,
        )
        return float(total)

    def count_by_status(self) -> dict[AssignmentStatus, int]:
        counts = dict.fromkeys(AssignmentStatus, 0)
        for row in self._db.query_all("SELECT status, COUNT(*) AS total FROM assignments GROUP BY status"):
            counts[AssignmentStatus(row["status"])] = row["total"]
        return counts

    # ------------------------------------------- bulk queries for services
    # Smart Match scores every volunteer at once; these grouped queries give it
    # all the facts it needs in a handful of round trips instead of one query
    # per volunteer.

    def upcoming_scheduled(
        self,
        *,
        after: datetime,
        volunteer_id: int | None = None,
        opportunity_id: int | None = None,
    ) -> list[Assignment]:
        """SCHEDULED sign-ups for shifts starting after ``after`` (optionally filtered)."""
        clauses = ["a.status = 'SCHEDULED'", "s.starts_at > ?"]
        params: list[Any] = [datetime_to_db(after)]
        if volunteer_id is not None:
            clauses.append("a.volunteer_id = ?")
            params.append(volunteer_id)
        if opportunity_id is not None:
            clauses.append("s.opportunity_id = ?")
            params.append(opportunity_id)
        rows = self._db.query_all(
            f"""
            SELECT {_ASSIGNMENT_COLUMNS}
            FROM assignments AS a JOIN shifts AS s ON s.shift_id = a.shift_id
            WHERE {" AND ".join(clauses)}
            ORDER BY s.starts_at
            """,
            params,
        )
        return [self._to_assignment(row) for row in rows]

    def volunteer_ids_on_shift(self, shift_id: int) -> set[int]:
        """Volunteers currently holding a spot on a shift (cancellations excluded)."""
        rows = self._db.query_all(
            "SELECT volunteer_id FROM assignments WHERE shift_id = ? AND status <> 'CANCELLED'", (shift_id,)
        )
        return {row["volunteer_id"] for row in rows}

    def busy_volunteer_ids(
        self, starts_at: datetime, ends_at: datetime, *, exclude_shift_id: int | None = None
    ) -> set[int]:
        """Volunteers already committed to a different shift that overlaps the interval."""
        rows = self._db.query_all(
            """
            SELECT DISTINCT a.volunteer_id
            FROM assignments AS a JOIN shifts AS s ON s.shift_id = a.shift_id
            WHERE a.status <> 'CANCELLED'
              AND s.starts_at < ? AND ? < s.ends_at
              AND s.shift_id <> ?
            """,
            (datetime_to_db(ends_at), datetime_to_db(starts_at), exclude_shift_id or 0),
        )
        return {row["volunteer_id"] for row in rows}

    def hours_by_volunteer(self, *, start: date, end: date) -> dict[int, float]:
        """Attended hours per volunteer for shifts dated within ``start``..``end`` (inclusive)."""
        rows = self._db.query_all(
            """
            SELECT a.volunteer_id, ROUND(SUM(a.hours_served), 2) AS hours
            FROM assignments AS a JOIN shifts AS s ON s.shift_id = a.shift_id
            WHERE a.status = 'ATTENDED' AND substr(s.starts_at, 1, 10) BETWEEN ? AND ?
            GROUP BY a.volunteer_id
            """,
            (date_to_db(start), date_to_db(end)),
        )
        return {row["volunteer_id"]: float(row["hours"]) for row in rows}

    def attended_count_by_volunteer(self, opportunity_id: int) -> dict[int, int]:
        """How many times each volunteer has served one opportunity."""
        rows = self._db.query_all(
            """
            SELECT a.volunteer_id, COUNT(*) AS visits
            FROM assignments AS a JOIN shifts AS s ON s.shift_id = a.shift_id
            WHERE a.status = 'ATTENDED' AND s.opportunity_id = ?
            GROUP BY a.volunteer_id
            """,
            (opportunity_id,),
        )
        return {row["volunteer_id"]: row["visits"] for row in rows}

    def attended_count_by_opportunity(self, volunteer_id: int) -> dict[int, int]:
        """How many times one volunteer has served each opportunity."""
        rows = self._db.query_all(
            """
            SELECT s.opportunity_id, COUNT(*) AS visits
            FROM assignments AS a JOIN shifts AS s ON s.shift_id = a.shift_id
            WHERE a.status = 'ATTENDED' AND a.volunteer_id = ?
            GROUP BY s.opportunity_id
            """,
            (volunteer_id,),
        )
        return {row["opportunity_id"]: row["visits"] for row in rows}

    def recent_activity(self, *, now: datetime, limit: int = 10) -> list[ActivityItem]:
        """
        Newest events first: sign-ups, completed service, and new applications.

        The feed is derived from existing records with one UNION query, so it is
        always accurate and needs no separate log table to keep in sync.
        """
        stamp = datetime_to_db(now)
        rows = self._db.query_all(
            f"""
            SELECT kind, occurred_at, volunteer_name, opportunity_title, hours, shift_starts_at FROM (
                SELECT 'SIGNED_UP' AS kind, a.signed_up_at AS occurred_at,
                       {_V_NAME} AS volunteer_name,
                       o.title AS opportunity_title, NULL AS hours, s.starts_at AS shift_starts_at
                FROM assignments AS a
                JOIN volunteers    AS v ON v.volunteer_id = a.volunteer_id
                JOIN shifts        AS s ON s.shift_id = a.shift_id
                JOIN opportunities AS o ON o.opportunity_id = s.opportunity_id
                WHERE a.status <> 'CANCELLED' AND a.signed_up_at <= :now
                UNION ALL
                SELECT 'SERVED', s.ends_at, {_V_NAME}, o.title, a.hours_served, s.starts_at
                FROM assignments AS a
                JOIN volunteers    AS v ON v.volunteer_id = a.volunteer_id
                JOIN shifts        AS s ON s.shift_id = a.shift_id
                JOIN opportunities AS o ON o.opportunity_id = s.opportunity_id
                WHERE a.status = 'ATTENDED' AND s.ends_at <= :now
                UNION ALL
                SELECT 'APPLIED', v.joined_on || 'T09:00', {_V_NAME}, '', NULL, NULL
                FROM volunteers AS v
                WHERE v.status = 'APPLICANT' AND v.joined_on || 'T09:00' <= :now
            )
            ORDER BY occurred_at DESC
            LIMIT :limit
            """,
            {"now": stamp, "limit": max(int(limit), 0)},
        )
        return [
            ActivityItem(
                kind=ActivityKind(row["kind"]),
                occurred_at=datetime_from_db(row["occurred_at"]),
                volunteer_name=row["volunteer_name"],
                opportunity_title=row["opportunity_title"] or "",
                hours=row["hours"],
                shift_starts_at=datetime_from_db(row["shift_starts_at"]) if row["shift_starts_at"] else None,
            )
            for row in rows
        ]

    # ---------------------------------------------------------------- reports

    def service_facts(self, *, start: date, end: date) -> list[ServiceFact]:
        """
        Every sign-up for shifts dated ``start``..``end`` (inclusive), flattened
        with its shift, program, and volunteer details — one query feeds
        every report.
        """
        rows = self._db.query_all(
            f"""
            SELECT a.assignment_id, a.status, a.hours_served,
                   s.shift_id, s.starts_at, s.ends_at, s.capacity,
                   o.opportunity_id, o.title AS opportunity_title, o.category,
                   v.volunteer_id, {_V_NAME} AS volunteer_name,
                   v.status AS volunteer_status, v.recruitment_source
            FROM assignments AS a
            JOIN shifts        AS s ON s.shift_id = a.shift_id
            JOIN opportunities AS o ON o.opportunity_id = s.opportunity_id
            JOIN volunteers    AS v ON v.volunteer_id = a.volunteer_id
            WHERE substr(s.starts_at, 1, 10) BETWEEN ? AND ?
            ORDER BY s.starts_at, v.last_name COLLATE NOCASE
            """,
            (date_to_db(start), date_to_db(end)),
        )
        return [
            ServiceFact(
                assignment_id=row["assignment_id"],
                status=AssignmentStatus(row["status"]),
                hours_served=row["hours_served"],
                shift_id=row["shift_id"],
                starts_at=datetime_from_db(row["starts_at"]),
                ends_at=datetime_from_db(row["ends_at"]),
                capacity=row["capacity"],
                opportunity_id=row["opportunity_id"],
                opportunity_title=row["opportunity_title"],
                category=OpportunityCategory(row["category"]),
                volunteer_id=row["volunteer_id"],
                volunteer_name=row["volunteer_name"],
                volunteer_status=VolunteerStatus(row["volunteer_status"]),
                recruitment_source=RecruitmentSource(row["recruitment_source"]),
            )
            for row in rows
        ]

    # ---------------------------------------------------------------- helpers

    @staticmethod
    def _to_params(assignment: Assignment) -> dict[str, Any]:
        return {
            "shift_id": assignment.shift_id,
            "volunteer_id": assignment.volunteer_id,
            "status": assignment.status.value,
            "hours_served": assignment.hours_served,
            "signed_up_at": datetime_to_db(assignment.signed_up_at),
        }

    @staticmethod
    def _to_assignment(row: sqlite3.Row) -> Assignment:
        return Assignment(
            shift_id=row["shift_id"],
            volunteer_id=row["volunteer_id"],
            status=AssignmentStatus(row["status"]),
            hours_served=row["hours_served"],
            signed_up_at=datetime_from_db(row["signed_up_at"]),
            assignment_id=row["assignment_id"],
        )
