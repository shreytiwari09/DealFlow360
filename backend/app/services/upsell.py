"""Upsell / cross-sell ranking (PRD A6, B5).

A deterministic lookup table, not ML (PLAN.md Section 20 rules that out
explicitly) — `app/models/upsell.py`'s own docstring gives the ranking order
this module implements:

    1. `is_promoted` on the suggested product ranks first
    2. `co_purchase_score` breaks ties within that
    3. a margin floor suppresses anything unhealthy outright

Pure ranking/filtering lives here, exactly the shape `risk.py` and
`fulfillment.py` use: no database, no I/O, fully unit-testable. The endpoint
does the querying and hands this module plain numbers.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

_PERCENT = Decimal("0.01")


def _percent(value: Decimal) -> Decimal:
    return value.quantize(_PERCENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class UpsellCandidate:
    suggested_product_id: int
    is_promoted: bool
    co_purchase_score: Decimal
    # The floor from `upsell_rules.min_margin_percent`.
    min_margin_percent: Decimal
    # The suggested product's OWN margin — (list_price - cost_price) /
    # list_price — compared against the floor. See PROJECT_CONTEXT.md's
    # note on this module for why this reading was chosen over the
    # alternative (comparing the floor to the order-wide margin *delta*
    # instead): a floor of "10" or "20" only makes sense as a plausible
    # product-margin percentage, not as a swing in the order's blended
    # margin, which is normally a few points at most.
    product_margin_percent: Decimal
    # PRD B5's own separate display field: how the QUOTATION's blended
    # margin would move if this suggestion were added at qty 1, 0% discount
    # - purely informational, not part of the suppression rule above.
    margin_delta_percent: Decimal


def rank_suggestions(candidates: list[UpsellCandidate]) -> list[UpsellCandidate]:
    """Suppress anything below its margin floor, then rank the rest.

    PRD A6: "Set minimum margin thresholds so only healthy margin suggestions
    surface" — that is a suppression rule, not a display sort key, so it is
    applied before ranking, not folded into it.
    """
    eligible = [c for c in candidates if c.product_margin_percent >= c.min_margin_percent]
    return sorted(eligible, key=lambda c: (not c.is_promoted, -c.co_purchase_score))


def product_margin_percent(list_price: Decimal, cost_price: Decimal) -> Decimal:
    if list_price <= 0:
        return Decimal("0")
    return _percent((list_price - cost_price) / list_price * Decimal("100"))


def margin_delta_if_added(
    *,
    current_net_revenue: Decimal,
    current_margin_amount: Decimal,
    added_list_price: Decimal,
    added_cost_price: Decimal,
) -> Decimal:
    """The live margin-impact figure PRD B5 shows next to each suggestion.

    Simulates exactly what clicking "+ Add" does in the builder: one new line
    at quantity 1 and 0% discount (`addProduct` in QuotationDetail.tsx never
    pre-fills a discount), so the number shown is the number that would
    actually appear a moment after the click — never a guess computed some
    other way.
    """
    current_margin_percent = (
        _percent(current_margin_amount / current_net_revenue * Decimal("100"))
        if current_net_revenue > 0
        else Decimal("0")
    )

    new_net_revenue = current_net_revenue + added_list_price
    new_margin_amount = current_margin_amount + (added_list_price - added_cost_price)
    new_margin_percent = (
        _percent(new_margin_amount / new_net_revenue * Decimal("100"))
        if new_net_revenue > 0
        else Decimal("0")
    )

    return _percent(new_margin_percent - current_margin_percent)
