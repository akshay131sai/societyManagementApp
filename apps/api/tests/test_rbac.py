"""RBAC — matrix integrity and enforcement."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from app.core.permissions import (
    ROLE_PERMISSIONS,
    TENANT_PERMISSIONS,
    TENANT_ROLES,
    Permission,
    Role,
    is_owner_scoped,
    permissions_for_roles,
)
from tests.conftest import SocietyFixture, auth


# --------------------------------------------------------------------------- #
# The matrix itself
# --------------------------------------------------------------------------- #


def test_every_role_has_a_permission_set() -> None:
    for role in Role:
        assert role in ROLE_PERMISSIONS, f"{role} has no entry in ROLE_PERMISSIONS"


def test_super_admin_holds_only_platform_permissions() -> None:
    perms = ROLE_PERMISSIONS[Role.SUPER_ADMIN]
    assert perms, "SUPER_ADMIN must hold platform permissions"
    assert all(p.resource == "platform" for p in perms)


def test_no_tenant_role_holds_a_platform_permission() -> None:
    """A tenant role must never be able to act on the platform."""
    for role in TENANT_ROLES:
        offending = {p for p in ROLE_PERMISSIONS[role] if p.resource == "platform"}
        assert not offending, f"{role} holds platform permissions: {offending}"


def test_society_admin_covers_all_tenant_permissions_except_task_progress() -> None:
    perms = ROLE_PERMISSIONS[Role.SOCIETY_ADMIN]
    expected = set(TENANT_PERMISSIONS) - {
        Permission.MAINTENANCE_TASK_PROGRESS,
        Permission.HOUSEKEEPING_TASK_PROGRESS,
    }
    assert perms == expected


def test_flat_owner_cannot_manage_the_society() -> None:
    perms = ROLE_PERMISSIONS[Role.FLAT_OWNER]
    forbidden = {
        Permission.THEME_UPDATE,
        Permission.SOCIETY_UPDATE,
        Permission.SOCIETY_SETTINGS_MANAGE,
        Permission.USER_CREATE,
        Permission.ROLE_ASSIGN,
        Permission.BILLING_PUBLISH,
        Permission.BILLING_MANAGE_TEMPLATE,
        Permission.BILLING_READ_ALL,
        Permission.FLAT_MANAGE,
        Permission.AUDIT_READ,
        # Structure reads serve the management screen, not a resident.
        Permission.BUILDING_READ,
        Permission.BLOCK_READ,
        Permission.FLOOR_READ,
    }
    assert not (perms & forbidden)


def test_family_tiers_narrow_as_they_descend() -> None:
    """CO_ADMIN >= MEMBER >= CHILD, with no tier gaining anything on the way down."""
    co_admin = ROLE_PERMISSIONS[Role.FLAT_CO_ADMIN]
    member = ROLE_PERMISSIONS[Role.FLAT_MEMBER]
    child = ROLE_PERMISSIONS[Role.FLAT_CHILD]

    assert child < member < co_admin


def test_flat_co_admin_matches_the_flat_owner() -> None:
    """A co-admin runs the flat. The two are separated by which residents row
    is primary, not by what they may do."""
    assert ROLE_PERMISSIONS[Role.FLAT_CO_ADMIN] == ROLE_PERMISSIONS[Role.FLAT_OWNER]


def test_restricted_family_member_sees_no_money_and_no_meters() -> None:
    perms = ROLE_PERMISSIONS[Role.FLAT_CHILD]
    assert not any(p.resource in {"billing", "payment"} for p in perms)
    assert not (perms & {Permission.WATER_READ, Permission.ELECTRICITY_READ})


def test_family_member_can_read_the_flat_but_not_change_it() -> None:
    perms = ROLE_PERMISSIONS[Role.FLAT_MEMBER]
    assert Permission.BILLING_READ in perms
    assert not any(p.action.startswith("manage") for p in perms)
    assert Permission.VISITOR_APPROVE not in perms, (
        "deciding who may walk in belongs to the flat admin"
    )


def test_only_flat_runners_manage_the_household() -> None:
    for role in (Role.FLAT_OWNER, Role.FLAT_CO_ADMIN, Role.SOCIETY_ADMIN):
        assert Permission.FAMILY_MANAGE in ROLE_PERMISSIONS[role]
    for role in (Role.FLAT_MEMBER, Role.FLAT_CHILD, Role.SECURITY, Role.MAINTENANCE):
        assert Permission.FAMILY_MANAGE not in ROLE_PERMISSIONS[role]


def test_family_manage_is_owner_scoped_for_a_resident_but_not_an_admin() -> None:
    assert is_owner_scoped(Permission.FAMILY_MANAGE, ROLE_PERMISSIONS[Role.FLAT_OWNER]) is True
    assert (
        is_owner_scoped(Permission.FAMILY_MANAGE, ROLE_PERMISSIONS[Role.SOCIETY_ADMIN]) is False
    ), "resident.manage must lift the owner scope"


def test_every_access_level_maps_to_a_role() -> None:
    from app.core.permissions import ACCESS_LEVEL_ROLES
    from app.models.tenant import FamilyAccessLevel

    grantable = {level.value for level in FamilyAccessLevel} - {FamilyAccessLevel.NONE.value}
    assert set(ACCESS_LEVEL_ROLES) == grantable
    for role in ACCESS_LEVEL_ROLES.values():
        assert role in ROLE_PERMISSIONS


def test_security_guard_cannot_see_money() -> None:
    perms = ROLE_PERMISSIONS[Role.SECURITY]
    assert not (
        perms
        & {
            Permission.BILLING_READ,
            Permission.PAYMENT_READ,
            Permission.WATER_READ,
            Permission.ELECTRICITY_READ,
        }
    )


def test_field_staff_cannot_manage_their_own_module() -> None:
    assert Permission.MAINTENANCE_MANAGE not in ROLE_PERMISSIONS[Role.MAINTENANCE]
    assert Permission.HOUSEKEEPING_MANAGE not in ROLE_PERMISSIONS[Role.HOUSEKEEPER]


def test_permission_codes_are_well_formed() -> None:
    for permission in Permission:
        assert "." in permission.value
        assert permission.value == f"{permission.resource}.{permission.action}"
        assert permission.value.islower() or "_" in permission.value


def test_permissions_for_roles_unions() -> None:
    combined = permissions_for_roles({Role.MAINTENANCE, Role.HOUSEKEEPER})
    assert combined == ROLE_PERMISSIONS[Role.MAINTENANCE] | ROLE_PERMISSIONS[Role.HOUSEKEEPER]


def test_owner_scope_lifts_with_a_broadening_permission() -> None:
    resident = ROLE_PERMISSIONS[Role.FLAT_OWNER]
    admin = ROLE_PERMISSIONS[Role.SOCIETY_ADMIN]

    assert is_owner_scoped(Permission.BILLING_READ, resident) is True
    assert is_owner_scoped(Permission.BILLING_READ, admin) is False, (
        "billing.read_all must lift the owner scope"
    )
    assert is_owner_scoped(Permission.THEME_READ, resident) is False


# --------------------------------------------------------------------------- #
# Seeded database matches the code
# --------------------------------------------------------------------------- #


async def test_seeded_matrix_matches_code(
    client: AsyncClient, society_a: SocietyFixture
) -> None:
    """The tenant tables and ROLE_PERMISSIONS must not silently diverge."""
    response = await client.get("/roles", headers=auth(society_a.admin_token))
    assert response.status_code == 200
    seeded = {r["code"]: set(r["permissions"]) for r in response.json()["data"]}

    assert set(seeded) == {r.value for r in TENANT_ROLES}

    for role in TENANT_ROLES:
        expected = {p.value for p in ROLE_PERMISSIONS[role]}
        assert seeded[role.value] == expected, f"{role.value} drifted from the code"


async def test_seeded_roles_are_system_roles(
    client: AsyncClient, society_a: SocietyFixture
) -> None:
    response = await client.get("/roles", headers=auth(society_a.admin_token))
    assert all(r["is_system"] for r in response.json()["data"])


# --------------------------------------------------------------------------- #
# Enforcement
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def resident_email() -> str:
    return f"resident-{uuid.uuid4().hex[:8]}@test.nestflow.in"


async def test_flat_owner_is_denied_admin_actions(
    client: AsyncClient, society_a: SocietyFixture, resident_email: str
) -> None:
    created = await client.post(
        "/users",
        headers=auth(society_a.admin_token),
        json={
            "email": resident_email,
            "full_name": "Test Resident",
            "role_codes": ["FLAT_OWNER"],
        },
    )
    assert created.status_code == 201, created.text
    token = f"dev:{resident_email}"

    me = await client.get("/auth/me", headers=auth(token))
    assert me.json()["data"]["principal"]["roles"] == ["FLAT_OWNER"]

    denied = [
        ("put", "/theme", {"primary_color": "#000000"}),
        ("put", "/society/settings", {"society_name": "nope"}),
        ("get", "/users", None),
        ("get", "/roles", None),
    ]
    for method, path, body in denied:
        response = await getattr(client, method)(
            path, headers=auth(token), **({"json": body} if body else {})
        )
        assert response.status_code == 403, f"{method} {path}"
        assert response.json()["code"] == "PERMISSION_DENIED"


async def test_unknown_role_is_rejected(
    client: AsyncClient, society_a: SocietyFixture
) -> None:
    response = await client.post(
        "/users",
        headers=auth(society_a.admin_token),
        json={
            "email": f"bad-{uuid.uuid4().hex[:6]}@test.nestflow.in",
            "full_name": "Bad Role",
            "role_codes": ["NOT_A_ROLE"],
        },
    )
    assert response.status_code == 422
    assert "NOT_A_ROLE" in response.json()["message"]


async def test_super_admin_role_cannot_be_assigned_in_a_society(
    client: AsyncClient, society_a: SocietyFixture
) -> None:
    """Privilege escalation from inside a tenant must be impossible."""
    response = await client.post(
        "/users",
        headers=auth(society_a.admin_token),
        json={
            "email": f"escalate-{uuid.uuid4().hex[:6]}@test.nestflow.in",
            "full_name": "Escalation Attempt",
            "role_codes": ["SUPER_ADMIN"],
        },
    )
    assert response.status_code == 422
    assert "platform role" in response.json()["message"]


async def test_last_society_admin_cannot_demote_themselves(
    client: AsyncClient, society_a: SocietyFixture
) -> None:
    me = (await client.get("/auth/me", headers=auth(society_a.admin_token))).json()
    tenant_user_id = me["data"]["principal"]["tenant_user_id"]

    response = await client.put(
        f"/users/{tenant_user_id}/roles",
        headers=auth(society_a.admin_token),
        json={"role_codes": ["FLAT_OWNER"]},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "CONFLICT"
