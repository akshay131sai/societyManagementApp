"""Billing endpoints: templates, versions, assignments, runs, bills, payments."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import TenantSession, require_permission
from app.auth.principal import Principal
from app.core.permissions import Permission
from app.engines.formula import catalogue, validator
from app.models.tenant import BillStatus, PaymentStatus
from app.schemas.billing import (
    AssignmentCreate,
    AssignmentRead,
    BillCalculation,
    BillDetail,
    BillingSummary,
    BillRead,
    BillVoidRequest,
    FieldSpecRead,
    FormulaValidateRequest,
    FormulaValidateResponse,
    PaymentCreate,
    PaymentRead,
    PeriodOption,
    PreviewRequest,
    RunCreate,
    RunRead,
    TemplateCreate,
    TemplateDetail,
    TemplateRead,
    TemplateUpdate,
    VersionCreate,
    VersionRead,
    VersionUpdate,
)
from app.schemas.common import Envelope, Page, PageParams, ok
from app.services.billing import (
    AssignmentService,
    BillingRunService,
    BillService,
    PaymentService,
    TemplateService,
    TemplateVersionService,
)

router = APIRouter(tags=["billing"])

PageDep = Annotated[PageParams, Depends()]


def _rid(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


# --------------------------------------------------------------------------- #
# The field catalogue — drives the Bill Builder palette
# --------------------------------------------------------------------------- #


@router.get(
    "/billing/fields",
    response_model=Envelope[list[FieldSpecRead]],
    summary="Fields a formula may reference",
    description="Generated from the engine's field registry, so the palette "
    "cannot offer a field the validator would reject.",
)
async def list_fields(
    tenant: TenantSession,
    principal: Annotated[
        Principal, Depends(require_permission(Permission.BILLING_MANAGE_TEMPLATE))
    ],
) -> dict[str, Any]:
    return ok(catalogue())


@router.post(
    "/billing/validate",
    response_model=Envelope[FormulaValidateResponse],
    summary="Validate a formula without saving",
)
async def validate_formula(
    body: FormulaValidateRequest,
    tenant: TenantSession,
    principal: Annotated[
        Principal, Depends(require_permission(Permission.BILLING_MANAGE_TEMPLATE))
    ],
) -> dict[str, Any]:
    errors = validator.validate(body.formula)
    return ok({"valid": not errors, "errors": [e.as_dict() for e in errors]})


@router.post(
    "/billing/preview",
    response_model=Envelope[dict],
    summary="Evaluate a formula against a real flat",
    description=(
        "Runs the same engine and the same context builder the real billing run "
        "uses, against one real flat, and persists nothing. This is what makes "
        "the Bill Builder preview trustworthy rather than an approximation."
    ),
)
async def preview_formula(
    body: PreviewRequest,
    tenant: TenantSession,
    principal: Annotated[
        Principal, Depends(require_permission(Permission.BILLING_MANAGE_TEMPLATE))
    ],
) -> dict[str, Any]:
    result = await TemplateVersionService(tenant).preview(
        None, body.formula, body.parameters, body.flat_id, principal
    )
    return ok(result)


# --------------------------------------------------------------------------- #
# Templates
# --------------------------------------------------------------------------- #


@router.get(
    "/bill-templates", response_model=Envelope[list[TemplateRead]], summary="List templates"
)
async def list_templates(
    tenant: TenantSession,
    principal: Annotated[
        Principal, Depends(require_permission(Permission.BILLING_MANAGE_TEMPLATE))
    ],
    include_inactive: Annotated[bool, Query()] = False,
) -> dict[str, Any]:
    return ok(await TemplateService(tenant).list(include_inactive=include_inactive))


@router.post(
    "/bill-templates",
    response_model=Envelope[TemplateDetail],
    status_code=201,
    summary="Create a template",
)
async def create_template(
    body: TemplateCreate,
    request: Request,
    tenant: TenantSession,
    principal: Annotated[
        Principal, Depends(require_permission(Permission.BILLING_MANAGE_TEMPLATE))
    ],
) -> dict[str, Any]:
    template = await TemplateService(tenant).create(
        name=body.name,
        description=body.description,
        frequency=body.frequency,
        formula=body.formula,
        parameters=body.parameters,
        principal=principal,
        request_id=_rid(request),
    )
    return ok(template, message="Template created.")


@router.get(
    "/bill-templates/{template_id}",
    response_model=Envelope[TemplateDetail],
    summary="Template with its versions and assignments",
)
async def get_template(
    template_id: uuid.UUID,
    tenant: TenantSession,
    principal: Annotated[
        Principal, Depends(require_permission(Permission.BILLING_MANAGE_TEMPLATE))
    ],
) -> dict[str, Any]:
    return ok(await TemplateService(tenant).get(template_id))


@router.patch(
    "/bill-templates/{template_id}",
    response_model=Envelope[TemplateDetail],
    summary="Rename or deactivate a template",
)
async def update_template(
    template_id: uuid.UUID,
    body: TemplateUpdate,
    request: Request,
    tenant: TenantSession,
    principal: Annotated[
        Principal, Depends(require_permission(Permission.BILLING_MANAGE_TEMPLATE))
    ],
) -> dict[str, Any]:
    values = body.model_dump(exclude_unset=True)
    return ok(
        await TemplateService(tenant).update(
            template_id, values, principal, request_id=_rid(request)
        ),
        message="Template updated.",
    )


@router.delete(
    "/bill-templates/{template_id}", response_model=Envelope[dict], summary="Delete a template"
)
async def delete_template(
    template_id: uuid.UUID,
    request: Request,
    tenant: TenantSession,
    principal: Annotated[
        Principal, Depends(require_permission(Permission.BILLING_MANAGE_TEMPLATE))
    ],
) -> dict[str, Any]:
    await TemplateService(tenant).delete(template_id, principal, request_id=_rid(request))
    return ok({"deleted": True}, message="Template deleted.")


# --------------------------------------------------------------------------- #
# Versions
# --------------------------------------------------------------------------- #


@router.post(
    "/bill-templates/{template_id}/versions",
    response_model=Envelope[VersionRead],
    status_code=201,
    summary="Add a version",
    description="Append-only. Existing versions are never modified, so bills "
    "generated from them stay reproducible forever.",
)
async def create_version(
    template_id: uuid.UUID,
    body: VersionCreate,
    request: Request,
    tenant: TenantSession,
    principal: Annotated[
        Principal, Depends(require_permission(Permission.BILLING_MANAGE_TEMPLATE))
    ],
) -> dict[str, Any]:
    version = await TemplateVersionService(tenant).create(
        template_id,
        formula=body.formula,
        parameters=body.parameters,
        notes=body.notes,
        activate=body.activate,
        principal=principal,
        request_id=_rid(request),
    )
    return ok(version, message=f"Version {version['version_number']} created.")


@router.patch(
    "/bill-template-versions/{version_id}",
    response_model=Envelope[VersionRead],
    summary="Edit an unpublished version",
)
async def update_version(
    version_id: uuid.UUID,
    body: VersionUpdate,
    request: Request,
    tenant: TenantSession,
    principal: Annotated[
        Principal, Depends(require_permission(Permission.BILLING_MANAGE_TEMPLATE))
    ],
) -> dict[str, Any]:
    return ok(
        await TemplateVersionService(tenant).update_draft(
            version_id,
            formula=body.formula,
            parameters=body.parameters,
            notes=body.notes,
            principal=principal,
            request_id=_rid(request),
        ),
        message="Version updated.",
    )


@router.post(
    "/bill-template-versions/{version_id}/activate",
    response_model=Envelope[VersionRead],
    summary="Make this the version future runs use",
)
async def activate_version(
    version_id: uuid.UUID,
    request: Request,
    tenant: TenantSession,
    principal: Annotated[
        Principal, Depends(require_permission(Permission.BILLING_MANAGE_TEMPLATE))
    ],
) -> dict[str, Any]:
    return ok(
        await TemplateVersionService(tenant).activate(
            version_id, principal, request_id=_rid(request)
        ),
        message="Version activated.",
    )


# --------------------------------------------------------------------------- #
# Assignments
# --------------------------------------------------------------------------- #


@router.get(
    "/bill-assignments", response_model=Envelope[list[AssignmentRead]], summary="List assignments"
)
async def list_assignments(
    tenant: TenantSession,
    principal: Annotated[
        Principal, Depends(require_permission(Permission.BILLING_MANAGE_TEMPLATE))
    ],
    template_id: Annotated[uuid.UUID | None, Query()] = None,
) -> dict[str, Any]:
    return ok(await AssignmentService(tenant).list(template_id=template_id))


@router.post(
    "/bill-assignments",
    response_model=Envelope[AssignmentRead],
    status_code=201,
    summary="Assign a template to flats",
)
async def create_assignment(
    body: AssignmentCreate,
    request: Request,
    tenant: TenantSession,
    principal: Annotated[
        Principal, Depends(require_permission(Permission.BILLING_MANAGE_TEMPLATE))
    ],
) -> dict[str, Any]:
    values = {
        "template_id": body.template_id,
        "scope": body.scope,
        "priority": body.priority,
        **body.targets(),
    }
    return ok(
        await AssignmentService(tenant).create(values, principal, request_id=_rid(request)),
        message="Assignment created.",
    )


@router.delete(
    "/bill-assignments/{assignment_id}",
    response_model=Envelope[dict],
    summary="Remove an assignment",
)
async def delete_assignment(
    assignment_id: uuid.UUID,
    request: Request,
    tenant: TenantSession,
    principal: Annotated[
        Principal, Depends(require_permission(Permission.BILLING_MANAGE_TEMPLATE))
    ],
) -> dict[str, Any]:
    await AssignmentService(tenant).delete(assignment_id, principal, request_id=_rid(request))
    return ok({"deleted": True}, message="Assignment removed.")


@router.get(
    "/bill-assignments/explain/{flat_id}",
    response_model=Envelope[dict],
    summary="Why this flat bills under this template",
)
async def explain_assignment(
    flat_id: uuid.UUID,
    tenant: TenantSession,
    principal: Annotated[
        Principal, Depends(require_permission(Permission.BILLING_MANAGE_TEMPLATE))
    ],
) -> dict[str, Any]:
    return ok(await AssignmentService(tenant).explain_for_flat(flat_id))


# --------------------------------------------------------------------------- #
# Runs
# --------------------------------------------------------------------------- #


@router.get("/billing/runs", response_model=Envelope[Page[RunRead]], summary="List billing runs")
async def list_runs(
    tenant: TenantSession,
    params: PageDep,
    principal: Annotated[Principal, Depends(require_permission(Permission.BILLING_READ_ALL))],
    template_id: Annotated[uuid.UUID | None, Query()] = None,
) -> dict[str, Any]:
    rows, total = await BillingRunService(tenant).list(
        page=params.page, limit=params.limit, template_id=template_id
    )
    return ok(Page.build(rows, page=params.page, limit=params.limit, total=total))


@router.get(
    "/billing/periods/{template_id}",
    response_model=Envelope[list[PeriodOption]],
    summary="Recent periods, and whether each is already billed",
)
async def list_periods(
    template_id: uuid.UUID,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.BILLING_CREATE))],
) -> dict[str, Any]:
    return ok(await BillingRunService(tenant).periods_for(template_id))


@router.post(
    "/billing/runs",
    response_model=Envelope[RunRead],
    status_code=201,
    summary="Generate draft bills",
    description=(
        "Generates DRAFT bills for every applicable flat. **Nothing is "
        "published** — a human reviews and publishes. A flat whose calculation "
        "fails is recorded as FAILED and the rest of the run continues."
    ),
)
async def create_run(
    body: RunCreate,
    request: Request,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.BILLING_CREATE))],
) -> dict[str, Any]:
    run = await BillingRunService(tenant).create(
        template_id=body.template_id,
        period_key=body.period_key,
        principal=principal,
        request_id=_rid(request),
    )
    return ok(
        run,
        message=f"{run['bills_generated']} draft bill(s) generated for {run['period_label']}.",
    )


@router.get("/billing/runs/{run_id}", response_model=Envelope[RunRead], summary="Run detail")
async def get_run(
    run_id: uuid.UUID,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.BILLING_READ_ALL))],
) -> dict[str, Any]:
    return ok(await BillingRunService(tenant).get(run_id))


@router.post(
    "/billing/runs/{run_id}/publish",
    response_model=Envelope[RunRead],
    summary="Publish a run",
    description="Irreversible. Published bills become immutable — a wrong bill "
    "is corrected with a credit note, never an edit.",
)
async def publish_run(
    run_id: uuid.UUID,
    request: Request,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.BILLING_PUBLISH))],
) -> dict[str, Any]:
    run = await BillingRunService(tenant).publish(run_id, principal, request_id=_rid(request))
    return ok(run, message=f"{run['bills_generated']} bill(s) published.")


@router.delete(
    "/billing/runs/{run_id}", response_model=Envelope[dict], summary="Discard a draft run"
)
async def delete_run(
    run_id: uuid.UUID,
    request: Request,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.BILLING_CREATE))],
) -> dict[str, Any]:
    await BillingRunService(tenant).delete_draft(run_id, principal, request_id=_rid(request))
    return ok({"deleted": True}, message="Draft run discarded.")


# --------------------------------------------------------------------------- #
# Bills
# --------------------------------------------------------------------------- #


@router.get(
    "/billing/summary", response_model=Envelope[BillingSummary], summary="Collection summary"
)
async def billing_summary(
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.BILLING_READ_ALL))],
) -> dict[str, Any]:
    return ok(await BillService(tenant).summary())


@router.get(
    "/billing/bills",
    response_model=Envelope[Page[BillRead]],
    summary="List bills",
    description="A resident sees only their own flats' bills.",
)
async def list_bills(
    tenant: TenantSession,
    params: PageDep,
    principal: Annotated[Principal, Depends(require_permission(Permission.BILLING_READ))],
    flat_id: Annotated[uuid.UUID | None, Query()] = None,
    run_id: Annotated[uuid.UUID | None, Query()] = None,
    period_key: Annotated[str | None, Query(max_length=20)] = None,
    status: Annotated[BillStatus | None, Query()] = None,
    payment_status: Annotated[PaymentStatus | None, Query()] = None,
) -> dict[str, Any]:
    rows, total = await BillService(tenant).list(
        principal,
        page=params.page,
        limit=params.limit,
        q=params.q,
        flat_id=flat_id,
        run_id=run_id,
        period_key=period_key,
        status=status,
        payment_status=payment_status,
    )
    return ok(Page.build(rows, page=params.page, limit=params.limit, total=total))


@router.get(
    "/billing/bills/{bill_id}", response_model=Envelope[BillDetail], summary="Bill with line items"
)
async def get_bill(
    bill_id: uuid.UUID,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.BILLING_READ))],
) -> dict[str, Any]:
    return ok(await BillService(tenant).get(bill_id, principal))


@router.get(
    "/billing/bills/{bill_id}/calculation",
    response_model=Envelope[BillCalculation],
    summary="How was this calculated?",
    description=(
        "Served entirely from the stored snapshot — the formula, the inputs and "
        "the step-by-step trace as they were at generation time. Nothing is "
        "re-evaluated, so a bill from years ago explains itself unchanged."
    ),
)
async def bill_calculation(
    bill_id: uuid.UUID,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.BILLING_READ))],
) -> dict[str, Any]:
    return ok(await BillService(tenant).calculation(bill_id, principal))


@router.post(
    "/billing/bills/{bill_id}/void", response_model=Envelope[BillRead], summary="Void a bill"
)
async def void_bill(
    bill_id: uuid.UUID,
    body: BillVoidRequest,
    request: Request,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.BILLING_UPDATE))],
) -> dict[str, Any]:
    return ok(
        await BillService(tenant).void(bill_id, body.reason, principal, request_id=_rid(request)),
        message="Bill voided.",
    )


# --------------------------------------------------------------------------- #
# Payments
# --------------------------------------------------------------------------- #


@router.get("/payments", response_model=Envelope[Page[PaymentRead]], summary="List payments")
async def list_payments(
    tenant: TenantSession,
    params: PageDep,
    principal: Annotated[Principal, Depends(require_permission(Permission.PAYMENT_READ))],
    flat_id: Annotated[uuid.UUID | None, Query()] = None,
    bill_id: Annotated[uuid.UUID | None, Query()] = None,
) -> dict[str, Any]:
    rows, total = await PaymentService(tenant).list(
        principal, page=params.page, limit=params.limit, flat_id=flat_id, bill_id=bill_id
    )
    return ok(Page.build(rows, page=params.page, limit=params.limit, total=total))


@router.post(
    "/payments",
    response_model=Envelope[PaymentRead],
    status_code=201,
    summary="Record a payment",
)
async def record_payment(
    body: PaymentCreate,
    request: Request,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.PAYMENT_RECORD))],
) -> dict[str, Any]:
    payment = await PaymentService(tenant).record(
        bill_id=body.bill_id,
        flat_id=body.flat_id,
        amount=body.amount,
        method=body.method,
        reference_number=body.reference_number,
        paid_at=body.paid_at,
        notes=body.notes,
        principal=principal,
        request_id=_rid(request),
    )
    return ok(payment, message="Payment recorded.")
