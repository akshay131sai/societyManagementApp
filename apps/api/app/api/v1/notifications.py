"""Notifications and the realtime socket.

The WebSocket carries no data the REST API does not. It exists so a screen that
is already open updates without polling — a guard's board, a resident waiting
on a visitor approval, an admin watching a billing run. Every event it delivers
has a durable counterpart in PostgreSQL, so a client that missed one while its
laptop was asleep loses nothing by reloading.

**Why the token is a query parameter here.** The browser WebSocket API cannot
set an ``Authorization`` header. The token is short-lived, the connection is
TLS, and the handshake URL is not logged with query strings in this deployment
(see docs/deployment/deployment.md). The same verifier and the same
``PrincipalResolver`` run as on every REST request — the socket is not a way
around a guard, and a locked society or an expired subscription is refused at
the handshake.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect

from app.api.deps import TenantSession, require_permission
from app.auth.principal import Principal
from app.core.errors import NestFlowError
from app.core.firebase import get_token_verifier
from app.core.permissions import Permission
from app.database.central import get_central_sessionmaker
from app.database.manager import get_tenant_manager
from app.realtime.hub import Connection, get_hub
from app.schemas.common import Envelope, Page, PageParams, ok
from app.schemas.notifications import (
    MarkReadRequest,
    MarkReadResult,
    NotificationFeed,
    NotificationRead,
    RealtimeStatus,
)
from app.services.notifications import NotificationService

log = structlog.get_logger(__name__)

router = APIRouter(tags=["notifications"])

PageDep = Annotated[PageParams, Depends()]

HEARTBEAT_SECONDS = 25
"""Below the 30-second idle timeout of every proxy worth deploying behind."""

WS_POLICY_VIOLATION = 1008
WS_INTERNAL_ERROR = 1011


# --------------------------------------------------------------------------- #
# REST
# --------------------------------------------------------------------------- #


@router.get(
    "/notifications",
    response_model=Envelope[Page[NotificationRead]],
    summary="List notifications",
)
async def list_notifications(
    tenant: TenantSession,
    principal: Annotated[
        Principal, Depends(require_permission(Permission.NOTIFICATION_READ))
    ],
    params: PageDep,
    unread_only: bool = False,
) -> dict[str, Any]:
    items, total = await NotificationService(tenant).list(
        principal, page=params.page, limit=params.limit, unread_only=unread_only
    )
    return ok(Page.build(items, page=params.page, limit=params.limit, total=total))


@router.get(
    "/notifications/feed",
    response_model=Envelope[NotificationFeed],
    summary="The bell menu: recent items and the unread count",
    description=(
        "One call rather than two, so the list and the badge cannot disagree "
        "while somebody else is working through the same queue."
    ),
)
async def notification_feed(
    tenant: TenantSession,
    principal: Annotated[
        Principal, Depends(require_permission(Permission.NOTIFICATION_READ))
    ],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> dict[str, Any]:
    return ok(await NotificationService(tenant).feed(principal, limit=limit))


@router.post(
    "/notifications/read",
    response_model=Envelope[MarkReadResult],
    summary="Mark specific notifications read",
)
async def mark_read(
    payload: MarkReadRequest,
    tenant: TenantSession,
    principal: Annotated[
        Principal, Depends(require_permission(Permission.NOTIFICATION_READ))
    ],
) -> dict[str, Any]:
    return ok(await NotificationService(tenant).mark_read(payload.ids, principal))


@router.post(
    "/notifications/read-all",
    response_model=Envelope[MarkReadResult],
    summary="Mark everything read",
)
async def mark_all_read(
    tenant: TenantSession,
    principal: Annotated[
        Principal, Depends(require_permission(Permission.NOTIFICATION_READ))
    ],
) -> dict[str, Any]:
    result = await NotificationService(tenant).mark_all_read(principal)
    return ok(result, f"{result['marked']} notification(s) marked read.")


@router.get(
    "/realtime/status",
    response_model=Envelope[RealtimeStatus],
    summary="Live socket counts for this worker",
)
async def realtime_status(
    principal: Annotated[Principal, Depends(require_permission(Permission.AUDIT_READ))],
) -> dict[str, Any]:
    hub = get_hub()
    return ok(
        {
            "connections": hub.connection_count(),
            "users": hub.user_count(),
            "society_connections": hub.connection_count(principal.society_id),
        }
    )


# --------------------------------------------------------------------------- #
# WebSocket
# --------------------------------------------------------------------------- #


async def _authenticate(token: str) -> Principal:
    """Run the ordinary guard chain against a handshake token.

    Deliberately the same code path as a REST request: identity, account,
    society status, subscription, tenant roles. A society locked while a
    resident had a tab open cannot keep receiving events by never reconnecting,
    because the token expires and the next handshake is refused.
    """
    from app.auth.resolver import PrincipalResolver

    verifier = get_token_verifier()
    identity = verifier.verify(token)

    factory = get_central_sessionmaker()
    async with factory() as central:
        resolver = PrincipalResolver(central, get_tenant_manager())
        context = await resolver.resolve(identity, auth_provider=verifier.name)
    return context.principal


@router.websocket("/ws")
async def realtime(websocket: WebSocket, token: Annotated[str | None, Query()] = None) -> None:
    if not token:
        await websocket.close(code=WS_POLICY_VIOLATION, reason="A token is required.")
        return

    try:
        principal = await _authenticate(token)
    except NestFlowError as exc:
        await websocket.close(code=WS_POLICY_VIOLATION, reason=exc.code.value)
        return
    except Exception:  # pragma: no cover - defensive
        log.exception("realtime.handshake.failed")
        await websocket.close(code=WS_INTERNAL_ERROR)
        return

    if principal.society_id is None or principal.tenant_user_id is None:
        # A platform super admin has no society to subscribe to. Refusing is
        # clearer than a socket that will never emit anything.
        await websocket.close(
            code=WS_POLICY_VIOLATION, reason="This connection needs a society account."
        )
        return

    hub = get_hub()
    connection = hub.subscribe(principal.society_id, principal.tenant_user_id)
    await websocket.accept()
    await websocket.send_json(
        {"type": "connected", "data": {"user_id": str(principal.tenant_user_id)}}
    )
    log.info("realtime.connected", email=principal.email)

    reader = asyncio.create_task(_drain(websocket))
    try:
        await _pump(websocket, connection)
    except WebSocketDisconnect:
        pass
    except Exception:  # pragma: no cover - transport failure
        log.info("realtime.dropped", email=principal.email)
    finally:
        reader.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await reader
        hub.unsubscribe(connection)
        log.info("realtime.disconnected", email=principal.email, dropped=connection.dropped)


async def _pump(websocket: WebSocket, connection: Connection) -> None:
    """Forward queued events, with a heartbeat so idle proxies do not hang up."""
    while True:
        try:
            event = await asyncio.wait_for(connection.receive(), timeout=HEARTBEAT_SECONDS)
        except TimeoutError:
            await websocket.send_json({"type": "ping", "data": {}})
            continue
        await websocket.send_json(event)


async def _drain(websocket: WebSocket) -> None:
    """Read and discard whatever the client sends.

    The socket is one-directional by design — a client that wants to change
    something calls the API, where the guards are. Reading anyway is what makes
    a browser-side close arrive promptly rather than at the next heartbeat.
    """
    with contextlib.suppress(WebSocketDisconnect, RuntimeError):
        while True:
            await websocket.receive_text()
