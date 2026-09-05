"""Upsell ranking tests (PRD A6, B5).

Pure logic only, matching risk.py's testing style: `rank_suggestions()`,
`product_margin_percent()` and `margin_delta_if_added()` take plain numbers
and return plain numbers, so every case here is a hand-computed expectation
against no database at all.
"""

from decimal import Decimal

from app.services.upsell import (
    UpsellCandidate,
    margin_delta_if_added,
    product_margin_percent,
    rank_suggestions,
)


def _candidate(
    product_id: int,
    *,
    promoted: bool = False,
    score: str = "5.0",
    floor: str = "0",
    own_margin: str = "50",
    delta: str = "1.0",
) -> UpsellCandidate:
    return UpsellCandidate(
        suggested_product_id=product_id,
        is_promoted=promoted,
        co_purchase_score=Decimal(score),
        min_margin_percent=Decimal(floor),
        product_margin_percent=Decimal(own_margin),
        margin_delta_percent=Decimal(delta),
    )


# ---------------------------------------------------------------------------
# rank_suggestions
# ---------------------------------------------------------------------------


def test_promoted_ranks_above_a_higher_score() -> None:
    """is_promoted is the PRIMARY key (app/models/upsell.py's own docstring),
    not merely a tiebreaker."""
    promoted = _candidate(1, promoted=True, score="1.0")
    higher_score = _candidate(2, promoted=False, score="9.9")

    ranked = rank_suggestions([higher_score, promoted])

    assert [c.suggested_product_id for c in ranked] == [1, 2]


def test_co_purchase_score_breaks_ties_within_the_same_promotion_tier() -> None:
    low = _candidate(1, score="3.0")
    high = _candidate(2, score="8.0")

    ranked = rank_suggestions([low, high])

    assert [c.suggested_product_id for c in ranked] == [2, 1]


def test_below_margin_floor_is_suppressed_entirely() -> None:
    """PRD A6: "only healthy margin suggestions surface" - not de-prioritized,
    removed."""
    healthy = _candidate(1, own_margin="30", floor="20")
    unhealthy = _candidate(2, own_margin="15", floor="20")

    ranked = rank_suggestions([healthy, unhealthy])

    assert [c.suggested_product_id for c in ranked] == [1]


def test_exactly_at_the_floor_is_not_suppressed() -> None:
    at_floor = _candidate(1, own_margin="20", floor="20")

    assert rank_suggestions([at_floor]) == [at_floor]


def test_empty_candidates_ranks_to_empty() -> None:
    assert rank_suggestions([]) == []


def test_all_suppressed_ranks_to_empty() -> None:
    only_unhealthy = _candidate(1, own_margin="5", floor="20")

    assert rank_suggestions([only_unhealthy]) == []


# ---------------------------------------------------------------------------
# product_margin_percent
# ---------------------------------------------------------------------------


def test_product_margin_percent_basic() -> None:
    # 25000 list, 16000 cost -> 9000/25000 = 36%
    assert product_margin_percent(Decimal("25000"), Decimal("16000")) == Decimal("36.00")


def test_product_margin_percent_zero_list_price_is_zero_not_a_crash() -> None:
    assert product_margin_percent(Decimal("0"), Decimal("0")) == Decimal("0")


def test_product_margin_percent_cost_above_list_is_negative() -> None:
    """A loss-leader product has a real negative margin - not clamped away,
    since a caller comparing it against a positive floor must see it fail."""
    assert product_margin_percent(Decimal("100"), Decimal("120")) == Decimal("-20.00")


# ---------------------------------------------------------------------------
# margin_delta_if_added
# ---------------------------------------------------------------------------


def test_margin_delta_of_a_higher_margin_addition_is_positive() -> None:
    """Order currently at 1000 net revenue, 300 margin (30%). Adding a
    product priced 500 costing 100 (80% margin) pulls the blended margin up."""
    delta = margin_delta_if_added(
        current_net_revenue=Decimal("1000"),
        current_margin_amount=Decimal("300"),
        added_list_price=Decimal("500"),
        added_cost_price=Decimal("100"),
    )

    # new revenue 1500, new margin 300+400=700 -> 46.67%; delta = +16.67
    assert delta == Decimal("16.67")


def test_margin_delta_of_a_lower_margin_addition_is_negative() -> None:
    delta = margin_delta_if_added(
        current_net_revenue=Decimal("1000"),
        current_margin_amount=Decimal("500"),  # 50% margin
        added_list_price=Decimal("1000"),
        added_cost_price=Decimal("900"),  # 10% margin on the addition
    )

    # new revenue 2000, new margin 500+100=600 -> 30%; delta = -20
    assert delta == Decimal("-20.00")


def test_margin_delta_with_zero_current_revenue_does_not_crash() -> None:
    """An order with nothing on it yet (net_revenue 0) must not divide by
    zero - the "current" side of the comparison is just defined as 0%."""
    delta = margin_delta_if_added(
        current_net_revenue=Decimal("0"),
        current_margin_amount=Decimal("0"),
        added_list_price=Decimal("100"),
        added_cost_price=Decimal("40"),
    )

    # new revenue 100, new margin 60 -> 60%; delta = +60 (from a defined 0%)
    assert delta == Decimal("60.00")
