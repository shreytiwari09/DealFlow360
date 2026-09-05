"""Signup tests (PRD A1, Locked Business Rules #5).

`authenticate()`/`rotate_refresh_token()` were previously covered only by the
live-API verification scripts, not pytest — `signup()` gets real DB-level
tests here because it has genuine logic worth locking down: it must always
land on Sales Rep regardless of who's asking, it must never store the
plaintext password, and a duplicate email must be rejected without ever
touching argon2 twice for the same slot.
"""

import inspect
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tokens import decode_token
from app.models import Role
from app.models.enums import RoleCode
from app.services.auth import SignupError, signup

NOW = datetime.now(UTC)


@pytest.fixture
async def sales_rep_role(db_session: AsyncSession) -> Role:
    existing = (
        await db_session.execute(select(Role).where(Role.code == RoleCode.SALES_REP))
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    role = Role(code=RoleCode.SALES_REP, name="Sales Rep")
    db_session.add(role)
    await db_session.flush()
    return role


async def test_signup_creates_a_sales_rep(db_session: AsyncSession, sales_rep_role: Role) -> None:
    user, _ = await signup(
        db_session,
        email=f"newrep-{NOW.timestamp()}@example.test",
        password="a-real-password",
        full_name="New Rep",
    )

    assert user.role_id == sales_rep_role.id
    assert user.customer_id is None  # signup can never create a portal account


async def test_signup_hashes_the_password_not_stores_it_plaintext(
    db_session: AsyncSession, sales_rep_role: Role
) -> None:
    user, _ = await signup(
        db_session,
        email=f"hashcheck-{NOW.timestamp()}@example.test",
        password="a-real-password",
        full_name="Hash Check",
    )

    assert user.password_hash != "a-real-password"
    assert user.password_hash.startswith("$argon2")


async def test_signup_normalizes_email_case_and_whitespace(
    db_session: AsyncSession, sales_rep_role: Role
) -> None:
    raw = f"  MixedCase-{NOW.timestamp()}@Example.Test  "
    user, _ = await signup(db_session, email=raw, password="a-real-password", full_name="X")

    assert user.email == raw.strip().lower()


async def test_signup_issues_a_valid_token_pair(
    db_session: AsyncSession, sales_rep_role: Role
) -> None:
    user, tokens = await signup(
        db_session,
        email=f"tokencheck-{NOW.timestamp()}@example.test",
        password="a-real-password",
        full_name="Token Check",
    )

    access_claims = decode_token(tokens.access_token, expect="access")
    refresh_claims = decode_token(tokens.refresh_token, expect="refresh")
    assert access_claims.user_id == user.id
    assert refresh_claims.user_id == user.id
    assert access_claims.jti != refresh_claims.jti


async def test_duplicate_email_is_rejected(db_session: AsyncSession, sales_rep_role: Role) -> None:
    email = f"dupe-{NOW.timestamp()}@example.test"
    await signup(db_session, email=email, password="a-real-password", full_name="First")

    with pytest.raises(SignupError, match="already exists"):
        await signup(db_session, email=email, password="another-password", full_name="Second")


async def test_duplicate_email_is_rejected_case_insensitively(
    db_session: AsyncSession, sales_rep_role: Role
) -> None:
    base = f"CaseDupe-{NOW.timestamp()}@Example.Test"
    await signup(db_session, email=base, password="a-real-password", full_name="First")

    with pytest.raises(SignupError, match="already exists"):
        await signup(
            db_session, email=base.lower(), password="another-password", full_name="Second"
        )


async def test_signup_ignores_any_extra_fields_a_crafted_payload_might_carry(
    db_session: AsyncSession, sales_rep_role: Role
) -> None:
    """There is no `role`/`customer_id` PARAMETER on `signup()` at all - this
    test exists to document that the mass-assignment defense is structural
    (SignupRequest the schema has no such field to begin with), not merely
    "signup() happens to ignore it today"."""
    parameters = set(inspect.signature(signup).parameters)
    assert "role" not in parameters
    assert "role_id" not in parameters
    assert "customer_id" not in parameters
