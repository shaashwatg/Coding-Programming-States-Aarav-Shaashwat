"""
DataStore — the single entry point to persistence (Facade pattern).

The service layer receives one ``DataStore`` instead of seven repositories
and a database handle. Because the store is passed in rather than created
inside each service (dependency injection), tests swap in an in-memory
database with one line and run in milliseconds.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import TracebackType

from servesync.data.database import IN_MEMORY, Database
from servesync.data.migrations import apply_migrations
from servesync.data.photo_store import PhotoStore
from servesync.data.repositories import (
    AccountRepository,
    AssignmentRepository,
    OpportunityRepository,
    PreferenceRepository,
    SettingsRepository,
    ShiftRepository,
    SkillRepository,
    VolunteerRepository,
)


class DataStore:
    """Bundles every repository around one shared, migrated database."""

    def __init__(self, db: Database, photos: PhotoStore | None = None) -> None:
        self.db = db
        self.photos = photos or PhotoStore(None)
        self.skills = SkillRepository(db)
        self.volunteers = VolunteerRepository(db, self.skills)
        self.opportunities = OpportunityRepository(db, self.skills)
        self.shifts = ShiftRepository(db)
        self.assignments = AssignmentRepository(db)
        self.accounts = AccountRepository(db)
        self.settings = SettingsRepository(db)
        self.preferences = PreferenceRepository(db)

    @classmethod
    def open(cls, path: Path | str) -> DataStore:
        """Open (creating if needed) the database file and upgrade its schema."""
        db = Database(path)
        try:
            apply_migrations(db)
        except BaseException:
            db.close()
            raise
        photo_folder = None if db.is_in_memory else Path(path).parent / "photos"
        return cls(db, PhotoStore(photo_folder))

    @classmethod
    def in_memory(cls) -> DataStore:
        """A private, empty database that disappears when closed (tests, demos)."""
        return cls.open(IN_MEMORY)

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Group several repository calls so they succeed or fail together."""
        with self.db.transaction() as connection:
            yield connection

    def is_empty(self) -> bool:
        """True when no volunteers or accounts exist (first launch)."""
        volunteers = int(self.db.query_value("SELECT COUNT(*) FROM volunteers", default=0))
        accounts = int(self.db.query_value("SELECT COUNT(*) FROM user_accounts", default=0))
        return volunteers == 0 and accounts == 0

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> DataStore:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
