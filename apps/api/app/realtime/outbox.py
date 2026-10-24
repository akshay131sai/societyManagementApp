"""Events wait for the transaction that produced them.

A complaint assignment writes a row, a timeline entry and a notification, then
tells the assignee. If the request fails after that, the row is rolled back —
and a "you have been assigned NF/2026/00042" toast for a ticket that does not
exist is worse than no toast at all.

So nothing publishes directly. Services append to a per-session outbox, and the
outbox is released by SQLAlchemy's ``after_commit`` hook: the events reach the
hub exactly when the rows they describe become real, and a rollback discards
them with the rest of the work.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

import structlog
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.realtime.hub import get_hub

log = structlog.get_logger(__name__)

_OUTBOX_KEY = "realtime_outbox"
_HOOKED_KEY = "realtime_outbox_hooked"
_SOCIETY_KEY = "society_id"


@dataclass(frozen=True, slots=True)
class RealtimeEvent:
    """One message, and who it is for.

    An empty ``user_ids`` with ``broadcast=True`` means the whole society —
    a published notice, where enumerating every resident to reach the same
    outcome would be wasteful.
    """

    type: str
    payload: dict[str, Any]
    user_ids: tuple[uuid.UUID, ...] = field(default=())
    broadcast: bool = False

    def as_message(self) -> dict[str, Any]:
        return {"type": self.type, "data": self.payload}


def bind_society(session: AsyncSession, society_id: uuid.UUID) -> None:
    """Record which tenant a session belongs to.

    Set once by the tenant-session dependency. Without it the outbox has no
    society to publish into and refuses to guess.
    """
    session.info[_SOCIETY_KEY] = society_id


def enqueue_events(session: AsyncSession, events: Iterable[RealtimeEvent]) -> None:
    """Queue events for release after this session commits."""
    pending: list[RealtimeEvent] = list(events)
    if not pending:
        return

    box: list[RealtimeEvent] = session.info.setdefault(_OUTBOX_KEY, [])
    box.extend(pending)
    _ensure_hook(session)


def enqueue(
    session: AsyncSession,
    *,
    type: str,
    payload: dict[str, Any],
    user_ids: Sequence[uuid.UUID] = (),
    broadcast: bool = False,
) -> None:
    """Convenience wrapper for the single-event case."""
    enqueue_events(
        session,
        [
            RealtimeEvent(
                type=type,
                payload=payload,
                user_ids=tuple(user_ids),
                broadcast=broadcast,
            )
        ],
    )


def pending_events(session: AsyncSession) -> list[RealtimeEvent]:
    """What is waiting on this session. Tests read this; nothing else should."""
    return list(session.info.get(_OUTBOX_KEY, []))


def _ensure_hook(session: AsyncSession) -> None:
    if session.info.get(_HOOKED_KEY):
        return
    session.info[_HOOKED_KEY] = True

    sync_session = session.sync_session

    @event.listens_for(sync_session, "after_commit")
    def _release(committed: Session) -> None:  # pragma: no cover - trivial glue
        _flush(committed)

    # Both hooks, deliberately. ``after_rollback`` fires only when a DBAPI
    # transaction actually existed; a service that enqueues an event and then
    # fails before touching the database gets a *soft* rollback, and without
    # this second listener its event would survive to be published by whatever
    # commit came next.
    @event.listens_for(sync_session, "after_rollback")
    def _discard(rolled_back: Session) -> None:  # pragma: no cover - trivial glue
        rolled_back.info.pop(_OUTBOX_KEY, None)

    @event.listens_for(sync_session, "after_soft_rollback")
    def _discard_soft(
        rolled_back: Session, previous_transaction: object
    ) -> None:  # pragma: no cover - trivial glue
        rolled_back.info.pop(_OUTBOX_KEY, None)


def _flush(sync_session: Session) -> None:
    """Release the outbox into the hub.

    Runs inside SQLAlchemy's synchronous commit callback, which is why nothing
    awaited happens here — the hub's ``publish`` is deliberately non-blocking.
    """
    events: list[RealtimeEvent] = sync_session.info.pop(_OUTBOX_KEY, [])
    society_id = sync_session.info.get(_SOCIETY_KEY)
    if not events or society_id is None:
        return

    hub = get_hub()
    for realtime_event in events:
        message = realtime_event.as_message()
        if realtime_event.broadcast:
            hub.broadcast(society_id, message)
        else:
            hub.publish(society_id, realtime_event.user_ids, message)
