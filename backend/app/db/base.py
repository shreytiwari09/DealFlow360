"""Declarative base and shared column mixins.

The naming convention matters: without it, Alembic autogenerate emits
unnamed CHECK/UNIQUE constraints that cannot be dropped in a later
migration. PLAN.md Section 7 requires the schema to stay migration-safe as
it evolves, so this is set once here rather than patched later.
"""

from datetime import datetime

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    """Audit columns required on every table by PLAN.md Section 7.

    `created_by` is added in Phase 2 alongside the users table, so that the
    foreign key can be declared properly rather than as a loose integer.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
