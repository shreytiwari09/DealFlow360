"""SQLAlchemy models.

Every model module MUST be imported here. Alembic autogenerate works from
`Base.metadata`, and a model that is never imported is not registered on it -
so it is silently omitted from migrations with no error. This file is the
single place that guarantees the metadata is complete.
"""

from app.db.base import ArchivableMixin, AuditMixin, Base, IdMixin, TimestampMixin
from app.models.approval import ApprovalRequest, ApprovalStep
from app.models.audit import AuditAction, AuditLog
from app.models.auth import RefreshToken
from app.models.billing import (
    BillingSchedule,
    Payment,
    ProrationRecord,
    Subscription,
    SubscriptionPlan,
)
from app.models.catalog import (
    PriceList,
    PriceListItem,
    Product,
    ProductCategory,
    ProductVariant,
)
from app.models.customer import Customer
from app.models.dealhealth import DealHealthSnapshot
from app.models.inventory import (
    Backorder,
    Fulfillment,
    FulfillmentSplit,
    StockLevel,
    Warehouse,
)
from app.models.policy import ApprovalChain, DiscountTier
from app.models.quotation import Quotation, QuotationLine
from app.models.rbac import Permission, Role, SalesTeam, User, role_permissions
from app.models.upsell import UpsellRule

__all__ = [
    # Base / mixins
    "ArchivableMixin",
    "AuditMixin",
    "Base",
    "IdMixin",
    "TimestampMixin",
    # Identity and access
    "Permission",
    "Role",
    "SalesTeam",
    "User",
    "role_permissions",
    # Commercial master data
    "Customer",
    "PriceList",
    "PriceListItem",
    "Product",
    "ProductCategory",
    "ProductVariant",
    # Discount governance
    "ApprovalChain",
    "DiscountTier",
    # Quotations
    "Quotation",
    "QuotationLine",
    # Approvals
    "ApprovalRequest",
    "ApprovalStep",
    "RefreshToken",
    # Inventory and fulfillment
    "Backorder",
    "Fulfillment",
    "FulfillmentSplit",
    "StockLevel",
    "Warehouse",
    # Billing
    "BillingSchedule",
    "Payment",
    "ProrationRecord",
    "Subscription",
    "SubscriptionPlan",
    # Supporting features
    "DealHealthSnapshot",
    "UpsellRule",
    # Audit
    "AuditAction",
    "AuditLog",
]
