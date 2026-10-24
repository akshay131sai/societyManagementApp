"""Society provisioning.

``CREATE DATABASE`` cannot run inside a transaction block, so this is a saga
with explicit state, not a single transaction. Each completed step is recorded
in ``database_registry.provisioning_state``, which makes the whole thing
**idempotent and resumable**: re-running detects what already exists and
continues from the first incomplete step.

It never silently half-succeeds into ``ACTIVE``. A failure marks the society
``PROVISIONING_FAILED`` and records the failing step, leaving the partial tenant
database in place for inspection.

See docs/architecture/tenant-isolation.md section 4.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AlreadyExistsError, NotFoundError, ProvisioningFailedError
from app.core.permissions import (
    PERMISSION_DESCRIPTIONS,
    ROLE_LABELS,
    ROLE_PERMISSIONS,
    TENANT_PERMISSIONS,
    TENANT_ROLES,
    Permission,
    Role,
)
from app.database.manager import TenantDatabaseManager
from app.models.central import (
    DatabaseRegistry,
    PlatformUser,
    ProvisioningState,
    Society,
    SocietyAdminAssignment,
    SocietyStatus,
    Subscription,
    SubscriptionPlan,
    SubscriptionStatus,
)
from app.models.tenant import PermissionRow, RolePermission, RoleRow, TenantUser, UserRole
from app.models.tenant.settings import DEFAULT_THEME, SocietySettings, ThemeSettings
from app.repositories.central import (
    DatabaseRegistryRepository,
    PlatformUserRepository,
    SocietyRepository,
    SubscriptionPlanRepository,
    SubscriptionRepository,
)

log = structlog.get_logger(__name__)

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


@dataclass(slots=True)
class SocietyAdminSpec:
    email: str
    display_name: str
    phone: str | None = None
    firebase_uid: str | None = None
    """When absent, a ``pending:`` placeholder is stored and bound on first
    sign-in (see ``PrincipalResolver._link_by_email``)."""


@dataclass(slots=True)
class ProvisioningResult:
    society: Society
    registry: DatabaseRegistry
    admin: PlatformUser
    subscription: Subscription
    database_name: str
    alembic_revision: str
    resumed: bool


class ProvisioningService:
    """Creates a society and everything it needs to be usable."""

    def __init__(self, central: AsyncSession, manager: TenantDatabaseManager) -> None:
        self.central = central
        self.manager = manager

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    async def provision(
        self,
        *,
        name: str,
        city: str,
        state: str,
        pincode: str,
        contact_email: str,
        contact_phone: str,
        admin: SocietyAdminSpec,
        plan_id: uuid.UUID | None = None,
        slug: str | None = None,
        registration_number: str | None = None,
        address_line1: str | None = None,
        address_line2: str | None = None,
        timezone_name: str = "Asia/Kolkata",
        created_by: uuid.UUID | None = None,
    ) -> ProvisioningResult:
        society_repo = SocietyRepository(self.central)

        slug = slug or await self._generate_slug(name)
        if await society_repo.slug_exists(slug):
            raise AlreadyExistsError(f"A society with the identifier '{slug}' already exists.")

        # --- Steps 1-5: durable central record before any DDL --------------
        society = Society(
            name=name.strip(),
            slug=slug,
            registration_number=registration_number,
            address_line1=address_line1,
            address_line2=address_line2,
            city=city.strip(),
            state=state.strip(),
            pincode=pincode.strip(),
            contact_email=contact_email.strip().lower(),
            contact_phone=contact_phone.strip(),
            timezone=timezone_name,
            status=SocietyStatus.PROVISIONING,
            created_by=created_by,
        )
        await society_repo.create(society)

        registry_repo = DatabaseRegistryRepository(self.central)
        sequence_number = await registry_repo.next_sequence_number()
        database_name = TenantDatabaseManager.build_database_name(sequence_number)

        from app.core.config import get_settings

        settings = get_settings()
        registry = DatabaseRegistry(
            society_id=society.id,
            database_name=database_name,
            sequence_number=sequence_number,
            host=settings.TENANT_DB_HOST,
            port=settings.TENANT_DB_PORT,
            provisioning_state=ProvisioningState.PENDING,
        )
        await registry_repo.create(registry)

        # The admin account is made durable *before* any tenant DDL. It carries
        # the only copy of the admin's identity, so creating it later would make
        # a failure during database creation or migration unresumable.
        # tenant_user_id is filled in after the tenant database is seeded.
        await self._ensure_platform_admin(society, admin, None, created_by)

        await self.central.commit()

        log.info(
            "provisioning.started",
            society_id=str(society.id),
            slug=slug,
            database=database_name,
        )

        return await self._run_saga(
            society=society,
            registry=registry,
            admin=admin,
            plan_id=plan_id,
            created_by=created_by,
            resumed=False,
        )

    async def retry(self, society_id: uuid.UUID) -> ProvisioningResult:
        """Resume a failed or incomplete provisioning run."""
        society = await SocietyRepository(self.central).get_by_id(society_id)
        if society is None:
            raise NotFoundError("Society")

        registry = await DatabaseRegistryRepository(self.central).get_by_society(society_id)
        if registry is None:
            raise NotFoundError("Database registration")

        if society.status is SocietyStatus.ACTIVE:
            raise AlreadyExistsError("This society is already provisioned and active.")

        existing_admin = await self._find_existing_admin(society_id)
        if existing_admin is None:
            # Only reachable for societies created before the admin record was
            # made durable up front. Nothing records the intended admin's
            # identity, so resuming would have to invent one.
            raise ProvisioningFailedError(
                "resume",
                "No admin account is recorded for this society, so provisioning "
                "cannot be resumed. Archive this society and create it again.",
            )

        return await self._run_saga(
            society=society,
            registry=registry,
            admin=SocietyAdminSpec(
                email=existing_admin.email,
                display_name=existing_admin.display_name,
                phone=existing_admin.phone,
                firebase_uid=existing_admin.firebase_uid,
            ),
            plan_id=None,
            created_by=society.created_by,
            resumed=True,
        )

    # ------------------------------------------------------------------ #
    # Saga
    # ------------------------------------------------------------------ #

    async def _run_saga(
        self,
        *,
        society: Society,
        registry: DatabaseRegistry,
        admin: SocietyAdminSpec,
        plan_id: uuid.UUID | None,
        created_by: uuid.UUID | None,
        resumed: bool,
    ) -> ProvisioningResult:
        step = "unknown"
        try:
            # --- 6: create the physical database (idempotent) --------------
            step = "create_database"
            created = await self.manager.create_database(registry.database_name)
            await self._advance(registry, ProvisioningState.DATABASE_CREATED, step)
            log.info(
                "provisioning.database",
                database=registry.database_name,
                newly_created=created,
            )

            # --- 7: tenant migrations --------------------------------------
            step = "run_migrations"
            revision = await self.manager.run_migrations(registry.database_name)
            registry.alembic_revision = revision
            registry.migrated_at = datetime.now(timezone.utc)
            await self._advance(registry, ProvisioningState.MIGRATED, step)

            await self.manager.register(society.id, registry.database_name)

            # --- 8-10: seed the tenant database ----------------------------
            step = "seed_tenant"
            tenant_user_id = await self._seed_tenant(society, admin)
            await self._advance(registry, ProvisioningState.SEEDED, step)

            # --- 11: central admin account ---------------------------------
            step = "create_admin"
            platform_admin = await self._ensure_platform_admin(
                society, admin, tenant_user_id, created_by
            )

            # --- 12: subscription ------------------------------------------
            step = "assign_subscription"
            subscription = await self._ensure_subscription(society, plan_id, created_by)

            # --- 13: activate ----------------------------------------------
            step = "activate"
            society.status = SocietyStatus.ACTIVE
            registry.provisioning_state = ProvisioningState.COMPLETED
            registry.provisioning_error = None
            registry.provisioning_step = None
            await self.central.commit()

            log.info(
                "provisioning.completed",
                society_id=str(society.id),
                database=registry.database_name,
                revision=revision,
            )

            return ProvisioningResult(
                society=society,
                registry=registry,
                admin=platform_admin,
                subscription=subscription,
                database_name=registry.database_name,
                alembic_revision=revision,
                resumed=resumed,
            )

        except Exception as exc:
            await self._mark_failed(society, registry, step, exc)
            if isinstance(exc, ProvisioningFailedError):
                raise
            raise ProvisioningFailedError(step, str(exc)) from exc

    async def _advance(
        self, registry: DatabaseRegistry, state: ProvisioningState, step: str
    ) -> None:
        registry.provisioning_state = state
        registry.provisioning_step = step
        await self.central.commit()

    async def _mark_failed(
        self,
        society: Society,
        registry: DatabaseRegistry,
        step: str,
        exc: Exception,
    ) -> None:
        """Record the failure durably.

        The partial tenant database is deliberately left in place: dropping it
        would destroy the evidence needed to diagnose the failure, and the
        resume path can reuse it.
        """
        await self.central.rollback()
        try:
            society.status = SocietyStatus.PROVISIONING_FAILED
            registry.provisioning_state = ProvisioningState.FAILED
            registry.provisioning_step = step
            registry.provisioning_error = f"{type(exc).__name__}: {exc}"[:2000]
            self.central.add(society)
            self.central.add(registry)
            await self.central.commit()
        except Exception:  # pragma: no cover - best effort
            await self.central.rollback()
        log.error(
            "provisioning.failed",
            society_id=str(society.id),
            step=step,
            error=str(exc),
            exc_info=True,
        )

    # ------------------------------------------------------------------ #
    # Tenant seeding
    # ------------------------------------------------------------------ #

    async def _seed_tenant(self, society: Society, admin: SocietyAdminSpec) -> uuid.UUID:
        """Seed permissions, roles, settings, theme and the admin user.

        Idempotent throughout so a resumed run converges rather than conflicting.
        """
        async with self.manager.session(society.id) as tenant:
            permission_ids = await self._seed_permissions(tenant)
            role_ids = await self._seed_roles(tenant, permission_ids)
            await self._seed_settings(tenant, society)
            await self._seed_theme(tenant)
            return await self._seed_admin_user(tenant, admin, role_ids[Role.SOCIETY_ADMIN])

    @staticmethod
    async def _seed_permissions(tenant: AsyncSession) -> dict[Permission, uuid.UUID]:
        from sqlalchemy import select

        existing = {
            code: pid
            for code, pid in (
                await tenant.execute(select(PermissionRow.code, PermissionRow.id))
            ).all()
        }
        result: dict[Permission, uuid.UUID] = {}
        for permission in TENANT_PERMISSIONS:
            if permission.value in existing:
                result[permission] = existing[permission.value]
                continue
            row = PermissionRow(
                code=permission.value,
                resource=permission.resource,
                action=permission.action,
                description=PERMISSION_DESCRIPTIONS.get(permission),
            )
            tenant.add(row)
            await tenant.flush()
            result[permission] = row.id
        return result

    @staticmethod
    async def _seed_roles(
        tenant: AsyncSession, permission_ids: dict[Permission, uuid.UUID]
    ) -> dict[Role, uuid.UUID]:
        from sqlalchemy import select

        existing = {
            code: rid
            for code, rid in (await tenant.execute(select(RoleRow.code, RoleRow.id))).all()
        }
        role_ids: dict[Role, uuid.UUID] = {}

        for role in sorted(TENANT_ROLES, key=lambda r: r.value):
            role_id = existing.get(role.value)
            if role_id is None:
                row = RoleRow(
                    code=role.value,
                    name=ROLE_LABELS[role],
                    description=f"{ROLE_LABELS[role]} — seeded from the NestFlow RBAC matrix",
                    is_system=True,
                )
                tenant.add(row)
                await tenant.flush()
                role_id = row.id
            role_ids[role] = role_id

            wanted = {
                permission_ids[p]
                for p in ROLE_PERMISSIONS.get(role, frozenset())
                if p in permission_ids
            }
            current = set(
                (
                    await tenant.scalars(
                        select(RolePermission.permission_id).where(
                            RolePermission.role_id == role_id
                        )
                    )
                ).all()
            )
            for permission_id in wanted - current:
                tenant.add(
                    RolePermission(role_id=role_id, permission_id=permission_id)
                )
            # Revoking matters as much as granting: a permission removed from
            # ROLE_PERMISSIONS must actually disappear from societies that were
            # provisioned before the change, or the code and the database drift
            # apart in the direction that leaves extra access behind.
            if revoked := current - wanted:
                from sqlalchemy import delete

                await tenant.execute(
                    delete(RolePermission).where(
                        RolePermission.role_id == role_id,
                        RolePermission.permission_id.in_(revoked),
                    )
                )
            await tenant.flush()

        return role_ids

    @staticmethod
    async def _seed_settings(tenant: AsyncSession, society: Society) -> None:
        settings = await tenant.get(SocietySettings, 1)
        if settings is not None:
            return
        tenant.add(
            SocietySettings(
                id=1,
                society_name=society.name,
                registration_number=society.registration_number,
                address_line1=society.address_line1,
                address_line2=society.address_line2,
                city=society.city,
                state=society.state,
                pincode=society.pincode,
                contact_email=society.contact_email,
                contact_phone=society.contact_phone,
                timezone=society.timezone,
            )
        )
        await tenant.flush()

    @staticmethod
    async def _seed_theme(tenant: AsyncSession) -> None:
        theme = await tenant.get(ThemeSettings, 1)
        if theme is not None:
            return
        tenant.add(ThemeSettings(id=1, **DEFAULT_THEME))  # type: ignore[arg-type]
        await tenant.flush()

    @staticmethod
    async def _seed_admin_user(
        tenant: AsyncSession, admin: SocietyAdminSpec, society_admin_role_id: uuid.UUID
    ) -> uuid.UUID:
        from sqlalchemy import func, select

        user = await tenant.scalar(
            select(TenantUser).where(func.lower(TenantUser.email) == admin.email.lower())
        )
        if user is None:
            user = TenantUser(
                firebase_uid=admin.firebase_uid or f"pending:{admin.email.lower()}",
                email=admin.email.lower(),
                phone=admin.phone,
                full_name=admin.display_name,
                is_active=True,
            )
            tenant.add(user)
            await tenant.flush()

        already = await tenant.scalar(
            select(func.count())
            .select_from(UserRole)
            .where(UserRole.user_id == user.id, UserRole.role_id == society_admin_role_id)
        )
        if not already:
            tenant.add(UserRole(user_id=user.id, role_id=society_admin_role_id))
            await tenant.flush()

        return user.id

    # ------------------------------------------------------------------ #
    # Central records
    # ------------------------------------------------------------------ #

    async def _find_existing_admin(self, society_id: uuid.UUID) -> PlatformUser | None:
        from sqlalchemy import select

        return await self.central.scalar(
            select(PlatformUser)
            .where(PlatformUser.society_id == society_id)
            .order_by(PlatformUser.created_at)
            .limit(1)
        )

    async def _ensure_platform_admin(
        self,
        society: Society,
        admin: SocietyAdminSpec,
        tenant_user_id: uuid.UUID | None,
        created_by: uuid.UUID | None,
    ) -> PlatformUser:
        repo = PlatformUserRepository(self.central)
        existing = await repo.get_by_email_in_society(admin.email, society.id)
        if existing is not None:
            if tenant_user_id is not None:
                existing.tenant_user_id = tenant_user_id
            await self.central.flush()
            return existing

        user = PlatformUser(
            firebase_uid=admin.firebase_uid or f"pending:{admin.email.lower()}",
            email=admin.email.lower(),
            phone=admin.phone,
            display_name=admin.display_name,
            is_super_admin=False,
            society_id=society.id,
            tenant_user_id=tenant_user_id,
            is_active=True,
        )
        await repo.create(user)

        self.central.add(
            SocietyAdminAssignment(
                society_id=society.id,
                platform_user_id=user.id,
                assigned_by=created_by,
                assigned_at=datetime.now(timezone.utc),
                is_active=True,
            )
        )
        await self.central.flush()
        return user

    async def _ensure_subscription(
        self, society: Society, plan_id: uuid.UUID | None, created_by: uuid.UUID | None
    ) -> Subscription:
        sub_repo = SubscriptionRepository(self.central)
        current = await sub_repo.get_current(society.id)
        if current is not None:
            return current

        plan_repo = SubscriptionPlanRepository(self.central)
        plan: SubscriptionPlan | None = None
        if plan_id is not None:
            plan = await plan_repo.get_by_id(plan_id)
            if plan is None:
                raise NotFoundError("Subscription plan")
        else:
            plans = await plan_repo.list(active_only=True)
            plan = plans[0] if plans else None

        if plan is None:
            raise ProvisioningFailedError(
                "assign_subscription",
                "No active subscription plan exists. Create a plan before provisioning "
                "a society.",
            )

        today = date.today()
        subscription = Subscription(
            society_id=society.id,
            plan_id=plan.id,
            status=SubscriptionStatus.TRIAL if plan.trial_days > 0 else SubscriptionStatus.ACTIVE,
            start_date=today,
            end_date=today + timedelta(days=plan.trial_days or 365),
            is_current=True,
            price_snapshot=plan.price,
            max_flats_snapshot=plan.max_flats,
            max_users_snapshot=plan.max_users,
            created_by=created_by,
        )
        # Populate the relationship on the instance. A freshly added object has
        # no loaded `plan`, and `lazy="selectin"` only applies to query loads —
        # reading `.plan` later would attempt sync IO inside async code.
        subscription.plan = plan
        return await sub_repo.create(subscription)

    # ------------------------------------------------------------------ #

    async def _generate_slug(self, name: str) -> str:
        base = _SLUG_STRIP.sub("-", name.lower()).strip("-")[:60] or "society"
        if len(base) < 3:
            base = f"{base}-society"
        repo = SocietyRepository(self.central)
        candidate = base
        suffix = 2
        while await repo.slug_exists(candidate):
            candidate = f"{base}-{suffix}"
            suffix += 1
        return candidate

    # ------------------------------------------------------------------ #

    async def sync_rbac(self, society_id: uuid.UUID) -> dict[str, int]:
        """Re-seed permissions and system-role grants into an existing society.

        Runtime authorization reads the tenant *tables*, so a change to
        ``ROLE_PERMISSIONS`` has no effect on societies that were already
        provisioned until this runs. Called by ``app.cli sync-rbac`` after any
        RBAC change, and safe to run repeatedly.

        Custom (non-system) roles are left untouched.
        """
        from sqlalchemy import func, select

        async with self.manager.session(society_id) as tenant:
            before = int(
                await tenant.scalar(select(func.count()).select_from(RolePermission)) or 0
            )
            permission_ids = await self._seed_permissions(tenant)
            await self._seed_roles(tenant, permission_ids)
            after = int(
                await tenant.scalar(select(func.count()).select_from(RolePermission)) or 0
            )
            permissions = int(
                await tenant.scalar(select(func.count()).select_from(PermissionRow)) or 0
            )

        return {
            "permissions": permissions,
            "grants_before": before,
            "grants_after": after,
            "delta": after - before,
        }

    async def verify_tenant(self, society_id: uuid.UUID) -> dict[str, object]:
        """Diagnostic: report what a tenant database actually contains."""
        async with self.manager.session(society_id) as tenant:
            db_name = await tenant.scalar(text("SELECT current_database()"))
            tables = list(
                await tenant.scalars(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'public' ORDER BY table_name"
                    )
                )
            )
            roles = list(await tenant.scalars(text("SELECT code FROM roles ORDER BY code")))
            permission_count = await tenant.scalar(text("SELECT count(*) FROM permissions"))
            user_count = await tenant.scalar(text("SELECT count(*) FROM users"))
        return {
            "database": db_name,
            "tables": tables,
            "roles": roles,
            "permissions": permission_count,
            "users": user_count,
        }
