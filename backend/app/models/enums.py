"""Domain enumerations.

Every enum here is persisted as VARCHAR + a named CHECK constraint, not as a
native PostgreSQL ENUM type. Rationale: adding a value to a native enum
requires `ALTER TYPE ... ADD VALUE`, which cannot run inside a transaction
block on older servers and is awkward to reverse in a downgrade. PLAN.md
Section 7 expects this schema to keep evolving, so a CHECK constraint - which
Alembic can drop and recreate like any other constraint - is the safer shape.
The database still rejects an invalid value; only the storage differs.

The metadata naming convention in `app/db/base.py` gives each of these CHECK
constraints a stable, predictable name.
"""

from enum import StrEnum

from sqlalchemy import Enum as SAEnum


def enum_column(enum_cls: type[StrEnum], name: str) -> SAEnum:
    """Build a VARCHAR-backed enum type with a named CHECK constraint.

    `values_callable` makes the database store the enum *value*
    (``"sales_rep"``) rather than the Python member *name* (``"SALES_REP"``),
    which keeps raw SQL readable during the demo.
    """
    return SAEnum(
        enum_cls,
        name=name,
        native_enum=False,
        length=40,
        values_callable=lambda enum: [member.value for member in enum],
        validate_strings=True,
    )


# --- Identity and access ---------------------------------------------------


class RoleCode(StrEnum):
    """The five PRD roles. SECURITY_SPEC.md Section 4 is authoritative here -
    this list must not be substituted for a generic role set."""

    ADMIN = "admin"
    SALES_MANAGER = "sales_manager"
    SALES_REP = "sales_rep"
    FINANCE_OPS = "finance_ops"
    CUSTOMER = "customer"


# --- Commercial master data ------------------------------------------------


class CustomerTier(StrEnum):
    """PRD A3 names Bronze/Silver/Gold explicitly."""

    BRONZE = "bronze"
    SILVER = "silver"
    GOLD = "gold"


class ItemType(StrEnum):
    """Distinguishes one-time products from recurring subscription lines.

    The same distinction applies to a product (what it *is*) and to a quotation
    line (how it is *being sold*), so one enum serves both. This is what makes
    hybrid billing possible on a single order.
    """

    ONE_TIME = "one_time"
    SUBSCRIPTION = "subscription"


class BillingInterval(StrEnum):
    """PRD A5: recurring plans are monthly, quarterly or yearly."""

    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"


class RefundPolicy(StrEnum):
    """PRD A5: cancellation and partial refund rules."""

    NONE = "none"
    PRORATED = "prorated"
    FULL = "full"


# --- Lifecycle states ------------------------------------------------------


class QuotationStatus(StrEnum):
    """Quotation lifecycle.

    NOTE - this is a deliberate SUPERSET of the list in PLAN.md Section 7,
    which gives draft -> pending_approval -> approved -> confirmed ->
    fulfilled / cancelled. Three extra states are required to satisfy the PRD
    itself, and PLAN.md Section 1 states the PRD wins on *what* to build:

      * `sent` and `under_negotiation` - PRD B8 requires the customer portal to
        display "Sent, Under Negotiation, Confirmed" as the quotation's status.
      * `rejected` - PRD A7 requires reporting to filter by "pending, approved,
        or rejected quotations", which needs a quotation-level state, not only
        an approval-record state.

    Flagged in PROJECT_CONTEXT.md for confirmation.
    """

    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    SENT = "sent"
    UNDER_NEGOTIATION = "under_negotiation"
    CONFIRMED = "confirmed"
    FULFILLED = "fulfilled"
    CANCELLED = "cancelled"


class ApprovalStatus(StrEnum):
    """Used by both an approval request and each of its individual steps."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    RETURNED_FOR_REVISION = "returned_for_revision"


class SubscriptionStatus(StrEnum):
    ACTIVE = "active"
    MODIFIED = "modified"
    CANCELLED = "cancelled"


class FulfillmentStatus(StrEnum):
    PENDING = "pending"
    PARTIALLY_FULFILLED = "partially_fulfilled"
    FULFILLED = "fulfilled"
    BACKORDERED = "backordered"


class BackorderStatus(StrEnum):
    OPEN = "open"
    CONSOLIDATED = "consolidated"
    FULFILLED = "fulfilled"
    CANCELLED = "cancelled"


# --- Billing ---------------------------------------------------------------


class BillingScheduleType(StrEnum):
    ONE_TIME = "one_time"
    RECURRING = "recurring"


class BillingScheduleStatus(StrEnum):
    SCHEDULED = "scheduled"
    INVOICED = "invoiced"
    PAID = "paid"
    CANCELLED = "cancelled"


class PaymentMethod(StrEnum):
    BANK_TRANSFER = "bank_transfer"
    CARD = "card"
    CASH = "cash"
    CHEQUE = "cheque"
    OTHER = "other"
