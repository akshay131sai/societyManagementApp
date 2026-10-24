"""Tenant isolation — the mandatory suite.

Society A must never read or write Society B's data. Each test maps to a threat
in docs/architecture/tenant-isolation.md section 1.

These tests must never be skipped or marked xfail. If one fails, the product
does not ship.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from tests.conftest import SocietyFixture, auth

pytestmark = pytest.mark.asyncio


async def test_two_societies_have_distinct_databases(
    society_a: SocietyFixture, society_b: SocietyFixture
) -> None:
    assert society_a.database_name != society_b.database_name
    assert society_a.id != society_b.id
    assert society_a.database_name.startswith("nestflow_society_")
    assert society_b.database_name.startswith("nestflow_society_")


async def test_engine_cache_returns_the_correct_database(
    society_a: SocietyFixture, society_b: SocietyFixture
) -> None:
    """T7 — interleaved access must not cross the engine cache."""
    from app.database.manager import get_tenant_manager

    manager = get_tenant_manager()
    a_id, b_id = uuid.UUID(society_a.id), uuid.UUID(society_b.id)

    for _ in range(3):
        assert await manager.current_database(a_id) == society_a.database_name
        assert await manager.current_database(b_id) == society_b.database_name


async def test_data_written_to_a_is_absent_in_b(
    client: AsyncClient, society_a: SocietyFixture, society_b: SocietyFixture
) -> None:
    marker = f"marker-{uuid.uuid4().hex[:8]}@test.nestflow.in"

    created = await client.post(
        "/users",
        headers=auth(society_a.admin_token),
        json={
            "email": marker,
            "full_name": "Isolation Probe",
            "role_codes": ["FLAT_OWNER"],
        },
    )
    assert created.status_code == 201, created.text

    in_a = await client.get("/users", headers=auth(society_a.admin_token), params={"q": marker})
    assert any(u["email"] == marker for u in in_a.json()["data"]["items"])

    in_b = await client.get("/users", headers=auth(society_b.admin_token), params={"q": marker})
    assert in_b.json()["data"]["items"] == []


async def test_society_id_in_body_is_ignored(
    client: AsyncClient, society_a: SocietyFixture, society_b: SocietyFixture
) -> None:
    """T1 — a foreign society_id in the payload must not redirect the write."""
    before_b = (await client.get("/society/settings", headers=auth(society_b.admin_token))).json()
    hijack = f"HIJACK-{uuid.uuid4().hex[:6]}"

    response = await client.put(
        "/society/settings",
        headers=auth(society_a.admin_token),
        json={"society_name": hijack, "society_id": society_b.id},
    )
    assert response.status_code == 200

    after_a = (await client.get("/society/settings", headers=auth(society_a.admin_token))).json()
    after_b = (await client.get("/society/settings", headers=auth(society_b.admin_token))).json()

    assert after_a["data"]["society_name"] == hijack, "the write went somewhere else"
    assert after_b["data"]["society_name"] == before_b["data"]["society_name"]


async def test_society_id_query_param_is_ignored(
    client: AsyncClient, society_a: SocietyFixture, society_b: SocietyFixture
) -> None:
    """T1 — query string variant."""
    await client.put(
        "/theme", headers=auth(society_a.admin_token), json={"primary_color": "#DB2777"}
    )
    await client.put(
        "/theme", headers=auth(society_b.admin_token), json={"primary_color": "#2563EB"}
    )

    response = await client.get(
        "/theme", headers=auth(society_a.admin_token), params={"society_id": society_b.id}
    )
    assert response.json()["data"]["primary_color"] == "#DB2777"


async def test_tenant_header_is_ignored(
    client: AsyncClient, society_a: SocietyFixture, society_b: SocietyFixture
) -> None:
    """T2 — no middleware reads a tenant header."""
    headers = auth(society_a.admin_token) | {
        "X-Society-Id": society_b.id,
        "X-Tenant-Db": society_b.database_name,
    }
    response = await client.get("/theme", headers=headers)
    assert response.json()["data"]["primary_color"] == "#DB2777"


async def test_foreign_user_id_returns_404(
    client: AsyncClient, society_a: SocietyFixture, society_b: SocietyFixture
) -> None:
    """T5 — a real id from another society is simply not present here."""
    b_users = await client.get("/users", headers=auth(society_b.admin_token))
    b_user_id = b_users.json()["data"]["items"][0]["id"]

    response = await client.get(f"/users/{b_user_id}", headers=auth(society_a.admin_token))
    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


async def test_super_admin_has_no_tenant_session(
    client: AsyncClient, super_admin: str, society_a: SocietyFixture
) -> None:
    """A platform admin never receives a tenant session."""
    for path in ("/theme", "/society/settings", "/users"):
        response = await client.get(path, headers=auth(super_admin))
        assert response.status_code == 403, path
        assert response.json()["code"] == "PERMISSION_DENIED"


async def test_society_admin_cannot_reach_platform_endpoints(
    client: AsyncClient, society_a: SocietyFixture
) -> None:
    for path in ("/platform/societies", "/platform/dashboard", "/platform/users"):
        response = await client.get(path, headers=auth(society_a.admin_token))
        assert response.status_code == 403, path


async def test_invalid_database_name_is_rejected_before_ddl() -> None:
    """T6 — the allowlist runs before any name reaches DDL."""
    from app.database.manager import TenantDatabaseManager

    manager = TenantDatabaseManager()
    for bad in (
        "postgres",
        "nestflow_platform",
        "nestflow_society_0001; DROP DATABASE nestflow_platform",
        'nestflow_society_"0001"',
        "nestflow_society_",
        "",
        "../etc/passwd",
    ):
        with pytest.raises(ValueError, match="Unsafe tenant database name"):
            manager.validate_database_name(bad)


async def test_generated_database_names_are_well_formed() -> None:
    from app.core.config import DB_NAME_PATTERN
    from app.database.manager import TenantDatabaseManager

    assert TenantDatabaseManager.build_database_name(1) == "nestflow_society_0001"
    assert TenantDatabaseManager.build_database_name(4321) == "nestflow_society_4321"
    assert TenantDatabaseManager.build_database_name(99999) == "nestflow_society_99999"
    for n in (1, 7, 250, 9999, 123456):
        assert DB_NAME_PATTERN.match(TenantDatabaseManager.build_database_name(n))


async def test_tenant_dsn_refuses_unsafe_name() -> None:
    from app.core.config import get_settings

    with pytest.raises(ValueError, match="Refusing to build a DSN"):
        get_settings().tenant_dsn_sync("postgres")
