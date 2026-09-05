"""Customer portal negotiation tests (PRD B8).

The interesting behaviour here is not the CRUD — it is the re-approval loop
and its one genuinely subtle rule: terms an approver has already signed off on
must NOT be sent back to them unchanged, or a quotation that ever needed an
approval could never be confirmed at all (PROJECT_CONTEXT.md Locked Business
Rules #8d). Both halves of that are tested against the real schema.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    ApprovalRequest,
    Customer,
    DiscountTier,
    Product,
    ProductCategory,
    Quotation,
    QuotationLine,
    Role,
    User,
)
from app.models.enums import (
    ApprovalStatus,
    CustomerTier,
    ItemType,
    QuotationStatus,
    RoleCode,
)
from app.services.portal import (
    PortalError,
    confirm_from_portal,
    submit_counter_offer,
    terms_already_approved,
)
from app.services.quotation import recalculate

NOW = datetime.now(UTC)


@pytest.fixture
async def rep_role(db_session: AsyncSession) -> Role:
    existing = (
        await db_session.execute(select(Role).where(Role.code == RoleCode.SALES_REP))
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    role = Role(code=RoleCode.SALES_REP, name="Sales Rep")
    db_session.add(role)
    await db_session.flush()
    return role


@pytest.fixture
async def rep(db_session: AsyncSession, rep_role: Role) -> User:
    user = User(
        email=f"portal-rep-{NOW.timestamp()}@example.test",
        password_hash="not-a-real-hash",
        full_name="Test Rep",
        role_id=rep_role.id,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.fixture
async def customer(db_session: AsyncSession) -> Customer:
    customer = Customer(code=f"CUST-{NOW.timestamp()}", name="Acme Corp", tier=CustomerTier.GOLD)
    db_session.add(customer)
    await db_session.flush()
    return customer


@pytest.fixture
async def product(db_session: AsyncSession) -> Product:
    """A Services product with a 10% ceiling for GOLD — the PRD's own example
    category, so a 20% discount is a real 10-point breach."""
    category = ProductCategory(code=f"SVC-{NOW.timestamp()}", name="Services")
    db_session.add(category)
    await db_session.flush()
    db_session.add(
        DiscountTier(
            customer_tier=CustomerTier.GOLD,
            category_id=category.id,
            max_discount_percent=Decimal("10"),
        )
    )
    product = Product(
        sku=f"SVC-{NOW.timestamp()}",
        name="Setup Service",
        category_id=category.id,
        list_price=Decimal("10000.00"),
        cost_price=Decimal("6000.00"),
        item_type=ItemType.ONE_TIME,
    )
    db_session.add(product)
    await db_session.flush()
    return product


async def _quotation(
    db_session: AsyncSession,
    customer: Customer,
    rep: User,
    product: Product,
    *,
    status: QuotationStatus,
    discount: str,
) -> Quotation:
    quotation = Quotation(
        quote_number=f"Q-PORTAL-{NOW.timestamp()}-{discount}",
        customer_id=customer.id,
        owner_id=rep.id,
        status=status,
    )
    db_session.add(quotation)
    await db_session.flush()
    db_session.add(
        QuotationLine(
            quotation_id=quotation.id,
            line_number=1,
            product_id=product.id,
            quantity=Decimal("1"),
            unit_list_price=product.list_price,
            unit_cost_price=product.cost_price,
            discount_percent=Decimal(discount),
        )
    )
    await db_session.flush()
    await db_session.refresh(quotation, attribute_names=["lines"])
    await recalculate(db_session, quotation)
    return quotation


@pytest.fixture
async def sent_quotation(
    db_session: AsyncSession, customer: Customer, rep: User, product: Product
) -> Quotation:
    """Compliant terms (5% against a 10% ceiling), sitting at `sent`."""
    return await _quotation(
        db_session, customer, rep, product, status=QuotationStatus.SENT, discount="5"
    )


# ---------------------------------------------------------------------------
# Submit Request (counter-offer)
# ---------------------------------------------------------------------------


async def test_counter_offer_moves_to_under_negotiation(
    db_session: AsyncSession, sent_quotation: Quotation
) -> None:
    await submit_counter_offer(db_session, sent_quotation, counter_discount_percent=Decimal("8"))

    assert sent_quotation.status == QuotationStatus.UNDER_NEGOTIATION


async def test_counter_offer_applies_the_discount_to_every_line(
    db_session: AsyncSession, sent_quotation: Quotation
) -> None:
    """Locked Business Rules #4 and #8a: a counter is an order-level discount,
    written onto every line, not scored as its own separate thing."""
    await submit_counter_offer(db_session, sent_quotation, counter_discount_percent=Decimal("20"))

    assert all(line.discount_percent == Decimal("20") for line in sent_quotation.lines)
    # And it is re-scored: 20% against a 10% ceiling is 10 points over.
    assert sent_quotation.max_line_excess == Decimal("10.00")


async def test_a_comment_only_request_leaves_the_numbers_alone(
    db_session: AsyncSession, sent_quotation: Quotation
) -> None:
    """A customer asking a question must not silently change the deal."""
    before = sent_quotation.total_amount

    await submit_counter_offer(db_session, sent_quotation, counter_discount_percent=None)

    assert sent_quotation.total_amount == before
    assert sent_quotation.status == QuotationStatus.UNDER_NEGOTIATION


async def test_a_second_counter_round_does_not_re_assert_the_transition(
    db_session: AsyncSession, sent_quotation: Quotation
) -> None:
    """`under_negotiation -> under_negotiation` is not a legal transition, and
    the service must not pretend it is by asserting one that would fail."""
    await submit_counter_offer(db_session, sent_quotation, counter_discount_percent=Decimal("8"))
    await submit_counter_offer(db_session, sent_quotation, counter_discount_percent=Decimal("12"))

    assert sent_quotation.status == QuotationStatus.UNDER_NEGOTIATION
    assert sent_quotation.lines[0].discount_percent == Decimal("12")


async def test_cannot_negotiate_a_draft_quotation(
    db_session: AsyncSession, customer: Customer, rep: User, product: Product
) -> None:
    draft = await _quotation(
        db_session, customer, rep, product, status=QuotationStatus.DRAFT, discount="5"
    )

    with pytest.raises(PortalError, match="cannot be negotiated"):
        await submit_counter_offer(db_session, draft, counter_discount_percent=Decimal("8"))


# ---------------------------------------------------------------------------
# Confirm Quotation, and the re-approval loop
# ---------------------------------------------------------------------------


async def test_confirming_compliant_terms_goes_straight_to_confirmed(
    db_session: AsyncSession, sent_quotation: Quotation, rep: User
) -> None:
    """PRD B8: "otherwise, the order moves directly to fulfillment"."""
    outcome = await confirm_from_portal(db_session, sent_quotation, actor_id=rep.id)

    assert not outcome.re_entered_approval
    assert sent_quotation.status == QuotationStatus.CONFIRMED


async def test_confirming_a_breaching_counter_re_enters_approval(
    db_session: AsyncSession, sent_quotation: Quotation, rep: User
) -> None:
    """PRD B8: "if final terms exceed approval thresholds, the quotation
    automatically re enters the approval flow from B4"."""
    await submit_counter_offer(db_session, sent_quotation, counter_discount_percent=Decimal("20"))

    outcome = await confirm_from_portal(db_session, sent_quotation, actor_id=rep.id)

    assert outcome.re_entered_approval
    assert outcome.required_steps  # at least a Sales Manager step
    assert sent_quotation.status == QuotationStatus.PENDING_APPROVAL


async def test_re_entry_raises_a_new_request_not_a_reopened_one(
    db_session: AsyncSession, sent_quotation: Quotation, rep: User
) -> None:
    """Decided approvals are terminal; a counter-offer creates a fresh record
    so the earlier decision on different terms survives in the trail."""
    await submit_counter_offer(db_session, sent_quotation, counter_discount_percent=Decimal("20"))
    await confirm_from_portal(db_session, sent_quotation, actor_id=rep.id)

    requests = (
        (
            await db_session.execute(
                select(ApprovalRequest).where(ApprovalRequest.quotation_id == sent_quotation.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(requests) == 1
    assert requests[0].status == ApprovalStatus.PENDING
    assert requests[0].max_line_excess == Decimal("10.00")


async def test_already_approved_terms_are_not_sent_back_for_approval(
    db_session: AsyncSession, customer: Customer, rep: User, product: Product
) -> None:
    """The regression this rule exists for (Locked Business Rules #8d).

    A quotation approved at 20% and then sent still SCORES as breaching —
    nothing about it changed. Routing on the score alone would bounce it back
    to the manager who just approved it, forever, and no quotation that ever
    needed an approval could be confirmed at all.
    """
    quotation = await _quotation(
        db_session, customer, rep, product, status=QuotationStatus.SENT, discount="20"
    )
    assessment = await recalculate(db_session, quotation)
    # An approver has already signed off on exactly these terms.
    db_session.add(
        ApprovalRequest(
            quotation_id=quotation.id,
            blended_risk_score=assessment.blended_score,
            max_line_excess=assessment.max_line_excess,
            status=ApprovalStatus.APPROVED,
            requested_at=NOW,
            created_by=rep.id,
        )
    )
    await db_session.flush()

    outcome = await confirm_from_portal(db_session, quotation, actor_id=rep.id)

    assert not outcome.re_entered_approval
    assert quotation.status == QuotationStatus.CONFIRMED


async def test_a_changed_counter_does_not_match_an_earlier_approval(
    db_session: AsyncSession, customer: Customer, rep: User, product: Product
) -> None:
    """Deliberately strict: 20% was approved, the customer counters to 15%,
    still over the 10% ceiling. Different terms that still breach policy go
    back for approval rather than riding on the earlier sign-off."""
    quotation = await _quotation(
        db_session, customer, rep, product, status=QuotationStatus.SENT, discount="20"
    )
    approved = await recalculate(db_session, quotation)
    db_session.add(
        ApprovalRequest(
            quotation_id=quotation.id,
            blended_risk_score=approved.blended_score,
            max_line_excess=approved.max_line_excess,
            status=ApprovalStatus.APPROVED,
            requested_at=NOW,
            created_by=rep.id,
        )
    )
    await db_session.flush()

    await submit_counter_offer(db_session, quotation, counter_discount_percent=Decimal("15"))
    outcome = await confirm_from_portal(db_session, quotation, actor_id=rep.id)

    assert outcome.re_entered_approval
    assert quotation.status == QuotationStatus.PENDING_APPROVAL


async def test_terms_already_approved_ignores_a_rejected_request(
    db_session: AsyncSession, customer: Customer, rep: User, product: Product
) -> None:
    """A REJECTED request at the same score is not a sign-off."""
    quotation = await _quotation(
        db_session, customer, rep, product, status=QuotationStatus.SENT, discount="20"
    )
    assessment = await recalculate(db_session, quotation)
    db_session.add(
        ApprovalRequest(
            quotation_id=quotation.id,
            blended_risk_score=assessment.blended_score,
            max_line_excess=assessment.max_line_excess,
            status=ApprovalStatus.REJECTED,
            requested_at=NOW,
            created_by=rep.id,
        )
    )
    await db_session.flush()

    assert not await terms_already_approved(db_session, quotation, assessment)


async def test_confirming_generates_billing(
    db_session: AsyncSession, sent_quotation: Quotation, rep: User
) -> None:
    """The customer's confirm must lock in billing exactly as the Admin
    override does — one shared implementation (`quotation.confirm`)."""
    await confirm_from_portal(db_session, sent_quotation, actor_id=rep.id)

    await db_session.refresh(sent_quotation, attribute_names=["billing_schedules"])
    assert len(sent_quotation.billing_schedules) == 1
    assert sent_quotation.billing_schedules[0].schedule_type == "one_time"


async def test_cannot_confirm_an_already_confirmed_quotation(
    db_session: AsyncSession, sent_quotation: Quotation, rep: User
) -> None:
    await confirm_from_portal(db_session, sent_quotation, actor_id=rep.id)

    with pytest.raises(PortalError, match="cannot be confirmed"):
        await confirm_from_portal(db_session, sent_quotation, actor_id=rep.id)


async def test_an_approved_quotation_is_still_negotiable(
    db_session: AsyncSession, customer: Customer, rep: User, product: Product
) -> None:
    """Regression: a quotation that needed approval before it ever reached the
    customer sits at `approved`, not `sent` - PRD B3's own flow never adds a
    separate "send to customer" step after that approval clears. A customer
    must be able to view, counter, AND confirm it, or a rep-approved quote can
    never reach the customer at all. Found live: the very first version of
    `NEGOTIABLE_STATUSES` omitted `approved` entirely.
    """
    quotation = await _quotation(
        db_session, customer, rep, product, status=QuotationStatus.APPROVED, discount="5"
    )

    # Confirming outright must work...
    outcome = await confirm_from_portal(db_session, quotation, actor_id=rep.id)
    assert not outcome.re_entered_approval
    assert quotation.status == QuotationStatus.CONFIRMED


async def test_countering_from_approved_re_enters_negotiation(
    db_session: AsyncSession, customer: Customer, rep: User, product: Product
) -> None:
    """...and so must asking for more than what was approved."""
    quotation = await _quotation(
        db_session, customer, rep, product, status=QuotationStatus.APPROVED, discount="5"
    )

    await submit_counter_offer(db_session, quotation, counter_discount_percent=Decimal("20"))

    assert quotation.status == QuotationStatus.UNDER_NEGOTIATION
    outcome = await confirm_from_portal(db_session, quotation, actor_id=rep.id)
    assert outcome.re_entered_approval
    assert quotation.status == QuotationStatus.PENDING_APPROVAL
