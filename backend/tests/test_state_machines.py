"""State machine tests.

PLAN.md Section 7 requires that invalid transitions be *rejected*, not merely
unused, so these assert the rejections as hard as the acceptances.

The completeness tests matter most for the future: they fail if someone adds a
value to an enum without adding it to the transition table, which would
otherwise surface as a KeyError at runtime in the middle of a demo.
"""

import pytest

from app.models.enums import (
    ApprovalStatus,
    BackorderStatus,
    BillingScheduleStatus,
    FulfillmentStatus,
    QuotationStatus,
    SubscriptionStatus,
)
from app.services.state_machine import (
    APPROVAL_TRANSITIONS,
    BACKORDER_TRANSITIONS,
    BILLING_SCHEDULE_TRANSITIONS,
    FULFILLMENT_TRANSITIONS,
    QUOTATION_TRANSITIONS,
    SUBSCRIPTION_TRANSITIONS,
    InvalidStateTransition,
    assert_transition,
    can_transition,
    terminal_states,
)

ALL_MACHINES = [
    ("Quotation", QuotationStatus, QUOTATION_TRANSITIONS),
    ("Approval", ApprovalStatus, APPROVAL_TRANSITIONS),
    ("Subscription", SubscriptionStatus, SUBSCRIPTION_TRANSITIONS),
    ("Fulfillment", FulfillmentStatus, FULFILLMENT_TRANSITIONS),
    ("Backorder", BackorderStatus, BACKORDER_TRANSITIONS),
    ("BillingSchedule", BillingScheduleStatus, BILLING_SCHEDULE_TRANSITIONS),
]


# --- Completeness ----------------------------------------------------------


@pytest.mark.parametrize("entity,enum_cls,table", ALL_MACHINES)
def test_every_state_has_a_transition_entry(entity, enum_cls, table) -> None:
    """Adding an enum member without a transition entry must fail here, not
    at runtime with a KeyError."""
    missing = set(enum_cls) - set(table)
    assert not missing, f"{entity}: states missing from transition table: {missing}"


@pytest.mark.parametrize("entity,enum_cls,table", ALL_MACHINES)
def test_transitions_only_target_known_states(entity, enum_cls, table) -> None:
    for state, reachable in table.items():
        unknown = reachable - set(enum_cls)
        assert not unknown, f"{entity}.{state}: targets unknown states {unknown}"


@pytest.mark.parametrize("entity,enum_cls,table", ALL_MACHINES)
def test_no_state_transitions_to_itself(entity, enum_cls, table) -> None:
    """A self-transition is almost always a modelling mistake.

    Subscription MODIFIED is the one deliberate exception: a subscription can
    be changed again while already in the modified state.
    """
    for state, reachable in table.items():
        if entity == "Subscription" and state is SubscriptionStatus.MODIFIED:
            continue
        assert state not in reachable, f"{entity}.{state} transitions to itself"


@pytest.mark.parametrize("entity,enum_cls,table", ALL_MACHINES)
def test_every_machine_has_at_least_one_terminal_state(entity, enum_cls, table) -> None:
    assert terminal_states(entity), f"{entity}: no terminal state - lifecycle never ends"


# --- Quotation -------------------------------------------------------------


def test_quotation_happy_path_is_allowed() -> None:
    path = [
        QuotationStatus.DRAFT,
        QuotationStatus.PENDING_APPROVAL,
        QuotationStatus.APPROVED,
        QuotationStatus.SENT,
        QuotationStatus.CONFIRMED,
        QuotationStatus.FULFILLED,
    ]
    for current, nxt in zip(path, path[1:], strict=False):
        assert_transition("Quotation", current, nxt)


def test_quotation_may_skip_approval_when_no_discount_breach() -> None:
    """PRD B3: a quote needing no approval goes straight out."""
    assert_transition("Quotation", QuotationStatus.DRAFT, QuotationStatus.SENT)


def test_portal_counter_offer_can_re_enter_approval() -> None:
    """PRD B8: a counter-offer breaching a threshold re-enters the flow."""
    assert_transition(
        "Quotation",
        QuotationStatus.UNDER_NEGOTIATION,
        QuotationStatus.PENDING_APPROVAL,
    )


def test_returned_for_revision_sends_quotation_back_to_draft() -> None:
    assert_transition("Quotation", QuotationStatus.PENDING_APPROVAL, QuotationStatus.DRAFT)


def test_cancelled_quotation_cannot_be_revived() -> None:
    """The exact failure PLAN.md names: a cancelled quote must not be
    re-approved."""
    with pytest.raises(InvalidStateTransition):
        assert_transition("Quotation", QuotationStatus.CANCELLED, QuotationStatus.APPROVED)


def test_fulfilled_quotation_is_terminal() -> None:
    for target in QuotationStatus:
        assert not can_transition("Quotation", QuotationStatus.FULFILLED, target)


def test_draft_cannot_jump_straight_to_fulfilled() -> None:
    with pytest.raises(InvalidStateTransition) as exc:
        assert_transition("Quotation", QuotationStatus.DRAFT, QuotationStatus.FULFILLED)

    message = str(exc.value)
    assert "draft" in message and "fulfilled" in message


def test_cancellation_is_reachable_from_every_non_terminal_state() -> None:
    for state, reachable in QUOTATION_TRANSITIONS.items():
        if not reachable:  # terminal
            continue
        assert QuotationStatus.CANCELLED in reachable, f"{state} cannot be cancelled"


# --- Approval --------------------------------------------------------------


@pytest.mark.parametrize(
    "outcome",
    [
        ApprovalStatus.APPROVED,
        ApprovalStatus.REJECTED,
        ApprovalStatus.RETURNED_FOR_REVISION,
    ],
)
def test_pending_approval_reaches_every_outcome(outcome) -> None:
    assert_transition("Approval", ApprovalStatus.PENDING, outcome)


@pytest.mark.parametrize(
    "decided",
    [
        ApprovalStatus.APPROVED,
        ApprovalStatus.REJECTED,
        ApprovalStatus.RETURNED_FOR_REVISION,
    ],
)
def test_a_decided_approval_cannot_be_reopened(decided) -> None:
    """Reopening a decision would destroy the audit trail the PRD requires."""
    with pytest.raises(InvalidStateTransition):
        assert_transition("Approval", decided, ApprovalStatus.PENDING)


# --- Fulfillment and backorders --------------------------------------------


def test_backordered_fulfillment_can_resume_when_stock_arrives() -> None:
    """PRD B6: "Consolidate Remaining Backorder"."""
    assert_transition(
        "Fulfillment",
        FulfillmentStatus.BACKORDERED,
        FulfillmentStatus.PARTIALLY_FULFILLED,
    )


def test_fulfilled_cannot_regress_to_partial() -> None:
    with pytest.raises(InvalidStateTransition):
        assert_transition(
            "Fulfillment",
            FulfillmentStatus.FULFILLED,
            FulfillmentStatus.PARTIALLY_FULFILLED,
        )


def test_cancelled_backorder_is_terminal() -> None:
    for target in BackorderStatus:
        assert not can_transition("Backorder", BackorderStatus.CANCELLED, target)


# --- Subscription and billing ----------------------------------------------


def test_subscription_returns_to_active_after_modification() -> None:
    assert_transition("Subscription", SubscriptionStatus.MODIFIED, SubscriptionStatus.ACTIVE)


def test_cancelled_subscription_cannot_be_reactivated() -> None:
    with pytest.raises(InvalidStateTransition):
        assert_transition("Subscription", SubscriptionStatus.CANCELLED, SubscriptionStatus.ACTIVE)


def test_invoice_must_be_issued_before_it_can_be_paid() -> None:
    with pytest.raises(InvalidStateTransition):
        assert_transition(
            "BillingSchedule",
            BillingScheduleStatus.SCHEDULED,
            BillingScheduleStatus.PAID,
        )

    assert_transition(
        "BillingSchedule",
        BillingScheduleStatus.SCHEDULED,
        BillingScheduleStatus.INVOICED,
    )
    assert_transition("BillingSchedule", BillingScheduleStatus.INVOICED, BillingScheduleStatus.PAID)


def test_paid_invoice_cannot_be_reopened() -> None:
    """A correction is a credit note, never an edit to a paid invoice."""
    for target in BillingScheduleStatus:
        assert not can_transition("BillingSchedule", BillingScheduleStatus.PAID, target)


def test_exception_carries_context_for_the_api_layer() -> None:
    with pytest.raises(InvalidStateTransition) as exc:
        assert_transition("Quotation", QuotationStatus.FULFILLED, QuotationStatus.DRAFT)

    assert exc.value.entity == "Quotation"
    assert exc.value.current is QuotationStatus.FULFILLED
    assert exc.value.attempted is QuotationStatus.DRAFT
