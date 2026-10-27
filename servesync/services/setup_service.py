"""
First-launch setup: either create the organization's first administrator,
or load the demo organization for exploring and presenting.

Both actions are only possible while the database has no accounts, so
they can never be used to take over an organization that is already set up.
"""

from __future__ import annotations

import logging

from servesync.core.errors import BusinessRuleError, ValidationError
from servesync.core.security import hash_password
from servesync.core.validators import clean_text, validate_field, validate_password_strength
from servesync.data import DataStore
from servesync.data.seed import SeedSummary, seed_demo_data
from servesync.models import UserAccount, UserRole
from servesync.services.base import Service
from servesync.services.clock import Clock
from servesync.services.session import Session

logger = logging.getLogger(__name__)


class SetupService(Service):
    def __init__(self, store: DataStore, clock: Clock, *, password_iterations: int) -> None:
        super().__init__(store, clock)
        self._iterations = password_iterations

    def needs_setup(self) -> bool:
        """True on first launch (no sign-in accounts exist yet)."""
        return not self._store.accounts.find_all()

    def create_first_admin(self, *, organization_name: str, username: str, password: str, confirm: str) -> Session:
        if not self.needs_setup():
            raise BusinessRuleError("ServeSync is already set up. Sign in with an existing account.")
        name = validate_field("organization_name", clean_text, organization_name, "Organization name", max_length=80)
        validate_field("password", validate_password_strength, password, username.strip().lower())
        if password != confirm:
            raise ValidationError.single("confirm_password", "The two passwords don't match.")
        with self._store.transaction():
            self._store.settings.set_organization_name(name)
            account = self._store.accounts.add(
                UserAccount(
                    username=username,
                    password_hash=hash_password(password, iterations=self._iterations),
                    role=UserRole.ADMIN,
                )
            )
        logger.info("First administrator created for %s", name)
        return Session(account.account_id or 0, account.username, account.role)

    def load_demo_data(self) -> SeedSummary:
        if not self.needs_setup() or not self._store.is_empty():
            raise BusinessRuleError("Demo data can only be loaded into a brand-new database.")
        return seed_demo_data(self._store, today=self._clock.now().date(), password_iterations=self._iterations)
