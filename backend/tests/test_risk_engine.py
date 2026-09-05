"""Blended discount risk engine tests.

The engine is the product's signature feature and the one calculation the whole
build is judged on, so these tests are deliberately paranoid.

Structure:
  1. The two worked examples from PRD Section 10, verbatim.
  2. Band boundaries, tested at the exact edge - NOT incidentally via the demo
     scenarios. A band that is off by one cent routes a deal to the wrong
     approver and nothing else would notice.
  3. The single-line Finance gate, likewise tested on its own.
  4. Rounding, empty and degenerate inputs.
  5. Order-level discount distribution.
"""

from decimal import Decimal

import pytest

from app.models.enums import RoleCode
from app.services.risk import (
    LINE_EXCESS_FINANCE_GATE,
    ApprovalBand,
    LineRiskInput,
    assess_lines,
    distribute_order_discount,
    plan_approval_steps,
)

# The seeded approval_chains rows (Locked Business Rules #2b), as values.
SEEDED_BANDS = [
    ApprovalBand(
        min_score=Decimal("0.01"),
        max_score=Decimal("25.00"),
        role_code=RoleCode.SALES_MANAGER,
        step_order=1,
    ),
    ApprovalBand(
        min_score=Decimal("25.00"),
        max_score=None,
        role_code=RoleCode.SALES_MANAGER,
        step_order=1,
    ),
    ApprovalBand(
        min_score=Decimal("25.00"),
        max_score=None,
        role_code=RoleCode.FINANCE_OPS,
        step_order=2,
    ),
]


def line(number, qty, price, given, allowed) -> LineRiskInput:
    return LineRiskInput(
        line_number=number,
        quantity=Decimal(str(qty)),
        unit_list_price=Decimal(str(price)),
        discount_percent=Decimal(str(given)),
        allowed_discount_percent=Decimal(str(allowed)),
    )


def route(assessment):
    return plan_approval_steps(assessment, SEEDED_BANDS, escalation_role_code=RoleCode.FINANCE_OPS)


def roles(steps) -> list[str]:
    return [step.role_code for step in steps]


# ---------------------------------------------------------------------------
# 1. The PRD's own worked examples
# ---------------------------------------------------------------------------


def test_prd_section_10_example_flags_the_quotation() -> None:
    """PRD Section 10, verbatim.

    Gold customer. Laptop (Hardware): 12% given, 15% allowed - fine.
    Setup Service: 18% given, 10% allowed - 8 points over.
    The PRD requires the whole quotation to be flagged because of that line.
    """
    assessment = assess_lines(
        [
            line(1, 1, "100000", "12", "15"),  # Hardware, within ceiling
            line(2, 1, "20000", "18", "10"),  # Service, 8 points over
        ]
    )

    # (0 x 100000 + 8 x 20000) / 120000 = 1.333... -> 1.33
    assert assessment.blended_score == Decimal("1.33")
    assert assessment.max_line_excess == Decimal("8")
    assert assessment.total_order_value == Decimal("120000")
    assert assessment.requires_approval is True
    assert assessment.finance_gate_tripped is False

    assert roles(route(assessment)) == [RoleCode.SALES_MANAGER]


def test_prd_many_small_violations_still_caught() -> None:
    """PRD Section 10: "no single line is badly over its limit, but many lines
    are each a little over ... small violations spread across many lines cannot
    slip through unnoticed"."""
    assessment = assess_lines(
        [
            line(1, 1, "10000", "12", "10"),  # 2 over
            line(2, 1, "10000", "13", "10"),  # 3 over
            line(3, 1, "10000", "12", "10"),  # 2 over
        ]
    )

    # (2 + 3 + 2) x 10000 / 30000 = 2.333... -> 2.33
    assert assessment.blended_score == Decimal("2.33")
    assert assessment.requires_approval is True
    assert roles(route(assessment)) == [RoleCode.SALES_MANAGER]


def test_per_line_breakdown_explains_the_score() -> None:
    """An approver must see which line caused the score, not just a number."""
    assessment = assess_lines(
        [
            line(1, 1, "100000", "12", "15"),
            line(2, 1, "20000", "18", "10"),
        ]
    )

    first, second = assessment.lines
    assert first.is_over_ceiling is False
    assert first.excess_points == Decimal("0")
    assert second.is_over_ceiling is True
    assert second.excess_points == Decimal("8")
    assert second.weighted_excess == Decimal("160000")


# ---------------------------------------------------------------------------
# 2. Band boundaries - tested at the exact edge, on their own
# ---------------------------------------------------------------------------


def test_no_breach_requires_no_approval() -> None:
    """Every line within its ceiling: score 0, straight to fulfillment."""
    assessment = assess_lines(
        [
            line(1, 1, "100000", "12", "15"),
            line(2, 1, "20000", "9", "10"),
        ]
    )

    assert assessment.blended_score == Decimal("0.00")
    assert assessment.requires_approval is False
    assert route(assessment) == ()


def test_discount_exactly_at_ceiling_is_not_a_breach() -> None:
    """A line at exactly its limit is compliant. Off-by-one here would send
    every fully-discounted-to-policy quote for approval."""
    assessment = assess_lines([line(1, 1, "10000", "15", "15")])

    assert assessment.max_line_excess == Decimal("0")
    assert assessment.blended_score == Decimal("0.00")
    assert route(assessment) == ()


def test_lower_band_edge_smallest_possible_breach_routes_to_manager() -> None:
    """score = 0.01 exactly, the bottom of the Manager band."""
    assessment = assess_lines([line(1, 1, "10000", "10.01", "10")])

    assert assessment.blended_score == Decimal("0.01")
    assert roles(route(assessment)) == [RoleCode.SALES_MANAGER]


def test_substantial_breach_below_the_gate_is_manager_only() -> None:
    """A serious but sub-gate breach: 12 points over, well inside [0.01, 25)
    and not enough to trip the >15 single-line gate."""
    assessment = assess_lines([line(1, 1, "10000", "22", "10")])

    assert assessment.blended_score == Decimal("12.00")
    assert assessment.finance_gate_tripped is False
    assert roles(route(assessment)) == [RoleCode.SALES_MANAGER]


@pytest.mark.parametrize(
    "lines",
    [
        [("1", "10000", "34.99", "10")],
        [("1", "10000", "18", "10"), ("1", "50000", "12", "10")],
        [("1", "10000", "25", "10"), ("1", "90000", "30", "15")],
        [("3", "5000", "40", "5"), ("1", "80000", "10", "15")],
    ],
)
def test_blended_score_never_exceeds_the_worst_line(lines) -> None:
    """The score is a value-WEIGHTED MEAN of the per-line excesses, and a
    weighted mean can never exceed its largest input.

    This property is what makes the next test true, so it is asserted directly
    rather than left as an argument in a comment.
    """
    assessment = assess_lines(
        [
            line(i, qty, price, given, allowed)
            for i, (qty, price, given, allowed) in enumerate(lines, start=1)
        ]
    )

    assert assessment.blended_score <= assessment.max_line_excess


def test_finance_band_is_unreachable_without_the_line_gate_firing_first() -> None:
    """FINDING, encoded so it cannot be quietly forgotten.

    Because `score <= max_line_excess` always holds (previous test), a score of
    25 implies some line is at least 25 points over its ceiling - which is more
    than the gate's 15, so the gate has already forced Finance escalation.

    The `>= 25` band therefore never independently decides anything: every
    quotation that could reach it was escalated by the gate first. The band is
    harmless belt-and-braces, but it is doing no work.

    Flagged in PROJECT_CONTEXT.md. If the band is ever retuned below 15 so that
    it CAN fire on its own, this test will fail and should be rewritten - that
    failure is the signal, not a nuisance.
    """
    reaching_the_band = assess_lines([line(1, 1, "10000", "35", "10")])

    assert reaching_the_band.blended_score >= Decimal("25.00")
    assert reaching_the_band.finance_gate_tripped is True, (
        "if this ever fails, the >=25 band has become independently reachable"
    )

    # And the converse: everything the gate does NOT catch scores at or below
    # the gate threshold, so it can never reach the 25 band either.
    below_gate = assess_lines([line(1, 1, "10000", "25", "10"), line(2, 1, "40000", "20", "15")])
    assert below_gate.finance_gate_tripped is False
    assert below_gate.blended_score <= LINE_EXCESS_FINANCE_GATE


def test_exactly_at_finance_band_escalates() -> None:
    """score = 25.00 exactly. The band is >= 25, so this MUST escalate.

    This is the single most likely off-by-one in the whole engine: a `>` where
    the locked rule says `>=` would leave this quotation with Manager approval
    only, and nothing on the demo path would reveal it.
    """
    assessment = assess_lines([line(1, 1, "10000", "35", "10")])

    assert assessment.blended_score == Decimal("25.00")
    assert roles(route(assessment)) == [RoleCode.SALES_MANAGER, RoleCode.FINANCE_OPS]


def test_well_above_finance_band_escalates() -> None:
    assessment = assess_lines([line(1, 1, "10000", "60", "10")])

    assert assessment.blended_score == Decimal("50.00")
    assert roles(route(assessment)) == [RoleCode.SALES_MANAGER, RoleCode.FINANCE_OPS]


def test_finance_step_is_ordered_after_manager() -> None:
    steps = route(assess_lines([line(1, 1, "10000", "35", "10")]))

    assert [step.step_order for step in steps] == [1, 2]
    assert steps[0].role_code == RoleCode.SALES_MANAGER
    assert steps[1].role_code == RoleCode.FINANCE_OPS


# ---------------------------------------------------------------------------
# 3. The single-line Finance gate - tested on its own, not via a demo scenario
# ---------------------------------------------------------------------------


def test_gate_not_tripped_exactly_at_fifteen_points_over() -> None:
    """The rule is `> 15`, strictly. A line exactly 15 points over must NOT
    trip it."""
    assessment = assess_lines([line(1, 1, "10000", "25", "10")])

    assert assessment.max_line_excess == LINE_EXCESS_FINANCE_GATE
    assert assessment.finance_gate_tripped is False


def test_gate_trips_just_above_fifteen_points_over() -> None:
    assessment = assess_lines([line(1, 1, "10000", "25.01", "10")])

    assert assessment.max_line_excess == Decimal("15.01")
    assert assessment.finance_gate_tripped is True


def test_gate_forces_finance_despite_a_low_blended_score() -> None:
    """The gate's whole purpose.

    One small line is 20 points over its ceiling, but it is dwarfed by a large
    compliant line, so the blended score stays far below 25. Without the gate
    this deal would get Manager-only approval and the severe breach would be
    diluted into insignificance - exactly the blind spot a value-weighted
    average has.
    """
    assessment = assess_lines(
        [
            line(1, 100, "10000", "10", "15"),  # 1,000,000 value, compliant
            line(2, 1, "5000", "35", "15"),  # 5,000 value, 20 points over
        ]
    )

    assert assessment.blended_score < Decimal("25.00")
    assert assessment.blended_score == Decimal("0.10")
    assert assessment.finance_gate_tripped is True

    steps = route(assessment)
    assert roles(steps) == [RoleCode.SALES_MANAGER, RoleCode.FINANCE_OPS]

    finance_step = steps[1]
    assert finance_step.forced_by_line_gate is True, (
        "an approver seeing Finance on a 0.10 score must be told why"
    )


def test_score_driven_escalation_is_not_marked_as_gate_forced() -> None:
    """Only escalations the gate actually caused carry the flag."""
    steps = route(assess_lines([line(1, 1, "10000", "35", "10")]))

    assert all(step.forced_by_line_gate is False for step in steps)


def test_gate_does_not_duplicate_an_existing_finance_step() -> None:
    """A quotation that both scores above 25 and trips the gate gets exactly
    one Finance step, not two."""
    assessment = assess_lines([line(1, 1, "10000", "50", "10")])

    assert assessment.blended_score >= Decimal("25.00")
    assert assessment.finance_gate_tripped is True
    assert roles(route(assessment)).count(RoleCode.FINANCE_OPS) == 1


def test_gate_cannot_manufacture_approval_where_there_is_no_breach() -> None:
    """With no line over its ceiling there is nothing to escalate."""
    assessment = assess_lines([line(1, 1, "10000", "5", "15")])

    assert assessment.finance_gate_tripped is False
    assert route(assessment) == ()


# ---------------------------------------------------------------------------
# 4. Rounding and degenerate inputs
# ---------------------------------------------------------------------------


def test_a_real_breach_never_rounds_away_to_zero() -> None:
    """The rounding trap.

    A single line one point over its ceiling inside a very large order produces
    a raw score around 0.0005, which would quantize to 0.00 - a stored score
    saying "no breach" for a quotation that has one, falling outside the
    [0.01, 25) Manager band and escaping approval entirely.

    A breach must always require approval, whatever the rounding does.
    """
    assessment = assess_lines(
        [
            line(1, 1000, "10000", "10", "15"),  # 10,000,000 value, compliant
            line(2, 1, "5000", "11", "10"),  # 5,000 value, 1 point over
        ]
    )

    raw = Decimal("5000") / Decimal("10005000")  # ~0.0005
    assert raw < Decimal("0.005"), "precondition: this really would round to 0.00"

    assert assessment.requires_approval is True
    assert assessment.blended_score == Decimal("0.01"), "floored, not rounded away"
    assert roles(route(assessment)) == [RoleCode.SALES_MANAGER]


def test_score_is_quantized_to_two_places() -> None:
    assessment = assess_lines(
        [
            line(1, 1, "100000", "12", "15"),
            line(2, 1, "20000", "18", "10"),
        ]
    )

    assert assessment.blended_score.as_tuple().exponent == -2


def test_rounding_is_half_up_not_bankers() -> None:
    """Python's built-in round() is banker's rounding and would give 2.66 here.
    The whole system must round one way only."""
    assessment = assess_lines(
        [
            line(1, 1, "10000", "12.665", "10"),
        ]
    )

    assert assessment.blended_score == Decimal("2.67")


def test_empty_quotation_scores_zero_without_dividing_by_zero() -> None:
    """The builder computes this live on a quote with no lines yet."""
    assessment = assess_lines([])

    assert assessment.blended_score == Decimal("0.00")
    assert assessment.total_order_value == Decimal("0")
    assert assessment.requires_approval is False
    assert route(assessment) == ()


def test_zero_value_lines_do_not_divide_by_zero() -> None:
    """A free line that is nonetheless over its ceiling. The denominator is
    zero, so there is no meaningful weighted average - but it must not crash
    the builder."""
    assessment = assess_lines([line(1, 1, "0", "50", "10")])

    assert assessment.total_order_value == Decimal("0")
    assert assessment.blended_score == Decimal("0.00")
    # The breach is still visible on the line, and still demands approval.
    assert assessment.max_line_excess == Decimal("40")
    assert assessment.requires_approval is True


def test_discount_below_ceiling_never_produces_negative_excess() -> None:
    """A generous ceiling must not create negative excess that offsets a real
    breach elsewhere in the order."""
    assessment = assess_lines(
        [
            line(1, 1, "10000", "0", "15"),  # 15 points *under*
            line(2, 1, "10000", "12", "10"),  # 2 points over
        ]
    )

    assert assessment.lines[0].excess_points == Decimal("0")
    assert assessment.blended_score == Decimal("1.00")
    assert assessment.requires_approval is True


# ---------------------------------------------------------------------------
# 5. Order-level discount distribution
# ---------------------------------------------------------------------------


def test_order_discount_is_scored_per_line_against_each_ceiling() -> None:
    """Locked Business Rules #4, worked example.

    12% at order level passes a Gold 15% tier cap, but the Services line has a
    10% ceiling of its own. Distributing the discount is what catches it.
    """
    lines = [
        line(1, 1, "100000", "0", "15"),  # Hardware, ceiling 15
        line(2, 1, "20000", "0", "10"),  # Services, ceiling 10
    ]

    distributed = distribute_order_discount(lines, Decimal("12"))
    assessment = assess_lines(distributed)

    assert [item.discount_percent for item in distributed] == [
        Decimal("12"),
        Decimal("12"),
    ]
    # (0 x 100000 + 2 x 20000) / 120000 = 0.333... -> 0.33
    assert assessment.blended_score == Decimal("0.33")
    assert assessment.requires_approval is True
    assert roles(route(assessment)) == [RoleCode.SALES_MANAGER]


def test_order_discount_overwrites_existing_line_discounts() -> None:
    """Overwrite, never stack: one discount number per line, always."""
    lines = [
        line(1, 1, "10000", "10", "15"),
        line(2, 1, "10000", "5", "10"),
    ]

    distributed = distribute_order_discount(lines, Decimal("12"))

    assert [item.discount_percent for item in distributed] == [
        Decimal("12"),
        Decimal("12"),
    ]
    # Not 22, not 20.8 - stacking is explicitly rejected.
    assert all(item.discount_percent == Decimal("12") for item in distributed)


def test_order_discount_preserves_each_line_own_ceiling() -> None:
    """Distribution must not flatten ceilings along with discounts."""
    lines = [
        line(1, 1, "10000", "0", "15"),
        line(2, 1, "10000", "0", "10"),
        line(3, 1, "10000", "0", "8"),
    ]

    distributed = distribute_order_discount(lines, Decimal("12"))

    assert [item.allowed_discount_percent for item in distributed] == [
        Decimal("15"),
        Decimal("10"),
        Decimal("8"),
    ]


@pytest.mark.parametrize(
    "given,allowed,expected_excess",
    [
        ("18", "10", "8"),
        ("10", "10", "0"),
        ("5", "10", "0"),
        ("100", "0", "100"),
        ("0", "0", "0"),
    ],
)
def test_line_excess_arithmetic(given, allowed, expected_excess) -> None:
    assessment = assess_lines([line(1, 1, "1000", given, allowed)])

    assert assessment.max_line_excess == Decimal(expected_excess)
