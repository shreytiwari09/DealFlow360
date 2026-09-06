"""Refresh token storage.

SECURITY_SPEC.md Section 3 requires refresh-token rotation with reuse
detection. That needs server-side state: a rotated token must be recognisable
as already-used when it comes back, which is the signal that a token was
stolen.

Only a hash of the token id is stored, never the token itself — the same
reasoning as password hashes. A database leak must not hand out live sessions.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IdMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.rbac import User


class RefreshToken(IdMixin, TimestampMixin, Base):
    __tablename__ = "refresh_tokens"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # SHA-256 of the token's jti. Unique so a replayed jti collides loudly.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Set when this token is rotated away or logged out. A token presented
    # after this is set is a REUSE: the whole family gets revoked, because
    # either the legitimate client or an attacker is replaying, and we cannot
    # tell which.
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replaced_by_hash: Mapped[str | None] = mapped_column(String(64))

    user: Mapped[User] = relationship()

    __table_args__ = (Index("ix_refresh_tokens_user_id_revoked_at", "user_id", "revoked_at"),)

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None


class UserInvitation(IdMixin, TimestampMixin, Base):
    """A one-time activation link for an Admin-provisioned account.

    Real ERPs (Salesforce Experience Cloud, SAP Ariba, NetSuite Customer
    Center, Odoo Portal Users) never let a customer self-register a portal
    login — there is no safe way for a stranger to self-select which
    `customer_id` they represent, and that is the exact IDOR risk
    `Locked Business Rules #5` in PROJECT_CONTEXT.md was written to rule out.
    Instead an Admin creates the account, and the account's first owner sets
    its own password out of an activation link — same shape as a password
    reset, and the same reason: nobody but the account holder ever handles
    the plaintext password, including the Admin who created the row.

    Only a hash of the token is stored, for the same reason as
    `RefreshToken.token_hash`: a database leak must not itself be a set of
    usable activation links.
    """

    __tablename__ = "user_invitations"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # SHA-256 of the raw token handed to the invitee. Unique so a collision
    # (astronomically unlikely for a 32-byte random token) fails loudly
    # rather than silently activating the wrong row.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    # Nullable/RESTRICT: who sent the invite is audit-relevant context, not a
    # dependency the invitation's own validity should hinge on.
    invited_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT", use_alter=True), index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(foreign_keys=[user_id])
    invited_by: Mapped[User | None] = relationship(foreign_keys=[invited_by_id])

    __table_args__ = (Index("ix_user_invitations_user_id_accepted_at", "user_id", "accepted_at"),)
