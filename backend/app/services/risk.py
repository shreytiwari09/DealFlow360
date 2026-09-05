"""Blended discount risk engine and approval routing.

PROJECT_CONTEXT.md "Locked Business Rules" #1, #2 and #4 are authoritative for
the semantics. This module is their implementation and must not drift from
them.

Everything here is pure: no database, no I/O, no ORM objects. Callers load
rows, convert them to the small input dataclasses below, and persist whatever
comes back. That keeps the arithmetic testable in isolation - which matters,
because this is the one calculation the whole product is judged on.

All money and percentage arithmetic uses `Decimal`. Never float: binary
floating point cannot represent 0.1, and a discount engine that is off by a
hundredth of a percent at a band boundary routes a deal to the wrong approver.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

# The single-line Finance gate (Locked Business Rules #2a). Any one line more
# than this many percentage points over its own ceiling forces Finance
# escalation regardless of the blended score.
#
# Deliberately a named constant rather than a configurable row, unlike the
# score bands: PRD A3 requires the *chain* to be Admin-editable, whereas this
# gate is a guard rail we added on top. Keeping it in one place keeps it
# auditable and unit-testable. If it ever needs to be configurable, move it to
# a settings row - do not scatter the number through the codebase.
LINE_EXCESS_FINANCE_GATE = Decimal("15")

# Scores are stored as NUMERIC(6,2), so this is the smallest representable
# non-zero score. See `_quantize_score` for why that matters.
MIN_REPRESENTABLE_SCORE = Decimal("0.01")

_TWO_PLACES = Decimal("0.01")


@dataclass(frozen=True)
class LineRiskInput:
    """One quotation line, reduced to only what the score needs."""

    line_number: int
    quantity: Decimal
    unit_list_price: Decimal
    discount_percent: Decimal
    # The ceiling that applies to this line, from discount_tiers keyed by
    # (customer tier x product category).
    allowed_discount_percent: Decimal


@dataclass(frozen=True)
class LineRisk:
    """Per-line breakdown, so an approver sees *why* a quote scored what it did."""

    line_number: int
    line_value: Decimal
    excess_points: Decimal
    weighted_excess: Decimal

    @property
    def is_over_ceiling(self) -> bool:
        return self.excess_points > 0


@dataclass(frozen=True)
class RiskAssessment:
    blended_score: Decimal
    max_line_excess: Decimal
    total_order_value: Decimal
    lines: tuple[LineRisk, ...]

    @property
    def requires_approval(self) -> bool:
        """True when any line breached its own ceiling.

        Derived from `max_line_excess`, NOT from `blended_score > 0`. The two
        are equivalent on the exact arithmetic, but the stored score is rounded
        to two places and a tiny breach inside a large order can round toward
        zero. Deriving the trigger from the unrounded per-line excess keeps the
        invariant "a breach always requires approval" true regardless of
        rounding. See `_quantize_score`.
        """
        return self.max_line_excess > 0

    @property
    def finance_gate_tripped(self) -> bool:
        """True when one line alone is severe enough to demand Finance."""
        return self.max_line_excess > LINE_EXCESS_FINANCE_GATE


@dataclass(frozen=True)
class ApprovalBand:
    """One row of `approval_chains`, as a plain value.

    The band is half-open: `min_score <= score < max_score`, with `max_score`
    of None meaning unbounded.
    """

    min_score: Decimal
    max_score: Decimal | None
    role_code: str
    step_order: int

    def contains(self, score: Decimal) -> bool:
        if score < self.min_score:
            return False
        return self.max_score is None or score < self.max_score


@dataclass(frozen=True)
class ApprovalStepPlan:
    """A step the router says must exist, before anything is written."""

    step_order: int
    role_code: str
    # True when this step is present only because of the single-line gate, not
    # because the blended score reached its band. Worth surfacing to an
    # approver: a low score with Finance attached otherwise looks like a bug.
    forced_by_line_gate: bool = False


def _quantize_score(raw: Decimal) -> Decimal:
    """Round a raw score to the 2 decimal places the column stores.

    ROUND_HALF_UP, matching the proration rule, so the whole system rounds one
    way and only one way.

    The floor matters. A single line one point over its ceiling inside a very
    large order produces a raw score like 0.004, which would quantize to 0.00 -
    a stored score that says "no breach" for a quotation that certainly has
    one, and that falls outside the [0.01, 25) Manager band. Rather than let a
    real breach round away to nothing, any non-zero raw score is floored at the
    smallest value the column can represent.
    """
    if raw > 0:
        quantized = raw.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)
        return max(quantized, MIN_REPRESENTABLE_SCORE)
    return Decimal("0.00")


def assess_lines(lines: list[LineRiskInput]) -> RiskAssessment:
    """Compute the blended discount risk score for a quotation.

                         SUM( line_excess_i x line_value_i )
    BLENDED_RISK_SCORE = ------------------------------------
                              total_order_value

    where `line_excess_i = max(0, discount_given_i - ceiling_i)` in percentage
    points and `line_value_i` is the PRE-discount list value of the line.

    The result is the value-weighted average number of points of discount given
    beyond policy, across the order. Equivalently: the total currency
    discounted beyond policy as a percentage of order list value.
    """
    breakdown: list[LineRisk] = []
    weighted_total = Decimal("0")
    order_value = Decimal("0")
    max_excess = Decimal("0")

    for line in lines:
        line_value = line.quantity * line.unit_list_price
        excess = max(Decimal("0"), line.discount_percent - line.allowed_discount_percent)
        weighted = excess * line_value

        order_value += line_value
        weighted_total += weighted
        max_excess = max(max_excess, excess)

        breakdown.append(
            LineRisk(
                line_number=line.line_number,
                line_value=line_value,
                excess_points=excess,
                weighted_excess=weighted,
            )
        )

    # A quotation with no lines, or one whose lines are all zero-value, has no
    # denominator. Guarding here rather than letting it raise keeps the live
    # score on a half-built quotation from blowing up the builder screen.
    if order_value > 0:
        raw_score = weighted_total / order_value
    else:
        raw_score = Decimal("0")

    return RiskAssessment(
        blended_score=_quantize_score(raw_score),
        max_line_excess=max_excess,
        total_order_value=order_value,
        lines=tuple(breakdown),
    )


def plan_approval_steps(
    assessment: RiskAssessment,
    bands: list[ApprovalBand],
    *,
    escalation_role_code: str,
) -> tuple[ApprovalStepPlan, ...]:
    """Decide which approvals a quotation needs.

    Resolution order (Locked Business Rules #2):

        no line over its ceiling      -> no approval at all
        otherwise                     -> every band matching the score
        plus, if the line gate tripped-> an escalation step if not already there

    `bands` comes from the `approval_chains` table, so the score boundaries are
    configuration and are never hardcoded here. The gate is applied on top of
    whatever the bands returned: it guarantees the escalation role is present
    without assuming what the band values happen to be, so retuning the bands
    cannot silently disable it.
    """
    if not assessment.requires_approval:
        return ()

    matched = sorted(
        (band for band in bands if band.contains(assessment.blended_score)),
        key=lambda band: band.step_order,
    )

    steps = [
        ApprovalStepPlan(step_order=band.step_order, role_code=band.role_code) for band in matched
    ]

    if assessment.finance_gate_tripped and not any(
        step.role_code == escalation_role_code for step in steps
    ):
        # Reuse the configured definition of the escalation step rather than
        # inventing one, so its role always matches what an Admin configured.
        escalation_bands = [band for band in bands if band.role_code == escalation_role_code]
        if escalation_bands:
            next_order = max((step.step_order for step in steps), default=0) + 1
            steps.append(
                ApprovalStepPlan(
                    step_order=next_order,
                    role_code=escalation_role_code,
                    forced_by_line_gate=True,
                )
            )

    return tuple(steps)


def distribute_order_discount(
    lines: list[LineRiskInput], order_discount_percent: Decimal
) -> list[LineRiskInput]:
    """Apply an order-level discount by writing it onto every line.

    Locked Business Rules #4: an order-level discount is distributed, not
    scored separately, and it OVERWRITES any existing per-line discount. There
    is exactly one discount number per line, always.

    Because every line receives the same percentage, the discount *amount* is
    automatically proportional to line value - "uniform percentage" and
    "pro-rata by value" are the same operation. The caller is responsible for
    warning the user before discarding manually-set line discounts.
    """
    return [
        LineRiskInput(
            line_number=line.line_number,
            quantity=line.quantity,
            unit_list_price=line.unit_list_price,
            discount_percent=order_discount_percent,
            allowed_discount_percent=line.allowed_discount_percent,
        )
        for line in lines
    ]
