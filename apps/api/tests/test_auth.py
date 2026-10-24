"""Authentication and access guards."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import SocietyFixture, auth

pytestmark = pytest.mark.asyncio


async def test_missing_token_is_unauthenticated(client: AsyncClient) -> None:
    response = await client.get("/auth/me")
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"


async def test_malformed_token_is_rejected(client: AsyncClient) -> None:
    response = await client.get("/auth/me", headers=auth("not-a-valid-token"))
    assert response.status_code == 401
    assert response.json()["code"] == "TOKEN_INVALID"


async def test_unknown_identity_is_not_registered(client: AsyncClient) -> None:
    """Authenticating with the identity provider does not create an account."""
    response = await client.get("/auth/me", headers=auth("dev:nobody@nowhere.example"))
    assert response.status_code == 401
    assert response.json()["code"] == "USER_NOT_REGISTERED"


async def test_super_admin_principal(client: AsyncClient, super_admin: str) -> None:
    response = await client.get("/auth/me", headers=auth(super_admin))
    assert response.status_code == 200
    data = response.json()["data"]
    principal = data["principal"]

    assert principal["is_super_admin"] is True
    assert principal["society_id"] is None, "a super admin must not be scoped to a society"
    assert principal["roles"] == ["SUPER_ADMIN"]
    assert all(p.startswith("platform.") for p in principal["permissions"])


async def test_society_admin_principal(
    client: AsyncClient, society_a: SocietyFixture
) -> None:
    response = await client.get("/auth/me", headers=auth(society_a.admin_token))
    assert response.status_code == 200
    data = response.json()["data"]

    assert data["principal"]["is_super_admin"] is False
    assert data["principal"]["society_id"] == society_a.id
    assert data["principal"]["roles"] == ["SOCIETY_ADMIN"]
    assert data["society"]["slug"] == society_a.slug
    assert data["subscription"]["status"] in {"TRIAL", "ACTIVE"}
    assert data["theme"] is not None
    assert data["navigation"], "navigation must be server-driven"


async def test_me_is_a_single_bootstrap_call(
    client: AsyncClient, society_a: SocietyFixture
) -> None:
    """The shell must render without a request waterfall."""
    data = (await client.get("/auth/me", headers=auth(society_a.admin_token))).json()["data"]
    for key in ("principal", "society", "subscription", "theme", "navigation", "auth_provider"):
        assert key in data and data[key] is not None, key


async def test_permissions_endpoint_matches_principal(
    client: AsyncClient, society_a: SocietyFixture
) -> None:
    me = (await client.get("/auth/me", headers=auth(society_a.admin_token))).json()
    perms = (await client.get("/auth/permissions", headers=auth(society_a.admin_token))).json()
    assert perms["data"] == me["data"]["principal"]["permissions"]


async def test_session_records_login(client: AsyncClient, society_a: SocietyFixture) -> None:
    response = await client.post("/auth/session", headers=auth(society_a.admin_token))
    assert response.status_code == 200
    assert response.json()["data"]["recorded"] is True


async def test_every_response_carries_a_request_id(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.headers.get("X-Request-Id")

    error = await client.get("/auth/me")
    assert error.json()["request_id"]


async def test_security_headers_are_present(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"


async def test_dev_provider_is_refused_in_production() -> None:
    """The process must not boot with the dev verifier in production."""
    import os
    from unittest import mock

    from pydantic import ValidationError

    from app.core.config import Settings

    env = {
        "ENVIRONMENT": "production",
        "AUTH_PROVIDER": "dev",
        "DEBUG": "false",
        "CENTRAL_DATABASE_URL": "postgresql+psycopg://u:p@localhost:5432/db",
        "TENANT_DB_USER": "u",
        "TENANT_DB_PASSWORD": "p",
    }
    with mock.patch.dict(os.environ, env, clear=False):
        with pytest.raises(ValidationError, match="AUTH_PROVIDER=dev is refused"):
            Settings(_env_file=None)  # type: ignore[call-arg]


async def test_health_endpoints_need_no_auth(client: AsyncClient) -> None:
    for path in ("/health", "/health/ready", "/health/info"):
        response = await client.get(path)
        assert response.status_code == 200, path
        assert response.json()["success"] is True


async def test_readiness_does_not_open_tenant_connections(client: AsyncClient) -> None:
    """A readiness probe must not connect to every tenant database."""
    from app.database.manager import get_tenant_manager

    before = get_tenant_manager().cached_count
    await client.get("/health/ready")
    assert get_tenant_manager().cached_count == before
