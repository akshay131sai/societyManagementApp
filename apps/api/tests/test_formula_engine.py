"""Formula engine — the authority for money.

Pure unit tests: no database, no fixtures, no network. If these are wrong,
people are billed wrong, so they are the most detailed suite in the project.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from app.engines.formula import (
    EvaluationContext,
    EvaluationError,
    FormulaDefinition,
    engine,
    validator,
)
from app.engines.formula.validator import FormulaErrorCode


def define(**kwargs: Any) -> FormulaDefinition:
    return FormulaDefinition.model_validate(kwargs)


def one(node: dict[str, Any], **ctx: Any) -> Decimal:
    """Evaluate a single expression as a one-line formula."""
    definition = define(line_items=[{"code": "X", "label": "x", "node": node}])
    values = {k: Decimal(str(v)) if isinstance(v, (int, float, str)) else v for k, v in ctx.items()}
    return engine.evaluate(definition, EvaluationContext(values)).total


V = lambda v: {"type": "VALUE", "value": str(v)}  # noqa: E731
F = lambda f: {"type": "FIELD", "field": f}  # noqa: E731


# --------------------------------------------------------------------------- #
# Arithmetic
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "op,args,expected",
    [
        ("ADD", [1, 2, 3], "6.00"),
        ("SUBTRACT", [10, 3, 2], "5.00"),
        ("MULTIPLY", [3, 4], "12.00"),
        ("MULTIPLY", [2, 3, 4], "24.00"),
        ("DIVIDE", [10, 4], "2.50"),
        ("DIVIDE", [100, 2, 5], "10.00"),
        ("MIN", [5, 2, 9], "2.00"),
        ("MAX", [5, 2, 9], "9.00"),
    ],
)
def test_arithmetic(op: str, args: list[int], expected: str) -> None:
    assert one({"type": op, "children": [V(a) for a in args]}) == Decimal(expected)


def test_nesting_controls_precedence() -> None:
    """There is no operator precedence — the tree is the precedence."""
    # 1500 + (1200 * 2.5)
    node = {
        "type": "ADD",
        "children": [V(1500), {"type": "MULTIPLY", "children": [V(1200), V("2.5")]}],
    }
    assert one(node) == Decimal("4500.00")


def test_percentage() -> None:
    assert one({"type": "PERCENTAGE", "children": [V(4500), V(10)]}) == Decimal("450.00")


def test_round_node() -> None:
    node = {"type": "ROUND", "children": [V("10.567")], "decimal_places": 1}
    assert one(node) == Decimal("10.60")


def test_division_by_zero_at_runtime() -> None:
    """A *field* that happens to be zero is caught at evaluation, per flat."""
    definition = define(
        line_items=[
            {
                "code": "X",
                "label": "x",
                "node": {"type": "DIVIDE", "children": [V(100), F("resident_count")]},
            }
        ]
    )
    with pytest.raises(EvaluationError) as exc:
        engine.evaluate(definition, EvaluationContext({"resident_count": Decimal(0)}))
    assert exc.value.code == "DIVISION_BY_ZERO"


# --------------------------------------------------------------------------- #
# Decimal policy
# --------------------------------------------------------------------------- #


def test_money_is_decimal_not_float() -> None:
    """0.1 + 0.2 must be 0.30, not 0.30000000000000004."""
    assert one({"type": "ADD", "children": [V("0.1"), V("0.2")]}) == Decimal("0.30")


def test_intermediate_results_are_not_rounded() -> None:
    """Rounding intermediates would lose paise on every multiplication."""
    # (1/3) * 3 must be 1.00, not 0.99
    node = {
        "type": "MULTIPLY",
        "children": [{"type": "DIVIDE", "children": [V(1), V(3)]}, V(3)],
    }
    assert one(node) == Decimal("1.00")


def test_rounding_is_half_up_not_bankers() -> None:
    """Python's default ROUND_HALF_EVEN would make 2.5 -> 2, which no Indian
    society's accountant expects."""
    assert one(V("0.125")) == Decimal("0.13")
    assert one(V("0.135")) == Decimal("0.14")


def test_line_items_sum_to_the_printed_total() -> None:
    """The total is the sum of the ROUNDED lines, so the printed rows add up.

    Summing unrounded values and rounding once would produce a bill that looks
    off by a paisa.
    """
    definition = define(
        line_items=[
            {"code": "A", "label": "a", "node": V("10.005")},
            {"code": "B", "label": "b", "node": V("10.005")},
            {"code": "C", "label": "c", "node": V("10.005")},
        ]
    )
    result = engine.evaluate(definition, EvaluationContext({}))
    assert [li.amount for li in result.line_items] == [Decimal("10.01")] * 3
    assert result.total == Decimal("30.03")
    assert sum(li.amount for li in result.line_items) == result.total


def test_credits_subtract_from_the_total() -> None:
    definition = define(
        line_items=[
            {"code": "A", "label": "a", "node": V(1000)},
            {"code": "D", "label": "discount", "node": V(100), "is_credit": True},
        ]
    )
    result = engine.evaluate(definition, EvaluationContext({}))
    assert result.subtotal == Decimal("1000.00")
    assert result.credits == Decimal("100.00")
    assert result.total == Decimal("900.00")


# --------------------------------------------------------------------------- #
# Slabs — Indian utility tariffs
# --------------------------------------------------------------------------- #


SLABS = [{"up_to": "10", "rate": "20"}, {"up_to": "25", "rate": "35"}, {"up_to": None, "rate": "50"}]


def slab(quantity: str, mode: str = "PROGRESSIVE") -> Decimal:
    return one(
        {
            "type": "SLAB",
            "mode": mode,
            "input": F("water_consumption"),
            "slabs": SLABS,
        },
        water_consumption=quantity,
    )


@pytest.mark.parametrize(
    "kl,expected,why",
    [
        ("0", "0.00", "no consumption"),
        ("8", "160.00", "8 x 20, entirely in band 1"),
        ("10", "200.00", "exactly the band-1 boundary"),
        ("11", "235.00", "10 x 20 + 1 x 35, crossing into band 2"),
        ("18", "480.00", "10 x 20 + 8 x 35"),
        ("25", "725.00", "10 x 20 + 15 x 35, exactly the band-2 boundary"),
        ("40", "1475.00", "10 x 20 + 15 x 35 + 15 x 50, into the open band"),
    ],
)
def test_progressive_slabs(kl: str, expected: str, why: str) -> None:
    assert slab(kl) == Decimal(expected), why


@pytest.mark.parametrize(
    "kl,expected",
    [("8", "160.00"), ("18", "630.00"), ("40", "2000.00")],
)
def test_flat_slabs_charge_the_whole_quantity_at_one_rate(kl: str, expected: str) -> None:
    assert slab(kl, mode="FLAT") == Decimal(expected)


def test_slab_trace_explains_the_bands() -> None:
    definition = define(
        line_items=[
            {
                "code": "W",
                "label": "Water",
                "node": {"type": "SLAB", "input": F("water_consumption"), "slabs": SLABS},
            }
        ]
    )
    result = engine.evaluate(
        definition, EvaluationContext({"water_consumption": Decimal(18)})
    )
    detail = next(t.detail for t in result.trace if t.node_type == "SLAB")
    assert "10" in detail and "8" in detail


# --------------------------------------------------------------------------- #
# Conditionals
# --------------------------------------------------------------------------- #


def test_if_takes_the_true_branch() -> None:
    node = {
        "type": "IF",
        "children": [
            {"type": "GT", "children": [F("flat_area"), V(1000)]},
            V(500),
            V(100),
        ],
    }
    assert one(node, flat_area=1200) == Decimal("500.00")
    assert one(node, flat_area=800) == Decimal("100.00")


def test_untaken_branch_is_not_evaluated() -> None:
    """A division by zero in the branch not taken must not fail the bill."""
    node = {
        "type": "IF",
        "children": [
            {"type": "GT", "children": [F("flat_area"), V(0)]},
            V(500),
            {"type": "DIVIDE", "children": [V(1), F("resident_count")]},
        ],
    }
    assert one(node, flat_area=1200, resident_count=0) == Decimal("500.00")


def test_boolean_field_as_a_condition() -> None:
    node = {"type": "IF", "children": [F("is_vacant"), V(0), V(1000)]}
    definition = define(line_items=[{"code": "X", "label": "x", "node": node}])
    assert engine.evaluate(definition, EvaluationContext({"is_vacant": True})).total == Decimal("0.00")
    assert engine.evaluate(definition, EvaluationContext({"is_vacant": False})).total == Decimal("1000.00")


def test_and_or_not() -> None:
    big = {"type": "GT", "children": [F("flat_area"), V(1000)]}
    rented = F("is_rented")

    both = {"type": "IF", "children": [{"type": "AND", "children": [big, rented]}, V(1), V(0)]}
    either = {"type": "IF", "children": [{"type": "OR", "children": [big, rented]}, V(1), V(0)]}
    neither = {"type": "IF", "children": [{"type": "NOT", "children": [big]}, V(1), V(0)]}

    for node, area, is_rented, expected in [
        (both, 1200, True, "1.00"),
        (both, 1200, False, "0.00"),
        (either, 800, True, "1.00"),
        (either, 800, False, "0.00"),
        (neither, 800, False, "1.00"),
    ]:
        definition = define(line_items=[{"code": "X", "label": "x", "node": node}])
        result = engine.evaluate(
            definition,
            EvaluationContext({"flat_area": Decimal(area), "is_rented": is_rented}),
        )
        assert result.total == Decimal(expected), (node, area, is_rented)


def test_text_comparison() -> None:
    node = {
        "type": "IF",
        "children": [
            {"type": "EQ", "children": [F("flat_type"), {"type": "TEXT", "text": "3BHK"}]},
            V(6000),
            V(4000),
        ],
    }
    for flat_type, expected in [("3BHK", "6000.00"), ("2BHK", "4000.00")]:
        definition = define(line_items=[{"code": "X", "label": "x", "node": node}])
        result = engine.evaluate(definition, EvaluationContext({"flat_type": flat_type}))
        assert result.total == Decimal(expected)


# --------------------------------------------------------------------------- #
# Context
# --------------------------------------------------------------------------- #


def test_missing_field_falls_back_to_its_default() -> None:
    """A flat with no water reading bills as zero consumption rather than
    aborting a 400-flat run."""
    assert one(F("water_consumption")) == Decimal("0.00")


def test_custom_parameters() -> None:
    definition = define(line_items=[{"code": "X", "label": "x", "node": F("custom.club_fee")}])
    result = engine.evaluate(
        definition, EvaluationContext({}, {"club_fee": Decimal("750")})
    )
    assert result.total == Decimal("750.00")


def test_snapshot_records_only_what_was_read() -> None:
    """A snapshot of every possible field would make bill diffs unreadable."""
    context = EvaluationContext(
        {"flat_area": Decimal(1200), "water_consumption": Decimal(5), "pet_count": Decimal(2)}
    )
    definition = define(line_items=[{"code": "X", "label": "x", "node": F("flat_area")}])
    engine.evaluate(definition, context)

    assert set(context.snapshot()) == {"flat_area"}
    assert "pet_count" not in context.snapshot()


def test_unknown_field_at_evaluation_raises() -> None:
    context = EvaluationContext({})
    with pytest.raises(EvaluationError) as exc:
        context.get("not_a_field")
    assert exc.value.code == "UNKNOWN_FIELD"


# --------------------------------------------------------------------------- #
# Trace
# --------------------------------------------------------------------------- #


def test_trace_records_each_step() -> None:
    definition = define(
        line_items=[
            {
                "code": "A",
                "label": "Area",
                "node": {"type": "MULTIPLY", "children": [F("flat_area"), V("2.5")]},
            }
        ]
    )
    result = engine.evaluate(definition, EvaluationContext({"flat_area": Decimal(1200)}))
    kinds = [t.node_type for t in result.trace]
    assert "FIELD" in kinds and "MULTIPLY" in kinds
    assert any(t.result == "3000.0" or t.result.startswith("3000") for t in result.trace)


def test_trace_can_be_disabled() -> None:
    definition = define(line_items=[{"code": "X", "label": "x", "node": F("flat_area")}])
    result = engine.evaluate(
        definition, EvaluationContext({"flat_area": Decimal(1)}), collect_trace=False
    )
    assert result.trace == []


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #


def codes(definition: FormulaDefinition) -> set[str]:
    return {e.code.value for e in validator.validate(definition)}


def test_valid_formula_has_no_errors() -> None:
    definition = define(
        line_items=[
            {"code": "BASE", "label": "Base", "node": F("base_maintenance")},
            {
                "code": "AREA",
                "label": "Area",
                "node": {"type": "MULTIPLY", "children": [F("flat_area"), V("2.5")]},
            },
        ]
    )
    assert validator.validate(definition) == []


def test_unknown_field_rejected() -> None:
    definition = define(line_items=[{"code": "X", "label": "x", "node": F("made_up")}])
    assert FormulaErrorCode.UNKNOWN_FIELD.value in codes(definition)


def test_literal_division_by_zero_rejected() -> None:
    definition = define(
        line_items=[
            {"code": "X", "label": "x", "node": {"type": "DIVIDE", "children": [V(1), V(0)]}}
        ]
    )
    assert FormulaErrorCode.DIVISION_BY_ZERO.value in codes(definition)


def test_empty_formula_rejected() -> None:
    assert FormulaErrorCode.EMPTY_FORMULA.value in codes(define(line_items=[]))


def test_duplicate_line_item_codes_rejected() -> None:
    definition = define(
        line_items=[
            {"code": "SAME", "label": "a", "node": V(1)},
            {"code": "SAME", "label": "b", "node": V(2)},
        ]
    )
    assert FormulaErrorCode.DUPLICATE_LINE_ITEM.value in codes(definition)


def test_number_as_condition_rejected() -> None:
    """IF(flat_area, ...) is almost always a mistake, and treating a non-zero
    amount as true would silently bill people for it."""
    definition = define(
        line_items=[
            {
                "code": "X",
                "label": "x",
                "node": {"type": "IF", "children": [F("flat_area"), V(1), V(2)]},
            }
        ]
    )
    assert FormulaErrorCode.TYPE_MISMATCH.value in codes(definition)


def test_text_ordering_comparison_rejected() -> None:
    definition = define(
        line_items=[
            {
                "code": "X",
                "label": "x",
                "node": {
                    "type": "IF",
                    "children": [
                        {"type": "GT", "children": [F("flat_type"), {"type": "TEXT", "text": "A"}]},
                        V(1),
                        V(2),
                    ],
                },
            }
        ]
    )
    assert FormulaErrorCode.TYPE_MISMATCH.value in codes(definition)


@pytest.mark.parametrize(
    "slabs,why",
    [
        ([{"up_to": "25", "rate": "1"}, {"up_to": "10", "rate": "2"}, {"up_to": None, "rate": "3"}],
         "boundaries must increase"),
        ([{"up_to": "10", "rate": "1"}, {"up_to": "10", "rate": "2"}, {"up_to": None, "rate": "3"}],
         "duplicate boundary"),
        ([{"up_to": None, "rate": "1"}, {"up_to": "10", "rate": "2"}],
         "open band must be last"),
        ([{"up_to": "10", "rate": "1"}],
         "last band must be open, or consumption above it is free"),
        ([{"up_to": "10", "rate": "-5"}, {"up_to": None, "rate": "3"}],
         "negative rate"),
    ],
)
def test_bad_slab_tables_rejected(slabs: list[dict[str, Any]], why: str) -> None:
    definition = define(
        line_items=[
            {
                "code": "X",
                "label": "x",
                "node": {"type": "SLAB", "input": F("water_consumption"), "slabs": slabs},
            }
        ]
    )
    assert FormulaErrorCode.INVALID_SLAB_TABLE.value in codes(definition), why


def test_excessive_nesting_rejected() -> None:
    node: dict[str, Any] = V(1)
    for _ in range(40):
        node = {"type": "ADD", "children": [node, V(1)]}
    definition = define(line_items=[{"code": "X", "label": "x", "node": node}])
    assert FormulaErrorCode.EXCESSIVE_NESTING.value in codes(definition)


def test_shared_node_reference_rejected() -> None:
    """A hand-built AST that reuses one node would evaluate exponentially."""
    from app.engines.formula.nodes import ArithmeticNode, ValueNode

    shared = ValueNode(value=Decimal(1))
    definition = FormulaDefinition(
        line_items=[],
        root=ArithmeticNode(type="ADD", children=[shared, shared]),  # type: ignore[arg-type]
    )
    assert FormulaErrorCode.CIRCULAR_REFERENCE.value in codes(definition)


def test_non_finite_literal_rejected_at_parse_time() -> None:
    from pydantic import ValidationError as PydanticError

    with pytest.raises(PydanticError):
        define(line_items=[{"code": "X", "label": "x", "node": {"type": "VALUE", "value": "NaN"}}])


def test_unknown_node_type_rejected_at_parse_time() -> None:
    from pydantic import ValidationError as PydanticError

    with pytest.raises(PydanticError):
        define(line_items=[{"code": "X", "label": "x", "node": {"type": "EXECUTE", "cmd": "rm"}}])


def test_extra_keys_rejected_at_parse_time() -> None:
    """extra=forbid: a typo'd key is an error, not silently ignored."""
    from pydantic import ValidationError as PydanticError

    with pytest.raises(PydanticError):
        define(
            line_items=[
                {"code": "X", "label": "x", "node": {"type": "VALUE", "value": "1", "typo": 2}}
            ]
        )


# --------------------------------------------------------------------------- #
# A realistic whole formula
# --------------------------------------------------------------------------- #


def test_realistic_society_bill() -> None:
    """Base + area rate + progressive water + vacancy rebate, end to end."""
    definition = define(
        line_items=[
            {"code": "BASE", "label": "Base maintenance", "sort_order": 1,
             "node": F("base_maintenance")},
            {"code": "AREA", "label": "Area charges", "sort_order": 2,
             "quantity_field": "flat_area", "unit": "sqft",
             "node": {"type": "MULTIPLY", "children": [F("flat_area"), V("2.50")]}},
            {"code": "WATER", "label": "Water", "sort_order": 3,
             "quantity_field": "water_consumption", "unit": "KL",
             "node": {"type": "SLAB", "input": F("water_consumption"), "slabs": SLABS}},
            {"code": "PARK", "label": "Parking", "sort_order": 4,
             "node": F("parking_charge_total")},
            {"code": "REBATE", "label": "Vacancy rebate", "is_credit": True, "sort_order": 5,
             "node": {"type": "IF", "children": [
                 F("is_vacant"),
                 {"type": "PERCENTAGE", "children": [F("base_maintenance"), V(10)]},
                 V(0),
             ]}},
        ]
    )
    assert validator.validate(definition) == []

    context = EvaluationContext(
        {
            "base_maintenance": Decimal(4500),
            "flat_area": Decimal(1200),
            "water_consumption": Decimal(18),
            "parking_charge_total": Decimal(1500),
            "is_vacant": False,
        }
    )
    result = engine.evaluate(definition, context)

    amounts = {li.code: li.amount for li in result.line_items}
    assert amounts["BASE"] == Decimal("4500.00")
    assert amounts["AREA"] == Decimal("3000.00")   # 1200 * 2.50
    assert amounts["WATER"] == Decimal("480.00")   # 10*20 + 8*35
    assert amounts["PARK"] == Decimal("1500.00")
    assert amounts["REBATE"] == Decimal("0.00")
    assert result.total == Decimal("9480.00")

    # The same formula, on a vacant flat, applies the rebate.
    vacant = EvaluationContext(
        {
            "base_maintenance": Decimal(4500),
            "flat_area": Decimal(1200),
            "water_consumption": Decimal(0),
            "parking_charge_total": Decimal(0),
            "is_vacant": True,
        }
    )
    vacant_result = engine.evaluate(definition, vacant)
    assert vacant_result.total == Decimal("7050.00")  # 4500 + 3000 - 450


def test_line_item_rate_is_derived_from_quantity() -> None:
    definition = define(
        line_items=[
            {
                "code": "AREA",
                "label": "Area",
                "quantity_field": "flat_area",
                "unit": "sqft",
                "node": {"type": "MULTIPLY", "children": [F("flat_area"), V("2.50")]},
            }
        ]
    )
    result = engine.evaluate(definition, EvaluationContext({"flat_area": Decimal(1200)}))
    line = result.line_items[0]
    assert line.quantity == Decimal(1200)
    assert line.unit == "sqft"
    assert line.rate == Decimal("2.5000")
