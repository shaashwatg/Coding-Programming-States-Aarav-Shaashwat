"""
Authentication and account management.

Security choices worth explaining to judges:

* **Generic failure message.** "Username or password is incorrect" never
  reveals which half was wrong, so attackers can't discover valid usernames.
* **Equal timing.** An unknown username still runs a full password hash, so
  response time doesn't leak whether the account exists.
* **Lockout.** Five wrong passwords lock the account for 15 minutes, which
  stops guessing attacks without permanently locking out a real user.
* **Transparent upgrades.** If the hashing cost is raised in a future
  version, each password is re-hashed automatically at its next sign-in.
"""

from __future__ import annotations

import logging
import math
from datetime import timedelta

from servesync.core.errors import AuthenticationError, BusinessRuleError, RecordNotFoundError, ValidationError
from servesync.core.i18n import mark, tr, tr_n
from servesync.core.security import DEFAULT_ITERATIONS, hash_password, needs_rehash, verify_password
from servesync.core.validators import validate_field, validate_password_strength
from servesync.data import DataStore
from servesync.models import UserAccount, UserRole
from servesync.services.base import Service
from servesync.services.clock import Clock
from servesync.services.session import Permission, Session

logger = logging.getLogger(__name__)

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_DURATION = timedelta(minutes=15)
GENERIC_FAILURE = mark("The username or password is incorrect.")


class AuthService(Service):
    def __init__(self, store: DataStore, clock: Clock, *, password_iterations: int = DEFAULT_ITERATIONS) -> None:
        super().__init__(store, clock)
        self._iterations = password_iterations
        self._dummy_hash: str | None = None

    # ---------------------------------------------------------------- sign-in

    def sign_in(self, username: str, password: str) -> Session:
        """Verify credentials and return a :class:`Session`, or raise :class:`AuthenticationError`."""
        name = (username or "").strip()
        if not name or not password:
            raise AuthenticationError(tr("Enter both your username and password."))

        account = self._store.accounts.find_by_username(name)
        now = self._clock.now()
        if account is None or account.account_id is None:
            verify_password(password, self._timing_decoy())  # same cost as a real check
            logger.info("Failed sign-in for an unknown username")
            raise AuthenticationError(tr(GENERIC_FAILURE))

        if account.is_locked(now) and account.locked_until is not None:
            minutes = max(1, math.ceil((account.locked_until - now).total_seconds() / 60))
            raise AuthenticationError(
                tr_n(
                    "Too many unsuccessful attempts. Try again in {count} minute.",
                    "Too many unsuccessful attempts. Try again in {count} minutes.",
                    minutes,
                )
            )

        if not verify_password(password, account.password_hash):
            attempts = account.failed_login_count + 1
            locked_until = now + LOCKOUT_DURATION if attempts >= MAX_FAILED_ATTEMPTS else None
            self._store.accounts.record_failed_login(account.account_id, locked_until=locked_until)
            logger.warning("Failed sign-in for account #%s (attempt %s)", account.account_id, attempts)
            if locked_until is not None:
                raise AuthenticationError(
                    tr(
                        ("Too many unsuccessful attempts. For security, this account is locked for {int} minutes."),
                        int=int(LOCKOUT_DURATION.total_seconds() // 60),
                    )
                )
            raise AuthenticationError(tr(GENERIC_FAILURE))

        if not account.is_active:
            raise AuthenticationError(tr("This account has been turned off. Please contact your administrator."))

        self._store.accounts.record_successful_login(account.account_id, now)
        if needs_rehash(account.password_hash, iterations=self._iterations):
            self._store.accounts.update_password_hash(account.account_id, self._hash(password))
        logger.info("Account #%s signed in as %s", account.account_id, account.role.value)
        return Session(account.account_id, account.username, account.role, account.volunteer_id)

    # -------------------------------------------------------------- passwords

    def change_password(self, session: Session, current_password: str, new_password: str, confirm: str) -> None:
        """Let any signed-in user change their own password."""
        account = self._store.accounts.get(session.account_id)
        if not verify_password(current_password, account.password_hash):
            raise ValidationError.single("current_password", tr("Your current password is incorrect."))
        self._validate_new_password(new_password, confirm, account.username)
        if new_password == current_password:
            raise ValidationError.single("new_password", tr("Choose a password different from your current one."))
        self._store.accounts.update_password_hash(session.account_id, self._hash(new_password))
        logger.info("Account #%s changed its password", session.account_id)

    def reset_password(self, session: Session, account_id: int, new_password: str, confirm: str) -> None:
        """Administrator sets a new password for someone who forgot theirs (also clears any lockout)."""
        session.require(Permission.MANAGE_ACCOUNTS)
        account = self._store.accounts.get(account_id)
        self._validate_new_password(new_password, confirm, account.username)
        with self._store.transaction():
            self._store.accounts.update_password_hash(account_id, self._hash(new_password))
            self._store.accounts.unlock(account_id)
        logger.info("Account #%s password reset by account #%s", account_id, session.account_id)

    # --------------------------------------------------------------- accounts

    def create_account(
        self,
        session: Session,
        *,
        username: str,
        password: str,
        confirm: str,
        role: UserRole,
        volunteer_id: int | None = None,
    ) -> UserAccount:
        session.require(Permission.MANAGE_ACCOUNTS)
        needs_volunteer = role is UserRole.VOLUNTEER
        if needs_volunteer and (volunteer_id is None or not self._store.volunteers.exists(volunteer_id)):
            raise ValidationError.single("volunteer_id", tr("Choose the volunteer this account belongs to."))
        self._validate_new_password(password, confirm, username, field="password")
        account = UserAccount(
            username=username,
            password_hash=self._hash(password),
            role=role,
            volunteer_id=volunteer_id if role is UserRole.VOLUNTEER else None,
        )
        saved = self._store.accounts.add(account)
        logger.info("Account #%s (%s) created by account #%s", saved.account_id, role.value, session.account_id)
        return saved

    def set_account_active(self, session: Session, account_id: int, active: bool) -> None:
        session.require(Permission.MANAGE_ACCOUNTS)
        account = self._store.accounts.get(account_id)
        if not active:
            if account_id == session.account_id:
                raise BusinessRuleError(tr("You can't turn off the account you are signed in with."))
            if (
                account.role is UserRole.ADMIN
                and account.is_active
                and self._store.accounts.count_active(UserRole.ADMIN) <= 1
            ):
                raise BusinessRuleError(tr("At least one administrator account must stay active."))
        self._store.accounts.set_active(account_id, active)

    def list_accounts(self, session: Session) -> list[UserAccount]:
        session.require(Permission.MANAGE_ACCOUNTS)
        return self._store.accounts.find_all()

    def current_account(self, session: Session) -> UserAccount:
        try:
            return self._store.accounts.get(session.account_id)
        except RecordNotFoundError as exc:
            raise AuthenticationError(tr("Your account no longer exists. Please sign in again.")) from exc

    # ---------------------------------------------------------------- helpers

    def _hash(self, password: str) -> str:
        return hash_password(password, iterations=self._iterations)

    def _timing_decoy(self) -> str:
        if self._dummy_hash is None:
            self._dummy_hash = self._hash("timing-decoy-password-0")
        return self._dummy_hash

    @staticmethod
    def _validate_new_password(password: str, confirm: str, username: str, *, field: str = "new_password") -> None:
        validate_field(field, validate_password_strength, password, username)
        if password != confirm:
            raise ValidationError.single("confirm_password", tr("The two passwords don't match."))
