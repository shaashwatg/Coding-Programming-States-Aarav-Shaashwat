"""Authentication: sign-in, lockout, password changes, and account administration."""

from __future__ import annotations

from datetime import timedelta

import pytest

from servesync.core.errors import AuthenticationError, BusinessRuleError, PermissionDeniedError, ValidationError
from servesync.core.security import hash_password
from servesync.data import DataStore
from servesync.models import UserAccount, UserRole
from servesync.services import FixedClock, Services, Session
from servesync.services.auth_service import GENERIC_FAILURE, LOCKOUT_DURATION, MAX_FAILED_ATTEMPTS
from tests.conftest import NOW, World
from tests.factories import COORDINATOR, FAST_ITERATIONS, fast_hash

PASSWORD = "Riverbend2026"


@pytest.fixture
def admin(store: DataStore) -> UserAccount:
    return store.accounts.add(UserAccount("boss", fast_hash(PASSWORD), UserRole.ADMIN))


def _session(services: Services, username: str = "boss", password: str = PASSWORD) -> Session:
    return services.auth.sign_in(username, password)


# ------------------------------------------------------------------ sign-in


def test_sign_in_returns_session_and_records_login(services: Services, store: DataStore, admin: UserAccount) -> None:
    session = _session(services, "  BOSS ")
    assert (session.username, session.role, session.account_id) == ("boss", UserRole.ADMIN, admin.account_id)
    assert store.accounts.get(session.account_id).last_login_at == NOW


def test_wrong_password_and_unknown_user_look_identical(services: Services, admin: UserAccount) -> None:
    with pytest.raises(AuthenticationError) as wrong_password:
        services.auth.sign_in("boss", "nope")
    with pytest.raises(AuthenticationError) as unknown_user:
        services.auth.sign_in("ghost", "nope")
    assert str(wrong_password.value) == str(unknown_user.value) == GENERIC_FAILURE


def test_blank_fields_are_rejected(services: Services) -> None:
    with pytest.raises(AuthenticationError, match="Enter both"):
        services.auth.sign_in("", "")


def test_lockout_after_repeated_failures(services: Services, clock: FixedClock, admin: UserAccount) -> None:
    for _ in range(MAX_FAILED_ATTEMPTS - 1):
        with pytest.raises(AuthenticationError, match="incorrect"):
            services.auth.sign_in("boss", "wrong")
    with pytest.raises(AuthenticationError, match="locked for 15 minutes"):
        services.auth.sign_in("boss", "wrong")
    with pytest.raises(AuthenticationError, match="Try again in 15 minutes"):
        services.auth.sign_in("boss", PASSWORD)  # even the right password waits

    clock.advance(LOCKOUT_DURATION + timedelta(minutes=1))
    assert _session(services).username == "boss"


def test_inactive_account_cannot_sign_in(services: Services, store: DataStore, admin: UserAccount) -> None:
    store.accounts.set_active(admin.account_id or 0, False)
    with pytest.raises(AuthenticationError, match="turned off"):
        _session(services)


def test_weak_hash_is_upgraded_on_sign_in(services: Services, store: DataStore) -> None:
    old = store.accounts.add(UserAccount("old", hash_password(PASSWORD, iterations=10), UserRole.ADMIN))
    _session(services, "old")
    upgraded = store.accounts.get(old.account_id or 0).password_hash
    assert upgraded.split("$")[1] == str(FAST_ITERATIONS)


# ---------------------------------------------------------------- passwords


def test_change_password_rules(services: Services, admin: UserAccount) -> None:
    session = _session(services)
    with pytest.raises(ValidationError) as caught:
        services.auth.change_password(session, "wrong", "NewPass2026x", "NewPass2026x")
    assert "current_password" in caught.value.errors
    with pytest.raises(ValidationError) as caught:
        services.auth.change_password(session, PASSWORD, "NewPass2026x", "Different2026")
    assert "confirm_password" in caught.value.errors
    with pytest.raises(ValidationError) as caught:
        services.auth.change_password(session, PASSWORD, "short", "short")
    assert "new_password" in caught.value.errors
    with pytest.raises(ValidationError, match="different"):
        services.auth.change_password(session, PASSWORD, PASSWORD, PASSWORD)

    services.auth.change_password(session, PASSWORD, "NewPass2026x", "NewPass2026x")
    assert _session(services, password="NewPass2026x").username == "boss"


def test_reset_password_also_unlocks(services: Services, store: DataStore, admin: UserAccount) -> None:
    session = _session(services)
    coordinator = store.accounts.add(UserAccount("coord", fast_hash(PASSWORD), UserRole.COORDINATOR))
    for _ in range(MAX_FAILED_ATTEMPTS):
        with pytest.raises(AuthenticationError):
            services.auth.sign_in("coord", "wrong")
    services.auth.reset_password(session, coordinator.account_id or 0, "FreshStart2026", "FreshStart2026")
    assert services.auth.sign_in("coord", "FreshStart2026").role is UserRole.COORDINATOR


# ----------------------------------------------------------------- accounts


def test_only_admins_manage_accounts(services: Services) -> None:
    with pytest.raises(PermissionDeniedError, match="Volunteer Coordinator"):
        services.auth.list_accounts(COORDINATOR)


def test_create_volunteer_account(services: Services, admin: UserAccount, world: World) -> None:
    session = _session(services)
    with pytest.raises(ValidationError) as caught:
        services.auth.create_account(
            session, username="ana", password=PASSWORD, confirm=PASSWORD, role=UserRole.VOLUNTEER
        )
    assert "volunteer_id" in caught.value.errors

    account = services.auth.create_account(
        session,
        username="ana",
        password=PASSWORD,
        confirm=PASSWORD,
        role=UserRole.VOLUNTEER,
        volunteer_id=world.ana_id,
    )
    assert services.auth.sign_in("ana", PASSWORD).volunteer_id == world.ana_id
    assert account.role is UserRole.VOLUNTEER

    with pytest.raises(ValidationError, match="taken"):
        services.auth.create_account(
            session, username="ANA", password=PASSWORD, confirm=PASSWORD, role=UserRole.COORDINATOR
        )


def test_create_account_rejects_weak_password(services: Services, admin: UserAccount) -> None:
    with pytest.raises(ValidationError) as caught:
        services.auth.create_account(
            _session(services), username="newbie", password="abc", confirm="abc", role=UserRole.COORDINATOR
        )
    assert "password" in caught.value.errors


def test_admin_safety_rails(services: Services, store: DataStore, admin: UserAccount) -> None:
    session = _session(services)
    with pytest.raises(BusinessRuleError, match="signed in with"):
        services.auth.set_account_active(session, admin.account_id or 0, False)

    other_admin = store.accounts.add(UserAccount("deputy", fast_hash(PASSWORD), UserRole.ADMIN))
    services.auth.set_account_active(session, other_admin.account_id or 0, False)  # fine: one admin remains

    deputy_session = Session(other_admin.account_id or 0, "deputy", UserRole.ADMIN)
    with pytest.raises(BusinessRuleError, match="At least one administrator"):
        services.auth.set_account_active(deputy_session, admin.account_id or 0, False)
