"""Society provisioning and subscription lifecycle."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from tests.conftest import SocietyFixture, auth

pytestmark = pytest.mark.asyncio


async def test_provisioning_creates_a_migrated_seeded_database(
    client: AsyncClient, super_admin: str, society_a: SocietyFixture
) -> None:
    response = await client.get(
        f"/platform/societies/{society_a.id}/verify", headers=auth(super_admin)
    )
    assert response.status_code == 200
    info = response.json()["data"]

    assert info["database"] == society_a.database_name
    assert {"users", "roles", "permissions", "role_permissions", "user_roles"} <= set(
        info["tables"]
    )
    assert {"society_settings", "theme_settings", "audit_logs", "notifications"} <= set(
        info["tables"]
    )
    assert "SOCIETY_ADMIN" in info["roles"]
    assert info["permissions"] > 50
    assert info["users"] >= 1


async def test_society_becomes_active(
    client: AsyncClient, super_admin: str, society_a: SocietyFixture
) -> None:
    response = await client.get(
        f"/platform/societies/{society_a.id}", headers=auth(super_admin)
    )
    detail = response.json()["data"]
    assert detail["status"] == "ACTIVE"
    assert detail["registry"]["provisioning_state"] == "COMPLETED"
    assert detail["registry"]["alembic_revision"]
    assert detail["subscription"]["status"] in {"TRIAL", "ACTIVE"}


async def test_admin_can_sign_in_immediately_after_provisioning(
    client: AsyncClient, society_a: SocietyFixture
) -> None:
    """The whole point of the Phase 1 milestone."""
    response = await client.get("/auth/me", headers=auth(society_a.admin_token))
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["society"]["id"] == society_a.id
    assert data["principal"]["roles"] == ["SOCIETY_ADMIN"]
    assert data["theme"] is not None


async def test_duplicate_slug_is_refused(
    client: AsyncClient, super_admin: str, society_a: SocietyFixture
) -> None:
    response = await client.post(
        "/platform/societies",
        headers=auth(super_admin),
        json={
            "name": "Duplicate Attempt",
            "slug": society_a.slug,
            "city": "Pune",
            "state": "Maharashtra",
            "pincode": "411001",
            "contact_email": "dup@test.nestflow.in",
            "contact_phone": "9800000009",
            "admin": {"email": "dup-admin@test.nestflow.in", "display_name": "Dup"},
        },
    )
    assert response.status_code == 409
    assert response.json()["code"] == "ALREADY_EXISTS"


@pytest.mark.parametrize(
    "field,value",
    [
        ("pincode", "000000"),
        ("pincode", "41104"),
        ("contact_phone", "1234567890"),
        ("contact_phone", "+919822012345"),
        ("contact_email", "not-an-email"),
        ("name", "ab"),
    ],
)
async def test_indian_format_validation(
    client: AsyncClient, super_admin: str, field: str, value: str
) -> None:
    payload = {
        "name": "Validation Test Society",
        "city": "Pune",
        "state": "Maharashtra",
        "pincode": "411001",
        "contact_email": "valid@test.nestflow.in",
        "contact_phone": "9800000003",
        "admin": {"email": "v-admin@test.nestflow.in", "display_name": "V Admin"},
    }
    payload[field] = value

    response = await client.post(
        "/platform/societies", headers=auth(super_admin), json=payload
    )
    assert response.status_code == 422, f"{field}={value} should be rejected"


async def test_only_super_admin_can_provision(
    client: AsyncClient, society_a: SocietyFixture
) -> None:
    response = await client.post(
        "/platform/societies",
        headers=auth(society_a.admin_token),
        json={
            "name": "Unauthorised Society",
            "city": "Pune",
            "state": "Maharashtra",
            "pincode": "411001",
            "contact_email": "x@test.nestflow.in",
            "contact_phone": "9800000004",
            "admin": {"email": "x-admin@test.nestflow.in", "display_name": "X"},
        },
    )
    assert response.status_code == 403


# --------------------------------------------------------------------------- #
# Lock / subscription enforcement
# --------------------------------------------------------------------------- #


async def test_locking_blocks_access_and_unlock_restores_it(
    client: AsyncClient, super_admin: str, society_b: SocietyFixture
) -> None:
    lock = await client.post(
        f"/platform/societies/{society_b.id}/lock",
        headers=auth(super_admin),
        json={"reason": "Test lock"},
    )
    assert lock.json()["data"]["status"] == "LOCKED"

    blocked = await client.get("/auth/me", headers=auth(society_b.admin_token))
    assert blocked.status_code == 403
    assert blocked.json()["code"] == "SOCIETY_LOCKED"
    assert blocked.json()["message"] == "Test lock"

    unlock = await client.post(
        f"/platform/societies/{society_b.id}/unlock", headers=auth(super_admin)
    )
    assert unlock.json()["data"]["status"] == "ACTIVE"

    restored = await client.get("/auth/me", headers=auth(society_b.admin_token))
    assert restored.status_code == 200


async def test_locking_one_society_does_not_affect_another(
    client: AsyncClient, super_admin: str, society_a: SocietyFixture, society_b: SocietyFixture
) -> None:
    await client.post(
        f"/platform/societies/{society_b.id}/lock",
        headers=auth(super_admin),
        json={"reason": "Blast radius test"},
    )
    try:
        assert (await client.get("/auth/me", headers=auth(society_a.admin_token))).status_code == 200
        assert (await client.get("/auth/me", headers=auth(society_b.admin_token))).status_code == 403
    finally:
        await client.post(
            f"/platform/societies/{society_b.id}/unlock", headers=auth(super_admin)
        )


async def test_suspended_subscription_returns_402(
    client: AsyncClient, super_admin: str, society_b: SocietyFixture
) -> None:
    subs = await client.get(
        "/platform/subscriptions", headers=auth(super_admin), params={"society_id": society_b.id}
    )
    subscription_id = subs.json()["data"][0]["id"]

    await client.post(
        f"/platform/subscriptions/{subscription_id}/suspend",
        headers=auth(super_admin),
        params={"reason": "Test suspension"},
    )
    blocked = await client.get("/auth/me", headers=auth(society_b.admin_token))
    assert blocked.status_code == 402, "an entitlement failure is 402, not 403"
    assert blocked.json()["code"] == "SUBSCRIPTION_SUSPENDED"

    extended = await client.post(
        f"/platform/subscriptions/{subscription_id}/extend",
        headers=auth(super_admin),
        json={"days": 30},
    )
    assert extended.json()["data"]["status"] == "ACTIVE"
    assert (await client.get("/auth/me", headers=auth(society_b.admin_token))).status_code == 200


async def test_expired_subscription_returns_402(
    client: AsyncClient, super_admin: str, society_b: SocietyFixture
) -> None:
    """The guard checks the end date directly, not a swept status flag."""
    from datetime import date, timedelta

    from sqlalchemy import update

    from app.database.central import central_session
    from app.database.manager import get_tenant_manager
    from app.models.central import Subscription

    society_id = uuid.UUID(society_b.id)
    async with central_session() as session:
        original = await session.scalar(
            update(Subscription)
            .where(Subscription.society_id == society_id, Subscription.is_current.is_(True))
            .values(
                start_date=date.today() - timedelta(days=60),
                end_date=date.today() - timedelta(days=1),
            )
            .returning(Subscription.id)
        )
    await get_tenant_manager().dispose(society_id)

    try:
        blocked = await client.get("/auth/me", headers=auth(society_b.admin_token))
        assert blocked.status_code == 402
        assert blocked.json()["code"] == "SUBSCRIPTION_EXPIRED"
    finally:
        async with central_session() as session:
            await session.execute(
                update(Subscription)
                .where(Subscription.id == original)
                .values(
                    start_date=date.today() - timedelta(days=1),
                    end_date=date.today() + timedelta(days=30),
                )
            )


async def test_extend_requires_a_later_date(
    client: AsyncClient, super_admin: str, society_a: SocietyFixture
) -> None:
    subs = await client.get(
        "/platform/subscriptions", headers=auth(super_admin), params={"society_id": society_a.id}
    )
    subscription_id = subs.json()["data"][0]["id"]

    response = await client.post(
        f"/platform/subscriptions/{subscription_id}/extend",
        headers=auth(super_admin),
        json={"new_end_date": "2020-01-01"},
    )
    assert response.status_code == 422


async def test_platform_dashboard_counts(
    client: AsyncClient, super_admin: str, society_a: SocietyFixture
) -> None:
    response = await client.get("/platform/dashboard", headers=auth(super_admin))
    data = response.json()["data"]
    assert data["total_societies"] >= 1
    assert data["active_societies"] >= 1
    assert data["active_subscriptions"] >= 1


async def test_audit_trail_records_provisioning(
    client: AsyncClient, super_admin: str, society_a: SocietyFixture
) -> None:
    response = await client.get(
        "/platform/audit-logs", headers=auth(super_admin), params={"society_id": society_a.id}
    )
    actions = {row["action"] for row in response.json()["data"]["items"]}
    assert "SOCIETY_PROVISIONED" in actions


async def test_audit_trail_never_stores_a_token(
    client: AsyncClient, super_admin: str
) -> None:
    response = await client.get(
        "/platform/audit-logs", headers=auth(super_admin), params={"limit": 100}
    )
    blob = str(response.json()).lower()
    assert "bearer " not in blob
    assert "authorization" not in blob
