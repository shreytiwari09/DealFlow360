"""Product catalogue and price lists (PRD A2)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import ArchivableMixin, AuditMixin, Base, IdMixin
from app.models.enums import CustomerTier, ItemType, enum_column

if TYPE_CHECKING:
    from app.models.policy import DiscountTier


class ProductCategory(IdMixin, AuditMixin, ArchivableMixin, Base):
    """A table, not an enum, because PRD A3 requires per-category discount
    ceilings to be configured by an Admin at runtime."""

    __tablename__ = "product_categories"

    code: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255))

    products: Mapped[list[Product]] = relationship(back_populates="category")
    discount_tiers: Mapped[list[DiscountTier]] = relationship(back_populates="category")


class Product(IdMixin, AuditMixin, ArchivableMixin, Base):
    __tablename__ = "products"

    sku: Mapped[str] = mapped_column(String(60), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(String(1000))

    # RESTRICT: a category with products must not be deletable.
    category_id: Mapped[int] = mapped_column(
        ForeignKey("product_categories.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    unit: Mapped[str] = mapped_column(String(20), nullable=False, server_default="unit")
    list_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    # Required for the live margin indicator (PRD B3) and the margin delta on
    # upsell suggestions (PRD B5). Without a cost there is no margin to show.
    cost_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, server_default="0")

    # Decides whether a line bills once or generates a billing schedule.
    item_type: Mapped[ItemType] = mapped_column(
        enum_column(ItemType, "product_item_type"),
        nullable=False,
        server_default=ItemType.ONE_TIME.value,
        index=True,
    )
    # PRD A6: promoted products rank higher in upsell suggestions.
    is_promoted: Mapped[bool] = mapped_column(nullable=False, server_default="false")

    category: Mapped[ProductCategory] = relationship(back_populates="products")
    variants: Mapped[list[ProductVariant]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("list_price >= 0", name="list_price_non_negative"),
        CheckConstraint("cost_price >= 0", name="cost_price_non_negative"),
        CheckConstraint("tax_rate >= 0 AND tax_rate <= 100", name="tax_rate_percentage_range"),
    )


class ProductVariant(IdMixin, AuditMixin, ArchivableMixin, Base):
    """PRD A2: "Variants: Attribute (example: Size or Pack), Values, Extra prices"."""

    __tablename__ = "product_variants"

    # CASCADE: a variant has no meaning without its parent product. This is
    # safe because products are archived rather than deleted, so the cascade
    # only fires on genuine cleanup.
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    attribute_name: Mapped[str] = mapped_column(String(60), nullable=False)
    attribute_value: Mapped[str] = mapped_column(String(60), nullable=False)
    sku_suffix: Mapped[str | None] = mapped_column(String(30))
    # Added to the parent's list price; may be negative for a cheaper variant.
    extra_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")

    product: Mapped[Product] = relationship(back_populates="variants")

    __table_args__ = (
        UniqueConstraint(
            "product_id",
            "attribute_name",
            "attribute_value",
            name="uq_product_variants_product_attribute",
        ),
    )


class PriceList(IdMixin, AuditMixin, ArchivableMixin, Base):
    """PRD A2: "Price Lists: Customer tier based pricing, currency specific rules"."""

    __tablename__ = "price_lists"

    code: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # NULL means the list applies to every tier.
    customer_tier: Mapped[CustomerTier | None] = mapped_column(
        enum_column(CustomerTier, "price_list_customer_tier"), index=True
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="INR")
    valid_from: Mapped[date | None] = mapped_column()
    valid_to: Mapped[date | None] = mapped_column()

    items: Mapped[list[PriceListItem]] = relationship(
        back_populates="price_list", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from",
            name="valid_period_ordered",
        ),
    )


class PriceListItem(IdMixin, AuditMixin, Base):
    __tablename__ = "price_list_items"

    price_list_id: Mapped[int] = mapped_column(
        ForeignKey("price_lists.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    # Supports volume breaks: the applicable row is the one with the highest
    # min_quantity not exceeding the ordered quantity.
    min_quantity: Mapped[Decimal] = mapped_column(
        Numeric(12, 3), nullable=False, server_default="1"
    )

    price_list: Mapped[PriceList] = relationship(back_populates="items")

    __table_args__ = (
        UniqueConstraint(
            "price_list_id",
            "product_id",
            "min_quantity",
            name="uq_price_list_items_list_product_qty",
        ),
        CheckConstraint("unit_price >= 0", name="unit_price_non_negative"),
        CheckConstraint("min_quantity > 0", name="min_quantity_positive"),
        Index("ix_price_list_items_product_id_price_list_id", "product_id", "price_list_id"),
    )
