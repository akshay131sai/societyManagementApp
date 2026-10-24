"""Scheduled work.

``jobs`` holds the coroutines; ``scheduler`` decides when they run. The split
means every job can be run by hand — from a test, or from
``python -m app.cli run-job <name>`` — without a scheduler existing.
"""

from app.workers.jobs import CENTRAL_JOBS, TENANT_JOBS, JobResult, run_all, run_for_all_societies
from app.workers.scheduler import (
    scheduler_status,
    shutdown_scheduler,
    start_scheduler,
)

__all__ = [
    "CENTRAL_JOBS",
    "TENANT_JOBS",
    "JobResult",
    "run_all",
    "run_for_all_societies",
    "scheduler_status",
    "shutdown_scheduler",
    "start_scheduler",
]
