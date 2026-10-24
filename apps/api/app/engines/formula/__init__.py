"""Formula engine — the authority for money.

Pure: no session, no clock, no I/O. ``eval()`` appears nowhere in this package.
"""

from app.engines.formula.evaluator import (
    EvaluationContext,
    EvaluationError,
    EvaluationResult,
    FormulaEngine,
    LineItemResult,
    TraceEntry,
    engine,
)
from app.engines.formula.fields import FIELDS, FieldKind, FieldSpec, catalogue
from app.engines.formula.nodes import (
    FormulaDefinition,
    FormulaNode,
    LineItemSpec,
    NodeType,
    SlabBand,
    SlabMode,
)
from app.engines.formula.validator import (
    FormulaError,
    FormulaErrorCode,
    FormulaValidator,
    validator,
)

__all__ = [
    "FIELDS",
    "EvaluationContext",
    "EvaluationError",
    "EvaluationResult",
    "FieldKind",
    "FieldSpec",
    "FormulaDefinition",
    "FormulaEngine",
    "FormulaError",
    "FormulaErrorCode",
    "FormulaNode",
    "FormulaValidator",
    "LineItemResult",
    "LineItemSpec",
    "NodeType",
    "SlabBand",
    "SlabMode",
    "TraceEntry",
    "catalogue",
    "engine",
    "validator",
]
