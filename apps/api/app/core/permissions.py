"""RBAC definitions — the single source of truth.

Permissions are a closed enum, so a typo is an ``AttributeError`` at import
rather than a silent authorization hole. Roles map to permission sets here; the
mapping is *seeded* into each tenant database at provisioning and read from the
tables at runtime, which is what makes per-society custom roles possible later
without changing this default.

``tests/test_rbac.py::test_seeded_matrix_matches_code`` asserts the seeded
tables equal this module for a freshly provisioned society, so the database and
this file cannot silently diverge.

See docs/architecture/rbac.md for the human-readable matrix.
"""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    SUPER_ADMIN = "SUPER_ADMIN"
    SOCIETY_ADMIN = "SOCIETY_ADMIN"
    FLAT_OWNER = "FLAT_OWNER"
    FLAT_CO_ADMIN = "FLAT_CO_ADMIN"
    FLAT_MEMBER = "FLAT_MEMBER"
    FLAT_CHILD = "FLAT_CHILD"
    MAINTENANCE_ADMIN = "MAINTENANCE_ADMIN"
    MAINTENANCE = "MAINTENANCE"
    HOUSEKEEPER_ADMIN = "HOUSEKEEPER_ADMIN"
    HOUSEKEEPER = "HOUSEKEEPER"
    SECURITY_ADMIN = "SECURITY_ADMIN"
    SECURITY = "SECURITY"


ROLE_LABELS: dict[Role, str] = {
    Role.SUPER_ADMIN: "Platform Super Admin",
    Role.SOCIETY_ADMIN: "Society Admin",
    Role.FLAT_OWNER: "Flat Owner",
    Role.FLAT_CO_ADMIN: "Flat Co-Admin",
    Role.FLAT_MEMBER: "Family Member",
    Role.FLAT_CHILD: "Family Member (Restricted)",
    Role.MAINTENANCE_ADMIN: "Maintenance Admin",
    Role.MAINTENANCE: "Maintenance Staff",
    Role.HOUSEKEEPER_ADMIN: "Housekeeping Admin",
    Role.HOUSEKEEPER: "Housekeeping Staff",
    Role.SECURITY_ADMIN: "Security Admin",
    Role.SECURITY: "Security Guard",
}

TENANT_ROLES: frozenset[Role] = frozenset(Role) - {Role.SUPER_ADMIN}
"""Roles that live inside a tenant database. SUPER_ADMIN is platform-only."""


class Permission(StrEnum):
    # --- Platform (central DB, SUPER_ADMIN only) -----------------------------
    PLATFORM_SOCIETY_READ = "platform.society.read"
    PLATFORM_SOCIETY_CREATE = "platform.society.create"
    PLATFORM_SOCIETY_UPDATE = "platform.society.update"
    PLATFORM_SOCIETY_LOCK = "platform.society.lock"
    PLATFORM_SOCIETY_UNLOCK = "platform.society.unlock"
    PLATFORM_SOCIETY_ARCHIVE = "platform.society.archive"
    PLATFORM_USER_READ = "platform.user.read"
    PLATFORM_USER_CREATE = "platform.user.create"
    PLATFORM_USER_UPDATE = "platform.user.update"
    PLATFORM_USER_DISABLE = "platform.user.disable"
    PLATFORM_PLAN_READ = "platform.plan.read"
    PLATFORM_PLAN_CREATE = "platform.plan.create"
    PLATFORM_PLAN_UPDATE = "platform.plan.update"
    PLATFORM_SUBSCRIPTION_READ = "platform.subscription.read"
    PLATFORM_SUBSCRIPTION_ASSIGN = "platform.subscription.assign"
    PLATFORM_SUBSCRIPTION_EXTEND = "platform.subscription.extend"
    PLATFORM_SUBSCRIPTION_SUSPEND = "platform.subscription.suspend"
    PLATFORM_AUDIT_READ = "platform.audit.read"

    # --- Society -------------------------------------------------------------
    SOCIETY_READ = "society.read"
    SOCIETY_UPDATE = "society.update"
    SOCIETY_SETTINGS_MANAGE = "society.settings.manage"
    THEME_READ = "theme.read"
    THEME_UPDATE = "theme.update"

    # --- Structure -----------------------------------------------------------
    BUILDING_READ = "building.read"
    BUILDING_MANAGE = "building.manage"
    BLOCK_READ = "block.read"
    BLOCK_MANAGE = "block.manage"
    FLOOR_READ = "floor.read"
    FLOOR_MANAGE = "floor.manage"
    FLAT_READ = "flat.read"
    FLAT_MANAGE = "flat.manage"
    RESIDENT_READ = "resident.read"
    RESIDENT_MANAGE = "resident.manage"
    FAMILY_MANAGE = "family.manage"

    # --- Users ---------------------------------------------------------------
    USER_READ = "user.read"
    USER_CREATE = "user.create"
    USER_UPDATE = "user.update"
    USER_DELETE = "user.delete"
    ROLE_ASSIGN = "role.assign"

    # --- Billing -------------------------------------------------------------
    BILLING_READ = "billing.read"
    BILLING_READ_ALL = "billing.read_all"
    BILLING_CREATE = "billing.create"
    BILLING_UPDATE = "billing.update"
    BILLING_PUBLISH = "billing.publish"
    BILLING_MANAGE_TEMPLATE = "billing.manage_template"

    # --- Utilities -----------------------------------------------------------
    WATER_READ = "water.read"
    WATER_MANAGE = "water.manage"
    ELECTRICITY_READ = "electricity.read"
    ELECTRICITY_MANAGE = "electricity.manage"

    # --- Assets --------------------------------------------------------------
    PARKING_READ = "parking.read"
    PARKING_MANAGE = "parking.manage"
    VEHICLE_READ = "vehicle.read"
    VEHICLE_MANAGE = "vehicle.manage"
    PET_READ = "pet.read"
    PET_MANAGE = "pet.manage"

    # --- Operations ----------------------------------------------------------
    COMPLAINT_READ = "complaint.read"
    COMPLAINT_CREATE = "complaint.create"
    COMPLAINT_MANAGE = "complaint.manage"
    MAINTENANCE_READ = "maintenance.read"
    MAINTENANCE_MANAGE = "maintenance.manage"
    MAINTENANCE_TASK_PROGRESS = "maintenance.task.progress"
    HOUSEKEEPING_READ = "housekeeping.read"
    HOUSEKEEPING_MANAGE = "housekeeping.manage"
    HOUSEKEEPING_TASK_PROGRESS = "housekeeping.task.progress"
    SECURITY_READ = "security.read"
    SECURITY_MANAGE = "security.manage"
    VISITOR_CREATE = "visitor.create"
    VISITOR_READ = "visitor.read"
    VISITOR_APPROVE = "visitor.approve"

    # --- Community -----------------------------------------------------------
    NOTICE_READ = "notice.read"
    NOTICE_MANAGE = "notice.manage"
    AMENITY_READ = "amenity.read"
    AMENITY_BOOK = "amenity.book"
    AMENITY_MANAGE = "amenity.manage"

    # --- Money & comms -------------------------------------------------------
    PAYMENT_READ = "payment.read"
    PAYMENT_RECORD = "payment.record"
    PAYMENT_REFUND = "payment.refund"
    NOTIFICATION_READ = "notification.read"
    NOTIFICATION_SEND = "notification.send"
    REPORT_READ = "report.read"
    AUDIT_READ = "audit.read"

    # ------------------------------------------------------------------ #

    @property
    def resource(self) -> str:
        """``billing.manage_template`` -> ``billing``."""
        return self.value.split(".", 1)[0]

    @property
    def action(self) -> str:
        """``billing.manage_template`` -> ``manage_template``."""
        return self.value.split(".", 1)[1]


PERMISSION_DESCRIPTIONS: dict[Permission, str] = {
    Permission.PLATFORM_SOCIETY_CREATE: "Create and provision a new society",
    Permission.PLATFORM_SOCIETY_LOCK: "Lock a society, blocking all access",
    Permission.BILLING_READ: "View bills (own flats only unless billing.read_all)",
    Permission.BILLING_READ_ALL: "View bills for every flat in the society",
    Permission.BILLING_PUBLISH: "Publish a billing run — irreversible",
    Permission.BILLING_MANAGE_TEMPLATE: "Create and version bill templates",
    Permission.THEME_UPDATE: "Change the society's appearance",
    Permission.ROLE_ASSIGN: "Assign roles to society users",
    Permission.VISITOR_APPROVE: "Approve a visitor's entry",
    Permission.FAMILY_MANAGE: (
        "Manage the household roster of your own flat, and grant or revoke "
        "family logins (own flat only unless resident.manage)"
    ),
}


# --------------------------------------------------------------------------- #
# Role -> permission matrix
# --------------------------------------------------------------------------- #

_PLATFORM_PERMISSIONS: frozenset[Permission] = frozenset(
    p for p in Permission if p.resource == "platform"
)

_SOCIETY_ADMIN_PERMISSIONS: frozenset[Permission] = frozenset(
    p for p in Permission if p.resource != "platform"
) - {
    # Society Admin oversees but does not personally progress a worker's task —
    # that grant belongs to the worker roles, so "who completed it" stays honest.
    Permission.MAINTENANCE_TASK_PROGRESS,
    Permission.HOUSEKEEPING_TASK_PROGRESS,
}

_READ_ONLY_COMMON: frozenset[Permission] = frozenset(
    {
        Permission.SOCIETY_READ,
        Permission.THEME_READ,
        Permission.NOTICE_READ,
        Permission.NOTIFICATION_READ,
    }
)

# --- Resident ------------------------------------------------------------- #
# A resident does not get building/block/floor read: those exist to serve the
# Structure management screen, and a flat already carries its building, block
# and floor names denormalised. Least privilege, and it keeps a management
# screen out of a resident's navigation.
_FLAT_OWNER_PERMISSIONS: frozenset[Permission] = _READ_ONLY_COMMON | {
    Permission.FLAT_READ,
    Permission.RESIDENT_READ,
    Permission.FAMILY_MANAGE,
    Permission.BILLING_READ,
    Permission.WATER_READ,
    Permission.ELECTRICITY_READ,
    Permission.PARKING_READ,
    Permission.VEHICLE_READ,
    Permission.VEHICLE_MANAGE,
    Permission.PET_READ,
    Permission.PET_MANAGE,
    Permission.COMPLAINT_CREATE,
    Permission.COMPLAINT_READ,
    Permission.VISITOR_CREATE,
    Permission.VISITOR_READ,
    Permission.VISITOR_APPROVE,
    Permission.AMENITY_READ,
    Permission.AMENITY_BOOK,
    Permission.PAYMENT_READ,
    Permission.PAYMENT_RECORD,
}

_FLAT_MEMBER_PERMISSIONS: frozenset[Permission] = _READ_ONLY_COMMON | {
    # An adult in the household: sees the whole flat, changes nothing about it.
    # No *_MANAGE, and no visitor.approve — deciding who may walk in stays with
    # the flat admin and their co-admin.
    Permission.FLAT_READ,
    Permission.RESIDENT_READ,
    Permission.BILLING_READ,
    Permission.PAYMENT_READ,
    Permission.WATER_READ,
    Permission.ELECTRICITY_READ,
    Permission.PARKING_READ,
    Permission.VEHICLE_READ,
    Permission.PET_READ,
    Permission.COMPLAINT_CREATE,
    Permission.COMPLAINT_READ,
    Permission.VISITOR_CREATE,
    Permission.VISITOR_READ,
    Permission.AMENITY_READ,
    Permission.AMENITY_BOOK,
}

_FLAT_CHILD_PERMISSIONS: frozenset[Permission] = _READ_ONLY_COMMON | {
    # Deliberately no money and no meters: a restricted member can see who is
    # visiting and what the society has announced, and can report a problem,
    # but the flat's finances are not theirs to read.
    Permission.FLAT_READ,
    Permission.RESIDENT_READ,
    Permission.COMPLAINT_CREATE,
    Permission.COMPLAINT_READ,
    Permission.VISITOR_READ,
    Permission.AMENITY_READ,
}

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.SUPER_ADMIN: _PLATFORM_PERMISSIONS,
    Role.SOCIETY_ADMIN: _SOCIETY_ADMIN_PERMISSIONS,
    Role.FLAT_OWNER: _FLAT_OWNER_PERMISSIONS,
    # A spouse who runs the flat's app account. Identical to the flat admin;
    # the two are separated by *which* row is primary in `residents`, not by
    # what they may do.
    Role.FLAT_CO_ADMIN: _FLAT_OWNER_PERMISSIONS,
    Role.FLAT_MEMBER: _FLAT_MEMBER_PERMISSIONS,
    Role.FLAT_CHILD: _FLAT_CHILD_PERMISSIONS,
    # --- Maintenance ------------------------------------------------------
    Role.MAINTENANCE_ADMIN: _READ_ONLY_COMMON
    | {
        Permission.BUILDING_READ,
        Permission.BLOCK_READ,
        Permission.FLOOR_READ,
        Permission.FLAT_READ,
        Permission.USER_READ,
        Permission.WATER_MANAGE,
        Permission.WATER_READ,
        Permission.ELECTRICITY_MANAGE,
        Permission.ELECTRICITY_READ,
        Permission.COMPLAINT_READ,
        Permission.COMPLAINT_CREATE,
        Permission.COMPLAINT_MANAGE,
        Permission.MAINTENANCE_READ,
        Permission.MAINTENANCE_MANAGE,
        Permission.MAINTENANCE_TASK_PROGRESS,
        Permission.NOTIFICATION_SEND,
        Permission.REPORT_READ,
    },
    Role.MAINTENANCE: _READ_ONLY_COMMON
    | {
        Permission.COMPLAINT_READ,
        Permission.MAINTENANCE_READ,
        Permission.MAINTENANCE_TASK_PROGRESS,
    },
    # --- Housekeeping -----------------------------------------------------
    Role.HOUSEKEEPER_ADMIN: _READ_ONLY_COMMON
    | {
        Permission.BUILDING_READ,
        Permission.BLOCK_READ,
        Permission.FLOOR_READ,
        Permission.FLAT_READ,
        Permission.USER_READ,
        Permission.COMPLAINT_READ,
        Permission.COMPLAINT_CREATE,
        Permission.COMPLAINT_MANAGE,
        Permission.HOUSEKEEPING_READ,
        Permission.HOUSEKEEPING_MANAGE,
        Permission.HOUSEKEEPING_TASK_PROGRESS,
        Permission.NOTIFICATION_SEND,
        Permission.REPORT_READ,
    },
    Role.HOUSEKEEPER: _READ_ONLY_COMMON
    | {
        Permission.HOUSEKEEPING_READ,
        Permission.HOUSEKEEPING_TASK_PROGRESS,
    },
    # --- Security ---------------------------------------------------------
    Role.SECURITY_ADMIN: _READ_ONLY_COMMON
    | {
        Permission.BUILDING_READ,
        Permission.BLOCK_READ,
        Permission.FLOOR_READ,
        Permission.FLAT_READ,
        Permission.RESIDENT_READ,
        Permission.USER_READ,
        Permission.PARKING_READ,
        Permission.VEHICLE_READ,
        Permission.COMPLAINT_CREATE,
        Permission.COMPLAINT_READ,
        Permission.SECURITY_READ,
        Permission.SECURITY_MANAGE,
        Permission.VISITOR_CREATE,
        Permission.VISITOR_READ,
        Permission.VISITOR_APPROVE,
        Permission.NOTIFICATION_SEND,
        Permission.REPORT_READ,
    },
    Role.SECURITY: _READ_ONLY_COMMON
    | {
        Permission.FLAT_READ,
        Permission.RESIDENT_READ,
        Permission.PARKING_READ,
        Permission.VEHICLE_READ,
        Permission.SECURITY_READ,
        Permission.VISITOR_CREATE,
        Permission.VISITOR_READ,
    },
}


# --------------------------------------------------------------------------- #
# Ownership scoping
# --------------------------------------------------------------------------- #

OWNER_SCOPED_PERMISSIONS: frozenset[Permission] = frozenset(
    {
        Permission.BILLING_READ,
        Permission.WATER_READ,
        Permission.ELECTRICITY_READ,
        Permission.PARKING_READ,
        Permission.VEHICLE_READ,
        Permission.VEHICLE_MANAGE,
        Permission.PET_READ,
        Permission.PET_MANAGE,
        Permission.COMPLAINT_READ,
        Permission.VISITOR_READ,
        Permission.VISITOR_APPROVE,
        Permission.AMENITY_BOOK,
        Permission.PAYMENT_READ,
        Permission.PAYMENT_RECORD,
        Permission.RESIDENT_READ,
        Permission.FLAT_READ,
        Permission.FAMILY_MANAGE,
    }
)
"""Permissions whose reach is narrowed to the principal's own flats.

Holding one of these grants the *capability*; the service layer decides *which
rows*. A principal that also holds the matching society-wide permission
(``BILLING_READ_ALL``, ``*_MANAGE``) is not narrowed.
"""

BROADENING_PERMISSIONS: dict[Permission, frozenset[Permission]] = {
    Permission.BILLING_READ: frozenset({Permission.BILLING_READ_ALL}),
    Permission.WATER_READ: frozenset({Permission.WATER_MANAGE}),
    Permission.ELECTRICITY_READ: frozenset({Permission.ELECTRICITY_MANAGE}),
    # SECURITY_READ broadens this for the same reason it broadens flat.read
    # and vehicle.read: a guard checking a car against its slot needs the
    # allotment list, and holds no flats of their own to be scoped to.
    Permission.PARKING_READ: frozenset(
        {Permission.PARKING_MANAGE, Permission.SECURITY_READ}
    ),
    Permission.VEHICLE_READ: frozenset({Permission.VEHICLE_MANAGE, Permission.SECURITY_READ}),
    Permission.VEHICLE_MANAGE: frozenset({Permission.PARKING_MANAGE}),
    Permission.PET_READ: frozenset({Permission.PET_MANAGE}),
    Permission.PET_MANAGE: frozenset({Permission.RESIDENT_MANAGE}),
    Permission.COMPLAINT_READ: frozenset({Permission.COMPLAINT_MANAGE}),
    Permission.VISITOR_READ: frozenset({Permission.SECURITY_READ}),
    Permission.VISITOR_APPROVE: frozenset({Permission.SECURITY_MANAGE}),
    Permission.PAYMENT_READ: frozenset({Permission.PAYMENT_REFUND}),
    Permission.PAYMENT_RECORD: frozenset({Permission.PAYMENT_REFUND}),
    Permission.AMENITY_BOOK: frozenset({Permission.AMENITY_MANAGE}),
    Permission.RESIDENT_READ: frozenset({Permission.RESIDENT_MANAGE}),
    Permission.FLAT_READ: frozenset({Permission.FLAT_MANAGE, Permission.SECURITY_READ}),
    Permission.FAMILY_MANAGE: frozenset({Permission.RESIDENT_MANAGE}),
}
"""Permissions that lift the owner-scope restriction on a scoped permission."""


ACCESS_LEVEL_ROLES: dict[str, Role] = {
    "CO_ADMIN": Role.FLAT_CO_ADMIN,
    "MEMBER": Role.FLAT_MEMBER,
    "CHILD": Role.FLAT_CHILD,
}
"""``FamilyAccessLevel`` -> the tenant role granted to that family member.

Keyed by the enum's *value* rather than the member so this module stays free of
model imports. ``NONE`` is absent on purpose: it means no login, so there is no
role to grant. ``tests/test_rbac.py`` asserts the mapping covers every level
other than ``NONE``.
"""


FAMILY_ROLES: frozenset[Role] = frozenset(ACCESS_LEVEL_ROLES.values())
"""Roles that only ever reach a flat through ``family_members``."""


def permissions_for_roles(roles: frozenset[Role] | set[Role]) -> frozenset[Permission]:
    """Union of the permission sets of the given roles."""
    result: set[Permission] = set()
    for role in roles:
        result |= ROLE_PERMISSIONS.get(role, frozenset())
    return frozenset(result)


def is_owner_scoped(
    permission: Permission,
    held: frozenset[Permission],
    _seen: frozenset[Permission] = frozenset(),
) -> bool:
    """Whether ``permission`` must be narrowed to the principal's own flats.

    A broadener only lifts the scope if the principal's hold of *it* is itself
    society-wide. This matters: a FLAT_OWNER holds ``vehicle.manage`` so they
    can register their own car, and that must not be read as authority over
    every vehicle in the society. Their ``vehicle.manage`` is only society-wide
    if they also hold ``parking.manage``, which a resident does not.

    Checking membership alone would let ``vehicle.read`` and ``pet.read`` leak
    the whole society to every resident.
    """
    if permission not in OWNER_SCOPED_PERMISSIONS:
        return False
    if permission in _seen:
        # A cycle in the broadening graph. Staying scoped is the safe answer.
        return True

    seen = _seen | {permission}
    for broadener in BROADENING_PERMISSIONS.get(permission, frozenset()):
        if broadener in held and not is_owner_scoped(broadener, held, seen):
            return False
    return True


ALL_PERMISSIONS: tuple[Permission, ...] = tuple(Permission)
TENANT_PERMISSIONS: tuple[Permission, ...] = tuple(
    p for p in Permission if p.resource != "platform"
)
