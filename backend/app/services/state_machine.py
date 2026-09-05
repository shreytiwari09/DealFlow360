"""Explicit state machines for every lifecycle entity.

PLAN.md Section 7 is emphatic that transitions must not be left implicit:
"Document each as an explicit enum plus its allowed transitions, validated in
code - invalid transitions must be rejected, not just unused."

Everything here is pure: no database, no I/O, no framework. That makes the
rules trivially testable and keeps the single source of truth for "what may
follow what" in one readable file rather than scattered across service code.

A transition table maps each state to the complete set of states reachable
from it. A state whose set is empty is terminal.
"""

from collections.abc import Mapping
from enum import StrEnum

from app.models.enums import (
    ApprovalStatus,
    BackorderStatus,
    BillingScheduleStatus,
    FulfillmentStatus,
    QuotationStatus,
    SubscriptionStatus,
)


class InvalidStateTransition(Exception):
    """Raised when code attempts a transition the lifecycle does not allow.

    Carries the entity, the current state and the attempted state so the API
    layer can turn it into a useful 409 without re-deriving the context.
    """

    def __init__(self, entity: str, current: StrEnum, attempted: StrEnum) -> None:
        self.entity = entity
        self.current = current
        self.attempted = attempted
        super().__init__(f"{entity}: cannot move from '{current.value}' to '{attempted.value}'")


# --- Quotation -------------------------------------------------------------
#
#   draft ─────────────────► pending_approval ──► approved ──► sent
#     ▲                            │  │                          │
#     │                            │  └──► rejected ──► draft    ▼
#     └── (revision) ──────────────┘                    under_negotiation
#                                                              │   │
#            (counter-offer breaches threshold) ◄──────────────┘   │
#                          back to pending_approval                ▼
#                                                             confirmed ──► fulfilled
#
# `cancelled` is reachable from every non-terminal state.
# `fulfilled` and `cancelled` are terminal.
QUOTATION_TRANSITIONS: Mapping[QuotationStatus, frozenset[QuotationStatus]] = {
    QuotationStatus.DRAFT: frozenset(
        {
            # A quote whose score is 0 needs no approval and may go straight
            # out to the customer (PRD B3: "or straight to fulfillment if no
            # approval is required").
            QuotationStatus.PENDING_APPROVAL,
            QuotationStatus.SENT,
            QuotationStatus.CANCELLED,
        }
    ),
    QuotationStatus.PENDING_APPROVAL: frozenset(
        {
            QuotationStatus.APPROVED,
            QuotationStatus.REJECTED,
            # "Returned for revision" lands the quotation back with the rep.
            QuotationStatus.DRAFT,
            QuotationStatus.CANCELLED,
        }
    ),
    QuotationStatus.APPROVED: frozenset(
        {
            QuotationStatus.SENT,
            QuotationStatus.CONFIRMED,
            QuotationStatus.CANCELLED,
        }
    ),
    QuotationStatus.REJECTED: frozenset(
        {
            QuotationStatus.DRAFT,
            QuotationStatus.CANCELLED,
        }
    ),
    QuotationStatus.SENT: frozenset(
        {
            QuotationStatus.UNDER_NEGOTIATION,
            QuotationStatus.CONFIRMED,
            QuotationStatus.CANCELLED,
        }
    ),
    QuotationStatus.UNDER_NEGOTIATION: frozenset(
        {
            # PRD B8: a counter-offer that pushes the blended risk score into a
            # higher band re-enters the approval flow automatically.
            QuotationStatus.PENDING_APPROVAL,
            QuotationStatus.SENT,
            QuotationStatus.CONFIRMED,
            QuotationStatus.CANCELLED,
        }
    ),
    QuotationStatus.CONFIRMED: frozenset(
        {
            QuotationStatus.FULFILLED,
            QuotationStatus.CANCELLED,
        }
    ),
    QuotationStatus.FULFILLED: frozenset(),
    QuotationStatus.CANCELLED: frozenset(),
}


# --- Approval (request and individual step) --------------------------------
#
# pending ──► approved / rejected / returned_for_revision   (all terminal)
APPROVAL_TRANSITIONS: Mapping[ApprovalStatus, frozenset[ApprovalStatus]] = {
    ApprovalStatus.PENDING: frozenset(
        {
            ApprovalStatus.APPROVED,
            ApprovalStatus.REJECTED,
            ApprovalStatus.RETURNED_FOR_REVISION,
        }
    ),
    # A decision is final. Re-opening a decided approval would destroy the
    # audit trail the PRD requires, so a fresh request is created instead.
    ApprovalStatus.APPROVED: frozenset(),
    ApprovalStatus.REJECTED: frozenset(),
    ApprovalStatus.RETURNED_FOR_REVISION: frozenset(),
}


# --- Subscription ----------------------------------------------------------
#
# active ◄──► modified ──► cancelled
SUBSCRIPTION_TRANSITIONS: Mapping[SubscriptionStatus, frozenset[SubscriptionStatus]] = {
    SubscriptionStatus.ACTIVE: frozenset(
        {
            SubscriptionStatus.MODIFIED,
            SubscriptionStatus.CANCELLED,
        }
    ),
    SubscriptionStatus.MODIFIED: frozenset(
        {
            # A modified subscription settles back to active once the
            # proration for the change has been recorded.
            SubscriptionStatus.ACTIVE,
            SubscriptionStatus.MODIFIED,
            SubscriptionStatus.CANCELLED,
        }
    ),
    SubscriptionStatus.CANCELLED: frozenset(),
}


# --- Fulfillment -----------------------------------------------------------
FULFILLMENT_TRANSITIONS: Mapping[FulfillmentStatus, frozenset[FulfillmentStatus]] = {
    FulfillmentStatus.PENDING: frozenset(
        {
            FulfillmentStatus.PARTIALLY_FULFILLED,
            FulfillmentStatus.FULFILLED,
            FulfillmentStatus.BACKORDERED,
        }
    ),
    FulfillmentStatus.PARTIALLY_FULFILLED: frozenset(
        {
            FulfillmentStatus.FULFILLED,
            FulfillmentStatus.BACKORDERED,
        }
    ),
    FulfillmentStatus.BACKORDERED: frozenset(
        {
            # Stock arriving mid-fulfillment lets a backordered shipment
            # resume (PRD B6: "Consolidate Remaining Backorder").
            FulfillmentStatus.PARTIALLY_FULFILLED,
            FulfillmentStatus.FULFILLED,
        }
    ),
    FulfillmentStatus.FULFILLED: frozenset(),
}


# --- Backorder -------------------------------------------------------------
BACKORDER_TRANSITIONS: Mapping[BackorderStatus, frozenset[BackorderStatus]] = {
    BackorderStatus.OPEN: frozenset(
        {
            BackorderStatus.CONSOLIDATED,
            BackorderStatus.FULFILLED,
            BackorderStatus.CANCELLED,
        }
    ),
    BackorderStatus.CONSOLIDATED: frozenset(
        {
            BackorderStatus.FULFILLED,
            BackorderStatus.CANCELLED,
        }
    ),
    BackorderStatus.FULFILLED: frozenset(),
    BackorderStatus.CANCELLED: frozenset(),
}


# --- Billing schedule ------------------------------------------------------
BILLING_SCHEDULE_TRANSITIONS: Mapping[BillingScheduleStatus, frozenset[BillingScheduleStatus]] = {
    BillingScheduleStatus.SCHEDULED: frozenset(
        {
            BillingScheduleStatus.INVOICED,
            BillingScheduleStatus.CANCELLED,
        }
    ),
    BillingScheduleStatus.INVOICED: frozenset(
        {
            BillingScheduleStatus.PAID,
            BillingScheduleStatus.CANCELLED,
        }
    ),
    # A paid invoice is never re-opened; a correction is a credit note.
    BillingScheduleStatus.PAID: frozenset(),
    BillingScheduleStatus.CANCELLED: frozenset(),
}


_TRANSITION_TABLES: dict[str, Mapping[StrEnum, frozenset[StrEnum]]] = {
    "Quotation": QUOTATION_TRANSITIONS,
    "Approval": APPROVAL_TRANSITIONS,
    "Subscription": SUBSCRIPTION_TRANSITIONS,
    "Fulfillment": FULFILLMENT_TRANSITIONS,
    "Backorder": BACKORDER_TRANSITIONS,
    "BillingSchedule": BILLING_SCHEDULE_TRANSITIONS,
}


def can_transition(entity: str, current: StrEnum, attempted: StrEnum) -> bool:
    """Return whether `entity` may move from `current` to `attempted`."""
    table = _TRANSITION_TABLES[entity]
    return attempted in table[current]


def assert_transition(entity: str, current: StrEnum, attempted: StrEnum) -> None:
    """Raise `InvalidStateTransition` unless the move is allowed.

    Call this before writing any status change. A transition that is merely
    "not used" is not the same as one that is rejected - PLAN.md Section 7
    requires the latter.
    """
    if not can_transition(entity, current, attempted):
        raise InvalidStateTransition(entity, current, attempted)


def terminal_states(entity: str) -> frozenset[StrEnum]:
    """States from which nothing further is reachable. Useful in tests."""
    table = _TRANSITION_TABLES[entity]
    return frozenset(state for state, nxt in table.items() if not nxt)
