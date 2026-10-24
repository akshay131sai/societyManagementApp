"""Billing repositories.

All SQL for templates, versions, assignments, runs, bills, line items and
payments. No business rules — a repository never decides whether a bill may be
published.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from sqlalchemy import Select, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.tenant import (
    BillLineItem,
    BillStatus,
    BillTemplate,
    BillTemplateAssignment,
    BillTemplateVersion,
    BillingRun,
    BillingRunStatus,
    Flat,
    MaintenanceBill,
    Payment,
    PaymentStatus,
)


async def _count(session: AsyncSession, stmt: Select) -> int:
    subq = stmt.order_by(None).subquery()
    return int(await session.scalar(select(func.count()).select_from(subq)) or 0)


class TemplateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, template_id: uuid.UUID) -> BillTemplate | None:
        return await self.session.get(BillTemplate, template_id)

    async def get_by_name(self, name: str) -> BillTemplate | None:
        return await self.session.scalar(
            select(BillTemplate).where(func.lower(BillTemplate.name) == name.lower())
        )

    async def list(self, *, include_inactive: bool = False) -> Sequence[BillTemplate]:
        stmt = select(BillTemplate)
        if not include_inactive:
            stmt = stmt.where(BillTemplate.is_active.is_(True))
        rows = await self.session.scalars(stmt.order_by(BillTemplate.name))
        return list(rows)

    async def create(self, template: BillTemplate) -> BillTemplate:
        self.session.add(template)
        await self.session.flush()
        return template

    async def version_counts(self) -> dict[uuid.UUID, int]:
        rows = await self.session.execute(
            select(BillTemplateVersion.template_id, func.count()).group_by(
                BillTemplateVersion.template_id
            )
        )
        return {k: int(v) for k, v in rows}

    async def run_counts(self) -> dict[uuid.UUID, int]:
        rows = await self.session.execute(
            select(BillingRun.template_id, func.count()).group_by(BillingRun.template_id)
        )
        return {k: int(v) for k, v in rows}


class TemplateVersionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, version_id: uuid.UUID) -> BillTemplateVersion | None:
        return await self.session.get(BillTemplateVersion, version_id)

    async def list_for_template(self, template_id: uuid.UUID) -> Sequence[BillTemplateVersion]:
        rows = await self.session.scalars(
            select(BillTemplateVersion)
            .where(BillTemplateVersion.template_id == template_id)
            .order_by(BillTemplateVersion.version_number.desc())
        )
        return list(rows)

    async def next_version_number(self, template_id: uuid.UUID) -> int:
        highest = await self.session.scalar(
            select(func.max(BillTemplateVersion.version_number)).where(
                BillTemplateVersion.template_id == template_id
            )
        )
        return int(highest or 0) + 1

    async def create(self, version: BillTemplateVersion) -> BillTemplateVersion:
        self.session.add(version)
        await self.session.flush()
        return version

    async def bill_counts(self, template_id: uuid.UUID) -> dict[uuid.UUID, int]:
        """How many bills cite each version — a published version with bills can
        never be removed, and the UI says so."""
        rows = await self.session.execute(
            select(MaintenanceBill.template_version_id, func.count())
            .where(MaintenanceBill.template_id == template_id)
            .group_by(MaintenanceBill.template_version_id)
        )
        return {k: int(v) for k, v in rows}


class AssignmentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, assignment_id: uuid.UUID) -> BillTemplateAssignment | None:
        return await self.session.get(BillTemplateAssignment, assignment_id)

    async def list(
        self, *, template_id: uuid.UUID | None = None
    ) -> Sequence[BillTemplateAssignment]:
        stmt = select(BillTemplateAssignment).where(
            BillTemplateAssignment.is_active.is_(True)
        )
        if template_id is not None:
            stmt = stmt.where(BillTemplateAssignment.template_id == template_id)
        rows = await self.session.scalars(
            stmt.order_by(BillTemplateAssignment.priority.desc())
        )
        return list(rows)

    async def create(self, assignment: BillTemplateAssignment) -> BillTemplateAssignment:
        self.session.add(assignment)
        await self.session.flush()
        return assignment


class BillingRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, run_id: uuid.UUID) -> BillingRun | None:
        return await self.session.get(BillingRun, run_id)

    async def get_for_period(
        self, template_id: uuid.UUID, period_key: str
    ) -> BillingRun | None:
        return await self.session.scalar(
            select(BillingRun).where(
                BillingRun.template_id == template_id,
                BillingRun.period_key == period_key,
                BillingRun.status != BillingRunStatus.FAILED,
            )
        )

    async def list(
        self, *, page: int = 1, limit: int = 25, template_id: uuid.UUID | None = None
    ) -> tuple[Sequence[BillingRun], int]:
        stmt = select(BillingRun)
        if template_id is not None:
            stmt = stmt.where(BillingRun.template_id == template_id)
        total = await _count(self.session, stmt)
        rows = await self.session.scalars(
            stmt.order_by(BillingRun.period_start.desc(), BillingRun.created_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
        )
        return list(rows), total

    async def create(self, run: BillingRun) -> BillingRun:
        self.session.add(run)
        await self.session.flush()
        return run


class BillRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, bill_id: uuid.UUID) -> MaintenanceBill | None:
        return await self.session.get(MaintenanceBill, bill_id)

    async def get_detailed(self, bill_id: uuid.UUID) -> MaintenanceBill | None:
        return await self.session.scalar(
            select(MaintenanceBill)
            .where(MaintenanceBill.id == bill_id)
            .options(
                selectinload(MaintenanceBill.line_items),
                selectinload(MaintenanceBill.flat),
            )
        )

    async def list(
        self,
        *,
        page: int = 1,
        limit: int = 25,
        q: str | None = None,
        flat_id: uuid.UUID | None = None,
        run_id: uuid.UUID | None = None,
        period_key: str | None = None,
        status: BillStatus | None = None,
        payment_status: PaymentStatus | None = None,
        only_flat_ids: Sequence[uuid.UUID] | None = None,
    ) -> tuple[Sequence[MaintenanceBill], int]:
        stmt = select(MaintenanceBill).options(selectinload(MaintenanceBill.flat))
        if q:
            stmt = stmt.where(func.lower(MaintenanceBill.bill_number).like(f"%{q.lower()}%"))
        if flat_id is not None:
            stmt = stmt.where(MaintenanceBill.flat_id == flat_id)
        if run_id is not None:
            stmt = stmt.where(MaintenanceBill.billing_run_id == run_id)
        if period_key:
            stmt = stmt.where(MaintenanceBill.period_key == period_key)
        if status is not None:
            stmt = stmt.where(MaintenanceBill.status == status)
        if payment_status is not None:
            stmt = stmt.where(MaintenanceBill.payment_status == payment_status)
        if only_flat_ids is not None:
            # Owner scoping. An empty list must match nothing, not everything.
            stmt = stmt.where(
                MaintenanceBill.flat_id.in_(list(only_flat_ids)) if only_flat_ids else False
            )

        total = await _count(self.session, stmt)
        rows = await self.session.scalars(
            stmt.order_by(MaintenanceBill.period_start.desc(), MaintenanceBill.bill_number)
            .offset((page - 1) * limit)
            .limit(limit)
        )
        return list(rows), total

    async def list_for_run(self, run_id: uuid.UUID) -> Sequence[MaintenanceBill]:
        rows = await self.session.scalars(
            select(MaintenanceBill).where(MaintenanceBill.billing_run_id == run_id)
        )
        return list(rows)

    async def existing_flat_ids(
        self, template_id: uuid.UUID, period_key: str
    ) -> set[uuid.UUID]:
        """Flats already billed for this template and period — the guard against
        double-billing when a run is retried."""
        rows = await self.session.scalars(
            select(MaintenanceBill.flat_id).where(
                MaintenanceBill.template_id == template_id,
                MaintenanceBill.period_key == period_key,
                MaintenanceBill.status != BillStatus.VOID,
            )
        )
        return set(rows)

    async def next_sequence(self, fy_label: str) -> int:
        prefix = f"NF/{fy_label.removeprefix('FY')}/"
        highest = await self.session.scalar(
            select(func.count()).select_from(MaintenanceBill).where(
                MaintenanceBill.bill_number.like(f"{prefix}%")
            )
        )
        return int(highest or 0) + 1

    async def create_many(self, bills: Sequence[MaintenanceBill]) -> None:
        self.session.add_all(list(bills))
        await self.session.flush()

    async def outstanding_for_flat(self, flat_id: uuid.UUID, before: date) -> Decimal:
        """Unpaid balance from published bills issued before ``before``."""
        total = await self.session.scalar(
            select(func.coalesce(func.sum(MaintenanceBill.total - MaintenanceBill.amount_paid), 0))
            .where(
                MaintenanceBill.flat_id == flat_id,
                MaintenanceBill.status == BillStatus.PUBLISHED,
                MaintenanceBill.period_end < before,
                MaintenanceBill.amount_paid < MaintenanceBill.total,
            )
        )
        return Decimal(str(total or 0))

    async def outstanding_bulk(self, before: date) -> dict[uuid.UUID, Decimal]:
        """Outstanding per flat, in one query — the billing run needs all of them."""
        rows = await self.session.execute(
            select(
                MaintenanceBill.flat_id,
                func.sum(MaintenanceBill.total - MaintenanceBill.amount_paid),
            )
            .where(
                MaintenanceBill.status == BillStatus.PUBLISHED,
                MaintenanceBill.period_end < before,
                MaintenanceBill.amount_paid < MaintenanceBill.total,
            )
            .group_by(MaintenanceBill.flat_id)
        )
        return {k: Decimal(str(v or 0)) for k, v in rows}

    async def oldest_overdue_bulk(self, on: date) -> dict[uuid.UUID, int]:
        """Days overdue per flat, from the oldest unpaid published bill."""
        rows = await self.session.execute(
            select(MaintenanceBill.flat_id, func.min(MaintenanceBill.due_date))
            .where(
                MaintenanceBill.status == BillStatus.PUBLISHED,
                MaintenanceBill.amount_paid < MaintenanceBill.total,
                MaintenanceBill.due_date < on,
            )
            .group_by(MaintenanceBill.flat_id)
        )
        return {k: (on - due).days for k, due in rows if due is not None}

    async def publish_run(self, run_id: uuid.UUID, issued_at: object) -> int:
        result = await self.session.execute(
            update(MaintenanceBill)
            .where(
                MaintenanceBill.billing_run_id == run_id,
                MaintenanceBill.status == BillStatus.DRAFT,
            )
            .values(status=BillStatus.PUBLISHED, issued_at=issued_at)
        )
        return int(result.rowcount or 0)

    async def summary(self) -> dict[str, object]:
        published = select(MaintenanceBill).where(
            MaintenanceBill.status == BillStatus.PUBLISHED
        )
        billed = await self.session.scalar(
            select(func.coalesce(func.sum(MaintenanceBill.total), 0)).where(
                MaintenanceBill.status == BillStatus.PUBLISHED
            )
        )
        collected = await self.session.scalar(
            select(func.coalesce(func.sum(MaintenanceBill.amount_paid), 0)).where(
                MaintenanceBill.status == BillStatus.PUBLISHED
            )
        )
        by_status = await self.session.execute(
            select(MaintenanceBill.payment_status, func.count())
            .where(MaintenanceBill.status == BillStatus.PUBLISHED)
            .group_by(MaintenanceBill.payment_status)
        )
        return {
            "total_bills": await _count(self.session, published),
            "total_billed": Decimal(str(billed or 0)),
            "total_collected": Decimal(str(collected or 0)),
            "by_payment_status": {str(s.value): int(c) for s, c in by_status},
        }


class LineItemRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_many(self, items: Sequence[BillLineItem]) -> None:
        self.session.add_all(list(items))
        await self.session.flush()


class PaymentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, payment_id: uuid.UUID) -> Payment | None:
        return await self.session.get(Payment, payment_id)

    async def list(
        self,
        *,
        page: int = 1,
        limit: int = 25,
        flat_id: uuid.UUID | None = None,
        bill_id: uuid.UUID | None = None,
        only_flat_ids: Sequence[uuid.UUID] | None = None,
    ) -> tuple[Sequence[Payment], int]:
        stmt = select(Payment).options(selectinload(Payment.bill))
        if flat_id is not None:
            stmt = stmt.where(Payment.flat_id == flat_id)
        if bill_id is not None:
            stmt = stmt.where(Payment.bill_id == bill_id)
        if only_flat_ids is not None:
            stmt = stmt.where(
                Payment.flat_id.in_(list(only_flat_ids)) if only_flat_ids else False
            )
        total = await _count(self.session, stmt)
        rows = await self.session.scalars(
            stmt.order_by(Payment.paid_at.desc().nullslast(), Payment.created_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
        )
        return list(rows), total

    async def create(self, payment: Payment) -> Payment:
        self.session.add(payment)
        await self.session.flush()
        return payment

    async def total_paid_for_bill(self, bill_id: uuid.UUID) -> Decimal:
        total = await self.session.scalar(
            select(func.coalesce(func.sum(Payment.amount), 0)).where(
                Payment.bill_id == bill_id, Payment.status == PaymentStatus.SUCCESS
            )
        )
        return Decimal(str(total or 0))

    async def find_by_provider(self, provider: str, provider_payment_id: str) -> Payment | None:
        """Webhook idempotency: a retried callback must not double-credit."""
        return await self.session.scalar(
            select(Payment).where(
                Payment.provider == provider,
                Payment.provider_payment_id == provider_payment_id,
            )
        )
