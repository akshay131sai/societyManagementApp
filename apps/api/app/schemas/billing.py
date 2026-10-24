"""Billing schemas.

``FormulaDefinition`` is reused directly from the engine — the wire format and
the stored format and the evaluated format are the same object, so there is no
translation layer to drift.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.engines.formula.nodes import FormulaDefinition, FormulaNode
from app.models.tenant import (
    AssignmentScope,
    BillingFrequency,
    BillingRunStatus,
    BillStatus,
    PaymentMethod,
    PaymentStatus,
)

Money = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=2)]


# --------------------------------------------------------------------------- #
# Templates
# --------------------------------------------------------------------------- #


class TemplateCreate(BaseModel):
    name: Annotated[str, Field(min_length=2, max_length=120)]
    description: Annotated[str | None, Field(max_length=2000)] = None
    frequency: BillingFrequency = BillingFrequency.MONTHLY
    formula: FormulaDefinition
    parameters: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()


class TemplateUpdate(BaseModel):
    name: Annotated[str | None, Field(min_length=2, max_length=120)] = None
    description: Annotated[str | None, Field(max_length=2000)] = None
    is_active: bool | None = None


class VersionCreate(BaseModel):
    formula: FormulaDefinition
    parameters: dict[str, Any] = Field(default_factory=dict)
    notes: Annotated[str | None, Field(max_length=1000)] = None
    activate: bool = True
    """Whether the next billing run should use this version."""


class VersionUpdate(BaseModel):
    formula: FormulaDefinition | None = None
    parameters: dict[str, Any] | None = None
    notes: Annotated[str | None, Field(max_length=1000)] = None


class VersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    template_id: uuid.UUID
    version_number: int
    formula: dict[str, Any]
    parameters: dict[str, Any]
    notes: str | None = None
    is_published: bool
    is_active: bool = False
    bill_count: int = 0
    created_at: datetime


class AssignmentCreate(BaseModel):
    template_id: uuid.UUID
    scope: AssignmentScope
    building_id: uuid.UUID | None = None
    block_id: uuid.UUID | None = None
    flat_id: uuid.UUID | None = None
    flat_type: Annotated[str | None, Field(max_length=20)] = None
    priority: Annotated[int, Field(ge=0, le=1000)] = 0

    def targets(self) -> dict[str, Any]:
        """Only the field this scope names — the DB CHECK enforces the rest."""
        match self.scope:
            case AssignmentScope.ALL:
                return {}
            case AssignmentScope.BUILDING:
                return {"building_id": self.building_id}
            case AssignmentScope.BLOCK:
                return {"block_id": self.block_id}
            case AssignmentScope.FLAT_TYPE:
                return {"flat_type": self.flat_type}
            case AssignmentScope.FLAT:
                return {"flat_id": self.flat_id}
            case _:  # pragma: no cover
                return {}


class AssignmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    template_id: uuid.UUID
    scope: AssignmentScope
    building_id: uuid.UUID | None = None
    block_id: uuid.UUID | None = None
    flat_id: uuid.UUID | None = None
    flat_type: str | None = None
    priority: int
    is_active: bool


class TemplateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None = None
    frequency: BillingFrequency
    is_active: bool
    active_version_id: uuid.UUID | None = None
    version_count: int = 0
    run_count: int = 0
    created_at: datetime


class TemplateDetail(TemplateRead):
    versions: list[VersionRead] = []
    assignments: list[AssignmentRead] = []


# --------------------------------------------------------------------------- #
# Preview & validation
# --------------------------------------------------------------------------- #


class FormulaValidateRequest(BaseModel):
    formula: FormulaDefinition


class FormulaValidateResponse(BaseModel):
    valid: bool
    errors: list[dict[str, str]] = []


class PreviewRequest(BaseModel):
    formula: FormulaDefinition
    parameters: dict[str, Any] = Field(default_factory=dict)
    flat_id: uuid.UUID | None = None
    """Which flat to preview against. Defaults to the first flat."""


class NodePreviewRequest(BaseModel):
    node: FormulaNode
    parameters: dict[str, Any] = Field(default_factory=dict)
    flat_id: uuid.UUID | None = None


class FieldSpecRead(BaseModel):
    key: str
    label: str
    kind: str
    unit: str | None = None
    description: str
    group: str


# --------------------------------------------------------------------------- #
# Runs
# --------------------------------------------------------------------------- #


class RunCreate(BaseModel):
    template_id: uuid.UUID
    period_key: Annotated[str | None, Field(max_length=20)] = None
    """Defaults to the period containing today."""


class RunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    template_id: uuid.UUID
    template_name: str | None = None
    template_version_id: uuid.UUID
    version_number: int | None = None
    frequency: BillingFrequency
    period_key: str
    period_label: str
    period_start: date
    period_end: date
    due_date: date
    status: BillingRunStatus
    total_flats: int
    bills_generated: int
    bills_failed: int
    total_amount: Decimal
    error_summary: list[dict[str, Any]] | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    published_at: datetime | None = None
    created_at: datetime


class PeriodOption(BaseModel):
    frequency: str
    key: str
    label: str
    start: str
    end: str
    already_billed: bool
    run_id: str | None = None


# --------------------------------------------------------------------------- #
# Bills
# --------------------------------------------------------------------------- #


class LineItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID | None = None
    sort_order: int = 0
    code: str
    label: str
    quantity: str | None = None
    unit: str | None = None
    rate: str | None = None
    amount: str
    is_credit: bool = False


class BillRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    bill_number: str
    billing_run_id: uuid.UUID
    flat_id: uuid.UUID
    flat_number: str | None = None
    template_id: uuid.UUID
    template_version_id: uuid.UUID
    period_key: str
    period_label: str
    period_start: date
    period_end: date
    subtotal: Decimal
    penalty: Decimal
    discount: Decimal
    tax: Decimal
    total: Decimal
    amount_paid: Decimal
    balance_due: Decimal
    status: BillStatus
    payment_status: PaymentStatus
    issued_at: datetime | None = None
    due_date: date
    paid_at: datetime | None = None
    failure_reason: str | None = None
    created_at: datetime


class BillDetail(BillRead):
    line_items: list[LineItemRead] = []


class BillCalculation(BaseModel):
    """Everything needed to answer "How was this calculated?".

    Served entirely from the stored snapshot — no re-evaluation, and no
    dependence on the flat's current data.
    """

    bill_id: str
    bill_number: str
    period_label: str
    inputs: dict[str, Any]
    formula: dict[str, Any]
    trace: list[dict[str, Any]]
    line_items: list[dict[str, Any]]
    subtotal: str
    discount: str
    total: str


class BillVoidRequest(BaseModel):
    reason: Annotated[str, Field(min_length=3, max_length=500)]


class BillingSummary(BaseModel):
    total_bills: int
    total_billed: str
    total_collected: str
    total_outstanding: str
    collection_rate: float
    by_payment_status: dict[str, int]


# --------------------------------------------------------------------------- #
# Payments
# --------------------------------------------------------------------------- #


class PaymentCreate(BaseModel):
    bill_id: uuid.UUID | None = None
    flat_id: uuid.UUID | None = None
    amount: Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=2)]
    method: PaymentMethod
    reference_number: Annotated[str | None, Field(max_length=80)] = None
    paid_at: datetime | None = None
    notes: Annotated[str | None, Field(max_length=1000)] = None


class PaymentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    bill_id: uuid.UUID | None = None
    bill_number: str | None = None
    flat_id: uuid.UUID
    amount: Decimal
    method: PaymentMethod
    status: PaymentStatus
    reference_number: str | None = None
    paid_at: datetime | None = None
    notes: str | None = None
    created_at: datetime
