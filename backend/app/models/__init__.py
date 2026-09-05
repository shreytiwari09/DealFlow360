"""SQLAlchemy models.

Phase 2 (PLAN.md Section 7) populates this package with the full data model.
Every model module must be imported here so that Alembic autogenerate sees it
on `Base.metadata` - a model that is not imported is silently invisible to
migrations.
"""

from app.db.base import Base

__all__ = ["Base"]
