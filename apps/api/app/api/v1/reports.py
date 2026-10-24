"""Reports and exports.

Three endpoints for ten reports, because the report *is* data: the catalogue
says what exists, ``/reports/{key}`` runs one, and ``/reports/{key}.csv``
exports the same rows. Adding a report touches no routing.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Response
from fastapi.responses import PlainTextResponse

from app.api.deps import TenantSession, require_any_permission
from app.auth.principal import Principal
from app.core.permissions import Permission
from app.schemas.common import Envelope, ok
from app.schemas.reports import ReportMeta, ReportRequest, ReportResult
from app.services.reports import ReportService

router = APIRouter(prefix="/reports", tags=["reports"])

# A principal reaches the reports module if they can run *any* report. Which
# ones they may actually run is decided per report, from the same registry the
# catalogue is built from — so the menu and the endpoint cannot disagree.
ReportReader = Annotated[
    Principal,
    Depends(
        # Both are society-wide permissions. An owner-scoped one — a resident's
        # ``payment.read`` — must never open this door: every report here
        # aggregates across the whole society.
        require_any_permission(Permission.REPORT_READ, Permission.BILLING_READ_ALL)
    ),
]

ReportKey = Annotated[str, Path(pattern=r"^[a-z][a-z0-9-]{2,40}$")]


@router.get(
    "",
    response_model=Envelope[list[ReportMeta]],
    summary="Reports this account can run",
)
async def catalogue(tenant: TenantSession, principal: ReportReader) -> dict[str, Any]:
    return ok(ReportService(tenant).catalogue(principal.permissions))


@router.get(
    "/{key}",
    response_model=Envelope[ReportResult],
    summary="Run a report",
    description=(
        "Filters that a report does not use are ignored rather than refused, so "
        "the client can send one filter bar for every report."
    ),
)
async def run_report(
    key: ReportKey,
    tenant: TenantSession,
    principal: ReportReader,
    filters: Annotated[ReportRequest, Depends()],
) -> dict[str, Any]:
    return ok(await ReportService(tenant).run(key, filters, held=principal.permissions))


@router.get(
    "/{key}/export",
    response_class=PlainTextResponse,
    summary="Run a report and download it as CSV",
    responses={200: {"content": {"text/csv": {}}, "description": "CSV export"}},
)
async def export_report(
    key: ReportKey,
    tenant: TenantSession,
    principal: ReportReader,
    filters: Annotated[ReportRequest, Depends()],
) -> Response:
    service = ReportService(tenant)
    report = await service.run(key, filters, held=principal.permissions)
    return Response(
        content=service.to_csv(report),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{key}-{report["generated_at"]}.csv"'
            ),
            # A report is a snapshot of live data; a cached copy is a wrong copy.
            "Cache-Control": "no-store",
        },
    )
