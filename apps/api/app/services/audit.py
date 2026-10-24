"""Audit logging service.

Writes to the central or tenant log as appropriate. Payloads pass through a
redaction step before storage — an audit trail that records a bearer token is
worse than no audit trail.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import Principal
from app.core.logging import SENSITIVE_KEYS
from app.models.central import PlatformAuditLog
from app.models.tenant import TenantAuditLog

log = structlog.get_logger(__name__)

REDACTED = "[REDACTED]"


def _scrub(value: Any, depth: int = 0) -> Any:
    if depth > 6:
        return value
    if isinstance(value, dict):
        return {
            k: (REDACTED if str(k).lower() in SENSITIVE_KEYS else _scrub(v, depth + 1))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_scrub(v, depth + 1) for v in value]
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


class AuditService:
    """Records what happened, who did it and what changed."""

    @staticmethod
    async def platform(
        session: AsyncSession,
        *,
        action: str,
        principal: Principal | None = None,
        society_id: uuid.UUID | None = None,
        target_type: str | None = None,
        target_id: str | uuid.UUID | None = None,
        changes: dict[str, Any] | None = None,
        request_id: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        status: str = "SUCCESS",
    ) -> None:
        session.add(
            PlatformAuditLog(
                request_id=request_id,
                action=action,
                actor_id=principal.platform_user_id if principal else None,
                actor_email=principal.email if principal else None,
                society_id=society_id,
                target_type=target_type,
                target_id=str(target_id) if target_id is not None else None,
                changes=_scrub(changes) if changes else None,
                ip_address=ip_address,
                user_agent=(user_agent or None) and user_agent[:500],
                status=status,
            )
        )
        log.info(
            "audit.platform",
            action=action,
            actor=principal.email if principal else "system",
            society_id=str(society_id) if society_id else None,
            status=status,
        )

    @staticmethod
    async def tenant(
        session: AsyncSession,
        *,
        action: str,
        principal: Principal | None = None,
        target_type: str | None = None,
        target_id: str | uuid.UUID | None = None,
        changes: dict[str, Any] | None = None,
        request_id: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        status: str = "SUCCESS",
    ) -> None:
        session.add(
            TenantAuditLog(
                request_id=request_id,
                action=action,
                actor_id=principal.tenant_user_id if principal else None,
                actor_email=principal.email if principal else None,
                target_type=target_type,
                target_id=str(target_id) if target_id is not None else None,
                changes=_scrub(changes) if changes else None,
                ip_address=ip_address,
                user_agent=(user_agent or None) and user_agent[:500],
                status=status,
            )
        )
        log.info(
            "audit.tenant",
            action=action,
            actor=principal.email if principal else "system",
            status=status,
        )


def diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Changed keys only, as ``{"before": ..., "after": ...}``.

    Storing only what changed keeps the log readable and small; a full snapshot
    of both sides makes real changes hard to spot.
    """
    changed = {
        k for k in set(before) | set(after) if before.get(k) != after.get(k)
    }
    return {
        "before": {k: before.get(k) for k in changed},
        "after": {k: after.get(k) for k in changed},
    }
