"""Test fixtures.

These are **integration** tests against a real PostgreSQL instance. Tenant
isolation is a property of how connections are routed, so testing it against
mocks would prove nothing. Two real societies are provisioned once per session
and dropped afterwards.

Requires the dev database from docs/deployment/deployment.md:

    docker run -d --name nestflow-postgres \
      -e POSTGRES_USER=nestflow -e POSTGRES_PASSWORD=nestflow_dev_pw \
      -e POSTGRES_DB=nestflow_platform -p 5433:5432 postgres:17-alpine
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Rate limiting is switched off for the suite and exercised directly in
# tests/test_ratelimit.py instead. A hundred tests sharing one token would
# otherwise trip the per-user budget and turn every assertion into a 429 —
# testing the limiter by accident, and nothing else on purpose.
os.environ["RATE_LIMIT_ENABLED"] = "false"

# Likewise pinned rather than inherited. test_the_scheduler_stays_off_when_disabled
# asserts the disabled path, and a developer whose .env enables the scheduler
# would otherwise see it fail for a reason that has nothing to do with them.
os.environ["SCHEDULER_ENABLED"] = "false"

from app.core.config import get_settings  # noqa: E402
from app.core.eventloop import IS_WINDOWS  # noqa: E402

get_settings.cache_clear()


@pytest.fixture(scope="session")
def event_loop_policy() -> asyncio.AbstractEventLoopPolicy:
    """psycopg's async mode needs a SelectorEventLoop on Windows.

    pytest-asyncio drives the loop itself, so ``loop_factory`` is not available
    here and the policy hook is the supported override point.
    """
    if IS_WINDOWS:
        return asyncio.WindowsSelectorEventLoopPolicy()  # type: ignore[attr-defined]
    return asyncio.DefaultEventLoopPolicy()


@dataclass(frozen=True, slots=True)
class SocietyFixture:
    id: str
    slug: str
    name: str
    database_name: str
    admin_email: str
    admin_token: str


SUPER_ADMIN_EMAIL = "test-superadmin@nestflow.in"
SUPER_ADMIN_TOKEN = f"dev:{SUPER_ADMIN_EMAIL}"


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture(scope="session")
async def client() -> AsyncIterator[AsyncClient]:
    from app.main import create_app

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api/v1", timeout=120.0
    ) as c:
        yield c

    from app.database.central import dispose_central_engine
    from app.database.manager import dispose_tenant_manager

    await dispose_tenant_manager()
    await dispose_central_engine()


@pytest_asyncio.fixture(scope="session")
async def super_admin(client: AsyncClient) -> str:
    """Ensure a super admin and at least one plan exist, then return the token."""
    from app.database.central import central_session
    from app.models.central import BillingCycle, PlatformUser, SubscriptionPlan
    from app.repositories.central import PlatformUserRepository, SubscriptionPlanRepository

    async with central_session() as session:
        plans = SubscriptionPlanRepository(session)
        if await plans.get_by_code("TEST_PLAN") is None:
            await plans.create(
                SubscriptionPlan(
                    name="Test Plan",
                    code="TEST_PLAN",
                    price=0,
                    billing_cycle=BillingCycle.MONTHLY,
                    max_flats=100,
                    max_users=200,
                    trial_days=30,
                    sort_order=0,
                    is_active=True,
                )
            )

        users = PlatformUserRepository(session)
        if await users.get_by_email_in_society(SUPER_ADMIN_EMAIL, None) is None:
            await users.create(
                PlatformUser(
                    firebase_uid=f"dev-uid-{SUPER_ADMIN_EMAIL}",
                    email=SUPER_ADMIN_EMAIL,
                    display_name="Test Super Admin",
                    is_super_admin=True,
                    society_id=None,
                    is_active=True,
                )
            )

    return SUPER_ADMIN_TOKEN


async def _provision(client: AsyncClient, super_admin_token: str, label: str) -> SocietyFixture:
    suffix = uuid.uuid4().hex[:8]
    slug = f"test-{label}-{suffix}"
    admin_email = f"admin-{label}-{suffix}@test.nestflow.in"

    response = await client.post(
        "/platform/societies",
        headers=auth(super_admin_token),
        json={
            "name": f"Test {label.title()} {suffix}",
            "slug": slug,
            "city": "Pune",
            "state": "Maharashtra",
            "pincode": "411001",
            "contact_email": f"office-{suffix}@test.nestflow.in",
            "contact_phone": "9800000001",
            "admin": {
                "email": admin_email,
                "display_name": f"Admin {label.title()}",
                "phone": "9800000002",
            },
        },
    )
    assert response.status_code == 201, response.text
    data = response.json()["data"]
    return SocietyFixture(
        id=data["society"]["id"],
        slug=slug,
        name=data["society"]["name"],
        database_name=data["database_name"],
        admin_email=admin_email,
        admin_token=f"dev:{admin_email}",
    )


@pytest_asyncio.fixture(scope="session")
async def society_a(client: AsyncClient, super_admin: str) -> AsyncIterator[SocietyFixture]:
    fixture = await _provision(client, super_admin, "alpha")
    yield fixture
    await _teardown(fixture)


@pytest_asyncio.fixture(scope="session")
async def society_b(client: AsyncClient, super_admin: str) -> AsyncIterator[SocietyFixture]:
    fixture = await _provision(client, super_admin, "bravo")
    yield fixture
    await _teardown(fixture)


async def _teardown(fixture: SocietyFixture) -> None:
    """Drop the tenant database and its central records."""
    from sqlalchemy import delete, text

    from app.database.central import central_session
    from app.database.manager import get_tenant_manager
    from app.models.central import (
        DatabaseRegistry,
        PlatformAuditLog,
        PlatformUser,
        Society,
        SocietyAdminAssignment,
        Subscription,
    )

    manager = get_tenant_manager()
    society_id = uuid.UUID(fixture.id)
    await manager.dispose(society_id)

    async with central_session() as session:
        for model in (
            DatabaseRegistry,
            SocietyAdminAssignment,
            Subscription,
            PlatformAuditLog,
        ):
            await session.execute(delete(model).where(model.society_id == society_id))
        await session.execute(delete(PlatformUser).where(PlatformUser.society_id == society_id))
        await session.execute(text("UPDATE societies SET created_by = NULL WHERE id = :i"), {"i": society_id})
        await session.execute(delete(Society).where(Society.id == society_id))

    try:
        await manager.drop_database(fixture.database_name)
    except Exception:  # pragma: no cover - best-effort cleanup
        pass
