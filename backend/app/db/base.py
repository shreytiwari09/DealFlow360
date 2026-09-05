"""Declarative base and shared column mixins.

The naming convention matters: without it, Alembic autogenerate emits
unnamed CHECK/UNIQUE constraints that cannot be dropped in a later
migration. PLAN.md Section 7 requires the schema to stay migration-safe as
it evolves, so this is set once here rather than patched later.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class IdMixin:
    """Surrogate integer primary key.

    Surrogate rather than natural keys throughout: business identifiers like
    SKU and quote number do change in practice, and a changing primary key
    propagates into every referencing row. Those identifiers still get UNIQUE
    constraints where they must be unique.
    """

    id: Mapped[int] = mapped_column(primary_key=True)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class AuditMixin(TimestampMixin):
    """The `created_at` / `updated_at` / `created_by` trio PLAN.md Section 7
    requires on every table.

    Two details that are easy to get wrong:

    * `declared_attr` is mandatory. A plain `mapped_column` on a mixin would
      be a single Column object shared by every subclass, which SQLAlchemy
      rejects.

    * `use_alter=True` breaks foreign-key cycles. `users.role_id` points at
      `roles`, and `roles.created_by` points back at `users`; likewise
      `users.customer_id` and `customers.created_by`. Without `use_alter`,
      SQLAlchemy cannot order the CREATE TABLE statements and raises
      "Can't sort tables; there are unresolvable cycles". With it, the
      constraint is added by a follow-up ALTER TABLE instead.

    Nullable on purpose: seed and system-generated rows have no creating user.
    RESTRICT on delete, because losing the author of a record would defeat the
    point of having an audit column.
    """

    @declared_attr
    def created_by(cls) -> Mapped[int | None]:  # noqa: N805
        return mapped_column(
            ForeignKey("users.id", ondelete="RESTRICT", use_alter=True),
            nullable=True,
            index=True,
        )


class ArchivableMixin:
    """Soft-delete / archival for master data.

    PLAN.md Section 7: products and customers are archived, never hard
    deleted. A hard delete would orphan historical quotations that reference
    the row, and an ERP must be able to reprint a two-year-old order.
    """

    is_active: Mapped[bool] = mapped_column(nullable=False, server_default="true", index=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
