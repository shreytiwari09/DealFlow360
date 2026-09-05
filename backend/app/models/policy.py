"""Discount governance: ceilings and approval routing (PRD A3).

These two tables are what make discount discipline *configuration* rather than
code. PROJECT_CONTEXT.md "Locked Business Rules" is authoritative for the
semantics; this module is its schema.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import ArchivableMixin, AuditMixin, Base, IdMixin
from app.models.enums import CustomerTier, enum_column

if TYPE_CHECKING:
    from app.models.catalog import ProductCategory
    from app.models.rbac import Role


class DiscountTier(IdMixin, AuditMixin, ArchivableMixin, Base):
    """The discount ceiling lookup: (customer tier x product category) -> max %.

    This is `ceiling_i` in the blended risk score. PRD A3 gives both halves:
    "discount ceilings per customer tier (Bronze up to 5 percent, Silver up to
    10 percent, Gold up to 15 percent)" and "category specific discount
    ceilings (some product categories allow higher discretion than others)".

    The composite UNIQUE is the important constraint - exactly one ceiling may
    exist per (tier, category) pair, otherwise the score is ambiguous.
    """

    __tablename__ = "discount_tiers"

    customer_tier: Mapped[CustomerTier] = mapped_column(
        enum_column(CustomerTier, "discount_tier_customer_tier"), nullable=False
    )
    category_id: Mapped[int] = mapped_column(
        ForeignKey("product_categories.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    max_discount_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)

    category: Mapped[ProductCategory] = relationship(back_populates="discount_tiers")

    __table_args__ = (
        UniqueConstraint("customer_tier", "category_id", name="uq_discount_tiers_tier_category"),
        CheckConstraint(
            "max_discount_percent >= 0 AND max_discount_percent <= 100",
            name="max_discount_percentage_range",
        ),
    )


class ApprovalChain(IdMixin, AuditMixin, ArchivableMixin, Base):
    """One step of the approval routing policy, as configurable data.

    PRD A3 asks for exactly this: "Configure approval chain: which discount
    range needs Sales Manager only, and which range needs Sales Manager
    followed by Finance". Keeping the boundaries in rows rather than constants
    is a locked decision - see PROJECT_CONTEXT.md Locked Business Rules #2.
    Do not reintroduce these numbers into application code.

    A band is half-open: `min_score <= score < max_score`, with a NULL
    `max_score` meaning unbounded. Seeded as:

        [ 0.01, 25.00 )  -> sales_manager  step 1
        [25.00,  NULL )  -> sales_manager  step 1
        [25.00,  NULL )  -> finance_ops    step 2

    A score of exactly 0 matches no band, which is how "no approval required"
    is expressed. The 0.01 floor is not arbitrary: scores are NUMERIC(6,2), so
    0.01 is the smallest representable non-zero score.

    The separate single-line Finance gate (`max(line_excess) > 15`) is NOT
    modelled here. It is a guard rail rather than a PRD-mandated configurable,
    and lives as one named constant in the risk engine so it stays auditable
    in a single place.
    """

    __tablename__ = "approval_chains"

    min_score: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    max_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    required_role_id: Mapped[int] = mapped_column(
        ForeignKey("roles.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    step_order: Mapped[int] = mapped_column(nullable=False)
    label: Mapped[str | None] = mapped_column(String(120))

    required_role: Mapped[Role] = relationship(lazy="selectin")

    __table_args__ = (
        UniqueConstraint("min_score", "step_order", name="uq_approval_chains_min_score_step"),
        CheckConstraint("max_score IS NULL OR max_score > min_score", name="score_band_ordered"),
        CheckConstraint("min_score >= 0", name="min_score_non_negative"),
        CheckConstraint("step_order >= 1", name="step_order_positive"),
        # The routing lookup filters on the band and orders by step.
        Index("ix_approval_chains_min_score_max_score", "min_score", "max_score"),
    )
