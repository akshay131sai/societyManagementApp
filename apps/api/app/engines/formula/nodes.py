"""The formula AST.

A formula is structured JSON, never a string — so it is inspectable,
diffable, storable as a snapshot, and impossible to turn into code execution.
``eval()`` appears nowhere in this package.

Every node is a Pydantic model, which means a malformed formula is rejected at
the API boundary before it ever reaches the evaluator.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator


class NodeType(StrEnum):
    VALUE = "VALUE"
    FIELD = "FIELD"

    ADD = "ADD"
    SUBTRACT = "SUBTRACT"
    MULTIPLY = "MULTIPLY"
    DIVIDE = "DIVIDE"
    MIN = "MIN"
    MAX = "MAX"
    PERCENTAGE = "PERCENTAGE"
    ROUND = "ROUND"
    SLAB = "SLAB"

    IF = "IF"
    AND = "AND"
    OR = "OR"
    NOT = "NOT"

    GT = "GT"
    GTE = "GTE"
    LT = "LT"
    LTE = "LTE"
    EQ = "EQ"
    NEQ = "NEQ"


ARITHMETIC = frozenset(
    {NodeType.ADD, NodeType.SUBTRACT, NodeType.MULTIPLY, NodeType.DIVIDE,
     NodeType.MIN, NodeType.MAX}
)
COMPARISON = frozenset(
    {NodeType.GT, NodeType.GTE, NodeType.LT, NodeType.LTE, NodeType.EQ, NodeType.NEQ}
)
LOGICAL = frozenset({NodeType.AND, NodeType.OR, NodeType.NOT})
"""Nodes that produce a boolean. Only these may sit in an ``IF`` condition."""

BOOLEAN_PRODUCING = COMPARISON | LOGICAL


class _Node(BaseModel):
    model_config = ConfigDict(extra="forbid")
    """extra=forbid: a typo'd key is a validation error, not silently ignored."""

    label: str | None = Field(default=None, max_length=60)
    """Optional name shown on the bill's line-item breakdown."""


class ValueNode(_Node):
    type: Literal[NodeType.VALUE] = NodeType.VALUE
    value: Decimal

    @field_validator("value")
    @classmethod
    def _finite(cls, v: Decimal) -> Decimal:
        if not v.is_finite():
            raise ValueError("value must be a finite number")
        if abs(v) > Decimal("1e12"):
            raise ValueError("value is out of range")
        return v


class TextValueNode(_Node):
    """A string literal, for comparing against ``flat_type`` and friends."""

    type: Literal["TEXT"] = "TEXT"
    text: str = Field(max_length=100)


class BoolValueNode(_Node):
    type: Literal["BOOL"] = "BOOL"
    bool_value: bool


class FieldNode(_Node):
    type: Literal[NodeType.FIELD] = NodeType.FIELD
    field: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)?$")


class ArithmeticNode(_Node):
    type: Literal[
        NodeType.ADD, NodeType.SUBTRACT, NodeType.MULTIPLY,
        NodeType.DIVIDE, NodeType.MIN, NodeType.MAX,
    ]
    children: list[FormulaNode] = Field(min_length=1, max_length=32)


class PercentageNode(_Node):
    """``children[0] * children[1] / 100`` — "12% of the base", written plainly."""

    type: Literal[NodeType.PERCENTAGE] = NodeType.PERCENTAGE
    children: list[FormulaNode] = Field(min_length=2, max_length=2)


class RoundNode(_Node):
    type: Literal[NodeType.ROUND] = NodeType.ROUND
    children: list[FormulaNode] = Field(min_length=1, max_length=1)
    decimal_places: int = Field(default=2, ge=0, le=6)


class SlabBand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    up_to: Decimal | None = Field(default=None)
    """Upper bound of this band. ``None`` means unbounded, and must be last."""
    rate: Decimal

    @field_validator("rate", "up_to")
    @classmethod
    def _finite(cls, v: Decimal | None) -> Decimal | None:
        if v is not None and not v.is_finite():
            raise ValueError("slab bounds must be finite")
        return v


class SlabMode(StrEnum):
    PROGRESSIVE = "PROGRESSIVE"
    """Each band charged separately — 18 KL = 10×rate1 + 8×rate2."""
    FLAT = "FLAT"
    """The whole quantity charged at the matched band's rate."""


class SlabNode(_Node):
    """Progressive slab pricing.

    Indian utility tariffs are slab-based, so this is a first-class node rather
    than a tower of nested ``IF``s that nobody can read or audit.
    """

    type: Literal[NodeType.SLAB] = NodeType.SLAB
    input: FormulaNode
    mode: SlabMode = SlabMode.PROGRESSIVE
    slabs: list[SlabBand] = Field(min_length=1, max_length=20)


class IfNode(_Node):
    type: Literal[NodeType.IF] = NodeType.IF
    children: list[FormulaNode] = Field(min_length=3, max_length=3)
    """``[condition, then, else]``. Only the taken branch is evaluated."""


class LogicalNode(_Node):
    type: Literal[NodeType.AND, NodeType.OR]
    children: list[FormulaNode] = Field(min_length=2, max_length=16)


class NotNode(_Node):
    type: Literal[NodeType.NOT] = NodeType.NOT
    children: list[FormulaNode] = Field(min_length=1, max_length=1)


class ComparisonNode(_Node):
    type: Literal[
        NodeType.GT, NodeType.GTE, NodeType.LT,
        NodeType.LTE, NodeType.EQ, NodeType.NEQ,
    ]
    children: list[FormulaNode] = Field(min_length=2, max_length=2)


FormulaNode = Annotated[
    Union[
        ValueNode,
        TextValueNode,
        BoolValueNode,
        FieldNode,
        ArithmeticNode,
        PercentageNode,
        RoundNode,
        SlabNode,
        IfNode,
        LogicalNode,
        NotNode,
        ComparisonNode,
    ],
    Field(discriminator="type"),
]

# Recursive union — every model referencing FormulaNode needs rebuilding.
for _model in (
    ArithmeticNode, PercentageNode, RoundNode, SlabNode,
    IfNode, LogicalNode, NotNode, ComparisonNode,
):
    _model.model_rebuild()


class LineItemSpec(BaseModel):
    """How one branch of the formula is presented as a bill line.

    Kept separate from the AST because presentation changes (renaming "Water
    charge" to "Water") must not require a new template version — only a change
    to the *money* does.
    """

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=40, pattern=r"^[A-Z][A-Z0-9_]*$")
    label: str = Field(min_length=1, max_length=80)
    node: FormulaNode
    is_credit: bool = False
    """Discounts and credits, shown negative and subtracted from the subtotal."""
    quantity_field: str | None = Field(default=None, max_length=80)
    """Optional field whose value is shown as the quantity on the line."""
    unit: str | None = Field(default=None, max_length=12)
    sort_order: int = 0


LineItemSpec.model_rebuild()


class FormulaDefinition(BaseModel):
    """A complete, storable formula: the money, and how it breaks down."""

    model_config = ConfigDict(extra="forbid")

    root: FormulaNode | None = None
    """Total. When ``None`` the total is the sum of the line items, which is the
    usual shape and keeps the printed rows adding up to the printed total."""

    line_items: list[LineItemSpec] = Field(default_factory=list, max_length=40)

    def is_empty(self) -> bool:
        return self.root is None and not self.line_items


FormulaDefinition.model_rebuild()
