"""Principal resolution and access guards.

This module implements the request lifecycle described in
docs/architecture/tenant-isolation.md section 2. It is the only place a
``society_id`` is produced, and it produces it from the authenticated identity
alone — never from the request.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import Principal
from app.core.errors import (
    SocietyArchivedError,
    SocietyLockedError,
    SocietyProvisioningError,
    SocietySuspendedError,
    SubscriptionExpiredError,
    SubscriptionMissingError,
    SubscriptionSuspendedError,
    UserDisabledError,
    UserNotRegisteredError,
)
from app.core.firebase import FirebaseIdentity
from app.core.permissions import Permission, Role
from app.database.manager import TenantDatabaseManager
from app.models.central import (
    DatabaseRegistry,
    PlatformUser,
    ProvisioningState,
    Society,
    SocietyStatus,
    Subscription,
    SubscriptionStatus,
)
from app.repositories.central import (
    DatabaseRegistryRepository,
    PlatformUserRepository,
    SocietyRepository,
    SubscriptionRepository,
)
from app.repositories.tenant import TenantUserRepository

log = structlog.get_logger(__name__)


@dataclass(slots=True)
class ResolvedContext:
    """Everything the request needs, resolved from the token alone."""

    principal: Principal
    platform_user: PlatformUser
    society: Society | None
    subscription: Subscription | None
    registry: DatabaseRegistry | None


class PrincipalResolver:
    def __init__(
        self,
        central_session: AsyncSession,
        tenant_manager: TenantDatabaseManager,
    ) -> None:
        self.central = central_session
        self.tenant_manager = tenant_manager

    async def resolve(
        self, identity: FirebaseIdentity, *, auth_provider: str = "firebase"
    ) -> ResolvedContext:
        """Turn a verified identity into a Principal.

        Order matters: identity -> account -> society status -> subscription ->
        tenant roles. Each step is a hard gate, and the tenant database is not
        touched until the society and subscription have both passed.
        """
        platform_user = await self.load_platform_user(identity)

        # --- Super admin: platform scope, no tenant session ever ------------
        if platform_user.is_super_admin:
            principal = Principal(
                platform_user_id=platform_user.id,
                firebase_uid=platform_user.firebase_uid,
                email=platform_user.email,
                display_name=platform_user.display_name,
                is_super_admin=True,
                society_id=None,
                tenant_user_id=None,
                roles=frozenset({Role.SUPER_ADMIN}),
                permissions=frozenset(
                    p for p in Permission if p.resource == "platform"
                ),
                auth_provider=auth_provider,
            )
            return ResolvedContext(
                principal=principal,
                platform_user=platform_user,
                society=None,
                subscription=None,
                registry=None,
            )

        # --- Tenant user ----------------------------------------------------
        assert platform_user.society_id is not None  # guaranteed by ck_scope
        society = await self._load_society(platform_user.society_id)
        subscription = await self._load_subscription(society.id)
        registry = await self._load_registry(society.id)

        await self.tenant_manager.register(society.id, registry.database_name)

        roles, permissions, flat_ids = await self._load_tenant_authorization(
            society.id, platform_user
        )

        principal = Principal(
            platform_user_id=platform_user.id,
            firebase_uid=platform_user.firebase_uid,
            email=platform_user.email,
            display_name=platform_user.display_name,
            is_super_admin=False,
            society_id=society.id,
            tenant_user_id=platform_user.tenant_user_id,
            roles=roles,
            permissions=permissions,
            flat_ids=flat_ids,
            auth_provider=auth_provider,
        )
        return ResolvedContext(
            principal=principal,
            platform_user=platform_user,
            society=society,
            subscription=subscription,
            registry=registry,
        )

    # ------------------------------------------------------------------ #

    async def load_platform_user(self, identity: FirebaseIdentity) -> PlatformUser:
        """The account behind an identity: registered, linked and active.

        Used alone by ``POST /auth/login``, which issues tokens to any active
        account and leaves society and subscription gates to the first request.
        """
        repo = PlatformUserRepository(self.central)
        user = await repo.get_by_firebase_uid(identity.uid)

        if user is None:
            # Fall back to email so a user provisioned before their first
            # Firebase sign-in can be linked on the way in. The Firebase UID is
            # then bound permanently.
            user = await self._link_by_email(identity)

        if user is None:
            log.info("auth.user_not_registered", firebase_uid=identity.uid)
            raise UserNotRegisteredError()

        if not user.is_active:
            raise UserDisabledError()

        return user

    async def _link_by_email(self, identity: FirebaseIdentity) -> PlatformUser | None:
        """Bind a pre-provisioned account to the Firebase UID on first sign-in.

        Only a row with a placeholder UID is eligible — an account already bound
        to a different Firebase UID is never re-bound, so this cannot be used to
        take over an existing account by registering its email address.
        """
        from sqlalchemy import func, select

        stmt = select(PlatformUser).where(
            func.lower(PlatformUser.email) == identity.email.lower(),
            PlatformUser.firebase_uid.like("pending:%"),
        )
        user = await self.central.scalar(stmt)
        if user is None:
            return None

        user.firebase_uid = identity.uid
        await self.central.flush()
        log.info(
            "auth.firebase_uid_linked",
            platform_user_id=str(user.id),
            email=identity.email,
        )
        return user

    async def _load_society(self, society_id: uuid.UUID) -> Society:
        society = await SocietyRepository(self.central).get_by_id(society_id)
        if society is None:
            raise UserNotRegisteredError()

        match society.status:
            case SocietyStatus.ACTIVE:
                return society
            case SocietyStatus.LOCKED:
                raise SocietyLockedError(
                    society.locked_reason or SocietyLockedError.message
                )
            case SocietyStatus.SUSPENDED:
                raise SocietySuspendedError()
            case SocietyStatus.ARCHIVED:
                raise SocietyArchivedError()
            case SocietyStatus.PROVISIONING | SocietyStatus.PROVISIONING_FAILED:
                raise SocietyProvisioningError()
            case _:  # pragma: no cover - exhaustive above
                raise SocietyProvisioningError()

    async def _load_subscription(self, society_id: uuid.UUID) -> Subscription:
        subscription = await SubscriptionRepository(self.central).get_current(society_id)
        if subscription is None:
            raise SubscriptionMissingError()

        if subscription.status is SubscriptionStatus.SUSPENDED:
            raise SubscriptionSuspendedError()

        if not subscription.is_valid_on(date.today()):
            raise SubscriptionExpiredError()

        return subscription

    async def _load_registry(self, society_id: uuid.UUID) -> DatabaseRegistry:
        registry = await DatabaseRegistryRepository(self.central).get_by_society(society_id)
        if registry is None or registry.provisioning_state is not ProvisioningState.COMPLETED:
            raise SocietyProvisioningError()
        return registry

    async def _load_tenant_authorization(
        self, society_id: uuid.UUID, platform_user: PlatformUser
    ) -> tuple[frozenset[Role], frozenset[Permission], frozenset[uuid.UUID]]:
        """Read roles and permissions from the *tenant* tables.

        Reading the tables rather than ``ROLE_PERMISSIONS`` is what allows a
        society-specific role to exist later without a deploy.
        """
        async with self.tenant_manager.session(society_id) as tenant:
            repo = TenantUserRepository(tenant)

            # tenant_user_id is the authoritative link between the two
            # databases. Resolving by it (rather than by firebase_uid) keeps
            # sign-in working when the central row has just been bound to a real
            # Firebase UID while the tenant mirror still holds the placeholder.
            user = None
            if platform_user.tenant_user_id is not None:
                user = await repo.get_with_authorization(platform_user.tenant_user_id)
            if user is None:
                user = await repo.get_by_firebase_uid(platform_user.firebase_uid)

            if user is None:
                log.warning(
                    "auth.tenant_user_missing",
                    society_id=str(society_id),
                    platform_user_id=str(platform_user.id),
                )
                raise UserNotRegisteredError()
            if not user.is_active:
                raise UserDisabledError()

            if user.firebase_uid != platform_user.firebase_uid:
                user.firebase_uid = platform_user.firebase_uid
                await tenant.flush()
                log.info(
                    "auth.tenant_uid_synced",
                    society_id=str(society_id),
                    tenant_user_id=str(user.id),
                )

            roles: set[Role] = set()
            permissions: set[Permission] = set()
            for user_role in user.user_roles:
                role_row = user_role.role
                try:
                    roles.add(Role(role_row.code))
                except ValueError:
                    # A society-defined custom role: it carries permissions but
                    # has no Role enum member. Keep the permissions, skip the
                    # role symbol.
                    log.debug("auth.custom_role", code=role_row.code)
                for rp in role_row.role_permissions:
                    try:
                        permissions.add(Permission(rp.permission.code))
                    except ValueError:
                        log.warning("auth.unknown_permission", code=rp.permission.code)

            # Flat ownership drives owner-scoped reads. The residents table
            # arrives in Phase 2; until then a Flat Owner simply owns no flats,
            # which fails closed rather than open.
            flat_ids = await self._load_flat_ids(tenant, user.id)

            if platform_user.tenant_user_id != user.id:
                platform_user.tenant_user_id = user.id
                await self.central.flush()

        return frozenset(roles), frozenset(permissions), frozenset(flat_ids)

    @staticmethod
    async def _load_flat_ids(tenant: AsyncSession, tenant_user_id: uuid.UUID) -> set[uuid.UUID]:
        """Flats this user may act on, by either route into a household.

        A resident reaches their flat directly. A family member reaches it
        through the resident who registered them — which is the whole of what
        makes a family login work: every owner-scoped service filters on
        ``principal.flat_ids``, so following this second edge here gives a
        spouse or child the same correctly-narrowed view of bills, meters,
        visitors and notices without a single service knowing they exist.

        Both sides require ``is_active``, so revoking a family member's access
        or moving a resident out takes effect on their next request.
        """
        from sqlalchemy import inspect, text

        def _tables(sync_conn: object) -> tuple[bool, bool]:
            inspector = inspect(sync_conn)  # type: ignore[arg-type]
            return inspector.has_table("residents"), inspector.has_table("family_members")

        conn = await tenant.connection()
        has_residents, has_family = await conn.run_sync(_tables)
        if not has_residents:
            return set()

        sql = (
            "SELECT flat_id FROM residents "
            "WHERE user_id = :uid AND is_active AND flat_id IS NOT NULL"
        )
        if has_family:
            sql += (
                " UNION "
                "SELECT r.flat_id FROM family_members fm "
                "JOIN residents r ON r.id = fm.resident_id "
                "WHERE fm.user_id = :uid AND fm.is_active "
                "AND r.is_active AND r.flat_id IS NOT NULL"
            )

        rows = await tenant.execute(text(sql), {"uid": tenant_user_id})
        return {row[0] for row in rows}
