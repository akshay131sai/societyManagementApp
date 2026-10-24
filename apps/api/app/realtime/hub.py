"""The WebSocket connection registry.

Design constraints that shaped this:

* **Publishing must never block a request.** A resident's browser on a bad
  connection must not slow down the admin who resolved their complaint, so each
  connection has a bounded queue and ``publish`` is ``put_nowait``. A queue that
  fills is a client that cannot keep up; it is dropped, and the durable
  notification row is still in PostgreSQL for the next page load.

* **Publishing must be callable from a synchronous callback.** Events are
  released by SQLAlchemy's ``after_commit`` hook, which is not a coroutine, so
  nothing here may be ``async``.

* **Delivery is keyed by (society, user).** The society is part of the key so
  that a bug in an event's user id cannot deliver another tenant's payload —
  the same defence in depth the tenant session gives the database.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

import structlog

log = structlog.get_logger(__name__)

QUEUE_SIZE = 100
"""Per-connection backlog. A client this far behind on a notification stream is
not going to catch up, and buffering more only delays admitting it."""


@dataclass(eq=False)
class Connection:
    """One WebSocket's inbox.

    ``eq=False`` so identity is the key: two connections from the same user in
    two browser tabs are two entries in the set, and closing one must not
    remove the other.
    """

    society_id: uuid.UUID
    user_id: uuid.UUID
    queue: asyncio.Queue[dict[str, Any]] = field(
        default_factory=lambda: asyncio.Queue(maxsize=QUEUE_SIZE)
    )
    dropped: int = 0

    async def receive(self) -> dict[str, Any]:
        return await self.queue.get()

    def offer(self, event: dict[str, Any]) -> bool:
        try:
            self.queue.put_nowait(event)
            return True
        except asyncio.QueueFull:
            self.dropped += 1
            return False


class RealtimeHub:
    """Connections held by this worker, grouped by society and user."""

    def __init__(self) -> None:
        self._by_user: dict[tuple[uuid.UUID, uuid.UUID], set[Connection]] = {}

    # -- lifecycle ---------------------------------------------------------- #

    def subscribe(self, society_id: uuid.UUID, user_id: uuid.UUID) -> Connection:
        connection = Connection(society_id=society_id, user_id=user_id)
        self._by_user.setdefault((society_id, user_id), set()).add(connection)
        return connection

    def unsubscribe(self, connection: Connection) -> None:
        key = (connection.society_id, connection.user_id)
        peers = self._by_user.get(key)
        if peers is None:
            return
        peers.discard(connection)
        if not peers:
            # Left in place, an empty set per user who ever connected is a slow
            # memory leak in a long-running process.
            del self._by_user[key]

    # -- delivery ----------------------------------------------------------- #

    def publish(
        self,
        society_id: uuid.UUID,
        user_ids: Iterable[uuid.UUID],
        event: dict[str, Any],
    ) -> int:
        """Offer ``event`` to every live connection of every listed user.

        Returns how many connections accepted it. Synchronous and total: an
        unreachable user is not an error, because the notification they missed
        is already a row in their society's database.
        """
        delivered = 0
        for user_id in user_ids:
            for connection in tuple(self._by_user.get((society_id, user_id), ())):
                if connection.offer(event):
                    delivered += 1
        return delivered

    def broadcast(self, society_id: uuid.UUID, event: dict[str, Any]) -> int:
        """Every connection in one society. Used for society-wide announcements."""
        delivered = 0
        for (sid, _uid), peers in self._by_user.items():
            if sid != society_id:
                continue
            for connection in tuple(peers):
                if connection.offer(event):
                    delivered += 1
        return delivered

    # -- introspection ------------------------------------------------------ #

    def connection_count(self, society_id: uuid.UUID | None = None) -> int:
        return sum(
            len(peers)
            for (sid, _uid), peers in self._by_user.items()
            if society_id is None or sid == society_id
        )

    def user_count(self, society_id: uuid.UUID | None = None) -> int:
        return sum(
            1
            for (sid, _uid), peers in self._by_user.items()
            if peers and (society_id is None or sid == society_id)
        )

    def clear(self) -> None:
        """Drop every connection. Shutdown and tests only."""
        self._by_user.clear()


_hub = RealtimeHub()


def get_hub() -> RealtimeHub:
    return _hub
