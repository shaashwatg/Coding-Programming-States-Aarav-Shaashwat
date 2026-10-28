"""
Data layer: SQLite persistence behind the Repository and Facade patterns.

Typical use::

    from servesync.data import DataStore
    store = DataStore.open(paths.database_file)
    active = store.volunteers.find_all(status=VolunteerStatus.ACTIVE)
"""

from servesync.data.database import Database
from servesync.data.migrations import LATEST_VERSION, apply_migrations
from servesync.data.store import DataStore

__all__ = ["LATEST_VERSION", "DataStore", "Database", "apply_migrations"]
