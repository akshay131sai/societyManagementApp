"""Billing: templates, versions, runs, bills, line items, payments.

Two properties are enforced by the database, not by convention, because this is
a financial record:

* **Template versions are append-only.** Raising a rate creates v2; every bill
  already generated still points at v1 and still carries v1's frozen formula.
* **Published bills are immutable.** A trigger permits only the
  payment-tracking columns to change after publication. A wrong bill is
  corrected with a credit note, never an edit.

See docs/architecture/billing.md.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import TenantBase, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.tenant.enums import (
    AssignmentScope,
    BillStatus,
    BillingFrequency,
    BillingRunStatus,
    PaymentMethod,
    PaymentStatus,
    assignment_scope_enum,
    bill_status_enum,
    billing_frequency_enum,
    billing_run_status_enum,
    payment_method_enum,
    payment_status_enum,
)

if TYPE_CHECKING:
    from app.models.tenant.structure import Flat


class BillTemplate(UUIDPrimaryKeyMixin, TimestampMixin, TenantBase):
    """A named, reusable billing configuration — "Standard Maintenance"."""

    __tablename__ = "bill_templates"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    frequency: Mapped[BillingFrequency] = mapped_column(
        billing_frequency_enum, nullable=False, server_default=BillingFrequency.MONTHLY.value
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    active_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "bill_template_versions.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_bill_templates_active_version",
        ),
    )
    """Which version a new billing run uses. Older versions stay readable
    forever because bills reference them directly."""

    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    versions: Mapped[list[BillTemplateVersion]] = relationship(
        back_populates="template",
        lazy="noload",
        cascade="all, delete-orphan",
        foreign_keys="BillTemplateVersion.template_id",
    )
    assignments: Mapped[list[BillTemplateAssignment]] = relationship(
        back_populates="template", lazy="noload", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ux_bill_templates_name", func.lower(name), unique=True),)

    def __repr__(self) -> str:
        return f"<BillTemplate {self.name}>"


class BillTemplateVersion(UUIDPrimaryKeyMixin, TenantBase):
    """One frozen version of a template's formula.

    No ``updated_at``: a published version never changes. A trigger rejects any
    update once ``is_published`` is set.
    """

    __tablename__ = "bill_template_versions"

    template_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("bill_templates.id", ondelete="CASCADE"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)

    formula: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    """The FormulaDefinition AST — structured JSON, never a string."""

    parameters: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    """Named constants the formula reads as ``custom.<key>``."""

    notes: Mapped[str | None] = mapped_column(Text)
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    template: Mapped[BillTemplate] = relationship(
        back_populates="versions", lazy="selectin", foreign_keys=[template_id]
    )

    __table_args__ = (
        UniqueConstraint("template_id", "version_number", name="template_version"),
        CheckConstraint("version_number > 0", name="version_positive"),
        Index("ix_bill_template_versions_template", "template_id", "version_number"),
    )

    def __repr__(self) -> str:
        return f"<BillTemplateVersion v{self.version_number}>"


class BillTemplateAssignment(UUIDPrimaryKeyMixin, TimestampMixin, TenantBase):
    """Which flats a template applies to.

    Most specific scope wins; ``priority`` breaks ties. Resolution is a pure
    function with its own tests, because "which template billed this flat" is
    the first question asked when a bill looks wrong.
    """

    __tablename__ = "bill_template_assignments"

    template_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("bill_templates.id", ondelete="CASCADE"), nullable=False
    )
    scope: Mapped[AssignmentScope] = mapped_column(assignment_scope_enum, nullable=False)

    building_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("buildings.id", ondelete="CASCADE")
    )
    block_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("blocks.id", ondelete="CASCADE")
    )
    flat_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("flats.id", ondelete="CASCADE")
    )
    flat_type: Mapped[str | None] = mapped_column(String(20))

    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    template: Mapped[BillTemplate] = relationship(back_populates="assignments", lazy="selectin")

    __table_args__ = (
        # Each scope must carry exactly the target it names, and nothing else.
        CheckConstraint(
            "(scope = 'ALL'      AND building_id IS NULL AND block_id IS NULL AND flat_id IS NULL AND flat_type IS NULL) OR "
            "(scope = 'BUILDING' AND building_id IS NOT NULL AND block_id IS NULL AND flat_id IS NULL) OR "
            "(scope = 'BLOCK'    AND block_id IS NOT NULL AND flat_id IS NULL) OR "
            "(scope = 'FLAT_TYPE'AND flat_type IS NOT NULL AND flat_id IS NULL) OR "
            "(scope = 'FLAT'     AND flat_id IS NOT NULL)",
            name="scope_target",
        ),
        Index("ix_assignments_template", "template_id", postgresql_where="is_active"),
        Index("ix_assignments_flat", "flat_id", postgresql_where="flat_id IS NOT NULL"),
    )


class BillingRun(UUIDPrimaryKeyMixin, TimestampMixin, TenantBase):
    """One execution: template version × period × flat set."""

    __tablename__ = "billing_runs"

    template_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("bill_templates.id", ondelete="RESTRICT"), nullable=False
    )
    template_version_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("bill_template_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )

    frequency: Mapped[BillingFrequency] = mapped_column(billing_frequency_enum, nullable=False)
    period_key: Mapped[str] = mapped_column(String(20), nullable=False)
    period_label: Mapped[str] = mapped_column(String(60), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)

    status: Mapped[BillingRunStatus] = mapped_column(
        billing_run_status_enum, nullable=False, server_default=BillingRunStatus.PENDING.value
    )

    total_flats: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    bills_generated: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    bills_failed: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(16, 2), nullable=False, server_default="0"
    )
    error_summary: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    template: Mapped[BillTemplate] = relationship(lazy="selectin")
    version: Mapped[BillTemplateVersion] = relationship(lazy="selectin")
    bills: Mapped[list[MaintenanceBill]] = relationship(
        back_populates="run", lazy="noload", cascade="all, delete-orphan"
    )

    __table_args__ = (
        # One run per (template, period) — the guard against double-billing a
        # whole society because someone clicked twice.
        Index(
            "ux_billing_runs_period",
            "template_id",
            "period_key",
            unique=True,
            postgresql_where="status <> 'FAILED'",
        ),
        Index("ix_billing_runs_status", "status", "created_at"),
        CheckConstraint("period_end >= period_start", name="period_order"),
    )

    def __repr__(self) -> str:
        return f"<BillingRun {self.period_key} {self.status}>"


class MaintenanceBill(UUIDPrimaryKeyMixin, TimestampMixin, TenantBase):
    """A bill for one flat for one period. Immutable once published."""

    __tablename__ = "maintenance_bills"

    bill_number: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    """``NF/2026-27/000123`` — human-quotable, unique forever."""

    billing_run_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("billing_runs.id", ondelete="CASCADE"), nullable=False
    )
    flat_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("flats.id", ondelete="RESTRICT"), nullable=False
    )

    # --- Provenance: what produced this number ---------------------------
    template_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("bill_templates.id", ondelete="RESTRICT"), nullable=False
    )
    template_version_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("bill_template_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    formula_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    input_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    calculation_trace: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    """Powers "How was this calculated?" years later, without re-running
    anything or needing the flat's current data."""

    # --- Period -----------------------------------------------------------
    period_key: Mapped[str] = mapped_column(String(20), nullable=False)
    period_label: Mapped[str] = mapped_column(String(60), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)

    # --- Money ------------------------------------------------------------
    subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, server_default="0")
    penalty: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, server_default="0")
    discount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, server_default="0")
    tax: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, server_default="0")
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, server_default="0")

    amount_paid: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, server_default="0"
    )
    """Mutable after publication — one of the few columns the trigger allows."""

    status: Mapped[BillStatus] = mapped_column(
        bill_status_enum, nullable=False, server_default=BillStatus.DRAFT.value
    )
    payment_status: Mapped[PaymentStatus] = mapped_column(
        payment_status_enum, nullable=False, server_default=PaymentStatus.UNPAID.value
    )

    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    failure_reason: Mapped[str | None] = mapped_column(Text)
    """Set when this flat's calculation failed; the rest of the run continues."""

    run: Mapped[BillingRun] = relationship(back_populates="bills", lazy="noload")
    flat: Mapped[Flat] = relationship(lazy="selectin")
    line_items: Mapped[list[BillLineItem]] = relationship(
        back_populates="bill",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="BillLineItem.sort_order",
    )

    __table_args__ = (
        Index(
            "ux_bills_flat_period",
            "flat_id",
            "template_id",
            "period_key",
            unique=True,
            postgresql_where="status <> 'VOID'",
        ),
        Index("ix_bills_flat", "flat_id", "period_start"),
        Index("ix_bills_status", "status", "payment_status"),
        Index(
            "ix_bills_due",
            "due_date",
            postgresql_where="payment_status IN ('UNPAID','PARTIAL','OVERDUE')",
        ),
        Index("ix_bills_run", "billing_run_id"),
        CheckConstraint("amount_paid >= 0", name="paid_non_negative"),
        CheckConstraint("total >= 0", name="total_non_negative"),
    )

    @property
    def balance_due(self) -> Decimal:
        return self.total - self.amount_paid

    def __repr__(self) -> str:
        return f"<MaintenanceBill {self.bill_number} {self.total}>"


class BillLineItem(UUIDPrimaryKeyMixin, TenantBase):
    """One presented row of a bill. Immutable with its bill."""

    __tablename__ = "bill_line_items"

    bill_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("maintenance_bills.id", ondelete="CASCADE"), nullable=False
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    label: Mapped[str] = mapped_column(String(80), nullable=False)

    quantity: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    unit: Mapped[str | None] = mapped_column(String(12))
    rate: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    is_credit: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    bill: Mapped[MaintenanceBill] = relationship(back_populates="line_items", lazy="noload")

    __table_args__ = (Index("ix_line_items_bill", "bill_id", "sort_order"),)


class Payment(UUIDPrimaryKeyMixin, TimestampMixin, TenantBase):
    """A payment against a bill, or a standalone credit to a flat."""

    __tablename__ = "payments"

    bill_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("maintenance_bills.id", ondelete="SET NULL")
    )
    flat_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("flats.id", ondelete="RESTRICT"), nullable=False
    )

    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    method: Mapped[PaymentMethod] = mapped_column(payment_method_enum, nullable=False)
    status: Mapped[PaymentStatus] = mapped_column(
        payment_status_enum, nullable=False, server_default=PaymentStatus.PENDING.value
    )

    # --- Provider abstraction: no Razorpay-specific column exists ---------
    provider: Mapped[str | None] = mapped_column(String(40))
    provider_payment_id: Mapped[str | None] = mapped_column(String(120))
    provider_order_id: Mapped[str | None] = mapped_column(String(120))
    provider_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    reference_number: Mapped[str | None] = mapped_column(String(80))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)

    recorded_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    bill: Mapped[MaintenanceBill | None] = relationship(lazy="selectin")

    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        Index("ix_payments_flat", "flat_id", "paid_at"),
        Index("ix_payments_bill", "bill_id"),
        # The idempotency key for gateway webhooks: a retried callback cannot
        # double-credit a flat.
        Index(
            "ux_payments_provider",
            "provider",
            "provider_payment_id",
            unique=True,
            postgresql_where="provider_payment_id IS NOT NULL",
        ),
    )

    def __repr__(self) -> str:
        return f"<Payment {self.amount} {self.status}>"
