"""
Versioned database schema ("migrations").

The schema version is stored in SQLite's built-in ``PRAGMA user_version``.
On start-up, every migration newer than the file's version runs once, inside
a transaction, in order. Shipping version 1.1 of ServeSync with a new column
therefore upgrades an organization's existing data file instead of deleting
it — the same technique professional frameworks (Django, Rails, Flyway) use.

Rule: a released migration is never edited. Changes go in a *new* migration,
which is why the CHECK lists below are literal snapshots rather than being
generated from the Python enums. ``tests/test_database.py`` verifies the two
stay in sync.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass

from servesync.config import DEFAULT_VOLUNTEER_HOUR_VALUE
from servesync.core.errors import DataStoreError
from servesync.data.database import Database, translate_sqlite_errors

logger = logging.getLogger(__name__)

_NOW = "(strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime'))"


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    description: str
    sql: str


_V1_INITIAL_SCHEMA = f"""
-- ---------------------------------------------------------------- settings
CREATE TABLE app_settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
) WITHOUT ROWID;

INSERT INTO app_settings (key, value) VALUES
    ('organization_name',    'My Nonprofit'),
    ('volunteer_hour_value', '{DEFAULT_VOLUNTEER_HOUR_VALUE:.2f}'),
    ('ui_font_scale',        '1.0'),
    ('ui_theme',             'LIGHT');

-- ------------------------------------------------------------------ skills
CREATE TABLE skills (
    skill_id INTEGER PRIMARY KEY,
    name     TEXT NOT NULL COLLATE NOCASE UNIQUE
             CHECK (length(name) BETWEEN 1 AND 40)
);

-- -------------------------------------------------------------- volunteers
CREATE TABLE volunteers (
    volunteer_id            INTEGER PRIMARY KEY,
    first_name              TEXT NOT NULL CHECK (length(first_name) BETWEEN 1 AND 50),
    last_name               TEXT NOT NULL CHECK (length(last_name) BETWEEN 1 AND 50),
    email                   TEXT NOT NULL COLLATE NOCASE UNIQUE,
    phone                   TEXT NOT NULL CHECK (length(phone) = 10),
    birth_date              TEXT NOT NULL,
    joined_on               TEXT NOT NULL,
    status                  TEXT NOT NULL
                            CHECK (status IN ('APPLICANT', 'ACTIVE', 'INACTIVE')),
    recruitment_source      TEXT NOT NULL
                            CHECK (recruitment_source IN ('WEBSITE', 'REFERRAL', 'SOCIAL_MEDIA',
                                   'SCHOOL', 'COMMUNITY_EVENT', 'PARTNER_ORG', 'OTHER')),
    emergency_contact_name  TEXT NOT NULL DEFAULT '',
    emergency_contact_phone TEXT NOT NULL DEFAULT ''
                            CHECK (emergency_contact_phone = '' OR length(emergency_contact_phone) = 10),
    notes                   TEXT NOT NULL DEFAULT '',
    created_at              TEXT NOT NULL DEFAULT {_NOW},
    updated_at              TEXT NOT NULL DEFAULT {_NOW}
);
CREATE INDEX idx_volunteers_status ON volunteers (status);
CREATE INDEX idx_volunteers_name   ON volunteers (last_name COLLATE NOCASE, first_name COLLATE NOCASE);

CREATE TABLE volunteer_skills (
    volunteer_id INTEGER NOT NULL REFERENCES volunteers (volunteer_id) ON DELETE CASCADE,
    skill_id     INTEGER NOT NULL REFERENCES skills (skill_id) ON DELETE CASCADE,
    PRIMARY KEY (volunteer_id, skill_id)
) WITHOUT ROWID;
CREATE INDEX idx_volunteer_skills_skill ON volunteer_skills (skill_id);

CREATE TABLE volunteer_availability (
    volunteer_id INTEGER NOT NULL REFERENCES volunteers (volunteer_id) ON DELETE CASCADE,
    weekday      INTEGER NOT NULL CHECK (weekday BETWEEN 0 AND 6),
    day_part     TEXT NOT NULL CHECK (day_part IN ('MORNING', 'AFTERNOON', 'EVENING')),
    PRIMARY KEY (volunteer_id, weekday, day_part)
) WITHOUT ROWID;
CREATE INDEX idx_availability_slot ON volunteer_availability (weekday, day_part);

-- ----------------------------------------------------------- opportunities
CREATE TABLE opportunities (
    opportunity_id   INTEGER PRIMARY KEY,
    title            TEXT NOT NULL CHECK (length(title) BETWEEN 3 AND 80),
    description      TEXT NOT NULL CHECK (length(description) BETWEEN 1 AND 1000),
    category         TEXT NOT NULL
                     CHECK (category IN ('FOOD_SECURITY', 'EDUCATION', 'ENVIRONMENT', 'HEALTH',
                            'ANIMAL_WELFARE', 'HOUSING', 'COMMUNITY_EVENTS', 'ADMINISTRATIVE')),
    location         TEXT NOT NULL CHECK (length(location) BETWEEN 1 AND 120),
    coordinator_name TEXT NOT NULL CHECK (length(coordinator_name) BETWEEN 1 AND 80),
    min_age          INTEGER NOT NULL CHECK (min_age BETWEEN 14 AND 99),
    status           TEXT NOT NULL CHECK (status IN ('DRAFT', 'OPEN', 'CLOSED')),
    created_at       TEXT NOT NULL DEFAULT {_NOW},
    updated_at       TEXT NOT NULL DEFAULT {_NOW}
);
CREATE INDEX idx_opportunities_status ON opportunities (status);

CREATE TABLE opportunity_skills (
    opportunity_id INTEGER NOT NULL REFERENCES opportunities (opportunity_id) ON DELETE CASCADE,
    skill_id       INTEGER NOT NULL REFERENCES skills (skill_id) ON DELETE CASCADE,
    PRIMARY KEY (opportunity_id, skill_id)
) WITHOUT ROWID;

-- ------------------------------------------------------------------ shifts
CREATE TABLE shifts (
    shift_id       INTEGER PRIMARY KEY,
    opportunity_id INTEGER NOT NULL REFERENCES opportunities (opportunity_id) ON DELETE CASCADE,
    starts_at      TEXT NOT NULL,
    ends_at        TEXT NOT NULL,
    capacity       INTEGER NOT NULL CHECK (capacity BETWEEN 1 AND 500),
    notes          TEXT NOT NULL DEFAULT '',
    created_at     TEXT NOT NULL DEFAULT {_NOW},
    updated_at     TEXT NOT NULL DEFAULT {_NOW},
    CHECK (ends_at > starts_at)
);
CREATE INDEX idx_shifts_opportunity ON shifts (opportunity_id);
CREATE INDEX idx_shifts_starts_at   ON shifts (starts_at);

-- ------------------------------------------------------------- assignments
-- ON DELETE RESTRICT: service history can never be erased by deleting a
-- shift or a volunteer. Leaders archive (Inactive / Closed) instead.
CREATE TABLE assignments (
    assignment_id INTEGER PRIMARY KEY,
    shift_id      INTEGER NOT NULL REFERENCES shifts (shift_id) ON DELETE RESTRICT,
    volunteer_id  INTEGER NOT NULL REFERENCES volunteers (volunteer_id) ON DELETE RESTRICT,
    status        TEXT NOT NULL
                  CHECK (status IN ('SCHEDULED', 'ATTENDED', 'NO_SHOW', 'CANCELLED')),
    hours_served  REAL CHECK (hours_served IS NULL OR (hours_served > 0 AND hours_served <= 12)),
    signed_up_at  TEXT NOT NULL,
    updated_at    TEXT NOT NULL DEFAULT {_NOW},
    UNIQUE (shift_id, volunteer_id),
    CHECK ((status = 'ATTENDED') = (hours_served IS NOT NULL))
);
CREATE INDEX idx_assignments_volunteer ON assignments (volunteer_id);

-- ---------------------------------------------------------------- accounts
CREATE TABLE user_accounts (
    account_id         INTEGER PRIMARY KEY,
    username           TEXT NOT NULL COLLATE NOCASE UNIQUE,
    password_hash      TEXT NOT NULL,
    role               TEXT NOT NULL CHECK (role IN ('ADMIN', 'COORDINATOR', 'VOLUNTEER')),
    volunteer_id       INTEGER UNIQUE REFERENCES volunteers (volunteer_id) ON DELETE CASCADE,
    is_active          INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    failed_login_count INTEGER NOT NULL DEFAULT 0 CHECK (failed_login_count >= 0),
    locked_until       TEXT,
    last_login_at      TEXT,
    created_at         TEXT NOT NULL DEFAULT {_NOW},
    CHECK ((role = 'VOLUNTEER') = (volunteer_id IS NOT NULL))
);

-- ------------------------------------------------------------------- views
-- Reporting views keep aggregate SQL in one tested place.
CREATE VIEW shift_fill AS
SELECT s.shift_id,
       s.capacity,
       COUNT(a.assignment_id) AS filled
FROM shifts AS s
LEFT JOIN assignments AS a
       ON a.shift_id = s.shift_id AND a.status <> 'CANCELLED'
GROUP BY s.shift_id;

CREATE VIEW volunteer_participation AS
SELECT v.volunteer_id,
       v.first_name || ' ' || v.last_name                                    AS full_name,
       v.status,
       ROUND(COALESCE(SUM(CASE WHEN a.status = 'ATTENDED' THEN a.hours_served END), 0), 2)
                                                                              AS total_hours,
       COUNT(CASE WHEN a.status = 'ATTENDED'  THEN 1 END)                    AS shifts_attended,
       COUNT(CASE WHEN a.status = 'NO_SHOW'   THEN 1 END)                    AS no_shows,
       COUNT(CASE WHEN a.status = 'CANCELLED' THEN 1 END)                    AS cancellations,
       COUNT(CASE WHEN a.status = 'SCHEDULED'
                   AND s.starts_at >= strftime('%Y-%m-%dT%H:%M', 'now', 'localtime')
                  THEN 1 END)                                                 AS upcoming_shifts,
       MAX(CASE WHEN a.status = 'ATTENDED' THEN substr(s.starts_at, 1, 10) END)
                                                                              AS last_served_on
FROM volunteers AS v
LEFT JOIN assignments AS a ON a.volunteer_id = v.volunteer_id
LEFT JOIN shifts      AS s ON s.shift_id = a.shift_id
GROUP BY v.volunteer_id;
"""

#: Ordered list of every schema change. Append new migrations; never edit old ones.
_V2_STORIES_AND_MISSION = """
-- Version 2: programs can link a story video, and the organization records
-- its mission statement for the home screen.
ALTER TABLE opportunities ADD COLUMN story_video_url TEXT NOT NULL DEFAULT ''
    CHECK (story_video_url = '' OR story_video_url LIKE 'http%');

INSERT INTO app_settings (key, value) VALUES ('mission_statement', '')
    ON CONFLICT (key) DO NOTHING;
"""

_ACCESS_CODES = "'STEP_FREE', 'SEATED', 'TRANSIT', 'QUIET', 'NO_COST', 'REMOTE'"

_V3_INCLUSION = f"""
-- The name a volunteer goes by, and pronouns they choose to share (both optional).
ALTER TABLE volunteers ADD COLUMN preferred_name TEXT NOT NULL DEFAULT ''
    CHECK (length(preferred_name) <= 50);
ALTER TABLE volunteers ADD COLUMN pronouns TEXT NOT NULL DEFAULT ''
    CHECK (length(pronouns) <= 30);

-- What a volunteer needs, and what a program offers, share one vocabulary.
CREATE TABLE volunteer_access_needs (
    volunteer_id INTEGER NOT NULL REFERENCES volunteers (volunteer_id) ON DELETE CASCADE,
    need         TEXT NOT NULL CHECK (need IN ({_ACCESS_CODES})),
    PRIMARY KEY (volunteer_id, need)
) WITHOUT ROWID;

CREATE TABLE opportunity_access_features (
    opportunity_id INTEGER NOT NULL REFERENCES opportunities (opportunity_id) ON DELETE CASCADE,
    feature        TEXT NOT NULL CHECK (feature IN ({_ACCESS_CODES})),
    PRIMARY KEY (opportunity_id, feature)
) WITHOUT ROWID;

-- Comfort settings follow the person (account), not the computer.
CREATE TABLE account_preferences (
    account_id INTEGER NOT NULL REFERENCES user_accounts (account_id) ON DELETE CASCADE,
    key        TEXT NOT NULL CHECK (length(key) BETWEEN 1 AND 40),
    value      TEXT NOT NULL CHECK (length(value) <= 40),
    PRIMARY KEY (account_id, key)
) WITHOUT ROWID;

-- Totals now show the name people go by.
DROP VIEW volunteer_participation;
CREATE VIEW volunteer_participation AS
SELECT v.volunteer_id,
       COALESCE(NULLIF(v.preferred_name, ''), v.first_name) || ' ' || v.last_name AS full_name,
       v.status,
       ROUND(COALESCE(SUM(CASE WHEN a.status = 'ATTENDED' THEN a.hours_served END), 0), 2)
                                                                              AS total_hours,
       COUNT(CASE WHEN a.status = 'ATTENDED'  THEN 1 END)                    AS shifts_attended,
       COUNT(CASE WHEN a.status = 'NO_SHOW'   THEN 1 END)                    AS no_shows,
       COUNT(CASE WHEN a.status = 'CANCELLED' THEN 1 END)                    AS cancellations,
       COUNT(CASE WHEN a.status = 'SCHEDULED'
                   AND s.starts_at >= strftime('%Y-%m-%dT%H:%M', 'now', 'localtime')
                  THEN 1 END)                                                 AS upcoming_shifts,
       MAX(CASE WHEN a.status = 'ATTENDED' THEN substr(s.starts_at, 1, 10) END)
                                                                              AS last_served_on
FROM volunteers AS v
LEFT JOIN assignments AS a ON a.volunteer_id = v.volunteer_id
LEFT JOIN shifts      AS s ON s.shift_id = a.shift_id
GROUP BY v.volunteer_id;
"""

MIGRATIONS: tuple[Migration, ...] = (
    Migration(1, "Initial schema", _V1_INITIAL_SCHEMA),
    Migration(2, "Program story videos and mission statement", _V2_STORIES_AND_MISSION),
    Migration(3, "Preferred names, pronouns, access needs, and per-person preferences", _V3_INCLUSION),
)

LATEST_VERSION: int = MIGRATIONS[-1].version


def current_version(db: Database) -> int:
    return int(db.query_value("PRAGMA user_version", default=0))


def apply_migrations(db: Database) -> list[int]:
    """
    Bring the database up to :data:`LATEST_VERSION`.

    Returns the versions applied (empty if already current). Refuses to open a
    file created by a *newer* ServeSync, which protects that data from damage.
    """
    if db.in_transaction:
        raise RuntimeError("apply_migrations() must not run inside a transaction.")

    version = current_version(db)
    if version > LATEST_VERSION:
        raise DataStoreError(
            "This data file was created by a newer version of ServeSync. Please update the app to open it."
        )

    connection = db.connect()
    applied: list[int] = []
    for migration in MIGRATIONS:
        if migration.version <= version:
            continue
        # The version bump lives inside the same transaction as the schema
        # change, so a migration is either fully applied or not at all.
        script = f"BEGIN IMMEDIATE;\n{migration.sql}\nPRAGMA user_version = {migration.version};\nCOMMIT;"
        try:
            with translate_sqlite_errors():
                connection.executescript(script)
        except DataStoreError as exc:
            if connection.in_transaction:
                try:
                    connection.execute("ROLLBACK")
                except sqlite3.Error:  # pragma: no cover
                    logger.exception("Rollback after failed migration also failed")
            raise DataStoreError(
                f"Could not upgrade the data file (step {migration.version}: {migration.description})."
            ) from exc
        logger.info("Applied migration %d: %s", migration.version, migration.description)
        applied.append(migration.version)
    return applied
