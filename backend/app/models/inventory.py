"""Warehouses, stock and multi-warehouse fulfillment (PRD A4, B6)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import ArchivableMixin, AuditMixin, Base, IdMixin
from app.models.enums import BackorderStatus, FulfillmentStatus, enum_column

if TYPE_CHECKING:
    from app.models.catalog import Product, ProductVariant
    from app.models.quotation import Quotation, QuotationLine


class Warehouse(IdMixin, AuditMixin, ArchivableMixin, Base):
    """PRD A4: "Main Warehouse", "East Depot", etc."""

    __tablename__ = "warehouses"

    code: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    location: Mapped[str | None] = mapped_column(String(255))
    # PRD A4: "Define shipping cost weighting used by the auto split logic to
    # minimise number of shipments." Lower weight = preferred source. This is
    # the primary sort key of the greedy warehouse-fill algorithm.
    shipping_cost_weight: Mapped[Decimal] = mapped_column(
        Numeric(8, 2), nullable=False, server_default="1"
    )

    stock_levels: Mapped[list[StockLevel]] = relationship(back_populates="warehouse")

    __table_args__ = (
        CheckConstraint("shipping_cost_weight >= 0", name="shipping_cost_weight_non_negative"),
    )


class StockLevel(IdMixin, AuditMixin, Base):
    """On-hand stock for one product (or variant) in one warehouse.

    `quantity_reserved` exists so that a confirmed-but-not-yet-shipped order
    cannot be double-sold. Available stock is
    `quantity_on_hand - quantity_reserved`, and the split algorithm must read
    it with `SELECT ... FOR UPDATE` to stay correct under concurrency.
    """

    __tablename__ = "stock_levels"

    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    variant_id: Mapped[int | None] = mapped_column(
        ForeignKey("product_variants.id", ondelete="RESTRICT"), index=True
    )

    quantity_on_hand: Mapped[Decimal] = mapped_column(
        Numeric(12, 3), nullable=False, server_default="0"
    )
    quantity_reserved: Mapped[Decimal] = mapped_column(
        Numeric(12, 3), nullable=False, server_default="0"
    )
    # PRD A4: "Configure stock levels and replenishment rules per warehouse."
    reorder_point: Mapped[Decimal] = mapped_column(
        Numeric(12, 3), nullable=False, server_default="0"
    )

    warehouse: Mapped[Warehouse] = relationship(back_populates="stock_levels")
    product: Mapped[Product] = relationship()
    variant: Mapped[ProductVariant | None] = relationship()

    __table_args__ = (
        # NULLS NOT DISTINCT is essential here. By default PostgreSQL treats
        # every NULL as distinct, so a plain UNIQUE would happily allow many
        # rows for the same (warehouse, product) whenever variant_id is NULL -
        # letting stock for a non-variant product be duplicated. Requires
        # PostgreSQL 15+; we run 16.
        Index(
            "uq_stock_levels_warehouse_product_variant",
            "warehouse_id",
            "product_id",
            "variant_id",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint("quantity_on_hand >= 0", name="quantity_on_hand_non_negative"),
        CheckConstraint("quantity_reserved >= 0", name="quantity_reserved_non_negative"),
        CheckConstraint("quantity_reserved <= quantity_on_hand", name="reserved_within_on_hand"),
        # The split algorithm looks up every warehouse holding a product.
        Index("ix_stock_levels_product_id_warehouse_id", "product_id", "warehouse_id"),
    )


class Fulfillment(IdMixin, AuditMixin, Base):
    """The fulfillment attempt for a confirmed quotation."""

    __tablename__ = "fulfillments"

    # RESTRICT: shipping history must outlive routine quotation cleanup.
    quotation_id: Mapped[int] = mapped_column(
        ForeignKey("quotations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[FulfillmentStatus] = mapped_column(
        enum_column(FulfillmentStatus, "fulfillment_status"),
        nullable=False,
        server_default=FulfillmentStatus.PENDING.value,
        index=True,
    )
    # PRD B6 displays "Estimated shipment count and cost".
    shipment_count: Mapped[int] = mapped_column(nullable=False, server_default="0")
    estimated_shipping_cost: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, server_default="0"
    )
    # True when a user overrode the suggested split (PRD B6 "Manual Override").
    is_manual_override: Mapped[bool] = mapped_column(nullable=False, server_default="false")
    # Delivery promise, against which the deal health dashboard measures
    # slippage (PRD B9).
    promised_date: Mapped[date | None] = mapped_column()
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    quotation: Mapped[Quotation] = relationship(back_populates="fulfillments")
    splits: Mapped[list[FulfillmentSplit]] = relationship(
        back_populates="fulfillment", cascade="all, delete-orphan"
    )
    backorders: Mapped[list[Backorder]] = relationship(
        back_populates="fulfillment", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("shipment_count >= 0", name="shipment_count_non_negative"),
        CheckConstraint(
            "estimated_shipping_cost >= 0", name="estimated_shipping_cost_non_negative"
        ),
    )


class FulfillmentSplit(IdMixin, AuditMixin, Base):
    """ "Take N units of this line from that warehouse."

    One row per (line, warehouse) pair; several rows for one line is exactly
    what "split across warehouses" means.
    """

    __tablename__ = "fulfillment_splits"

    fulfillment_id: Mapped[int] = mapped_column(
        ForeignKey("fulfillments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    quotation_line_id: Mapped[int] = mapped_column(
        ForeignKey("quotation_lines.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    is_manual_override: Mapped[bool] = mapped_column(nullable=False, server_default="false")

    fulfillment: Mapped[Fulfillment] = relationship(back_populates="splits")
    quotation_line: Mapped[QuotationLine] = relationship()
    warehouse: Mapped[Warehouse] = relationship()

    __table_args__ = (
        CheckConstraint("quantity > 0", name="split_quantity_positive"),
        Index(
            "ix_fulfillment_splits_line_warehouse",
            "quotation_line_id",
            "warehouse_id",
        ),
    )


class Backorder(IdMixin, AuditMixin, Base):
    """Quantity that could not be sourced from any warehouse.

    Kept as its own row rather than a flag on the split, because a backorder
    has its own lifecycle: it stays open, may be consolidated when stock
    arrives (PRD B6), and is eventually fulfilled or cancelled.
    """

    __tablename__ = "backorders"

    fulfillment_id: Mapped[int] = mapped_column(
        ForeignKey("fulfillments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    quotation_line_id: Mapped[int] = mapped_column(
        ForeignKey("quotation_lines.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    quantity_outstanding: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    status: Mapped[BackorderStatus] = mapped_column(
        enum_column(BackorderStatus, "backorder_status"),
        nullable=False,
        server_default=BackorderStatus.OPEN.value,
        index=True,
    )
    expected_date: Mapped[date | None] = mapped_column()
    notes: Mapped[str | None] = mapped_column(Text)

    fulfillment: Mapped[Fulfillment] = relationship(back_populates="backorders")
    quotation_line: Mapped[QuotationLine] = relationship()

    __table_args__ = (
        CheckConstraint("quantity_outstanding > 0", name="backorder_quantity_positive"),
    )
