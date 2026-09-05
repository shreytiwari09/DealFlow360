"""Identity, roles and permissions.

Shape mandated by SECURITY_SPEC.md Section 4:

    users -> role_id -> roles -> role_permissions -> permissions

Permission-based, not hardcoded role checks. An endpoint asks "does this user
hold `deal.approve_finance`?", never "is this user a manager?" - so adding a
role later is seed data, not a code change scattered across routers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Column, ForeignKey, Index, String, Table, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import ArchivableMixin, AuditMixin, Base, IdMixin
from app.models.enums import RoleCode, enum_column

if TYPE_CHECKING:
    from app.models.customer import Customer
    from app.models.quotation import Quotation


# Association table. A plain Table rather than a mapped class: it carries no
# attributes of its own, so there is nothing to model.
role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column(
        "role_id",
        ForeignKey("roles.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "permission_id",
        ForeignKey("permissions.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class Role(IdMixin, AuditMixin, Base):
    __tablename__ = "roles"

    code: Mapped[RoleCode] = mapped_column(
        enum_column(RoleCode, "role_code"), nullable=False, unique=True
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255))

    permissions: Mapped[list[Permission]] = relationship(
        secondary=role_permissions, back_populates="roles", lazy="selectin"
    )
    # foreign_keys is required: roles.created_by is a second FK path back
    # to users, so "which users hold this role" is otherwise ambiguous.
    users: Mapped[list[User]] = relationship(back_populates="role", foreign_keys="User.role_id")


class Permission(IdMixin, AuditMixin, Base):
    """A single capability, e.g. `deal.approve_finance`.

    Codes follow `<resource>.<action>` so they group naturally and read well
    in an authorization decision.
    """

    __tablename__ = "permissions"

    code: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(String(255))

    roles: Mapped[list[Role]] = relationship(
        secondary=role_permissions, back_populates="permissions"
    )


class SalesTeam(IdMixin, AuditMixin, ArchivableMixin, Base):
    """PRD A7 requires reporting to be filterable by "Sales Team / Rep"."""

    __tablename__ = "sales_teams"

    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    # RESTRICT, not CASCADE: deleting a user must never silently delete a team.
    manager_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT", use_alter=True), index=True
    )

    manager: Mapped[User | None] = relationship(
        foreign_keys=[manager_id], back_populates="managed_teams"
    )
    members: Mapped[list[User]] = relationship(
        back_populates="sales_team", foreign_keys="User.sales_team_id"
    )


class User(IdMixin, AuditMixin, ArchivableMixin, Base):
    """An internal user or a customer portal user.

    Portal users are ordinary rows with `role.code == "customer"` and a
    populated `customer_id`. Keeping them in one table means authentication
    has exactly one code path - SECURITY_SPEC.md forbids duplicating auth
    logic in multiple inconsistent places.
    """

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    # Argon2/bcrypt digest, never the password. Populated in Phase 6.
    # Never exposed through a response DTO (SECURITY_SPEC.md Section 6).
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(160), nullable=False)

    role_id: Mapped[int] = mapped_column(
        ForeignKey("roles.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    sales_team_id: Mapped[int | None] = mapped_column(
        ForeignKey("sales_teams.id", ondelete="SET NULL"), index=True
    )
    # Set only for portal users; links the login to the account whose
    # quotations they may see. This is the anchor for the customer-side
    # ownership check that prevents IDOR.
    customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT", use_alter=True), index=True
    )

    role: Mapped[Role] = relationship(
        back_populates="users", foreign_keys=[role_id], lazy="selectin"
    )
    sales_team: Mapped[SalesTeam | None] = relationship(
        back_populates="members", foreign_keys=[sales_team_id]
    )
    managed_teams: Mapped[list[SalesTeam]] = relationship(
        back_populates="manager", foreign_keys="SalesTeam.manager_id"
    )
    customer: Mapped[Customer | None] = relationship(
        back_populates="portal_users", foreign_keys=[customer_id]
    )
    owned_quotations: Mapped[list[Quotation]] = relationship(
        back_populates="owner", foreign_keys="Quotation.owner_id"
    )

    __table_args__ = (
        # Email lookups happen on every login; the UNIQUE constraint already
        # provides the index, so no second one is added here.
        UniqueConstraint("email", name="uq_users_email"),
        Index("ix_users_role_id_is_active", "role_id", "is_active"),
    )

    # NOTE - the invariant "role is customer  <=>  customer_id is set" cannot
    # be a CHECK constraint: PostgreSQL CHECK cannot read another table, and
    # the role code lives in `roles`. Enforcing it would require either
    # denormalising the role code onto `users` (which then drifts) or a
    # trigger (heavier than it is worth here). It is enforced in the service
    # layer instead, and this comment exists so the next reader knows the
    # omission was considered rather than overlooked.
