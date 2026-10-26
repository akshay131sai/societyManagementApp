"""Email-and-password sign-in (``AUTH_PROVIDER=password``)."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from tests.conftest import SocietyFixture, auth

pytestmark = pytest.mark.asyncio

GOOD = "Correct-horse-42"


# --------------------------------------------------------------------------- #
# Hashing and policy
# --------------------------------------------------------------------------- #


async def test_a_hash_verifies_only_its_own_password() -> None:
    from app.auth.passwords import hash_password, verify_password

    stored = hash_password(GOOD)
    assert stored.startswith("scrypt$")
    assert GOOD not in stored
    assert verify_password(GOOD, stored)
    assert not verify_password(GOOD + "x", stored)


async def test_two_hashes_of_one_password_differ() -> None:
    from app.auth.passwords import hash_password

    assert hash_password(GOOD) != hash_password(GOOD), "every hash must be salted"


async def test_a_missing_or_malformed_hash_never_matches() -> None:
    from app.auth.passwords import verify_password

    for stored in (None, "", "plain-text", "scrypt$1$2", "bcrypt$x$y$z$a$b"):
        assert not verify_password(GOOD, stored)


@pytest.mark.parametrize(
    ("password", "fine"),
    [("short1", False), ("lettersonly", False), ("1234567890", False), ("abcdefg1", True)],
)
async def test_password_policy(password: str, fine: bool) -> None:
    from app.auth.passwords import password_problem

    assert (password_problem(password) is None) is fine


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


async def _platform_user_id(client: AsyncClient, super_admin: str, email: str) -> str:
    response = await client.get("/platform/users", headers=auth(super_admin), params={"q": email})
    items = [u for u in response.json()["data"]["items"] if u["email"] == email]
    assert items, f"no platform user {email}"
    return str(items[0]["id"])


async def _set_platform_password(
    client: AsyncClient, super_admin: str, email: str, password: str
) -> None:
    user_id = await _platform_user_id(client, super_admin, email)
    response = await client.post(
        f"/platform/users/{user_id}/password",
        headers=auth(super_admin),
        json={"password": password},
    )
    assert response.status_code == 200, response.text


async def _login(client: AsyncClient, email: str, password: str):  # type: ignore[no-untyped-def]
    return await client.post("/auth/login", json={"email": email, "password": password})


async def _new_society_user(
    client: AsyncClient, society: SocietyFixture, password: str | None = GOOD
) -> dict[str, str]:
    email = f"guard-{uuid.uuid4().hex[:8]}@test.nestflow.in"
    body: dict[str, object] = {
        "email": email,
        "full_name": "Password Guard",
        "role_codes": ["SECURITY"],
    }
    if password is not None:
        body["password"] = password
    response = await client.post("/users", headers=auth(society.admin_token), json=body)
    assert response.status_code == 201, response.text
    return {"id": response.json()["data"]["id"], "email": email}


# --------------------------------------------------------------------------- #
# Login
# --------------------------------------------------------------------------- #


async def test_login_with_the_right_password(
    client: AsyncClient, super_admin: str, society_a: SocietyFixture, password_mode: None
) -> None:
    await _set_platform_password(client, super_admin, society_a.admin_email, GOOD)

    response = await _login(client, society_a.admin_email, GOOD)
    assert response.status_code == 200, response.text
    access = response.json()["data"]["access_token"]

    me = await client.get("/auth/me", headers={"Authorization": f"Bearer {access}"})
    assert me.json()["data"]["principal"]["email"] == society_a.admin_email
    assert me.json()["data"]["auth_provider"] == "password"


async def test_email_is_case_insensitive(
    client: AsyncClient, super_admin: str, society_a: SocietyFixture, password_mode: None
) -> None:
    await _set_platform_password(client, super_admin, society_a.admin_email, GOOD)
    response = await _login(client, f"  {society_a.admin_email.upper()} ", GOOD)
    assert response.status_code == 200


async def test_wrong_password_unknown_email_and_no_password_look_the_same(
    client: AsyncClient, super_admin: str, society_a: SocietyFixture, password_mode: None
) -> None:
    await _set_platform_password(client, super_admin, society_a.admin_email, GOOD)
    no_password = await _new_society_user(client, society_a, password=None)

    attempts = [
        (society_a.admin_email, GOOD + "-wrong"),
        ("nobody@nowhere.example", GOOD),
        (no_password["email"], GOOD),
    ]
    bodies = []
    for email, password in attempts:
        response = await _login(client, email, password)
        assert response.status_code == 401, email
        bodies.append((response.json()["code"], response.json()["message"]))
    assert len(set(bodies)) == 1, "the response must not reveal which part was wrong"
    assert bodies[0][0] == "INVALID_CREDENTIALS"


async def test_a_disabled_account_cannot_sign_in(
    client: AsyncClient, society_a: SocietyFixture, password_mode: None
) -> None:
    user = await _new_society_user(client, society_a)
    await client.delete(f"/users/{user['id']}", headers=auth(society_a.admin_token))

    from sqlalchemy import update

    from app.database.central import central_session
    from app.models.central import PlatformUser

    async with central_session() as session:
        await session.execute(
            update(PlatformUser).where(PlatformUser.email == user["email"]).values(is_active=False)
        )

    response = await _login(client, user["email"], GOOD)
    assert response.status_code == 403
    assert response.json()["code"] == "USER_DISABLED"


async def test_password_mode_refuses_identity_tokens(
    client: AsyncClient, super_admin: str, password_mode: None
) -> None:
    response = await client.post("/auth/login", json={"id_token": super_admin})
    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_CREDENTIALS"


async def test_dev_mode_refuses_passwords(client: AsyncClient, society_a: SocietyFixture) -> None:
    """Outside password mode an email and password is not a way in."""
    response = await _login(client, society_a.admin_email, GOOD)
    assert response.status_code == 401
    assert response.json()["code"] == "TOKEN_INVALID"


async def test_passwords_never_appear_in_responses(
    client: AsyncClient, society_a: SocietyFixture
) -> None:
    user = await _new_society_user(client, society_a)
    detail = await client.get(f"/users/{user['id']}", headers=auth(society_a.admin_token))
    text = detail.text
    assert GOOD not in text
    assert "password_hash" not in text and "scrypt$" not in text


# --------------------------------------------------------------------------- #
# Setting passwords
# --------------------------------------------------------------------------- #


async def test_a_user_created_with_a_password_can_sign_in(
    client: AsyncClient, society_a: SocietyFixture, password_mode: None
) -> None:
    user = await _new_society_user(client, society_a)
    response = await _login(client, user["email"], GOOD)
    assert response.status_code == 200, response.text


async def test_a_weak_password_is_refused_at_creation(
    client: AsyncClient, society_a: SocietyFixture
) -> None:
    response = await client.post(
        "/users",
        headers=auth(society_a.admin_token),
        json={
            "email": f"weak-{uuid.uuid4().hex[:8]}@test.nestflow.in",
            "full_name": "Weak Password",
            "role_codes": ["SECURITY"],
            "password": "password",
        },
    )
    assert response.status_code == 422


async def test_admin_reset_replaces_the_password_and_ends_sessions(
    client: AsyncClient, society_a: SocietyFixture, password_mode: None
) -> None:
    user = await _new_society_user(client, society_a)
    session = (await _login(client, user["email"], GOOD)).json()["data"]

    response = await client.post(
        f"/users/{user['id']}/password",
        headers=auth(society_a.admin_token),
        json={"password": "Brand-new-77"},
    )
    assert response.status_code == 200, response.text

    assert (await _login(client, user["email"], GOOD)).status_code == 401
    assert (await _login(client, user["email"], "Brand-new-77")).status_code == 200

    refresh = await client.post(
        "/auth/refresh", json={"refresh_token": session["refresh_token"]}
    )
    assert refresh.status_code == 401, "a reset must sign the user out everywhere"


async def test_an_admin_cannot_reset_another_societys_user(
    client: AsyncClient, society_a: SocietyFixture, society_b: SocietyFixture
) -> None:
    user = await _new_society_user(client, society_b)
    response = await client.post(
        f"/users/{user['id']}/password",
        headers=auth(society_a.admin_token),
        json={"password": "Brand-new-77"},
    )
    assert response.status_code == 404


async def test_staff_cannot_reset_passwords(
    client: AsyncClient, society_a: SocietyFixture, password_mode: None
) -> None:
    staff = await _new_society_user(client, society_a)
    victim = await _new_society_user(client, society_a)
    response = await client.post(
        f"/users/{victim['id']}/password",
        headers=auth(f"dev:{staff['email']}"),
        json={"password": "Brand-new-77"},
    )
    assert response.status_code == 403


async def test_changing_your_own_password(
    client: AsyncClient, society_a: SocietyFixture, password_mode: None
) -> None:
    user = await _new_society_user(client, society_a)
    first = (await _login(client, user["email"], GOOD)).json()["data"]
    bearer = {"Authorization": f"Bearer {first['access_token']}"}

    wrong = await client.post(
        "/auth/password",
        headers=bearer,
        json={"current_password": "not-it-1", "new_password": "Brand-new-77"},
    )
    assert wrong.status_code == 422
    assert wrong.json()["details"]["fields"][0]["field"] == "current_password"

    weak = await client.post(
        "/auth/password",
        headers=bearer,
        json={"current_password": GOOD, "new_password": "short"},
    )
    assert weak.status_code == 422

    changed = await client.post(
        "/auth/password",
        headers=bearer,
        json={"current_password": GOOD, "new_password": "Brand-new-77"},
    )
    assert changed.status_code == 200, changed.text
    fresh = changed.json()["data"]

    assert (await _login(client, user["email"], GOOD)).status_code == 401
    assert (await _login(client, user["email"], "Brand-new-77")).status_code == 200

    # Other sessions end; the device that made the change keeps a fresh one.
    old = await client.post("/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert old.status_code == 401
    kept = await client.post("/auth/refresh", json={"refresh_token": fresh["refresh_token"]})
    assert kept.status_code == 200
