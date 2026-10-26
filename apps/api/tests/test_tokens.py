"""Access and refresh tokens: login, rotation, reuse detection, sign-out."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from httpx import AsyncClient

from tests.conftest import SUPER_ADMIN_EMAIL, SocietyFixture

pytestmark = pytest.mark.asyncio


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def login(client: AsyncClient, id_token: str) -> dict[str, object]:
    response = await client.post("/auth/login", json={"id_token": id_token})
    assert response.status_code == 200, response.text
    return response.json()["data"]


# --------------------------------------------------------------------------- #
# Login
# --------------------------------------------------------------------------- #


async def test_login_issues_a_working_pair(client: AsyncClient, super_admin: str) -> None:
    pair = await login(client, super_admin)

    assert pair["token_type"] == "bearer"
    assert pair["expires_in"] == 15 * 60
    assert pair["refresh_expires_in"] == 14 * 24 * 3600

    me = await client.get("/auth/me", headers=bearer(str(pair["access_token"])))
    assert me.status_code == 200
    assert me.json()["data"]["principal"]["email"] == SUPER_ADMIN_EMAIL


async def test_login_for_a_society_user(client: AsyncClient, society_a: SocietyFixture) -> None:
    pair = await login(client, society_a.admin_token)
    me = await client.get("/auth/me", headers=bearer(str(pair["access_token"])))
    assert me.json()["data"]["principal"]["society_id"] == society_a.id


async def test_login_refuses_an_unregistered_identity(client: AsyncClient) -> None:
    response = await client.post("/auth/login", json={"id_token": "dev:nobody@nowhere.example"})
    assert response.status_code == 401
    assert response.json()["code"] == "USER_NOT_REGISTERED"


async def test_login_refuses_a_malformed_identity(client: AsyncClient) -> None:
    response = await client.post("/auth/login", json={"id_token": "not-a-token"})
    assert response.status_code == 401
    assert response.json()["code"] == "TOKEN_INVALID"


# --------------------------------------------------------------------------- #
# Access tokens
# --------------------------------------------------------------------------- #


async def test_an_identity_token_is_not_a_bearer_token(
    client: AsyncClient, super_admin: str
) -> None:
    """``dev:<email>`` is accepted by /auth/login only — never on a resource."""
    response = await client.get("/auth/me", headers=bearer(super_admin))
    assert response.status_code == 401
    assert response.json()["code"] == "TOKEN_INVALID"


async def test_a_refresh_token_is_not_a_bearer_token(
    client: AsyncClient, super_admin: str
) -> None:
    pair = await login(client, super_admin)
    response = await client.get("/auth/me", headers=bearer(str(pair["refresh_token"])))
    assert response.status_code == 401
    assert response.json()["code"] == "TOKEN_INVALID"


async def test_an_expired_access_token_says_so(client: AsyncClient) -> None:
    from app.core.config import get_settings

    settings = get_settings()
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    token = jwt.encode(
        {
            "sub": f"dev-uid-{SUPER_ADMIN_EMAIL}",
            "email": SUPER_ADMIN_EMAIL,
            "typ": "access",
            "jti": "x",
            "iss": settings.JWT_ISSUER,
            "aud": settings.JWT_AUDIENCE,
            "iat": past - timedelta(minutes=15),
            "exp": past,
        },
        settings.jwt_secret,
        algorithm="HS256",
    )
    response = await client.get("/auth/me", headers=bearer(token))
    assert response.status_code == 401
    assert response.json()["code"] == "TOKEN_EXPIRED"


async def test_a_token_signed_with_another_key_is_rejected(
    client: AsyncClient, super_admin: str
) -> None:
    pair = await login(client, super_admin)
    claims = jwt.decode(str(pair["access_token"]), options={"verify_signature": False})
    forged = jwt.encode(claims, "x" * 48, algorithm="HS256")
    response = await client.get("/auth/me", headers=bearer(forged))
    assert response.status_code == 401
    assert response.json()["code"] == "TOKEN_INVALID"


async def test_an_unsigned_token_is_rejected(client: AsyncClient, super_admin: str) -> None:
    pair = await login(client, super_admin)
    claims = jwt.decode(str(pair["access_token"]), options={"verify_signature": False})
    unsigned = jwt.encode(claims, None, algorithm="none")
    response = await client.get("/auth/me", headers=bearer(unsigned))
    assert response.status_code == 401
    assert response.json()["code"] == "TOKEN_INVALID"


# --------------------------------------------------------------------------- #
# Refresh
# --------------------------------------------------------------------------- #


async def test_refresh_rotates_the_pair(client: AsyncClient, super_admin: str) -> None:
    first = await login(client, super_admin)

    response = await client.post("/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert response.status_code == 200, response.text
    second = response.json()["data"]

    assert second["refresh_token"] != first["refresh_token"]
    me = await client.get("/auth/me", headers=bearer(second["access_token"]))
    assert me.status_code == 200


async def test_reusing_a_refresh_token_revokes_the_family(
    client: AsyncClient, super_admin: str
) -> None:
    first = await login(client, super_admin)
    rotated = (
        await client.post("/auth/refresh", json={"refresh_token": first["refresh_token"]})
    ).json()["data"]

    replay = await client.post("/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert replay.status_code == 401
    assert replay.json()["code"] == "TOKEN_REVOKED"

    # The legitimate successor dies with it: we cannot tell who holds which copy.
    successor = await client.post(
        "/auth/refresh", json={"refresh_token": rotated["refresh_token"]}
    )
    assert successor.status_code == 401
    assert successor.json()["code"] == "TOKEN_REVOKED"


async def test_reuse_does_not_touch_other_sign_ins(
    client: AsyncClient, super_admin: str
) -> None:
    laptop = await login(client, super_admin)
    phone = await login(client, super_admin)

    await client.post("/auth/refresh", json={"refresh_token": laptop["refresh_token"]})
    await client.post("/auth/refresh", json={"refresh_token": laptop["refresh_token"]})

    response = await client.post("/auth/refresh", json={"refresh_token": phone["refresh_token"]})
    assert response.status_code == 200


async def test_an_access_token_cannot_refresh(client: AsyncClient, super_admin: str) -> None:
    pair = await login(client, super_admin)
    response = await client.post("/auth/refresh", json={"refresh_token": pair["access_token"]})
    assert response.status_code == 401
    assert response.json()["code"] == "TOKEN_INVALID"


async def test_refresh_refuses_a_disabled_user(
    client: AsyncClient, society_a: SocietyFixture
) -> None:
    from sqlalchemy import update

    from app.database.central import central_session
    from app.models.central import PlatformUser

    pair = await login(client, society_a.admin_token)
    async with central_session() as session:
        await session.execute(
            update(PlatformUser)
            .where(PlatformUser.email == society_a.admin_email)
            .values(is_active=False)
        )
    try:
        response = await client.post(
            "/auth/refresh", json={"refresh_token": pair["refresh_token"]}
        )
        assert response.status_code == 403
        assert response.json()["code"] == "USER_DISABLED"
    finally:
        async with central_session() as session:
            await session.execute(
                update(PlatformUser)
                .where(PlatformUser.email == society_a.admin_email)
                .values(is_active=True)
            )


# --------------------------------------------------------------------------- #
# Logout
# --------------------------------------------------------------------------- #


async def test_logout_ends_the_session(client: AsyncClient, super_admin: str) -> None:
    pair = await login(client, super_admin)

    response = await client.post("/auth/logout", json={"refresh_token": pair["refresh_token"]})
    assert response.status_code == 200
    assert response.json()["data"]["signed_out"] is True

    after = await client.post("/auth/refresh", json={"refresh_token": pair["refresh_token"]})
    assert after.status_code == 401
    assert after.json()["code"] == "TOKEN_REVOKED"


async def test_logout_with_garbage_still_succeeds(client: AsyncClient) -> None:
    response = await client.post("/auth/logout", json={"refresh_token": "garbage"})
    assert response.status_code == 200


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #


def _settings_env(**overrides: str) -> dict[str, str]:
    return {
        "CENTRAL_DATABASE_URL": "postgresql+psycopg://u:p@localhost:5432/db",
        "TENANT_DB_USER": "u",
        "TENANT_DB_PASSWORD": "p",
        "AUTH_PROVIDER": "dev",
        **overrides,
    }


async def test_a_signing_key_is_required_outside_development() -> None:
    import os
    from unittest import mock

    from pydantic import ValidationError

    from app.core.config import Settings

    env = _settings_env(ENVIRONMENT="staging")
    with mock.patch.dict(os.environ, env, clear=False):
        os.environ.pop("JWT_SECRET_KEY", None)
        with pytest.raises(ValidationError, match="JWT_SECRET_KEY is required"):
            Settings(_env_file=None)  # type: ignore[call-arg]


async def test_a_short_signing_key_is_refused() -> None:
    import os
    from unittest import mock

    from pydantic import ValidationError

    from app.core.config import Settings

    env = _settings_env(ENVIRONMENT="development", JWT_SECRET_KEY="short")
    with mock.patch.dict(os.environ, env, clear=False):
        with pytest.raises(ValidationError, match="at least 32 characters"):
            Settings(_env_file=None)  # type: ignore[call-arg]
