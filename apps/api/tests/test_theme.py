"""Theme system — per-society independence and input safety."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import SocietyFixture, auth

pytestmark = pytest.mark.asyncio


async def test_default_theme_is_seeded(
    client: AsyncClient, society_b: SocietyFixture
) -> None:
    response = await client.get("/theme", headers=auth(society_b.admin_token))
    assert response.status_code == 200
    theme = response.json()["data"]
    assert theme["primary_color"].startswith("#")
    assert theme["theme_mode"] in {"light", "dark", "system"}
    assert 0 <= theme["border_radius"] <= 32


async def test_changing_a_does_not_affect_b(
    client: AsyncClient, society_a: SocietyFixture, society_b: SocietyFixture
) -> None:
    """The headline requirement: Society A pink, Society B blue."""
    a = await client.put(
        "/theme",
        headers=auth(society_a.admin_token),
        json={"primary_color": "#DB2777", "theme_mode": "light", "border_radius": 18},
    )
    b = await client.put(
        "/theme",
        headers=auth(society_b.admin_token),
        json={"primary_color": "#2563EB", "theme_mode": "dark", "border_radius": 8},
    )
    assert a.status_code == 200 and b.status_code == 200

    a_read = (await client.get("/theme", headers=auth(society_a.admin_token))).json()["data"]
    b_read = (await client.get("/theme", headers=auth(society_b.admin_token))).json()["data"]

    assert a_read["primary_color"] == "#DB2777"
    assert a_read["theme_mode"] == "light"
    assert a_read["border_radius"] == 18

    assert b_read["primary_color"] == "#2563EB"
    assert b_read["theme_mode"] == "dark"
    assert b_read["border_radius"] == 8


async def test_theme_isolation_at_the_database_level(
    society_a: SocietyFixture, society_b: SocietyFixture
) -> None:
    """Verified through the tenant sessions, bypassing the API entirely."""
    import uuid

    from sqlalchemy import text

    from app.database.manager import get_tenant_manager

    manager = get_tenant_manager()
    async with manager.session(uuid.UUID(society_a.id)) as session:
        a_color = await session.scalar(text("SELECT primary_color FROM theme_settings"))
        a_db = await session.scalar(text("SELECT current_database()"))
    async with manager.session(uuid.UUID(society_b.id)) as session:
        b_color = await session.scalar(text("SELECT primary_color FROM theme_settings"))
        b_db = await session.scalar(text("SELECT current_database()"))

    assert a_db == society_a.database_name
    assert b_db == society_b.database_name
    assert a_color != b_color


@pytest.mark.parametrize(
    "value",
    [
        "red",
        "#FFF",
        "#GGGGGG",
        "rgb(0,0,0)",
        "#4F46E5; } body { display: none",
        "var(--x)",
        "",
    ],
)
async def test_invalid_colour_is_rejected(
    client: AsyncClient, society_a: SocietyFixture, value: str
) -> None:
    """These values end up inside a CSS custom property, so validation matters."""
    response = await client.put(
        "/theme", headers=auth(society_a.admin_token), json={"primary_color": value}
    )
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize("radius", [-1, 33, 999])
async def test_radius_out_of_range_is_rejected(
    client: AsyncClient, society_a: SocietyFixture, radius: int
) -> None:
    response = await client.put(
        "/theme", headers=auth(society_a.admin_token), json={"border_radius": radius}
    )
    assert response.status_code == 422


async def test_invalid_mode_is_rejected(
    client: AsyncClient, society_a: SocietyFixture
) -> None:
    response = await client.put(
        "/theme", headers=auth(society_a.admin_token), json={"theme_mode": "neon"}
    )
    assert response.status_code == 422


async def test_reset_restores_defaults(
    client: AsyncClient, society_a: SocietyFixture
) -> None:
    await client.put(
        "/theme", headers=auth(society_a.admin_token), json={"primary_color": "#EA580C"}
    )
    response = await client.post("/theme/reset", headers=auth(society_a.admin_token))
    assert response.status_code == 200
    assert response.json()["data"]["primary_color"] == "#4F46E5"
    assert response.json()["data"]["border_radius"] == 14


async def test_presets_are_available(client: AsyncClient, society_a: SocietyFixture) -> None:
    response = await client.get("/theme/presets", headers=auth(society_a.admin_token))
    presets = response.json()["data"]["presets"]
    assert set(presets) >= {"indigo", "blue", "purple", "pink", "green", "orange"}
    assert all(v.startswith("#") and len(v) == 7 for v in presets.values())


async def test_theme_is_included_in_bootstrap(
    client: AsyncClient, society_a: SocietyFixture
) -> None:
    """The theme must arrive with /auth/me to avoid a second round trip."""
    await client.put(
        "/theme", headers=auth(society_a.admin_token), json={"primary_color": "#059669"}
    )
    me = await client.get("/auth/me", headers=auth(society_a.admin_token))
    assert me.json()["data"]["theme"]["primary_color"] == "#059669"
