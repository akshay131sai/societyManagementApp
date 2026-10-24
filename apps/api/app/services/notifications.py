"""Notification fan-out.

This is the module every other module talks to when something happened that a
person should know about. Three rules keep it from becoming noise:

* **A notification names a link, not a screen.** ``link`` is a route the client
  already has (``/app/complaints/<id>``), so adding a notification category
  never requires a client release.

* **Nobody is notified of their own action.** The admin who resolves a ticket
  does not get "your ticket was resolved". ``exclude`` is applied centrally
  rather than remembered at eleven call sites.

* **The row is the record; the socket is a convenience.** Rows are written in
  the caller's transaction and the realtime event is released only when that
  transaction commits, so a rolled-back action never produces a toast for
  something that did not happen.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from typing import Any

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import Principal
from app.core.errors import NotFoundError
from app.models.tenant import Notification, NotificationChannel
from app.realtime.outbox import RealtimeEvent, enqueue_events

log = structlog.get_logger(__name__)

FEED_LIMIT = 20


class Category:
    """Notification categories.

    Strings rather than an enum: the set grows with every feature, and a
    tenant database column that has to be migrated to add "amenity booked" is a
    column that discourages adding it.
    """

    COMPLAINT_RAISED = "complaint.raised"
    COMPLAINT_ASSIGNED = "complaint.assigned"
    COMPLAINT_UPDATED = "complaint.updated"
    COMPLAINT_RESOLVED = "complaint.resolved"
    COMPLAINT_COMMENT = "complaint.comment"
    TASK_ASSIGNED = "task.assigned"
    TASK_COMPLETED = "task.completed"
    TASK_OVERDUE = "task.overdue"
    VISITOR_AWAITING = "visitor.awaiting_approval"
    VISITOR_ARRIVED = "visitor.arrived"
    VISITOR_DENIED = "visitor.denied"
    INCIDENT_REPORTED = "incident.reported"
    NOTICE_PUBLISHED = "notice.published"
    BOOKING_CONFIRMED = "booking.confirmed"
    BOOKING_PENDING = "booking.pending"
    BOOKING_DECIDED = "booking.decided"
    BOOKING_REMINDER = "booking.reminder"
    BILL_PUBLISHED = "bill.published"
    PAYMENT_RECEIVED = "payment.received"


def _notification_dict(n: Notification) -> dict[str, Any]:
    return {
        "id": n.id,
        "channel": n.channel,
        "category": n.category,
        "title": n.title,
        "body": n.body,
        "link": n.link,
        "payload": n.payload,
        "is_read": n.is_read,
        "read_at": n.read_at,
        "created_at": n.created_at,
    }


class NotificationService:
    def __init__(self, tenant: AsyncSession) -> None:
        self.tenant = tenant

    # -- fan-out ------------------------------------------------------------ #

    async def notify(
        self,
        user_ids: Iterable[uuid.UUID | None],
        *,
        category: str,
        title: str,
        body: str | None = None,
        link: str | None = None,
        payload: dict[str, Any] | None = None,
        exclude: uuid.UUID | None = None,
        event_type: str = "notification",
    ) -> int:
        """Write one notification per recipient and queue the realtime nudge.

        Returns the number of people notified. Duplicate ids collapse, ``None``
        ids (an unlinked resident) are skipped, and ``exclude`` drops the actor
        — all three happen here so no caller has to remember them.
        """
        recipients = [
            uid
            for uid in dict.fromkeys(u for u in user_ids if u is not None)
            if uid != exclude
        ]
        if not recipients:
            return 0

        rows = [
            Notification(
                user_id=user_id,
                channel=NotificationChannel.IN_APP,
                category=category,
                title=title,
                body=body,
                link=link,
                payload=payload,
                sent_at=func.now(),
            )
            for user_id in recipients
        ]
        self.tenant.add_all(rows)
        await self.tenant.flush()

        enqueue_events(
            self.tenant,
            [
                RealtimeEvent(
                    type=event_type,
                    payload={
                        "category": category,
                        "title": title,
                        "body": body,
                        "link": link,
                        **(payload or {}),
                    },
                    user_ids=tuple(recipients),
                )
            ],
        )
        log.info("notification.sent", category=category, recipients=len(recipients))
        return len(recipients)

    async def broadcast(
        self,
        *,
        category: str,
        title: str,
        body: str | None = None,
        link: str | None = None,
        payload: dict[str, Any] | None = None,
        event_type: str = "notification",
    ) -> None:
        """A society-wide nudge with no per-user rows.

        Used where the durable record already exists somewhere else — a
        published notice is its own record, and writing 300 notification rows
        to say "there is a notice" duplicates it.
        """
        enqueue_events(
            self.tenant,
            [
                RealtimeEvent(
                    type=event_type,
                    payload={
                        "category": category,
                        "title": title,
                        "body": body,
                        "link": link,
                        **(payload or {}),
                    },
                    broadcast=True,
                )
            ],
        )

    # -- reads -------------------------------------------------------------- #

    async def feed(
        self, principal: Principal, *, limit: int = FEED_LIMIT, unread_only: bool = False
    ) -> dict[str, Any]:
        if principal.tenant_user_id is None:
            return {"items": [], "unread": 0, "total": 0}

        stmt = select(Notification).where(Notification.user_id == principal.tenant_user_id)
        if unread_only:
            stmt = stmt.where(Notification.is_read.is_(False))

        rows = await self.tenant.scalars(
            stmt.order_by(Notification.created_at.desc()).limit(limit)
        )
        counts = (
            await self.tenant.execute(
                select(
                    func.count(),
                    func.count().filter(Notification.is_read.is_(False)),
                )
                .select_from(Notification)
                .where(Notification.user_id == principal.tenant_user_id)
            )
        ).first()
        total, unread = counts or (0, 0)
        return {
            "items": [_notification_dict(n) for n in rows],
            "unread": int(unread or 0),
            "total": int(total or 0),
        }

    async def list(
        self, principal: Principal, *, page: int, limit: int, unread_only: bool = False
    ) -> tuple[list[dict[str, Any]], int]:
        if principal.tenant_user_id is None:
            return [], 0

        stmt = select(Notification).where(Notification.user_id == principal.tenant_user_id)
        if unread_only:
            stmt = stmt.where(Notification.is_read.is_(False))

        total = int(
            await self.tenant.scalar(
                select(func.count()).select_from(stmt.order_by(None).subquery())
            )
            or 0
        )
        rows = await self.tenant.scalars(
            stmt.order_by(Notification.created_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
        )
        return [_notification_dict(n) for n in rows], total

    async def unread_count(self, principal: Principal) -> int:
        if principal.tenant_user_id is None:
            return 0
        return int(
            await self.tenant.scalar(
                select(func.count())
                .select_from(Notification)
                .where(
                    Notification.user_id == principal.tenant_user_id,
                    Notification.is_read.is_(False),
                )
            )
            or 0
        )

    # -- writes ------------------------------------------------------------- #

    async def mark_read(
        self, notification_ids: Sequence[uuid.UUID], principal: Principal
    ) -> dict[str, int]:
        """Mark specific notifications read.

        The ``user_id`` predicate is what makes another user's id in the body
        harmless: it matches nothing, and the caller is told zero were marked
        rather than being handed a 403 that confirms the row exists.
        """
        if principal.tenant_user_id is None:
            raise NotFoundError("Notification")

        result = await self.tenant.execute(
            update(Notification)
            .where(
                Notification.id.in_(list(notification_ids)),
                Notification.user_id == principal.tenant_user_id,
                Notification.is_read.is_(False),
            )
            .values(is_read=True, read_at=func.now())
        )
        return {
            "marked": int(result.rowcount or 0),
            "unread": await self.unread_count(principal),
        }

    async def mark_all_read(self, principal: Principal) -> dict[str, int]:
        if principal.tenant_user_id is None:
            raise NotFoundError("Notification")

        result = await self.tenant.execute(
            update(Notification)
            .where(
                Notification.user_id == principal.tenant_user_id,
                Notification.is_read.is_(False),
            )
            .values(is_read=True, read_at=func.now())
        )
        return {"marked": int(result.rowcount or 0), "unread": 0}
