"""Customer master data."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import ArchivableMixin, AuditMixin, Base, IdMixin
from app.models.enums import CustomerTier, enum_column

if TYPE_CHECKING:
    from app.models.quotation import Quotation
    from app.models.rbac import User


class Customer(IdMixin, AuditMixin, ArchivableMixin, Base):
    """A buying account.

    `tier` is the left-hand key of the discount ceiling lookup
    (tier x product category -> max discount %), so it is central to the
    blended risk score, not merely descriptive.
    """

    __tablename__ = "customers"

    code: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    tier: Mapped[CustomerTier] = mapped_column(
        enum_column(CustomerTier, "customer_tier"),
        nullable=False,
        index=True,
    )

    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(40))
    billing_address: Mapped[str | None] = mapped_column(String(500))
    # ISO 4217. Multi-currency is 🟢 Bonus scope per PLAN.md Section 18, but
    # carrying the code from the start costs nothing and avoids a painful
    # retrofit if the bonus is attempted.
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="INR")

    quotations: Mapped[list[Quotation]] = relationship(back_populates="customer")
    portal_users: Mapped[list[User]] = relationship(
        back_populates="customer", foreign_keys="User.customer_id"
    )
