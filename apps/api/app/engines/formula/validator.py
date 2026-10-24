"""Formula validation.

Runs at **save** time and again at **evaluate** time. Saving is where an admin
gets a useful error; evaluating is where a formula stored before a field was
renamed would otherwise blow up mid-run.

Every failure carries a machine code, a human message, and a path to the
offending node, so the Bill Builder can highlight it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

from app.engines.formula import fields as registry
from app.engines.formula.nodes import (
    BOOLEAN_PRODUCING,
    ArithmeticNode,
    BoolValueNode,
    ComparisonNode,
    FieldNode,
    FormulaDefinition,
    FormulaNode,
    IfNode,
    LineItemSpec,
    LogicalNode,
    NodeType,
    NotNode,
    PercentageNode,
    RoundNode,
    SlabNode,
    TextValueNode,
    ValueNode,
)

MAX_DEPTH = 32
MAX_NODES = 500


class FormulaErrorCode(StrEnum):
    UNKNOWN_FIELD = "UNKNOWN_FIELD"
    INVALID_VALUE = "INVALID_VALUE"
    DIVISION_BY_ZERO = "DIVISION_BY_ZERO"
    EXCESSIVE_NESTING = "EXCESSIVE_NESTING"
    FORMULA_TOO_LARGE = "FORMULA_TOO_LARGE"
    CIRCULAR_REFERENCE = "CIRCULAR_REFERENCE"
    TYPE_MISMATCH = "TYPE_MISMATCH"
    INVALID_SLAB_TABLE = "INVALID_SLAB_TABLE"
    EMPTY_FORMULA = "EMPTY_FORMULA"
    DUPLICATE_LINE_ITEM = "DUPLICATE_LINE_ITEM"


@dataclass(frozen=True, slots=True)
class FormulaError:
    code: FormulaErrorCode
    message: str
    path: str
    """Dotted path to the node, e.g. ``line_items[1].node.children[0]``."""

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code.value, "message": self.message, "path": self.path}


class ValueType(StrEnum):
    NUMBER = "NUMBER"
    TEXT = "TEXT"
    BOOLEAN = "BOOLEAN"


@dataclass(slots=True)
class _State:
    errors: list[FormulaError] = field(default_factory=list)
    node_count: int = 0
    seen: set[int] = field(default_factory=set)
    """Object identities, to catch a hand-built AST that shares a node — which
    would make evaluation exponential and a cycle non-terminating."""


class FormulaValidator:
    """Static checks over a formula. Pure — no database, no context."""

    def validate(self, definition: FormulaDefinition) -> list[FormulaError]:
        state = _State()

        if definition.is_empty():
            state.errors.append(
                FormulaError(
                    FormulaErrorCode.EMPTY_FORMULA,
                    "A formula needs at least one line item or a total.",
                    "root",
                )
            )
            return state.errors

        codes: set[str] = set()
        for i, item in enumerate(definition.line_items):
            if item.code in codes:
                state.errors.append(
                    FormulaError(
                        FormulaErrorCode.DUPLICATE_LINE_ITEM,
                        f"Line item code '{item.code}' is used more than once.",
                        f"line_items[{i}]",
                    )
                )
            codes.add(item.code)
            self._check_line_item(item, f"line_items[{i}]", state)

        if definition.root is not None:
            self._walk(definition.root, "root", 0, state, expect=ValueType.NUMBER)

        if state.node_count > MAX_NODES:
            state.errors.append(
                FormulaError(
                    FormulaErrorCode.FORMULA_TOO_LARGE,
                    f"This formula has {state.node_count} parts; the limit is {MAX_NODES}.",
                    "root",
                )
            )

        return state.errors

    def validate_node(self, node: FormulaNode) -> list[FormulaError]:
        """Validate a single expression — used by the Bill Builder per node."""
        state = _State()
        self._walk(node, "node", 0, state, expect=ValueType.NUMBER)
        return state.errors

    # ------------------------------------------------------------------ #

    def _check_line_item(self, item: LineItemSpec, path: str, state: _State) -> None:
        if item.quantity_field and not registry.is_known(item.quantity_field):
            state.errors.append(
                FormulaError(
                    FormulaErrorCode.UNKNOWN_FIELD,
                    f"'{item.quantity_field}' is not a field that can be billed.",
                    f"{path}.quantity_field",
                )
            )
        self._walk(item.node, f"{path}.node", 0, state, expect=ValueType.NUMBER)

    def _walk(
        self,
        node: FormulaNode,
        path: str,
        depth: int,
        state: _State,
        *,
        expect: ValueType,
    ) -> ValueType:
        state.node_count += 1

        if depth > MAX_DEPTH:
            state.errors.append(
                FormulaError(
                    FormulaErrorCode.EXCESSIVE_NESTING,
                    f"This formula nests deeper than {MAX_DEPTH} levels.",
                    path,
                )
            )
            return expect

        identity = id(node)
        if identity in state.seen:
            state.errors.append(
                FormulaError(
                    FormulaErrorCode.CIRCULAR_REFERENCE,
                    "The same node appears twice in this formula.",
                    path,
                )
            )
            return expect
        state.seen.add(identity)

        actual = self._check(node, path, depth, state)

        if not self._compatible(actual, expect):
            state.errors.append(
                FormulaError(
                    FormulaErrorCode.TYPE_MISMATCH,
                    f"Expected {expect.value.lower()} here, but this produces "
                    f"{actual.value.lower()}.",
                    path,
                )
            )
        return actual

    @staticmethod
    def _compatible(actual: ValueType, expect: ValueType) -> bool:
        if actual is expect:
            return True
        # A boolean used where a number is expected is a real mistake (₹True),
        # but text vs number is caught by the comparison rules instead.
        return False

    def _check(self, node: FormulaNode, path: str, depth: int, state: _State) -> ValueType:
        match node:
            case ValueNode():
                return ValueType.NUMBER

            case TextValueNode():
                return ValueType.TEXT

            case BoolValueNode():
                return ValueType.BOOLEAN

            case FieldNode():
                if not registry.is_known(node.field):
                    state.errors.append(
                        FormulaError(
                            FormulaErrorCode.UNKNOWN_FIELD,
                            f"'{node.field}' is not a field that can be billed.",
                            path,
                        )
                    )
                    return ValueType.NUMBER
                if registry.is_boolean(node.field):
                    return ValueType.BOOLEAN
                spec = registry.spec_for(node.field)
                if spec is not None and spec.kind is registry.FieldKind.TEXT:
                    return ValueType.TEXT
                return ValueType.NUMBER

            case ArithmeticNode():
                self._check_arity(node, path, state)
                for i, child in enumerate(node.children):
                    self._walk(child, f"{path}.children[{i}]", depth + 1, state,
                               expect=ValueType.NUMBER)
                if node.type is NodeType.DIVIDE:
                    self._check_literal_divisors(node, path, state)
                return ValueType.NUMBER

            case PercentageNode():
                for i, child in enumerate(node.children):
                    self._walk(child, f"{path}.children[{i}]", depth + 1, state,
                               expect=ValueType.NUMBER)
                return ValueType.NUMBER

            case RoundNode():
                self._walk(node.children[0], f"{path}.children[0]", depth + 1, state,
                           expect=ValueType.NUMBER)
                return ValueType.NUMBER

            case SlabNode():
                self._walk(node.input, f"{path}.input", depth + 1, state,
                           expect=ValueType.NUMBER)
                self._check_slabs(node, path, state)
                return ValueType.NUMBER

            case IfNode():
                condition, then, otherwise = node.children
                self._require_boolean(condition, f"{path}.children[0]", depth + 1, state)
                self._walk(then, f"{path}.children[1]", depth + 1, state,
                           expect=ValueType.NUMBER)
                self._walk(otherwise, f"{path}.children[2]", depth + 1, state,
                           expect=ValueType.NUMBER)
                return ValueType.NUMBER

            case LogicalNode():
                for i, child in enumerate(node.children):
                    self._require_boolean(child, f"{path}.children[{i}]", depth + 1, state)
                return ValueType.BOOLEAN

            case NotNode():
                self._require_boolean(node.children[0], f"{path}.children[0]", depth + 1, state)
                return ValueType.BOOLEAN

            case ComparisonNode():
                left, right = node.children
                left_type = self._walk(left, f"{path}.children[0]", depth + 1, state,
                                       expect=ValueType.NUMBER
                                       if node.type not in (NodeType.EQ, NodeType.NEQ)
                                       else self._infer(left))
                right_type = self._walk(right, f"{path}.children[1]", depth + 1, state,
                                        expect=left_type)
                if node.type not in (NodeType.EQ, NodeType.NEQ) and (
                    left_type is ValueType.TEXT or right_type is ValueType.TEXT
                ):
                    state.errors.append(
                        FormulaError(
                            FormulaErrorCode.TYPE_MISMATCH,
                            "Text can only be compared with 'is' or 'is not'.",
                            path,
                        )
                    )
                return ValueType.BOOLEAN

            case _:  # pragma: no cover - the union is closed
                return ValueType.NUMBER

    def _infer(self, node: FormulaNode) -> ValueType:
        """Shallow type guess, so EQ can compare text to text without complaint."""
        match node:
            case TextValueNode():
                return ValueType.TEXT
            case BoolValueNode():
                return ValueType.BOOLEAN
            case FieldNode():
                if registry.is_boolean(node.field):
                    return ValueType.BOOLEAN
                spec = registry.spec_for(node.field)
                if spec is not None and spec.kind is registry.FieldKind.TEXT:
                    return ValueType.TEXT
                return ValueType.NUMBER
            case _:
                return ValueType.NUMBER

    def _require_boolean(
        self, node: FormulaNode, path: str, depth: int, state: _State
    ) -> None:
        """An IF condition must be a comparison or a boolean, not a number.

        ``IF(flat_area, ...)`` is almost always a mistake, and silently treating
        a non-zero amount as true would bill people for it.
        """
        is_boolean_shape = (
            getattr(node, "type", None) in BOOLEAN_PRODUCING
            or isinstance(node, BoolValueNode)
            or (isinstance(node, FieldNode) and registry.is_boolean(node.field))
        )
        if not is_boolean_shape:
            state.errors.append(
                FormulaError(
                    FormulaErrorCode.TYPE_MISMATCH,
                    "A condition must be a comparison (is greater than, is, …) "
                    "or a yes/no field.",
                    path,
                )
            )
        self._walk(node, path, depth, state, expect=ValueType.BOOLEAN)

    @staticmethod
    def _check_arity(node: ArithmeticNode, path: str, state: _State) -> None:
        needs_two = {NodeType.SUBTRACT, NodeType.DIVIDE}
        if node.type in needs_two and len(node.children) < 2:
            state.errors.append(
                FormulaError(
                    FormulaErrorCode.INVALID_VALUE,
                    f"{node.type.value.title()} needs at least two values.",
                    path,
                )
            )

    @staticmethod
    def _check_literal_divisors(node: ArithmeticNode, path: str, state: _State) -> None:
        for i, child in enumerate(node.children[1:], start=1):
            if isinstance(child, ValueNode) and child.value == 0:
                state.errors.append(
                    FormulaError(
                        FormulaErrorCode.DIVISION_BY_ZERO,
                        "This divides by zero.",
                        f"{path}.children[{i}]",
                    )
                )

    @staticmethod
    def _check_slabs(node: SlabNode, path: str, state: _State) -> None:
        bounds: list[Decimal | None] = [band.up_to for band in node.slabs]

        for i, band in enumerate(node.slabs):
            if band.up_to is None and i != len(node.slabs) - 1:
                state.errors.append(
                    FormulaError(
                        FormulaErrorCode.INVALID_SLAB_TABLE,
                        "Only the last slab may be open-ended.",
                        f"{path}.slabs[{i}]",
                    )
                )
            if band.up_to is not None and band.up_to <= 0:
                state.errors.append(
                    FormulaError(
                        FormulaErrorCode.INVALID_SLAB_TABLE,
                        "A slab boundary must be greater than zero.",
                        f"{path}.slabs[{i}].up_to",
                    )
                )
            if band.rate < 0:
                state.errors.append(
                    FormulaError(
                        FormulaErrorCode.INVALID_SLAB_TABLE,
                        "A slab rate cannot be negative.",
                        f"{path}.slabs[{i}].rate",
                    )
                )

        finite = [b for b in bounds if b is not None]
        if len(set(finite)) != len(finite):
            state.errors.append(
                FormulaError(
                    FormulaErrorCode.INVALID_SLAB_TABLE,
                    "Two slabs share the same boundary.",
                    f"{path}.slabs",
                )
            )
        if finite != sorted(finite):
            state.errors.append(
                FormulaError(
                    FormulaErrorCode.INVALID_SLAB_TABLE,
                    "Slab boundaries must increase.",
                    f"{path}.slabs",
                )
            )
        if bounds and bounds[-1] is not None:
            state.errors.append(
                FormulaError(
                    FormulaErrorCode.INVALID_SLAB_TABLE,
                    "The last slab must be open-ended, or consumption above it "
                    "would not be charged at all.",
                    f"{path}.slabs",
                )
            )


validator = FormulaValidator()
