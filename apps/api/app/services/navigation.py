"""Server-driven navigation.

The sidebar is built from the principal's permissions on the server. Two
reasons this beats a hard-coded client menu:

* The client cannot show an item the backend would refuse, so "menu says yes,
  API says 403" cannot happen.
* Adding a module is a backend change; old mobile builds pick up new navigation
  without shipping.

The client still guards its routes — this is convenience, not enforcement.
"""

from __future__ import annotations

from typing import Any

from app.auth.principal import Principal
from app.core.permissions import Permission

# (key, label, icon, path, required permission | None)
_PLATFORM_NAV: list[tuple[str, str, str, str, str | None]] = [
    ("dashboard", "Dashboard", "LayoutDashboard", "/admin/dashboard", None),
    ("societies", "Societies", "Building2", "/admin/societies", Permission.PLATFORM_SOCIETY_READ),
    ("plans", "Subscription Plans", "Package", "/admin/plans", Permission.PLATFORM_PLAN_READ),
    (
        "subscriptions",
        "Subscriptions",
        "CreditCard",
        "/admin/subscriptions",
        Permission.PLATFORM_SUBSCRIPTION_READ,
    ),
    ("users", "Platform Users", "Users", "/admin/users", Permission.PLATFORM_USER_READ),
    ("audit", "Audit Logs", "ScrollText", "/admin/audit-logs", Permission.PLATFORM_AUDIT_READ),
    ("settings", "Settings", "Settings", "/admin/settings", None),
]

_SOCIETY_NAV: list[tuple[str, str, str, str, str | None]] = [
    ("dashboard", "Dashboard", "LayoutDashboard", "/app/dashboard", None),
    # One "Structure" screen covers buildings, blocks and floors — three
    # sibling nav items for three levels of one hierarchy is worse UX than
    # a tree, so blocks and floors are managed inside this route.
    ("buildings", "Structure", "Building", "/app/buildings", Permission.BUILDING_READ),
    ("flats", "Flats", "DoorOpen", "/app/flats", Permission.FLAT_READ),
    ("residents", "Residents", "Users", "/app/residents", Permission.RESIDENT_READ),
    ("family", "My Family", "UsersRound", "/app/family", Permission.FAMILY_MANAGE),
    ("users", "Users & Roles", "UserCog", "/app/users", Permission.USER_READ),
    (
        "bill-builder",
        "Bill Builder",
        "Blocks",
        "/app/bill-templates",
        Permission.BILLING_MANAGE_TEMPLATE,
    ),
    ("bills", "Bills", "ReceiptIndianRupee", "/app/bills", Permission.BILLING_READ),
    ("payments", "Payments", "Wallet", "/app/payments", Permission.PAYMENT_READ),
    ("water", "Water", "Droplets", "/app/water", Permission.WATER_READ),
    ("electricity", "Electricity", "Zap", "/app/electricity", Permission.ELECTRICITY_READ),
    ("parking", "Parking", "SquareParking", "/app/parking", Permission.PARKING_READ),
    ("vehicles", "Vehicles", "Car", "/app/vehicles", Permission.VEHICLE_READ),
    ("pets", "Pets", "PawPrint", "/app/pets", Permission.PET_READ),
    ("complaints", "Complaints", "MessageSquareWarning", "/app/complaints", Permission.COMPLAINT_READ),
    ("maintenance", "Maintenance", "Wrench", "/app/maintenance", Permission.MAINTENANCE_READ),
    ("housekeeping", "Housekeeping", "Sparkles", "/app/housekeeping", Permission.HOUSEKEEPING_READ),
    ("security", "Security", "ShieldCheck", "/app/security", Permission.SECURITY_READ),
    ("visitors", "Visitors", "UserRoundCheck", "/app/visitors", Permission.VISITOR_READ),
    ("notices", "Notices", "Megaphone", "/app/notices", Permission.NOTICE_READ),
    ("amenities", "Amenities", "Trees", "/app/amenities", Permission.AMENITY_READ),
    ("reports", "Reports", "ChartColumn", "/app/reports", Permission.REPORT_READ),
    ("appearance", "Appearance", "Palette", "/app/appearance", Permission.THEME_UPDATE),
    ("settings", "Settings", "Settings", "/app/settings", Permission.SOCIETY_SETTINGS_MANAGE),
]

_LIVE_KEYS = frozenset(
    {
        # Phase 1
        "dashboard", "societies", "plans", "subscriptions", "users", "audit",
        "settings", "appearance",
        # Phase 2
        "buildings", "flats", "residents", "family",
        # Phase 3
        "bill-builder", "bills",
        # Phase 4
        "payments", "water", "electricity", "parking", "vehicles", "pets",
        # Phase 5
        "complaints", "maintenance", "housekeeping", "security", "visitors",
        "notices", "amenities",
        # Phase 6
        "reports",
    }
)
"""Routes with real screens today.

Every society route now has one. The flag stays because the client renders a
disabled item rather than a link to an empty page, and the next module to be
added will want it again.
"""


_DIRECTORY_KEYS: dict[str, Permission] = {
    "residents": Permission.RESIDENT_READ,
}
"""Screens that only make sense with a society-wide view of their subject.

A resident holds ``resident.read``, but theirs is narrowed to their own flat —
so a "Residents" directory would list nothing but their own household, which
"My Family" already does properly. Hiding it follows the same reasoning that
keeps Structure out of a resident's menu: a management screen is not a
resident's screen.

This is presentation only. The permission is untouched, because the family
screen reads ``/residents`` and ``/residents/{id}/family`` to find the flat's
primary resident.
"""

_HOUSEHOLD_KEYS: dict[str, Permission] = {
    "family": Permission.FAMILY_MANAGE,
    "pets": Permission.PET_READ,
}
"""The mirror of ``_DIRECTORY_KEYS``: screens about *my* home, not the society.

A Society Admin's ``family.manage`` and ``pet.read`` are society-wide, so these
would open a register of every household in the society — which is not what
either screen is for. Their society-wide equivalents live elsewhere: residents
under Residents, and pet totals on the utility dashboard.

A Society Admin who also owns a flat reaches their own household the same way
any resident does, from the Residents screen for that flat.
"""


def build_navigation(principal: Principal) -> list[dict[str, Any]]:
    source = _PLATFORM_NAV if principal.is_super_admin else _SOCIETY_NAV
    items: list[dict[str, Any]] = []

    for key, label, icon, path, permission in source:
        if permission is not None and not principal.has(Permission(permission)):
            continue

        # Two symmetric filters, both presentation-only: a society-wide screen
        # is pointless for someone narrowed to one flat, and a my-household
        # screen is pointless for someone who sees the whole society.
        directory_permission = _DIRECTORY_KEYS.get(key)
        if directory_permission is not None and principal.is_scoped_to_own(
            directory_permission
        ):
            continue

        household_permission = _HOUSEHOLD_KEYS.get(key)
        if household_permission is not None and not principal.is_scoped_to_own(
            household_permission
        ):
            continue
        items.append(
            {
                "key": key,
                "label": label,
                "icon": icon,
                "path": path,
                "permission": str(permission) if permission else None,
                "badge": None if key in _LIVE_KEYS else "coming_soon",
                "children": [],
            }
        )
    return items
