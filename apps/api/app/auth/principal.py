"""The Principal — the single authenticated-subject object.

Immutable, built once per request, and passed explicitly to services. There is
no ambient "current user": if a function needs to know who is acting, it takes
a ``Principal`` parameter, which makes authorization decisions visible in every
signature.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from app.core.permissions import Permission, Role, is_owner_scoped


@dataclass(frozen=True, slots=True)
class Principal:
    platform_user_id: uuid.UUID
    firebase_uid: str
    email: str
    display_name: str
    is_super_admin: bool

    society_id: uuid.UUID | None = None
    """Resolved server-side from ``platform_users``. Never from the request."""

    tenant_user_id: uuid.UUID | None = None

    roles: frozenset[Role] = field(default_factory=frozenset)
    permissions: frozenset[Permission] = field(default_factory=frozenset)
    flat_ids: frozenset[uuid.UUID] = field(default_factory=frozenset)

    auth_provider: str = "firebase"

    # ------------------------------------------------------------------ #

    def has(self, permission: Permission) -> bool:
        return permission in self.permissions

    def has_any(self, *permissions: Permission) -> bool:
        return any(p in self.permissions for p in permissions)

    def has_all(self, *permissions: Permission) -> bool:
        return all(p in self.permissions for p in permissions)

    def has_role(self, role: Role) -> bool:
        return role in self.roles

    def owns_flat(self, flat_id: uuid.UUID) -> bool:
        return flat_id in self.flat_ids

    def is_scoped_to_own(self, permission: Permission) -> bool:
        """Whether this principal's use of ``permission`` is narrowed to own flats.

        Services call this to decide whether to apply an owner filter, rather
        than checking for the ``FLAT_OWNER`` role — a principal that also holds
        a broadening permission is correctly not narrowed.
        """
        return is_owner_scoped(permission, self.permissions)

    @property
    def is_tenant_user(self) -> bool:
        return self.society_id is not None

    def __repr__(self) -> str:
        scope = "platform" if self.is_super_admin else f"society={self.society_id}"
        return f"<Principal {self.email} {scope} roles={sorted(self.roles)}>"
