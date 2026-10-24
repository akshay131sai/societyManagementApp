"""In-process realtime delivery.

One hub per worker process, holding the WebSocket connections that worker is
serving. There is no broker: with a single deployable, a fan-out that has to
reach a user reaches them through the worker they are connected to, and the
notification row in PostgreSQL is the durable record either way.

The scaling seam is deliberate and documented in
docs/architecture/overview.md section 6 — when a second worker appears, the hub
grows a Postgres ``LISTEN``/``NOTIFY`` bridge and nothing above it changes.
"""

from app.realtime.hub import Connection, RealtimeHub, get_hub
from app.realtime.outbox import RealtimeEvent, enqueue_events

__all__ = [
    "Connection",
    "RealtimeEvent",
    "RealtimeHub",
    "enqueue_events",
    "get_hub",
]
