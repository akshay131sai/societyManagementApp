"""The scheduled work.

Every job here is the same shape: a coroutine that takes a tenant session and
returns a count. That makes each one directly callable from a test or the CLI
without a scheduler in the way, and it is why the runner below can be a dozen
lines rather than a framework.

Three rules the jobs obey:

* **One society's failure is not another's.** ``run_for_all_societies`` opens a
  session per society and logs a failure rather than aborting the sweep. The
  society whose database is being restored must not stop the other ninety-nine
  from generating this morning's tasks.

* **Every job is idempotent.** Running the whole set twice in one morning
  produces the same state as running it once. That is what makes a restart in
  the middle of the 6 a.m. sweep uneventful.

* **A job is not a place for business rules.** Each one calls the same service
  method the API calls. There is exactly one definition of "auto-close a
  resolved complaint", and it is not in this file.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.central import central_session
from app.database.manager import get_tenant_manager
from app.models.central import Society, SocietyStatus
from app.realtime.outbox import bind_society
from app.services.community import AmenityService, NoticeService
from app.services.operations import ComplaintService, ScheduleGenerator, VisitorService

log = structlog.get_logger(__name__)

TenantJob = Callable[[AsyncSession], Awaitable[int]]


@dataclass(frozen=True, slots=True)
class JobResult:
    name: str
    societies: int
    affected: int
    failures: int


# --------------------------------------------------------------------------- #
# The jobs themselves
# --------------------------------------------------------------------------- #


async def generate_scheduled_work(tenant: AsyncSession) -> int:
    """Raise today's maintenance and housekeeping tasks from their schedules."""
    result = await ScheduleGenerator(tenant).run()
    return int(result["tasks_created"])


async def close_stale_complaints(tenant: AsyncSession) -> int:
    """Close resolved tickets the resident never came back to."""
    return await ComplaintService(tenant).auto_close_resolved()


async def escalate_overdue_complaints(tenant: AsyncSession) -> int:
    """Tell the managers which tickets have passed their promised time."""
    return await ComplaintService(tenant).escalate_overdue()


async def expire_visitor_passes(tenant: AsyncSession) -> int:
    """Clear out pre-approvals whose window closed with nobody arriving."""
    return await VisitorService(tenant).expire_stale()


async def publish_due_notices(tenant: AsyncSession) -> int:
    """Publish notices whose scheduled moment has arrived."""
    return await NoticeService(tenant).publish_scheduled()


async def complete_past_bookings(tenant: AsyncSession) -> int:
    """Retire bookings whose slot has ended so they stop holding it."""
    return await AmenityService(tenant).complete_past()


async def remind_upcoming_bookings(tenant: AsyncSession) -> int:
    """Nudge residents whose booking starts within the day."""
    return await AmenityService(tenant).send_reminders(within_hours=24)


TENANT_JOBS: dict[str, TenantJob] = {
    "generate-scheduled-work": generate_scheduled_work,
    "close-stale-complaints": close_stale_complaints,
    "escalate-overdue-complaints": escalate_overdue_complaints,
    "expire-visitor-passes": expire_visitor_passes,
    "publish-due-notices": publish_due_notices,
    "complete-past-bookings": complete_past_bookings,
    "remind-upcoming-bookings": remind_upcoming_bookings,
}
"""Everything that can be run per society, by name.

The names are the CLI's arguments and the scheduler's job ids, so a job that
misbehaves in production can be run by hand against one society without editing
any code.
"""


# --------------------------------------------------------------------------- #
# Fan-out
# --------------------------------------------------------------------------- #


async def active_society_ids() -> list[uuid.UUID]:
    """Societies worth visiting.

    A locked, archived or still-provisioning society has no tasks to generate
    and possibly no schema to generate them into.
    """
    async with central_session() as session:
        rows = await session.scalars(
            select(Society.id).where(Society.status == SocietyStatus.ACTIVE)
        )
        return list(rows)


async def run_for_society(job: TenantJob, society_id: uuid.UUID) -> int:
    manager = get_tenant_manager()
    async with manager.session(society_id) as tenant:
        # Jobs emit notifications, and those notifications reach open browsers
        # the same way a request's would.
        bind_society(tenant, society_id)
        return await job(tenant)


async def run_for_all_societies(name: str, job: TenantJob | None = None) -> JobResult:
    """Run one job across every active society, isolating failures."""
    runner = job or TENANT_JOBS.get(name)
    if runner is None:
        raise KeyError(f"Unknown job: {name}")

    societies = await active_society_ids()
    affected = 0
    failures = 0

    for society_id in societies:
        try:
            affected += await run_for_society(runner, society_id)
        except Exception:
            failures += 1
            # One tenant's outage is not a reason to skip the rest, and a
            # stack trace in the log is how it gets noticed.
            log.exception("job.failed", job=name, society_id=str(society_id))

    log.info(
        "job.completed",
        job=name,
        societies=len(societies),
        affected=affected,
        failures=failures,
    )
    return JobResult(name=name, societies=len(societies), affected=affected, failures=failures)


async def run_all() -> list[JobResult]:
    """Every tenant job, in order. The nightly sweep."""
    return [await run_for_all_societies(name) for name in TENANT_JOBS]


# --------------------------------------------------------------------------- #
# Central jobs
# --------------------------------------------------------------------------- #


async def expire_subscriptions() -> int:
    """Mark past-due subscriptions EXPIRED in the central database.

    The access guard already refuses a subscription past its end date, so this
    is bookkeeping rather than enforcement — but a platform dashboard that
    still calls an expired subscription ACTIVE is a dashboard nobody trusts.
    """
    from app.services.platform import SubscriptionService

    async with central_session() as session:
        expired = await SubscriptionService(session, get_tenant_manager()).expire_due()
    log.info("job.completed", job="expire-subscriptions", affected=expired)
    return int(expired)


CENTRAL_JOBS: dict[str, Callable[[], Awaitable[Any]]] = {
    "expire-subscriptions": expire_subscriptions,
}
