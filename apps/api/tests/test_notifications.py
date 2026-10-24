"""Phase 6: notifications, the realtime hub and the scheduled jobs.

The hub and the outbox are tested directly rather than through HTTP. They are
the two pieces where a mistake is silent — a notification that never arrives
looks exactly like a notification nobody sent — so they get unit tests with no
web server in the way.

The one property worth stating plainly: **a rolled-back transaction must not
produce a toast.** ``test_a_rolled_back_transaction_publishes_nothing`` is the
whole reason the outbox exists.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient

from tests.conftest import SocietyFixture, auth

pytestmark = pytest.mark.asyncio


class NotifyFixture:
    def __init__(self) -> None:
        self.flat: dict[str, Any] = {}
        self.resident_token: str = ""
        self.resident_user: dict[str, Any] = {}
        self.other_user: dict[str, Any] = {}
        self.other_token: str = ""


@pytest_asyncio.fixture(scope="module")
async def notify(client: AsyncClient, society_a: SocietyFixture) -> NotifyFixture:
    admin = auth(society_a.admin_token)
    fixture = NotifyFixture()
    tag = uuid.uuid4().hex[:5].upper()

    building = (
        await client.post(
            "/buildings", headers=admin, json={"name": f"Notif {tag}", "code": f"N{tag}"}
        )
    ).json()["data"]
    block = (
        await client.get("/blocks", headers=admin, params={"building_id": building["id"]})
    ).json()["data"][0]
    floor = (
        await client.post("/floors", headers=admin, json={"block_id": block["id"], "number": 7})
    ).json()["data"]
    fixture.flat = (
        await client.post(
            "/flats",
            headers=admin,
            json={"floor_id": floor["id"], "flat_number": f"{tag}-701", "area_sqft": 800},
        )
    ).json()["data"]

    for label in ("resident", "other"):
        email = f"notif-{label}-{tag.lower()}@test.nestflow.in"
        user = (
            await client.post(
                "/users",
                headers=admin,
                json={
                    "email": email,
                    "full_name": f"Notif {label.title()}",
                    "role_codes": ["FLAT_OWNER"],
                },
            )
        ).json()["data"]
        setattr(fixture, f"{label}_user", user)
        setattr(fixture, f"{label}_token", f"dev:{email}")

    await client.post(
        "/residents",
        headers=admin,
        json={
            "flat_id": fixture.flat["id"],
            "full_name": "Notif Resident",
            "resident_type": "OWNER",
            "is_primary": True,
            "user_id": fixture.resident_user["id"],
        },
    )
    return fixture


# --------------------------------------------------------------------------- #
# The hub
# --------------------------------------------------------------------------- #


async def test_the_hub_delivers_to_every_tab_a_user_has_open() -> None:
    from app.realtime.hub import RealtimeHub

    hub = RealtimeHub()
    society, user = uuid.uuid4(), uuid.uuid4()

    laptop = hub.subscribe(society, user)
    phone = hub.subscribe(society, user)

    delivered = hub.publish(society, [user], {"type": "notification", "data": {}})
    assert delivered == 2
    assert hub.connection_count(society) == 2
    assert hub.user_count(society) == 1

    # Closing one tab must not close the other.
    hub.unsubscribe(laptop)
    assert hub.publish(society, [user], {"type": "ping", "data": {}}) == 1
    hub.unsubscribe(phone)
    assert hub.connection_count(society) == 0


async def test_the_hub_will_not_cross_societies() -> None:
    """The society is part of the key, so a wrong user id cannot leak a payload."""
    from app.realtime.hub import RealtimeHub

    hub = RealtimeHub()
    user = uuid.uuid4()
    society_a, society_b = uuid.uuid4(), uuid.uuid4()

    hub.subscribe(society_a, user)
    assert hub.publish(society_b, [user], {"type": "notification", "data": {}}) == 0
    assert hub.broadcast(society_b, {"type": "notification", "data": {}}) == 0
    assert hub.broadcast(society_a, {"type": "notification", "data": {}}) == 1


async def test_a_client_that_cannot_keep_up_is_dropped_not_buffered() -> None:
    from app.realtime.hub import QUEUE_SIZE, RealtimeHub

    hub = RealtimeHub()
    society, user = uuid.uuid4(), uuid.uuid4()
    connection = hub.subscribe(society, user)

    for _ in range(QUEUE_SIZE + 25):
        hub.publish(society, [user], {"type": "notification", "data": {}})

    assert connection.queue.qsize() == QUEUE_SIZE
    assert connection.dropped == 25
    # The durable rows are still in PostgreSQL, which is the point.


async def test_publishing_to_nobody_is_not_an_error() -> None:
    from app.realtime.hub import RealtimeHub

    hub = RealtimeHub()
    assert hub.publish(uuid.uuid4(), [uuid.uuid4()], {"type": "x", "data": {}}) == 0


# --------------------------------------------------------------------------- #
# The outbox
# --------------------------------------------------------------------------- #


async def test_events_wait_for_the_commit(society_a: SocietyFixture) -> None:
    from app.database.manager import get_tenant_manager
    from app.realtime.hub import get_hub
    from app.realtime.outbox import bind_society, enqueue, pending_events

    society_id = uuid.UUID(society_a.id)
    user_id = uuid.uuid4()
    hub = get_hub()
    connection = hub.subscribe(society_id, user_id)

    try:
        async with get_tenant_manager().session(society_id) as session:
            bind_society(session, society_id)
            enqueue(
                session,
                type="notification",
                payload={"title": "Committed"},
                user_ids=[user_id],
            )
            # Nothing has been published yet: the transaction is still open.
            assert connection.queue.empty()
            assert len(pending_events(session)) == 1
            await session.commit()

        assert connection.queue.qsize() == 1
        assert connection.queue.get_nowait()["data"]["title"] == "Committed"
    finally:
        hub.unsubscribe(connection)


async def test_a_rolled_back_transaction_publishes_nothing(
    society_a: SocietyFixture,
) -> None:
    """The reason the outbox exists.

    A toast for a complaint that was never saved is worse than no toast.
    """
    from sqlalchemy import func, select

    from app.database.manager import get_tenant_manager
    from app.models.tenant import TenantUser
    from app.realtime.hub import get_hub
    from app.realtime.outbox import bind_society, enqueue

    society_id = uuid.UUID(society_a.id)
    user_id = uuid.uuid4()
    hub = get_hub()
    connection = hub.subscribe(society_id, user_id)

    class Boom(RuntimeError):
        """Whatever went wrong after the notification was queued."""

    try:
        with pytest.raises(Boom):
            # Exactly the production path: the session manager rolls back and
            # never reaches its commit.
            async with get_tenant_manager().session(society_id) as session:
                bind_society(session, society_id)
                await session.execute(select(func.count()).select_from(TenantUser))
                enqueue(
                    session,
                    type="notification",
                    payload={"title": "Never happened"},
                    user_ids=[user_id],
                )
                raise Boom

        assert connection.queue.empty()
    finally:
        hub.unsubscribe(connection)


async def test_a_broadcast_reaches_a_society_without_naming_anyone(
    society_a: SocietyFixture,
) -> None:
    from app.database.manager import get_tenant_manager
    from app.realtime.hub import get_hub
    from app.realtime.outbox import bind_society, enqueue

    society_id = uuid.UUID(society_a.id)
    hub = get_hub()
    first = hub.subscribe(society_id, uuid.uuid4())
    second = hub.subscribe(society_id, uuid.uuid4())

    try:
        async with get_tenant_manager().session(society_id) as session:
            bind_society(session, society_id)
            enqueue(
                session,
                type="notification",
                payload={"title": "Notice for everyone"},
                broadcast=True,
            )
            await session.commit()

        assert first.queue.qsize() == 1
        assert second.queue.qsize() == 1
    finally:
        hub.unsubscribe(first)
        hub.unsubscribe(second)


# --------------------------------------------------------------------------- #
# The REST surface
# --------------------------------------------------------------------------- #


async def test_the_feed_badge_matches_the_feed(
    client: AsyncClient, society_a: SocietyFixture, notify: NotifyFixture
) -> None:
    admin = auth(society_a.admin_token)
    resident = auth(notify.resident_token)

    await client.post(
        "/complaints",
        headers=resident,
        json={"title": "Feed check", "description": "Something is wrong."},
    )
    # The admin resolving it notifies the resident.
    listed = (
        await client.get("/complaints", headers=admin, params={"limit": 5, "open_only": True})
    ).json()["data"]
    ticket = listed["items"][0]
    await client.post(
        f"/complaints/{ticket['id']}/transition",
        headers=admin,
        json={"status": "RESOLVED", "note": "Fixed it."},
    )

    feed = (await client.get("/notifications/feed", headers=resident)).json()["data"]
    unread_page = (
        await client.get(
            "/notifications", headers=resident, params={"unread_only": True, "limit": 100}
        )
    ).json()["data"]

    assert feed["unread"] == unread_page["total"]
    assert feed["unread"] > 0


async def test_marking_read_moves_the_badge(
    client: AsyncClient, notify: NotifyFixture
) -> None:
    resident = auth(notify.resident_token)
    feed = (await client.get("/notifications/feed", headers=resident)).json()["data"]
    assert feed["items"], "expected the earlier tests to have produced notifications"

    first = feed["items"][0]["id"]
    result = (
        await client.post("/notifications/read", headers=resident, json={"ids": [first]})
    ).json()["data"]
    assert result["marked"] == 1
    assert result["unread"] == feed["unread"] - 1

    # Idempotent: marking it again marks nothing.
    again = (
        await client.post("/notifications/read", headers=resident, json={"ids": [first]})
    ).json()["data"]
    assert again["marked"] == 0


async def test_another_users_notification_id_marks_nothing(
    client: AsyncClient, notify: NotifyFixture
) -> None:
    """The ``user_id`` predicate is the defence, not a 403.

    Sending somebody else's id matches no rows, so the caller learns nothing
    about whether it existed.
    """
    resident = auth(notify.resident_token)
    feed = (await client.get("/notifications/feed", headers=resident)).json()["data"]
    assert feed["items"]

    someone_elses = feed["items"][0]["id"]
    result = (
        await client.post(
            "/notifications/read",
            headers=auth(notify.other_token),
            json={"ids": [someone_elses]},
        )
    ).json()["data"]
    assert result["marked"] == 0


async def test_mark_all_read_empties_the_badge(
    client: AsyncClient, notify: NotifyFixture
) -> None:
    resident = auth(notify.resident_token)
    result = (await client.post("/notifications/read-all", headers=resident)).json()["data"]
    assert result["unread"] == 0

    feed = (await client.get("/notifications/feed", headers=resident)).json()["data"]
    assert feed["unread"] == 0
    assert all(n["is_read"] for n in feed["items"])


async def test_notifications_do_not_leak_between_users(
    client: AsyncClient, notify: NotifyFixture
) -> None:
    mine = (await client.get("/notifications/feed", headers=auth(notify.resident_token))).json()[
        "data"
    ]
    theirs = (
        await client.get("/notifications/feed", headers=auth(notify.other_token))
    ).json()["data"]

    assert not ({n["id"] for n in mine["items"]} & {n["id"] for n in theirs["items"]})


# --------------------------------------------------------------------------- #
# The socket handshake
# --------------------------------------------------------------------------- #


def _ws_client() -> Any:
    """A test client that does **not** run the application lifespan.

    Entering the lifespan would dispose the central engine and the tenant
    manager on the way out — both of which are process-globals shared with the
    session-scoped ``client`` fixture, so every later test would find its
    database gone.
    """
    from starlette.testclient import TestClient

    from app.main import create_app

    return TestClient(create_app())


async def test_the_socket_refuses_a_connection_without_a_token() -> None:
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as caught:
        with _ws_client().websocket_connect("/api/v1/ws"):
            pass
    assert caught.value.code == 1008


async def test_the_socket_refuses_a_bad_token() -> None:
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as caught:
        with _ws_client().websocket_connect("/api/v1/ws?token=dev:nobody@nowhere.test"):
            pass
    # The same guard chain as a REST request, so an unregistered identity is
    # refused at the handshake rather than after connecting.
    assert caught.value.code == 1008


# --------------------------------------------------------------------------- #
# Scheduled jobs
# --------------------------------------------------------------------------- #


async def test_every_scheduled_job_is_runnable_and_idempotent(
    society_a: SocietyFixture,
) -> None:
    """Run the whole nightly sweep twice.

    The second pass must not fail and must not double anything — that is what
    makes a restart in the middle of the 6 a.m. run uneventful.
    """
    from app.workers.jobs import TENANT_JOBS, run_for_society

    society_id = uuid.UUID(society_a.id)
    first = {name: await run_for_society(job, society_id) for name, job in TENANT_JOBS.items()}
    second = {name: await run_for_society(job, society_id) for name, job in TENANT_JOBS.items()}

    for name in TENANT_JOBS:
        assert first[name] >= 0
        assert second[name] >= 0
    # Nothing new to generate, publish, expire or retire on the second pass.
    assert second["generate-scheduled-work"] == 0
    assert second["publish-due-notices"] == 0
    assert second["complete-past-bookings"] == 0
    assert second["expire-visitor-passes"] == 0


async def test_the_schedule_covers_every_job() -> None:
    """A job that exists but is never scheduled is a job that never runs."""
    from app.workers.jobs import TENANT_JOBS
    from app.workers.scheduler import SCHEDULE, build_scheduler

    scheduled = {name for name, _hour, _minute in SCHEDULE}
    assert scheduled == set(TENANT_JOBS)

    # Built, not started: the jobs are registered at construction, and starting
    # a real clock inside the suite would be a background thread nobody asked
    # for.
    scheduler = build_scheduler()
    ids = {job.id for job in scheduler.get_jobs()}
    assert set(TENANT_JOBS) <= ids
    assert "expire-subscriptions" in ids


async def test_an_unknown_job_is_refused() -> None:
    from app.workers.jobs import run_for_all_societies

    with pytest.raises(KeyError):
        await run_for_all_societies("not-a-job")


async def test_a_stale_visitor_pass_expires(
    client: AsyncClient, society_a: SocietyFixture, notify: NotifyFixture
) -> None:
    """The sweep clears yesterday's expected guests off the guard's board."""
    from datetime import timedelta as _td

    from sqlalchemy import update

    from app.database.manager import get_tenant_manager
    from app.models.tenant import Visitor
    from app.realtime.outbox import bind_society
    from app.services.operations import VisitorService

    now = datetime.now(UTC)
    pass_ = (
        await client.post(
            "/visitors/pre-approvals",
            headers=auth(notify.resident_token),
            json={
                "visitor_name": "Yesterday's plumber",
                "expected_from": (now - _td(hours=1)).isoformat(),
                "expected_to": (now + _td(hours=1)).isoformat(),
            },
        )
    ).json()["data"]

    society_id = uuid.UUID(society_a.id)
    async with get_tenant_manager().session(society_id) as session:
        bind_society(session, society_id)
        # Age the window rather than waiting an hour for it.
        # Age the whole window, not just its end: the row's CHECK refuses a
        # window that closes before it opens, and rightly so.
        await session.execute(
            update(Visitor)
            .where(Visitor.id == uuid.UUID(pass_["id"]))
            .values(expected_from=now - _td(hours=4), expected_to=now - _td(hours=2))
        )
        expired = await VisitorService(session).expire_stale()
        assert expired >= 1
        await session.commit()

    after = (
        await client.get(f"/visitors/{pass_['id']}", headers=auth(notify.resident_token))
    ).json()["data"]
    assert after["status"] == "EXPIRED"


async def test_a_resolved_complaint_closes_itself_eventually(
    client: AsyncClient, society_a: SocietyFixture, notify: NotifyFixture
) -> None:
    """Without this, "open complaints" only ever goes up."""
    from sqlalchemy import update

    from app.database.manager import get_tenant_manager
    from app.models.tenant import Complaint
    from app.realtime.outbox import bind_society
    from app.services.operations import AUTO_CLOSE_DAYS, ComplaintService

    admin = auth(society_a.admin_token)
    ticket = (
        await client.post(
            "/complaints",
            headers=auth(notify.resident_token),
            json={"title": "Auto close", "description": "A small thing."},
        )
    ).json()["data"]
    await client.post(
        f"/complaints/{ticket['id']}/transition",
        headers=admin,
        json={"status": "RESOLVED", "note": "Done."},
    )

    society_id = uuid.UUID(society_a.id)
    async with get_tenant_manager().session(society_id) as session:
        bind_society(session, society_id)
        await session.execute(
            update(Complaint)
            .where(Complaint.id == uuid.UUID(ticket["id"]))
            # ``created_at`` moves with it — the row's CHECK refuses a
            # resolution that predates the complaint.
            .values(
                created_at=datetime.now(UTC) - timedelta(days=AUTO_CLOSE_DAYS + 2),
                resolved_at=datetime.now(UTC) - timedelta(days=AUTO_CLOSE_DAYS + 1),
            )
        )
        closed = await ComplaintService(session).auto_close_resolved()
        assert closed >= 1
        await session.commit()

    after = (
        await client.get(f"/complaints/{ticket['id']}", headers=admin)
    ).json()["data"]
    assert after["status"] == "CLOSED"
    # The resolution notes survive, so a resident who disagrees can reopen it.
    assert after["resolution_notes"] == "Done."


async def test_a_scheduled_notice_publishes_itself(
    client: AsyncClient, society_a: SocietyFixture
) -> None:
    from sqlalchemy import update

    from app.database.manager import get_tenant_manager
    from app.models.tenant import Notice
    from app.realtime.outbox import bind_society
    from app.services.community import NoticeService

    admin = auth(society_a.admin_token)
    notice = (
        await client.post(
            "/notices",
            headers=admin,
            json={
                "title": "Scheduled for later",
                "body": "Published by the worker.",
                "publish_now": False,
                "publish_at": (datetime.now(UTC) + timedelta(days=2)).isoformat(),
            },
        )
    ).json()["data"]

    society_id = uuid.UUID(society_a.id)
    async with get_tenant_manager().session(society_id) as session:
        bind_society(session, society_id)
        await session.execute(
            update(Notice)
            .where(Notice.id == uuid.UUID(notice["id"]))
            .values(is_published=False, publish_at=datetime.now(UTC) - timedelta(minutes=5))
        )
        published = await NoticeService(session).publish_scheduled()
        assert published >= 1
        await session.commit()

    listing = (
        await client.get("/notices", headers=admin, params={"limit": 100})
    ).json()["data"]
    row = next(n for n in listing["items"] if n["id"] == notice["id"])
    assert row["is_published"] is True


async def test_generation_can_be_replayed_after_a_crash(
    client: AsyncClient, society_a: SocietyFixture
) -> None:
    from app.database.manager import get_tenant_manager
    from app.realtime.outbox import bind_society
    from app.services.operations import ScheduleGenerator

    admin = auth(society_a.admin_token)
    await client.post(
        "/housekeeping/schedules",
        headers=admin,
        json={
            "title": f"Daily lobby sweep {uuid.uuid4().hex[:4]}",
            "recurrence": "DAILY",
            "starts_on": date.today().isoformat(),
            "lead_days": 0,
        },
    )

    society_id = uuid.UUID(society_a.id)
    async with get_tenant_manager().session(society_id) as session:
        bind_society(session, society_id)
        first = await ScheduleGenerator(session).run()
        await session.commit()

    async with get_tenant_manager().session(society_id) as session:
        bind_society(session, society_id)
        second = await ScheduleGenerator(session).run()
        await session.commit()

    assert first["tasks_created"] >= 1
    assert second["tasks_created"] == 0
    assert second["schedules_examined"] >= 0


async def test_the_scheduler_stays_off_when_disabled() -> None:
    """Two web workers running the same sweep double every notification."""
    from app.workers.scheduler import shutdown_scheduler, start_scheduler

    # The suite runs with SCHEDULER_ENABLED=false.
    assert start_scheduler() is None
    shutdown_scheduler()


async def test_await_is_never_needed_to_publish() -> None:
    """The outbox releases events from SQLAlchemy's synchronous commit hook.

    If ``publish`` ever became a coroutine this test would fail. In production
    the failure mode would instead be an un-awaited coroutine swallowed inside
    the commit callback — a notification that silently never arrives.
    """
    import inspect

    from app.realtime.hub import RealtimeHub

    for name in ("publish", "broadcast", "subscribe", "unsubscribe"):
        assert not inspect.iscoroutinefunction(getattr(RealtimeHub, name))
