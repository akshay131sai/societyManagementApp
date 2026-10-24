"""Billing services: templates, versions, runs, bills, payments.

The transaction and authorization boundary. Three rules shape this module:

* **A published version is never edited.** Changing a formula creates v2.
* **Nothing is published automatically.** A run always produces DRAFT bills; a
  human publishes.
* **One flat's failure never aborts the run.** A bad meter reading marks that
  bill FAILED and the other 399 still generate.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import Principal
from app.core.errors import (
    AlreadyExistsError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from app.core.permissions import Permission
from app.engines.billing.context import BillingContextBuilder
from app.engines.billing.periods import (
    BillingFrequency,
    BillingPeriod,
    financial_year_label,
    financial_year_start,
    period_for,
)
from app.engines.billing.resolver import FlatScope, applicable_flats, explain, resolve_for_flat
from app.engines.formula import (
    EvaluationError,
    FormulaDefinition,
    engine,
    validator,
)
from app.models.tenant import (
    BillLineItem,
    BillStatus,
    BillTemplate,
    BillTemplateAssignment,
    BillTemplateVersion,
    BillingRun,
    BillingRunStatus,
    MaintenanceBill,
    Payment,
    PaymentMethod,
    PaymentStatus,
)
from app.repositories.billing import (
    AssignmentRepository,
    BillRepository,
    BillingRunRepository,
    LineItemRepository,
    PaymentRepository,
    TemplateRepository,
    TemplateVersionRepository,
)
from app.repositories.structure import FlatRepository
from app.repositories.tenant import SocietySettingsRepository
from app.services.audit import AuditService, diff

log = structlog.get_logger(__name__)

MAX_FLATS_PER_RUN = 5000


class BillingAuditAction:
    TEMPLATE_CREATED = "TEMPLATE_CREATED"
    TEMPLATE_UPDATED = "TEMPLATE_UPDATED"
    TEMPLATE_DELETED = "TEMPLATE_DELETED"
    TEMPLATE_VERSION_CREATED = "TEMPLATE_VERSION_CREATED"
    TEMPLATE_VERSION_PUBLISHED = "TEMPLATE_VERSION_PUBLISHED"
    TEMPLATE_VERSION_ACTIVATED = "TEMPLATE_VERSION_ACTIVATED"
    ASSIGNMENT_CREATED = "ASSIGNMENT_CREATED"
    ASSIGNMENT_DELETED = "ASSIGNMENT_DELETED"
    BILLING_RUN_STARTED = "BILLING_RUN_STARTED"
    BILLS_PUBLISHED = "BILLS_PUBLISHED"
    BILL_VOIDED = "BILL_VOIDED"
    PAYMENT_RECORDED = "PAYMENT_RECORDED"


# --------------------------------------------------------------------------- #
# Templates
# --------------------------------------------------------------------------- #


class TemplateService:
    def __init__(self, tenant: AsyncSession) -> None:
        self.tenant = tenant
        self.repo = TemplateRepository(tenant)
        self.versions = TemplateVersionRepository(tenant)

    async def list(self, *, include_inactive: bool = False) -> list[dict[str, Any]]:
        templates = await self.repo.list(include_inactive=include_inactive)
        version_counts = await self.repo.version_counts()
        run_counts = await self.repo.run_counts()
        return [
            _template_dict(t, version_counts.get(t.id, 0), run_counts.get(t.id, 0))
            for t in templates
        ]

    async def get(self, template_id: uuid.UUID) -> dict[str, Any]:
        template = await self.repo.get(template_id)
        if template is None:
            raise NotFoundError("Bill template")
        versions = await self.versions.list_for_template(template_id)
        bill_counts = await self.versions.bill_counts(template_id)
        assignments = await AssignmentRepository(self.tenant).list(template_id=template_id)

        payload = _template_dict(template, len(versions), 0)
        payload["versions"] = [
            _version_dict(v, bill_counts.get(v.id, 0), v.id == template.active_version_id)
            for v in versions
        ]
        payload["assignments"] = [_assignment_dict(a) for a in assignments]
        return payload

    async def create(
        self,
        *,
        name: str,
        description: str | None,
        frequency: BillingFrequency,
        formula: FormulaDefinition,
        parameters: dict[str, Any],
        principal: Principal,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        if await self.repo.get_by_name(name):
            raise AlreadyExistsError(f"A template named '{name}' already exists.")

        errors = validator.validate(formula)
        if errors:
            raise ValidationError(
                "This formula is not valid.",
                details={"errors": [e.as_dict() for e in errors]},
            )

        template = BillTemplate(
            name=name.strip(),
            description=description,
            frequency=frequency,
            created_by=principal.tenant_user_id,
        )
        await self.repo.create(template)

        version = BillTemplateVersion(
            template_id=template.id,
            version_number=1,
            formula=formula.model_dump(mode="json"),
            parameters=parameters,
            notes="Initial version",
            is_published=False,
            created_by=principal.tenant_user_id,
        )
        await self.versions.create(version)

        template.active_version_id = version.id
        await self.tenant.flush()

        await AuditService.tenant(
            self.tenant,
            action=BillingAuditAction.TEMPLATE_CREATED,
            principal=principal,
            target_type="bill_template",
            target_id=template.id,
            changes={"after": {"name": template.name, "frequency": frequency.value}},
            request_id=request_id,
        )
        return await self.get(template.id)

    async def update(
        self,
        template_id: uuid.UUID,
        values: dict[str, Any],
        principal: Principal,
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        template = await self.repo.get(template_id)
        if template is None:
            raise NotFoundError("Bill template")

        before = {"name": template.name, "is_active": template.is_active}
        for field_name, value in values.items():
            setattr(template, field_name, value)
        await self.tenant.flush()

        await AuditService.tenant(
            self.tenant,
            action=BillingAuditAction.TEMPLATE_UPDATED,
            principal=principal,
            target_type="bill_template",
            target_id=template.id,
            changes=diff(before, {"name": template.name, "is_active": template.is_active}),
            request_id=request_id,
        )
        return await self.get(template.id)

    async def delete(
        self, template_id: uuid.UUID, principal: Principal, *, request_id: str | None = None
    ) -> None:
        template = await self.repo.get(template_id)
        if template is None:
            raise NotFoundError("Bill template")

        runs = (await self.repo.run_counts()).get(template_id, 0)
        if runs:
            raise ConflictError(
                f"This template has {runs} billing run(s) and cannot be deleted. "
                "Deactivate it instead — historical bills must keep their formula."
            )

        await self.tenant.delete(template)
        await self.tenant.flush()
        await AuditService.tenant(
            self.tenant,
            action=BillingAuditAction.TEMPLATE_DELETED,
            principal=principal,
            target_type="bill_template",
            target_id=template_id,
            changes={"before": {"name": template.name}},
            request_id=request_id,
        )


class TemplateVersionService:
    def __init__(self, tenant: AsyncSession) -> None:
        self.tenant = tenant
        self.repo = TemplateVersionRepository(tenant)
        self.templates = TemplateRepository(tenant)

    async def create(
        self,
        template_id: uuid.UUID,
        *,
        formula: FormulaDefinition,
        parameters: dict[str, Any],
        notes: str | None,
        activate: bool,
        principal: Principal,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """Append a new version. Existing versions are never touched."""
        template = await self.templates.get(template_id)
        if template is None:
            raise NotFoundError("Bill template")

        errors = validator.validate(formula)
        if errors:
            raise ValidationError(
                "This formula is not valid.",
                details={"errors": [e.as_dict() for e in errors]},
            )

        version = BillTemplateVersion(
            template_id=template_id,
            version_number=await self.repo.next_version_number(template_id),
            formula=formula.model_dump(mode="json"),
            parameters=parameters,
            notes=notes,
            is_published=False,
            created_by=principal.tenant_user_id,
        )
        await self.repo.create(version)

        if activate:
            template.active_version_id = version.id
            await self.tenant.flush()

        await AuditService.tenant(
            self.tenant,
            action=BillingAuditAction.TEMPLATE_VERSION_CREATED,
            principal=principal,
            target_type="bill_template_version",
            target_id=version.id,
            changes={
                "after": {
                    "template": template.name,
                    "version": version.version_number,
                    "activated": activate,
                }
            },
            request_id=request_id,
        )
        return _version_dict(version, 0, activate)

    async def update_draft(
        self,
        version_id: uuid.UUID,
        *,
        formula: FormulaDefinition | None,
        parameters: dict[str, Any] | None,
        notes: str | None,
        principal: Principal,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """Edit an unpublished version. A published one is refused by the DB too."""
        version = await self.repo.get(version_id)
        if version is None:
            raise NotFoundError("Template version")
        if version.is_published:
            raise ConflictError(
                f"Version {version.version_number} is published and cannot be edited. "
                "Create a new version instead."
            )

        if formula is not None:
            errors = validator.validate(formula)
            if errors:
                raise ValidationError(
                    "This formula is not valid.",
                    details={"errors": [e.as_dict() for e in errors]},
                )
            version.formula = formula.model_dump(mode="json")
        if parameters is not None:
            version.parameters = parameters
        if notes is not None:
            version.notes = notes

        await self.tenant.flush()
        return _version_dict(version, 0, False)

    async def activate(
        self, version_id: uuid.UUID, principal: Principal, *, request_id: str | None = None
    ) -> dict[str, Any]:
        version = await self.repo.get(version_id)
        if version is None:
            raise NotFoundError("Template version")
        template = await self.templates.get(version.template_id)
        if template is None:  # pragma: no cover - FK guarantees this
            raise NotFoundError("Bill template")

        template.active_version_id = version.id
        await self.tenant.flush()

        await AuditService.tenant(
            self.tenant,
            action=BillingAuditAction.TEMPLATE_VERSION_ACTIVATED,
            principal=principal,
            target_type="bill_template_version",
            target_id=version.id,
            changes={"after": {"version": version.version_number}},
            request_id=request_id,
        )
        return _version_dict(version, 0, True)

    async def preview(
        self,
        version_id: uuid.UUID | None,
        formula: FormulaDefinition,
        parameters: dict[str, Any],
        flat_id: uuid.UUID | None,
        principal: Principal,
    ) -> dict[str, Any]:
        """Evaluate against one real flat without persisting anything.

        This is what makes the Bill Builder's live preview trustworthy: it is
        the same engine and the same context builder the real run uses, not a
        client-side approximation.
        """
        errors = validator.validate(formula)
        if errors:
            return {
                "valid": False,
                "errors": [e.as_dict() for e in errors],
                "flat": None,
                "line_items": [],
                "total": "0.00",
                "trace": [],
            }

        flat_repo = FlatRepository(self.tenant)
        flat = (
            await flat_repo.get_detailed(flat_id)
            if flat_id
            else next(iter((await flat_repo.list(page=1, limit=1))[0]), None)
        )
        if flat is None:
            return {
                "valid": True,
                "errors": [],
                "flat": None,
                "line_items": [],
                "total": "0.00",
                "trace": [],
                "message": "Add a flat to see a preview against real data.",
            }

        settings = await SocietySettingsRepository(self.tenant).get()
        fy_month = settings.financial_year_start_month if settings else 4
        period = period_for(BillingFrequency.MONTHLY, date.today(), fy_start_month=fy_month)

        inputs = await BillingContextBuilder(self.tenant).build([flat], period, parameters)
        context = inputs.context_for(flat.id)

        try:
            result = engine.evaluate(formula, context)
        except EvaluationError as exc:
            return {
                "valid": False,
                "errors": [{"code": exc.code, "message": exc.message, "path": exc.path}],
                "flat": {"id": str(flat.id), "flat_number": flat.flat_number},
                "line_items": [],
                "total": "0.00",
                "trace": [],
            }

        return {
            "valid": True,
            "errors": [],
            "flat": {
                "id": str(flat.id),
                "flat_number": flat.flat_number,
                "area_sqft": str(flat.area_sqft),
                "flat_type": flat.flat_type,
                "occupancy_status": flat.occupancy_status.value,
            },
            "period": period.as_dict(),
            "line_items": [li.as_dict() for li in result.line_items],
            "subtotal": str(result.subtotal),
            "credits": str(result.credits),
            "total": str(result.total),
            "trace": result.trace_as_list(),
            "inputs": context.snapshot(),
        }


class AssignmentService:
    def __init__(self, tenant: AsyncSession) -> None:
        self.tenant = tenant
        self.repo = AssignmentRepository(tenant)

    async def list(self, *, template_id: uuid.UUID | None = None) -> list[dict[str, Any]]:
        return [_assignment_dict(a) for a in await self.repo.list(template_id=template_id)]

    async def create(
        self, values: dict[str, Any], principal: Principal, *, request_id: str | None = None
    ) -> dict[str, Any]:
        if await TemplateRepository(self.tenant).get(values["template_id"]) is None:
            raise NotFoundError("Bill template")

        assignment = BillTemplateAssignment(**values)
        await self.repo.create(assignment)
        await AuditService.tenant(
            self.tenant,
            action=BillingAuditAction.ASSIGNMENT_CREATED,
            principal=principal,
            target_type="bill_template_assignment",
            target_id=assignment.id,
            changes={"after": {"scope": assignment.scope.value}},
            request_id=request_id,
        )
        return _assignment_dict(assignment)

    async def delete(
        self, assignment_id: uuid.UUID, principal: Principal, *, request_id: str | None = None
    ) -> None:
        assignment = await self.repo.get(assignment_id)
        if assignment is None:
            raise NotFoundError("Assignment")
        await self.tenant.delete(assignment)
        await self.tenant.flush()
        await AuditService.tenant(
            self.tenant,
            action=BillingAuditAction.ASSIGNMENT_DELETED,
            principal=principal,
            target_type="bill_template_assignment",
            target_id=assignment_id,
            request_id=request_id,
        )

    async def explain_for_flat(self, flat_id: uuid.UUID) -> dict[str, Any]:
        """Why this flat bills under this template — the first support question."""
        flat = await FlatRepository(self.tenant).get(flat_id)
        if flat is None:
            raise NotFoundError("Flat")

        assignments = list(await self.repo.list())
        scope = FlatScope.of(flat)
        winner = resolve_for_flat(assignments, scope)
        return {
            "flat_id": str(flat.id),
            "flat_number": flat.flat_number,
            "template_id": str(winner.template_id) if winner else None,
            "candidates": explain(assignments, scope),
        }


# --------------------------------------------------------------------------- #
# Billing runs
# --------------------------------------------------------------------------- #


class BillingRunService:
    def __init__(self, tenant: AsyncSession) -> None:
        self.tenant = tenant
        self.runs = BillingRunRepository(tenant)
        self.bills = BillRepository(tenant)
        self.templates = TemplateRepository(tenant)
        self.versions = TemplateVersionRepository(tenant)

    async def list(
        self, *, page: int, limit: int, template_id: uuid.UUID | None = None
    ) -> tuple[list[dict[str, Any]], int]:
        rows, total = await self.runs.list(page=page, limit=limit, template_id=template_id)
        return [_run_dict(r) for r in rows], total

    async def get(self, run_id: uuid.UUID) -> dict[str, Any]:
        run = await self.runs.get(run_id)
        if run is None:
            raise NotFoundError("Billing run")
        return _run_dict(run)

    async def create(
        self,
        *,
        template_id: uuid.UUID,
        period_key: str | None,
        principal: Principal,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """Generate DRAFT bills for every applicable flat.

        Nothing is published here. A human reviews and publishes.
        """
        template = await self.templates.get(template_id)
        if template is None:
            raise NotFoundError("Bill template")
        if not template.is_active:
            raise ConflictError("This template is inactive.")
        if template.active_version_id is None:
            raise ConflictError("This template has no active version.")

        version = await self.versions.get(template.active_version_id)
        if version is None:  # pragma: no cover - FK guarantees this
            raise NotFoundError("Template version")

        settings = await SocietySettingsRepository(self.tenant).get()
        fy_month = settings.financial_year_start_month if settings else 4
        due_days = settings.bill_due_days if settings else 15

        period = self._resolve_period(template.frequency, period_key, fy_month)

        existing = await self.runs.get_for_period(template_id, period.key)
        if existing is not None:
            raise ConflictError(
                f"{template.name} has already been billed for {period.label}. "
                f"Open that run instead of creating another."
            )

        formula = FormulaDefinition.model_validate(version.formula)
        errors = validator.validate(formula)
        if errors:
            raise ValidationError(
                "The active version's formula is no longer valid.",
                details={"errors": [e.as_dict() for e in errors]},
            )

        assignments = list(await AssignmentRepository(self.tenant).list())
        all_flats = list((await FlatRepository(self.tenant).list(page=1, limit=MAX_FLATS_PER_RUN))[0])
        flats = (
            applicable_flats(assignments, all_flats, template_id)
            if assignments
            else all_flats
        )

        if not flats:
            raise ConflictError(
                "No flats are assigned to this template. Add an assignment, or "
                "create one with scope ALL."
            )

        already_billed = await self.bills.existing_flat_ids(template_id, period.key)
        flats = [f for f in flats if f.id not in already_billed]
        if not flats:
            raise ConflictError(
                f"Every applicable flat already has a bill for {period.label}."
            )

        run = BillingRun(
            template_id=template_id,
            template_version_id=version.id,
            frequency=template.frequency,
            period_key=period.key,
            period_label=period.label,
            period_start=period.start,
            period_end=period.end,
            due_date=period.due_date(due_days),
            status=BillingRunStatus.RUNNING,
            total_flats=len(flats),
            started_at=datetime.now(timezone.utc),
            created_by=principal.tenant_user_id,
        )
        await self.runs.create(run)

        generated, failed, errors_summary, total_amount = await self._generate(
            run, formula, version, flats, period, fy_month
        )

        run.bills_generated = generated
        run.bills_failed = failed
        run.total_amount = total_amount
        run.error_summary = errors_summary or None
        run.status = (
            BillingRunStatus.COMPLETED_WITH_ERRORS if failed else BillingRunStatus.COMPLETED
        )
        run.completed_at = datetime.now(timezone.utc)
        await self.tenant.flush()

        await AuditService.tenant(
            self.tenant,
            action=BillingAuditAction.BILLING_RUN_STARTED,
            principal=principal,
            target_type="billing_run",
            target_id=run.id,
            changes={
                "after": {
                    "template": template.name,
                    "period": period.key,
                    "generated": generated,
                    "failed": failed,
                    "total": str(total_amount),
                }
            },
            request_id=request_id,
        )
        log.info(
            "billing.run_completed",
            society_id=str(principal.society_id),
            period=period.key,
            generated=generated,
            failed=failed,
        )
        return _run_dict(run)

    async def _generate(
        self,
        run: BillingRun,
        formula: FormulaDefinition,
        version: BillTemplateVersion,
        flats: list[Any],
        period: BillingPeriod,
        fy_month: int,
    ) -> tuple[int, int, list[dict[str, Any]], Decimal]:
        inputs = await BillingContextBuilder(self.tenant).build(
            flats, period, version.parameters or {}
        )

        fy_label = financial_year_label(financial_year_start(period.end, fy_month))
        sequence = await self.bills.next_sequence(fy_label)
        formula_snapshot = version.formula

        bills: list[MaintenanceBill] = []
        results: list[tuple[MaintenanceBill, Any]] = []
        failures: list[dict[str, Any]] = []
        total_amount = Decimal(0)

        for flat in flats:
            context = inputs.context_for(flat.id)
            bill_number = f"NF/{fy_label.removeprefix('FY')}/{sequence:06d}"
            sequence += 1

            try:
                result = engine.evaluate(formula, context)
            except EvaluationError as exc:
                # One flat's failure must not abort the run. The bill is
                # recorded as FAILED so the admin can see exactly which flats
                # need attention, and re-run once they are fixed.
                failures.append(
                    {
                        "flat_id": str(flat.id),
                        "flat_number": flat.flat_number,
                        "code": exc.code,
                        "message": exc.message,
                    }
                )
                bills.append(
                    MaintenanceBill(
                        bill_number=bill_number,
                        billing_run_id=run.id,
                        flat_id=flat.id,
                        template_id=run.template_id,
                        template_version_id=version.id,
                        formula_snapshot=formula_snapshot,
                        input_snapshot=context.snapshot(),
                        calculation_trace=[],
                        period_key=period.key,
                        period_label=period.label,
                        period_start=period.start,
                        period_end=period.end,
                        due_date=run.due_date,
                        status=BillStatus.FAILED,
                        failure_reason=f"{exc.code}: {exc.message}",
                    )
                )
                continue

            bill = MaintenanceBill(
                bill_number=bill_number,
                billing_run_id=run.id,
                flat_id=flat.id,
                template_id=run.template_id,
                template_version_id=version.id,
                formula_snapshot=formula_snapshot,
                input_snapshot=context.snapshot(),
                calculation_trace=result.trace_as_list(),
                period_key=period.key,
                period_label=period.label,
                period_start=period.start,
                period_end=period.end,
                subtotal=result.subtotal,
                discount=result.credits,
                total=result.total,
                due_date=run.due_date,
                status=BillStatus.DRAFT,
                payment_status=PaymentStatus.UNPAID,
            )
            bills.append(bill)
            results.append((bill, result))
            total_amount += result.total

        # Bill ids are generated by the database, so line items can only be
        # built once the bills have been flushed.
        await self.bills.create_many(bills)

        line_items = [
            BillLineItem(
                bill_id=bill.id,
                sort_order=item.sort_order,
                code=item.code,
                label=item.label,
                quantity=item.quantity,
                unit=item.unit,
                rate=item.rate,
                amount=item.amount,
                is_credit=item.is_credit,
            )
            for bill, result in results
            for item in result.line_items
        ]
        await LineItemRepository(self.tenant).create_many(line_items)

        generated = sum(1 for b in bills if b.status is BillStatus.DRAFT)
        return generated, len(failures), failures, total_amount

    async def publish(
        self, run_id: uuid.UUID, principal: Principal, *, request_id: str | None = None
    ) -> dict[str, Any]:
        """Publish every DRAFT bill in the run. Irreversible."""
        run = await self.runs.get(run_id)
        if run is None:
            raise NotFoundError("Billing run")
        if run.status is BillingRunStatus.PUBLISHED:
            raise ConflictError("This run has already been published.")
        if run.status not in (
            BillingRunStatus.COMPLETED,
            BillingRunStatus.COMPLETED_WITH_ERRORS,
        ):
            raise ConflictError("Only a completed run can be published.")

        issued_at = datetime.now(timezone.utc)
        published = await self.bills.publish_run(run_id, issued_at)

        run.status = BillingRunStatus.PUBLISHED
        run.published_at = issued_at
        run.published_by = principal.tenant_user_id
        await self.tenant.flush()

        await AuditService.tenant(
            self.tenant,
            action=BillingAuditAction.BILLS_PUBLISHED,
            principal=principal,
            target_type="billing_run",
            target_id=run.id,
            changes={"after": {"period": run.period_key, "bills": published}},
            request_id=request_id,
        )
        log.info(
            "billing.published",
            society_id=str(principal.society_id),
            period=run.period_key,
            bills=published,
        )
        return _run_dict(run)

    async def delete_draft(
        self, run_id: uuid.UUID, principal: Principal, *, request_id: str | None = None
    ) -> None:
        run = await self.runs.get(run_id)
        if run is None:
            raise NotFoundError("Billing run")
        if run.status is BillingRunStatus.PUBLISHED:
            raise ConflictError(
                "A published run cannot be discarded. Void individual bills instead."
            )
        await self.tenant.delete(run)
        await self.tenant.flush()

    async def periods_for(self, template_id: uuid.UUID) -> list[dict[str, Any]]:
        """Recent periods with whether each has already been billed."""
        from app.engines.billing.periods import recent_periods

        template = await self.templates.get(template_id)
        if template is None:
            raise NotFoundError("Bill template")

        settings = await SocietySettingsRepository(self.tenant).get()
        fy_month = settings.financial_year_start_month if settings else 4
        periods = recent_periods(template.frequency, date.today(), 6, fy_start_month=fy_month)

        result = []
        for period in periods:
            existing = await self.runs.get_for_period(template_id, period.key)
            result.append(
                {
                    **period.as_dict(),
                    "already_billed": existing is not None,
                    "run_id": str(existing.id) if existing else None,
                }
            )
        return result

    @staticmethod
    def _resolve_period(
        frequency: BillingFrequency, period_key: str | None, fy_month: int
    ) -> BillingPeriod:
        from app.engines.billing.periods import parse_key

        if period_key is None:
            return period_for(frequency, date.today(), fy_start_month=fy_month)
        try:
            period = parse_key(period_key, fy_start_month=fy_month)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        if period.frequency is not frequency:
            raise ValidationError(
                f"'{period_key}' is a {period.frequency.value.lower()} period, but this "
                f"template bills {frequency.value.lower()}."
            )
        return period


# --------------------------------------------------------------------------- #
# Bills & payments
# --------------------------------------------------------------------------- #


class BillService:
    def __init__(self, tenant: AsyncSession) -> None:
        self.tenant = tenant
        self.repo = BillRepository(tenant)

    def _owner_scope(self, principal: Principal) -> list[uuid.UUID] | None:
        if principal.is_scoped_to_own(Permission.BILLING_READ):
            return sorted(principal.flat_ids)
        return None

    async def list(
        self,
        principal: Principal,
        *,
        page: int,
        limit: int,
        q: str | None = None,
        flat_id: uuid.UUID | None = None,
        run_id: uuid.UUID | None = None,
        period_key: str | None = None,
        status: BillStatus | None = None,
        payment_status: PaymentStatus | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        rows, total = await self.repo.list(
            page=page,
            limit=limit,
            q=q,
            flat_id=flat_id,
            run_id=run_id,
            period_key=period_key,
            status=status,
            payment_status=payment_status,
            only_flat_ids=self._owner_scope(principal),
        )
        return [_bill_dict(b) for b in rows], total

    async def get(self, bill_id: uuid.UUID, principal: Principal) -> dict[str, Any]:
        bill = await self.repo.get_detailed(bill_id)
        if bill is None:
            raise NotFoundError("Bill")

        scope = self._owner_scope(principal)
        if scope is not None and bill.flat_id not in scope:
            raise NotFoundError("Bill")

        payload = _bill_dict(bill)
        payload["line_items"] = [
            {
                "id": str(li.id),
                "sort_order": li.sort_order,
                "code": li.code,
                "label": li.label,
                "quantity": str(li.quantity) if li.quantity is not None else None,
                "unit": li.unit,
                "rate": str(li.rate) if li.rate is not None else None,
                "amount": str(li.amount),
                "is_credit": li.is_credit,
            }
            for li in bill.line_items
        ]
        return payload

    async def calculation(self, bill_id: uuid.UUID, principal: Principal) -> dict[str, Any]:
        """"How was this calculated?" — served entirely from the snapshot.

        No re-evaluation, no reliance on the flat's *current* data. A bill from
        three years ago explains itself with the numbers it was actually built
        from.
        """
        bill = await self.repo.get_detailed(bill_id)
        if bill is None:
            raise NotFoundError("Bill")

        scope = self._owner_scope(principal)
        if scope is not None and bill.flat_id not in scope:
            raise NotFoundError("Bill")

        return {
            "bill_id": str(bill.id),
            "bill_number": bill.bill_number,
            "period_label": bill.period_label,
            "inputs": bill.input_snapshot,
            "formula": bill.formula_snapshot,
            "trace": bill.calculation_trace,
            "line_items": [
                {
                    "code": li.code,
                    "label": li.label,
                    "quantity": str(li.quantity) if li.quantity is not None else None,
                    "unit": li.unit,
                    "rate": str(li.rate) if li.rate is not None else None,
                    "amount": str(li.amount),
                    "is_credit": li.is_credit,
                }
                for li in bill.line_items
            ],
            "subtotal": str(bill.subtotal),
            "discount": str(bill.discount),
            "total": str(bill.total),
        }

    async def void(
        self,
        bill_id: uuid.UUID,
        reason: str,
        principal: Principal,
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        bill = await self.repo.get(bill_id)
        if bill is None:
            raise NotFoundError("Bill")
        if bill.status is BillStatus.VOID:
            raise ConflictError("This bill is already void.")

        bill.status = BillStatus.VOID
        bill.failure_reason = reason
        await self.tenant.flush()

        await AuditService.tenant(
            self.tenant,
            action=BillingAuditAction.BILL_VOIDED,
            principal=principal,
            target_type="maintenance_bill",
            target_id=bill.id,
            changes={"after": {"status": "VOID", "reason": reason}},
            request_id=request_id,
        )
        return _bill_dict(bill)

    async def summary(self) -> dict[str, Any]:
        data = await self.repo.summary()
        billed = Decimal(str(data["total_billed"]))
        collected = Decimal(str(data["total_collected"]))
        return {
            "total_bills": data["total_bills"],
            "total_billed": str(billed),
            "total_collected": str(collected),
            "total_outstanding": str(billed - collected),
            "collection_rate": (
                round(float(collected / billed * 100), 1) if billed > 0 else 0.0
            ),
            "by_payment_status": data["by_payment_status"],
        }


class PaymentService:
    def __init__(self, tenant: AsyncSession) -> None:
        self.tenant = tenant
        self.repo = PaymentRepository(tenant)
        self.bills = BillRepository(tenant)

    def _owner_scope(self, principal: Principal) -> list[uuid.UUID] | None:
        if principal.is_scoped_to_own(Permission.PAYMENT_READ):
            return sorted(principal.flat_ids)
        return None

    async def list(
        self,
        principal: Principal,
        *,
        page: int,
        limit: int,
        flat_id: uuid.UUID | None = None,
        bill_id: uuid.UUID | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        rows, total = await self.repo.list(
            page=page,
            limit=limit,
            flat_id=flat_id,
            bill_id=bill_id,
            only_flat_ids=self._owner_scope(principal),
        )
        return [_payment_dict(p) for p in rows], total

    async def record(
        self,
        *,
        bill_id: uuid.UUID | None,
        flat_id: uuid.UUID | None,
        amount: Decimal,
        method: PaymentMethod,
        reference_number: str | None,
        paid_at: datetime | None,
        notes: str | None,
        principal: Principal,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        bill: MaintenanceBill | None = None
        if bill_id is not None:
            bill = await self.bills.get(bill_id)
            if bill is None:
                raise NotFoundError("Bill")
            if bill.status is not BillStatus.PUBLISHED:
                raise ConflictError("Only a published bill can be paid.")
            flat_id = bill.flat_id

        if flat_id is None:
            raise ValidationError("A payment needs either a bill or a flat.")

        scope = self._owner_scope(principal)
        if scope is not None and flat_id not in scope:
            raise NotFoundError("Bill")

        if bill is not None and amount > bill.balance_due:
            raise ValidationError(
                f"This payment of ₹{amount} exceeds the outstanding balance of "
                f"₹{bill.balance_due}."
            )

        payment = Payment(
            bill_id=bill_id,
            flat_id=flat_id,
            amount=amount,
            method=method,
            status=PaymentStatus.SUCCESS,
            reference_number=reference_number,
            paid_at=paid_at or datetime.now(timezone.utc),
            notes=notes,
            recorded_by=principal.tenant_user_id,
        )
        await self.repo.create(payment)

        if bill is not None:
            await self._apply_to_bill(bill)

        await AuditService.tenant(
            self.tenant,
            action=BillingAuditAction.PAYMENT_RECORDED,
            principal=principal,
            target_type="payment",
            target_id=payment.id,
            changes={
                "after": {
                    "amount": str(amount),
                    "method": method.value,
                    "bill": bill.bill_number if bill else None,
                }
            },
            request_id=request_id,
        )
        return _payment_dict(payment)

    async def _apply_to_bill(self, bill: MaintenanceBill) -> None:
        """Recompute the bill's payment state from its payments.

        Derived, not incremented: a recomputation cannot drift, and the trigger
        permits exactly these columns to change on a published bill.
        """
        paid = await self.repo.total_paid_for_bill(bill.id)
        bill.amount_paid = paid

        if paid >= bill.total:
            bill.payment_status = PaymentStatus.PAID
            bill.paid_at = datetime.now(timezone.utc)
        elif paid > 0:
            bill.payment_status = PaymentStatus.PARTIAL
            bill.paid_at = None
        elif bill.due_date < date.today():
            bill.payment_status = PaymentStatus.OVERDUE
        else:
            bill.payment_status = PaymentStatus.UNPAID

        await self.tenant.flush()


# --------------------------------------------------------------------------- #
# Serialisers
# --------------------------------------------------------------------------- #


def _template_dict(t: BillTemplate, versions: int, runs: int) -> dict[str, Any]:
    return {
        "id": t.id,
        "name": t.name,
        "description": t.description,
        "frequency": t.frequency,
        "is_active": t.is_active,
        "active_version_id": t.active_version_id,
        "version_count": versions,
        "run_count": runs,
        "created_at": t.created_at,
    }


def _version_dict(v: BillTemplateVersion, bill_count: int, is_active: bool) -> dict[str, Any]:
    return {
        "id": v.id,
        "template_id": v.template_id,
        "version_number": v.version_number,
        "formula": v.formula,
        "parameters": v.parameters,
        "notes": v.notes,
        "is_published": v.is_published,
        "is_active": is_active,
        "bill_count": bill_count,
        "created_at": v.created_at,
    }


def _assignment_dict(a: BillTemplateAssignment) -> dict[str, Any]:
    return {
        "id": a.id,
        "template_id": a.template_id,
        "scope": a.scope,
        "building_id": a.building_id,
        "block_id": a.block_id,
        "flat_id": a.flat_id,
        "flat_type": a.flat_type,
        "priority": a.priority,
        "is_active": a.is_active,
    }


def _run_dict(r: BillingRun) -> dict[str, Any]:
    return {
        "id": r.id,
        "template_id": r.template_id,
        "template_name": r.template.name if "template" in r.__dict__ and r.template else None,
        "template_version_id": r.template_version_id,
        "version_number": r.version.version_number if "version" in r.__dict__ and r.version else None,
        "frequency": r.frequency,
        "period_key": r.period_key,
        "period_label": r.period_label,
        "period_start": r.period_start,
        "period_end": r.period_end,
        "due_date": r.due_date,
        "status": r.status,
        "total_flats": r.total_flats,
        "bills_generated": r.bills_generated,
        "bills_failed": r.bills_failed,
        "total_amount": r.total_amount,
        "error_summary": r.error_summary,
        "started_at": r.started_at,
        "completed_at": r.completed_at,
        "published_at": r.published_at,
        "created_at": r.created_at,
    }


def _bill_dict(b: MaintenanceBill) -> dict[str, Any]:
    flat = b.flat if "flat" in b.__dict__ else None
    return {
        "id": b.id,
        "bill_number": b.bill_number,
        "billing_run_id": b.billing_run_id,
        "flat_id": b.flat_id,
        "flat_number": flat.flat_number if flat else None,
        "building_name": None,
        "template_id": b.template_id,
        "template_version_id": b.template_version_id,
        "period_key": b.period_key,
        "period_label": b.period_label,
        "period_start": b.period_start,
        "period_end": b.period_end,
        "subtotal": b.subtotal,
        "penalty": b.penalty,
        "discount": b.discount,
        "tax": b.tax,
        "total": b.total,
        "amount_paid": b.amount_paid,
        "balance_due": b.total - b.amount_paid,
        "status": b.status,
        "payment_status": b.payment_status,
        "issued_at": b.issued_at,
        "due_date": b.due_date,
        "paid_at": b.paid_at,
        "failure_reason": b.failure_reason,
        "created_at": b.created_at,
    }


def _payment_dict(p: Payment) -> dict[str, Any]:
    return {
        "id": p.id,
        "bill_id": p.bill_id,
        "bill_number": p.bill.bill_number if "bill" in p.__dict__ and p.bill else None,
        "flat_id": p.flat_id,
        "amount": p.amount,
        "method": p.method,
        "status": p.status,
        "reference_number": p.reference_number,
        "paid_at": p.paid_at,
        "notes": p.notes,
        "created_at": p.created_at,
    }
