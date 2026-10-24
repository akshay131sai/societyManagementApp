"""In-process cron.

APScheduler inside the API process, not Celery and not a second deployable.
The work is a handful of short sweeps a day over tables that are already warm;
a broker, a result backend and a worker fleet would be three more things to
operate for no gain. The seam is small — every job is an ordinary coroutine in
``app.workers.jobs`` — so moving to a separate process later is a change to
this file alone.

Two properties matter more than the schedule itself:

* **Jobs never overlap.** ``max_instances=1`` plus ``coalesce=True`` means a
  sweep that runs long is not started again alongside itself, and a process
  that was asleep runs each missed job once rather than N times.

* **The clock is IST.** A society's day starts and ends in Asia/Kolkata, so
  "close yesterday's visitor passes at 2 a.m." has to mean 2 a.m. there.
"""

from __future__ import annotations

from typing import Any
from zoneinfo import ZoneInfo

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import get_settings
from app.workers.jobs import expire_subscriptions, run_for_all_societies

log = structlog.get_logger(__name__)

TZ = ZoneInfo("Asia/Kolkata")

MISFIRE_GRACE_SECONDS = 3600
"""How late a missed job may still run. An hour covers a deploy or a restart;
beyond that the next day's run is the right answer anyway."""


# (job id, hour, minute) — IST.
SCHEDULE: tuple[tuple[str, int, int], ...] = (
    # Before the working day: today's tasks exist when the first person opens
    # the app, and yesterday's passes are already cleared.
    ("expire-visitor-passes", 2, 0),
    ("complete-past-bookings", 2, 15),
    ("publish-due-notices", 6, 0),
    ("generate-scheduled-work", 6, 15),
    ("close-stale-complaints", 6, 30),
    # Mid-morning, once people are at their desks and can act on it.
    ("escalate-overdue-complaints", 10, 0),
    # Evening, for tomorrow's bookings.
    ("remind-upcoming-bookings", 18, 0),
)

_scheduler: AsyncIOScheduler | None = None


def _tenant_job(name: str) -> Any:
    async def _run() -> None:
        await run_for_all_societies(name)

    _run.__name__ = f"job_{name.replace('-', '_')}"
    return _run


async def _expire_subscriptions() -> None:
    await expire_subscriptions()


def build_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(
        timezone=TZ,
        job_defaults={
            "coalesce": True,
            "max_instances": 1,
            "misfire_grace_time": MISFIRE_GRACE_SECONDS,
        },
    )

    for name, hour, minute in SCHEDULE:
        scheduler.add_job(
            _tenant_job(name),
            CronTrigger(hour=hour, minute=minute, timezone=TZ),
            id=name,
            name=name,
            replace_existing=True,
        )

    scheduler.add_job(
        _expire_subscriptions,
        CronTrigger(hour=1, minute=0, timezone=TZ),
        id="expire-subscriptions",
        name="expire-subscriptions",
        replace_existing=True,
    )
    return scheduler


def start_scheduler() -> AsyncIOScheduler | None:
    """Start the scheduler unless it is switched off.

    Returns ``None`` when disabled, which is the normal state under pytest and
    the correct state for a second web worker: two processes running the same
    sweep would double every notification the sweeps send.
    """
    global _scheduler

    settings = get_settings()
    if not settings.SCHEDULER_ENABLED:
        log.info("scheduler.disabled")
        return None
    if _scheduler is not None and _scheduler.running:
        return _scheduler

    _scheduler = build_scheduler()
    _scheduler.start()
    log.info(
        "scheduler.started",
        timezone=str(TZ),
        jobs=[job.id for job in _scheduler.get_jobs()],
    )
    return _scheduler


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        # ``wait=False``: shutdown runs during application teardown, and a job
        # mid-sweep will be picked up by the next run anyway.
        _scheduler.shutdown(wait=False)
        log.info("scheduler.stopped")
    _scheduler = None


def scheduler_status() -> dict[str, Any]:
    """What is scheduled and when it next fires. Surfaced by ``/health/info``."""
    if _scheduler is None or not _scheduler.running:
        return {"running": False, "jobs": []}
    return {
        "running": True,
        "timezone": str(TZ),
        "jobs": [
            {
                "id": job.id,
                "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
            }
            for job in _scheduler.get_jobs()
        ],
    }
