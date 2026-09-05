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
