"""Formula evaluation.

Pure: no session, no clock, no I/O. Give it an AST and a context of values and
it returns a number and a trace. That is what makes billing testable without a
database, and reproducible years later from a stored snapshot.

**Numeric policy** (docs/architecture/billing.md section 4):

* Everything is ``Decimal``. ``float`` never touches a money path.
* Intermediate results are **not** rounded.
* Each line item rounds to 2 dp with ``ROUND_HALF_UP`` at presentation.
* The total is the **sum of the rounded line items**, so the printed rows
  always add up to the printed total.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, DivisionByZero, InvalidOperation, ROUND_HALF_UP, localcontext
from typing import Any

from app.engines.formula import fields as registry
from app.engines.formula.nodes import (
    ArithmeticNode,
    BoolValueNode,
    ComparisonNode,
    FieldNode,
    FormulaDefinition,
    FormulaNode,
    IfNode,
    LogicalNode,
    NodeType,
    NotNode,
    PercentageNode,
    RoundNode,
    SlabMode,
    SlabNode,
    TextValueNode,
    ValueNode,
)

WORKING_PRECISION = 28
MONEY_PLACES = Decimal("0.01")

ZERO = Decimal(0)


class EvaluationError(Exception):
    """A formula that cannot be evaluated for *this* flat.

    Raised per flat, caught per flat: one bad meter reading must not abort a
    400-flat billing run.
    """

    def __init__(self, code: str, message: str, path: str = "") -> None:
        self.code = code
        self.message = message
        self.path = path
        super().__init__(message)


@dataclass(slots=True)
class TraceEntry:
    """One step of the calculation, for "How was this calculated?"."""

    path: str
    node_type: str
    label: str | None
    inputs: list[str]
    result: str
    detail: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "node_type": self.node_type,
            "label": self.label,
            "inputs": self.inputs,
            "result": self.result,
            "detail": self.detail,
        }


@dataclass(slots=True)
class LineItemResult:
    code: str
    label: str
    amount: Decimal
    is_credit: bool
    quantity: Decimal | None = None
    unit: str | None = None
    rate: Decimal | None = None
    sort_order: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "label": self.label,
            "amount": str(self.amount),
            "is_credit": self.is_credit,
            "quantity": str(self.quantity) if self.quantity is not None else None,
            "unit": self.unit,
            "rate": str(self.rate) if self.rate is not None else None,
            "sort_order": self.sort_order,
        }


@dataclass(slots=True)
class EvaluationResult:
    total: Decimal
    line_items: list[LineItemResult] = field(default_factory=list)
    trace: list[TraceEntry] = field(default_factory=list)

    @property
    def subtotal(self) -> Decimal:
        return sum((li.amount for li in self.line_items if not li.is_credit), ZERO)

    @property
    def credits(self) -> Decimal:
        return sum((li.amount for li in self.line_items if li.is_credit), ZERO)

    def trace_as_list(self) -> list[dict[str, Any]]:
        return [t.as_dict() for t in self.trace]


class EvaluationContext:
    """The values a formula may read for one flat.

    Missing values fall back to the field's declared default rather than
    raising — a flat with no water reading yet bills as zero consumption, which
    is the honest answer and does not stop the run.
    """

    __slots__ = ("_values", "_parameters", "_accessed")

    def __init__(
        self,
        values: dict[str, Any] | None = None,
        parameters: dict[str, Any] | None = None,
    ) -> None:
        self._values = dict(values or {})
        self._parameters = dict(parameters or {})
        self._accessed: dict[str, Any] = {}

    def get(self, key: str) -> Decimal | str | bool:
        if key.startswith("custom."):
            raw = self._parameters.get(key.removeprefix("custom."), ZERO)
        elif key in self._values:
            raw = self._values[key]
        else:
            spec = registry.spec_for(key)
            if spec is None:
                raise EvaluationError(
                    "UNKNOWN_FIELD", f"'{key}' is not a field that can be billed."
                )
            raw = spec.default

        value = self._coerce(key, raw)
        self._accessed[key] = value
        return value

    @staticmethod
    def _coerce(key: str, raw: Any) -> Decimal | str | bool:
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, Decimal):
            return raw
        if isinstance(raw, (int, float)):
            return Decimal(str(raw))
        if isinstance(raw, str):
            spec = registry.spec_for(key)
            if spec is not None and spec.kind is registry.FieldKind.TEXT:
                return raw
            try:
                return Decimal(raw)
            except (InvalidOperation, ValueError) as exc:
                raise EvaluationError(
                    "INVALID_VALUE", f"'{key}' is not a number: {raw!r}"
                ) from exc
        if raw is None:
            return ZERO
        raise EvaluationError("INVALID_VALUE", f"'{key}' has an unusable value.")

    def snapshot(self) -> dict[str, str]:
        """Exactly the inputs this evaluation read, for the bill snapshot.

        Only what was *accessed* — a snapshot of every possible field would be
        noise, and would make a diff between two bills unreadable.
        """
        return {k: str(v) for k, v in sorted(self._accessed.items())}

    def full_snapshot(self) -> dict[str, str]:
        return {
            **{k: str(v) for k, v in sorted(self._values.items())},
            **{f"custom.{k}": str(v) for k, v in sorted(self._parameters.items())},
        }


class FormulaEngine:
    """Evaluates a formula against a context. The authority for money."""

    def evaluate(
        self,
        definition: FormulaDefinition,
        context: EvaluationContext,
        *,
        collect_trace: bool = True,
    ) -> EvaluationResult:
        with localcontext() as ctx:
            ctx.prec = WORKING_PRECISION
            trace: list[TraceEntry] = []

            line_items: list[LineItemResult] = []
            for i, spec in enumerate(sorted(definition.line_items, key=lambda s: s.sort_order)):
                raw = self._eval(spec.node, f"line_items[{i}].node", context, trace, collect_trace)
                amount = self._to_money(raw)

                quantity: Decimal | None = None
                if spec.quantity_field:
                    value = context.get(spec.quantity_field)
                    quantity = value if isinstance(value, Decimal) else None

                rate = None
                if quantity is not None and quantity != 0:
                    rate = (amount / quantity).quantize(
                        Decimal("0.0001"), rounding=ROUND_HALF_UP
                    )

                line_items.append(
                    LineItemResult(
                        code=spec.code,
                        label=spec.label,
                        amount=amount,
                        is_credit=spec.is_credit,
                        quantity=quantity,
                        unit=spec.unit,
                        rate=rate,
                        sort_order=spec.sort_order,
                    )
                )

            if definition.root is not None:
                total = self._to_money(
                    self._eval(definition.root, "root", context, trace, collect_trace)
                )
            else:
                # Sum of the ROUNDED line items, so the printed rows add up to
                # the printed total. Rounding an unrounded total instead
                # produces bills that appear off by a paisa.
                total = sum(
                    (li.amount if not li.is_credit else -li.amount for li in line_items),
                    ZERO,
                )

            return EvaluationResult(total=total, line_items=line_items, trace=trace)

    def evaluate_node(
        self, node: FormulaNode, context: EvaluationContext
    ) -> tuple[Decimal, list[TraceEntry]]:
        """Evaluate one expression — used by the Bill Builder's live preview."""
        with localcontext() as ctx:
            ctx.prec = WORKING_PRECISION
            trace: list[TraceEntry] = []
            value = self._eval(node, "node", context, trace, True)
            return self._to_money(value), trace

    # ------------------------------------------------------------------ #

    @staticmethod
    def _to_money(value: Decimal | str | bool) -> Decimal:
        if isinstance(value, bool):
            raise EvaluationError(
                "TYPE_MISMATCH", "A yes/no value cannot be used as an amount."
            )
        if isinstance(value, str):
            raise EvaluationError("TYPE_MISMATCH", "Text cannot be used as an amount.")
        if not value.is_finite():
            raise EvaluationError("INVALID_VALUE", "The result is not a finite number.")
        return value.quantize(MONEY_PLACES, rounding=ROUND_HALF_UP)

    @staticmethod
    def _number(value: Decimal | str | bool, path: str) -> Decimal:
        if isinstance(value, bool) or isinstance(value, str):
            raise EvaluationError(
                "TYPE_MISMATCH", "Expected a number here.", path
            )
        return value

    def _record(
        self,
        trace: list[TraceEntry],
        collect: bool,
        path: str,
        node: FormulaNode,
        inputs: list[Any],
        result: Any,
        detail: str | None = None,
    ) -> None:
        if not collect:
            return
        trace.append(
            TraceEntry(
                path=path,
                node_type=str(getattr(node, "type", "?")),
                label=getattr(node, "label", None),
                inputs=[str(i) for i in inputs],
                result=str(result),
                detail=detail,
            )
        )

    def _eval(
        self,
        node: FormulaNode,
        path: str,
        context: EvaluationContext,
        trace: list[TraceEntry],
        collect: bool,
    ) -> Decimal | str | bool:
        match node:
            case ValueNode():
                return node.value

            case TextValueNode():
                return node.text

            case BoolValueNode():
                return node.bool_value

            case FieldNode():
                value = context.get(node.field)
                self._record(trace, collect, path, node, [node.field], value)
                return value

            case ArithmeticNode():
                values = [
                    self._number(
                        self._eval(c, f"{path}.children[{i}]", context, trace, collect),
                        f"{path}.children[{i}]",
                    )
                    for i, c in enumerate(node.children)
                ]
                result = self._arithmetic(node.type, values, path)
                self._record(trace, collect, path, node, values, result)
                return result

            case PercentageNode():
                base = self._number(
                    self._eval(node.children[0], f"{path}.children[0]", context, trace, collect),
                    path,
                )
                percent = self._number(
                    self._eval(node.children[1], f"{path}.children[1]", context, trace, collect),
                    path,
                )
                result = base * percent / Decimal(100)
                self._record(
                    trace, collect, path, node, [base, percent], result,
                    detail=f"{percent}% of {base}",
                )
                return result

            case RoundNode():
                value = self._number(
                    self._eval(node.children[0], f"{path}.children[0]", context, trace, collect),
                    path,
                )
                quantum = Decimal(1).scaleb(-node.decimal_places)
                result = value.quantize(quantum, rounding=ROUND_HALF_UP)
                self._record(trace, collect, path, node, [value], result)
                return result

            case SlabNode():
                quantity = self._number(
                    self._eval(node.input, f"{path}.input", context, trace, collect), path
                )
                result, detail = self._slab(node, quantity)
                self._record(trace, collect, path, node, [quantity], result, detail=detail)
                return result

            case IfNode():
                condition = self._eval(
                    node.children[0], f"{path}.children[0]", context, trace, collect
                )
                taken = 1 if self._truthy(condition, path) else 2
                # Only the taken branch is evaluated — an untaken division by
                # zero must not fail the bill.
                result = self._eval(
                    node.children[taken], f"{path}.children[{taken}]", context, trace, collect
                )
                self._record(
                    trace, collect, path, node, [condition], result,
                    detail="then" if taken == 1 else "otherwise",
                )
                return result

            case LogicalNode():
                if node.type is NodeType.AND:
                    result = all(
                        self._truthy(
                            self._eval(c, f"{path}.children[{i}]", context, trace, collect), path
                        )
                        for i, c in enumerate(node.children)
                    )
                else:
                    result = any(
                        self._truthy(
                            self._eval(c, f"{path}.children[{i}]", context, trace, collect), path
                        )
                        for i, c in enumerate(node.children)
                    )
                self._record(trace, collect, path, node, [], result)
                return result

            case NotNode():
                inner = self._eval(
                    node.children[0], f"{path}.children[0]", context, trace, collect
                )
                result = not self._truthy(inner, path)
                self._record(trace, collect, path, node, [inner], result)
                return result

            case ComparisonNode():
                left = self._eval(node.children[0], f"{path}.children[0]", context, trace, collect)
                right = self._eval(node.children[1], f"{path}.children[1]", context, trace, collect)
                result = self._compare(node.type, left, right, path)
                self._record(trace, collect, path, node, [left, right], result)
                return result

            case _:  # pragma: no cover - the union is closed
                raise EvaluationError("UNKNOWN_NODE_TYPE", "Unsupported formula node.", path)

    @staticmethod
    def _arithmetic(op: NodeType, values: list[Decimal], path: str) -> Decimal:
        try:
            match op:
                case NodeType.ADD:
                    return sum(values, ZERO)
                case NodeType.SUBTRACT:
                    result = values[0]
                    for v in values[1:]:
                        result -= v
                    return result
                case NodeType.MULTIPLY:
                    result = values[0]
                    for v in values[1:]:
                        result *= v
                    return result
                case NodeType.DIVIDE:
                    result = values[0]
                    for v in values[1:]:
                        if v == 0:
                            raise EvaluationError(
                                "DIVISION_BY_ZERO",
                                "This calculation divides by zero.",
                                path,
                            )
                        result /= v
                    return result
                case NodeType.MIN:
                    return min(values)
                case NodeType.MAX:
                    return max(values)
                case _:  # pragma: no cover
                    raise EvaluationError("UNKNOWN_NODE_TYPE", "Unsupported operator.", path)
        except (DivisionByZero, InvalidOperation) as exc:
            raise EvaluationError("INVALID_VALUE", "This calculation is not valid.", path) from exc

    @staticmethod
    def _slab(node: SlabNode, quantity: Decimal) -> tuple[Decimal, str]:
        if quantity <= 0:
            return ZERO, "no consumption"

        if node.mode is SlabMode.FLAT:
            for band in node.slabs:
                if band.up_to is None or quantity <= band.up_to:
                    return quantity * band.rate, f"{quantity} × ₹{band.rate} (flat rate)"
            return ZERO, "no matching slab"

        total = ZERO
        lower = ZERO
        parts: list[str] = []
        for band in node.slabs:
            upper = band.up_to if band.up_to is not None else quantity
            if quantity <= lower:
                break
            billable = min(quantity, upper) - lower
            if billable > 0:
                total += billable * band.rate
                parts.append(f"{billable} × ₹{band.rate}")
            lower = upper

        return total, " + ".join(parts) if parts else "no consumption"

    @staticmethod
    def _truthy(value: Decimal | str | bool, path: str) -> bool:
        if isinstance(value, bool):
            return value
        raise EvaluationError(
            "TYPE_MISMATCH",
            "A condition must be a comparison or a yes/no value.",
            path,
        )

    @staticmethod
    def _compare(
        op: NodeType, left: Decimal | str | bool, right: Decimal | str | bool, path: str
    ) -> bool:
        if op is NodeType.EQ:
            return left == right
        if op is NodeType.NEQ:
            return left != right

        if isinstance(left, str) or isinstance(right, str):
            raise EvaluationError(
                "TYPE_MISMATCH", "Text can only be compared with 'is' or 'is not'.", path
            )
        if isinstance(left, bool) or isinstance(right, bool):
            raise EvaluationError(
                "TYPE_MISMATCH", "Yes/no values can only be compared with 'is'.", path
            )

        match op:
            case NodeType.GT:
                return left > right
            case NodeType.GTE:
                return left >= right
            case NodeType.LT:
                return left < right
            case NodeType.LTE:
                return left <= right
            case _:  # pragma: no cover
                raise EvaluationError("UNKNOWN_NODE_TYPE", "Unsupported comparison.", path)


engine = FormulaEngine()
