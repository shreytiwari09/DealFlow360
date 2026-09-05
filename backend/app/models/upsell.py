"""Rule-based upsell / cross-sell pairings (PRD A6, B5).

Deliberately a lookup table, not a model. PLAN.md Section 20 rules out ML
here: the PRD itself describes co-purchase pairings, and a deterministic table
is both explainable in the viva and incapable of embarrassing us live.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import ArchivableMixin, AuditMixin, Base, IdMixin

if TYPE_CHECKING:
    from app.models.catalog import Product


class UpsellRule(IdMixin, AuditMixin, ArchivableMixin, Base):
    """ "When the cart contains A, suggest B."

    Ranking inputs, in the order the panel applies them:
      1. `is_promoted` on the suggested product (PRD A6: promoted products
         rank higher)
      2. `co_purchase_score` - how often the pair sells together
      3. the live margin delta, which must clear `min_margin_percent` or the
         suggestion is suppressed entirely (PRD A6: "only healthy margin
         suggestions surface")
    """

    __tablename__ = "upsell_rules"

    trigger_product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    suggested_product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Derived from historical co-purchase data; higher ranks first.
    co_purchase_score: Mapped[Decimal] = mapped_column(
        Numeric(6, 2), nullable=False, server_default="0"
    )
    # Floor below which this suggestion is not shown at all.
    min_margin_percent: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, server_default="0"
    )

    trigger_product: Mapped[Product] = relationship(foreign_keys=[trigger_product_id])
    suggested_product: Mapped[Product] = relationship(foreign_keys=[suggested_product_id])

    __table_args__ = (
        UniqueConstraint(
            "trigger_product_id",
            "suggested_product_id",
            name="uq_upsell_rules_trigger_suggested",
        ),
        CheckConstraint(
            "trigger_product_id <> suggested_product_id",
            name="trigger_differs_from_suggested",
        ),
        CheckConstraint("co_purchase_score >= 0", name="co_purchase_score_non_negative"),
        CheckConstraint(
            "min_margin_percent >= 0 AND min_margin_percent <= 100",
            name="min_margin_percentage_range",
        ),
        # The panel looks up suggestions for the products already in the cart
        # and ranks them; this index serves that query directly.
        Index(
            "ix_upsell_rules_trigger_score",
            "trigger_product_id",
            "co_purchase_score",
        ),
    )
