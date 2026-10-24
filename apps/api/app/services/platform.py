"""Platform (Super Admin) application services.

Society lifecycle, subscription plans, subscriptions and the platform
dashboard. Everything here operates on the **central** database only.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import Principal
from app.core.errors import AlreadyExistsError, ConflictError, NotFoundError, ValidationError
from app.database.manager import TenantDatabaseManager
from app.models.central import (
    PlatformUser,
    Society,
    SocietyStatus,
    Subscription,
    SubscriptionPlan,
    SubscriptionStatus,
)
from app.models.central.audit import AuditAction
from app.repositories.central import (
    DatabaseRegistryRepository,
    PlatformAuditRepository,
    PlatformUserRepository,
    SocietyAdminAssignmentRepository,
    SocietyRepository,
    SubscriptionPlanRepository,
    SubscriptionRepository,
)
from app.schemas.platform import (
    PlanCreate,
    PlanUpdate,
    SocietyCreate,
    SocietyUpdate,
    SubscriptionAssign,
    SubscriptionExtend,
)
from app.services.audit import AuditService, diff
from app.services.provisioning import ProvisioningResult, ProvisioningService, SocietyAdminSpec

log = structlog.get_logger(__name__)


class SocietyService:
    def __init__(self, central: AsyncSession, manager: TenantDatabaseManager) -> None:
        self.central = central
        self.manager = manager
        self.societies = SocietyRepository(central)
        self.registries = DatabaseRegistryRepository(central)
        self.subscriptions = SubscriptionRepository(central)
        self.users = PlatformUserRepository(central)

    async def create(
        self, payload: SocietyCreate, principal: Principal, *, request_id: str | None = None
    ) -> ProvisioningResult:
        service = ProvisioningService(self.central, self.manager)
        result = await service.provision(
            name=payload.name,
            slug=payload.slug,
            registration_number=payload.registration_number,
            address_line1=payload.address_line1,
            address_line2=payload.address_line2,
            city=payload.city,
            state=payload.state,
            pincode=payload.pincode,
            contact_email=str(payload.contact_email),
            contact_phone=payload.contact_phone,
            timezone_name=payload.timezone,
            admin=SocietyAdminSpec(
                email=str(payload.admin.email),
                display_name=payload.admin.display_name,
                phone=payload.admin.phone,
                firebase_uid=payload.admin.firebase_uid,
            ),
            plan_id=payload.plan_id,
            created_by=principal.platform_user_id,
        )
        await AuditService.platform(
            self.central,
            action=AuditAction.SOCIETY_PROVISIONED,
            principal=principal,
            society_id=result.society.id,
            target_type="society",
            target_id=result.society.id,
            changes={
                "after": {
                    "name": result.society.name,
                    "slug": result.society.slug,
                    "database": result.database_name,
                    "admin_email": result.admin.email,
                }
            },
            request_id=request_id,
        )
        await self.central.commit()
        return result

    async def retry_provisioning(
        self, society_id: uuid.UUID, principal: Principal, *, request_id: str | None = None
    ) -> ProvisioningResult:
        service = ProvisioningService(self.central, self.manager)
        result = await service.retry(society_id)
        await AuditService.platform(
            self.central,
            action=AuditAction.SOCIETY_PROVISIONED,
            principal=principal,
            society_id=society_id,
            target_type="society",
            target_id=society_id,
            changes={"after": {"resumed": True, "database": result.database_name}},
            request_id=request_id,
        )
        await self.central.commit()
        return result

    async def get(self, society_id: uuid.UUID) -> Society:
        society = await self.societies.get_by_id(society_id)
        if society is None:
            raise NotFoundError("Society")
        return society

    async def detail(self, society_id: uuid.UUID) -> dict[str, Any]:
        society = await self.get(society_id)
        registry = await self.registries.get_by_society(society_id)
        subscription = await self.subscriptions.get_current(society_id)
        user_count = await self.users.count_in_society(society_id)
        admins = await SocietyAdminAssignmentRepository(self.central).list_active(society_id)
        return {
            "society": society,
            "registry": registry,
            "subscription": subscription,
            "user_count": user_count,
            "admin_count": len(admins),
        }

    async def update(
        self,
        society_id: uuid.UUID,
        payload: SocietyUpdate,
        principal: Principal,
        *,
        request_id: str | None = None,
    ) -> Society:
        society = await self.get(society_id)
        before = _snapshot(society)

        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(society, field, str(value) if field == "contact_email" else value)

        await self.central.flush()
        # Server-side onupdate expires updated_at; refresh before it is
        # serialised outside the session.
        await self.central.refresh(society)
        await AuditService.platform(
            self.central,
            action=AuditAction.SOCIETY_UPDATED,
            principal=principal,
            society_id=society_id,
            target_type="society",
            target_id=society_id,
            changes=diff(before, _snapshot(society)),
            request_id=request_id,
        )
        await self.central.commit()
        return society

    async def lock(
        self,
        society_id: uuid.UUID,
        reason: str,
        principal: Principal,
        *,
        request_id: str | None = None,
    ) -> Society:
        society = await self.get(society_id)
        if society.status is SocietyStatus.ARCHIVED:
            raise ConflictError("An archived society cannot be locked.")

        society.status = SocietyStatus.LOCKED
        society.locked_at = datetime.now(timezone.utc)
        society.locked_reason = reason
        await self.central.flush()

        # Drop the cached engine so in-flight workers cannot keep using a warm
        # connection to a society that was just locked.
        await self.manager.dispose(society_id)

        await AuditService.platform(
            self.central,
            action=AuditAction.SOCIETY_LOCKED,
            principal=principal,
            society_id=society_id,
            target_type="society",
            target_id=society_id,
            changes={"after": {"status": "LOCKED", "reason": reason}},
            request_id=request_id,
        )
        await self.central.commit()
        log.warning("society.locked", society_id=str(society_id), reason=reason)
        return society

    async def unlock(
        self, society_id: uuid.UUID, principal: Principal, *, request_id: str | None = None
    ) -> Society:
        society = await self.get(society_id)
        if society.status not in (SocietyStatus.LOCKED, SocietyStatus.SUSPENDED):
            raise ConflictError("This society is not locked.")

        registry = await self.registries.get_by_society(society_id)
        if registry is None or not registry.is_ready:
            raise ConflictError(
                "This society's database is not fully provisioned; "
                "retry provisioning before unlocking."
            )

        society.status = SocietyStatus.ACTIVE
        society.locked_at = None
        society.locked_reason = None
        await self.central.flush()
        await AuditService.platform(
            self.central,
            action=AuditAction.SOCIETY_UNLOCKED,
            principal=principal,
            society_id=society_id,
            target_type="society",
            target_id=society_id,
            changes={"after": {"status": "ACTIVE"}},
            request_id=request_id,
        )
        await self.central.commit()
        return society

    async def archive(
        self, society_id: uuid.UUID, principal: Principal, *, request_id: str | None = None
    ) -> Society:
        """Archive a society.

        The tenant database is deliberately **not** dropped — archival is
        reversible by an operator, erasure is a separate, explicit act.
        """
        society = await self.get(society_id)
        society.status = SocietyStatus.ARCHIVED
        society.archived_at = datetime.now(timezone.utc)
        await self.central.flush()
        await self.manager.dispose(society_id)
        await AuditService.platform(
            self.central,
            action=AuditAction.SOCIETY_ARCHIVED,
            principal=principal,
            society_id=society_id,
            target_type="society",
            target_id=society_id,
            request_id=request_id,
        )
        await self.central.commit()
        return society

    async def dashboard(self) -> dict[str, int]:
        counts = await self.societies.counts_by_status()
        # limit=1 because only the total is needed; the page itself is discarded.
        _, user_total = await self.users.list_all(page=1, limit=1)
        plans = await SubscriptionPlanRepository(self.central).list()
        active_subs = await self.subscriptions.count_active()
        expiring = await self.subscriptions.list_expiring(date.today() + timedelta(days=30))
        return {
            "total_societies": sum(
                v for k, v in counts.items() if k != SocietyStatus.ARCHIVED.value
            ),
            "active_societies": counts.get(SocietyStatus.ACTIVE.value, 0),
            "locked_societies": counts.get(SocietyStatus.LOCKED.value, 0)
            + counts.get(SocietyStatus.SUSPENDED.value, 0),
            "provisioning_societies": counts.get(SocietyStatus.PROVISIONING.value, 0),
            "failed_societies": counts.get(SocietyStatus.PROVISIONING_FAILED.value, 0),
            "active_subscriptions": active_subs,
            "expiring_soon": len([s for s in expiring if s.end_date >= date.today()]),
            "total_users": user_total,
            "total_plans": len(plans),
        }


class PlanService:
    def __init__(self, central: AsyncSession) -> None:
        self.central = central
        self.plans = SubscriptionPlanRepository(central)

    async def list(self, *, active_only: bool = False) -> list[SubscriptionPlan]:
        return list(await self.plans.list(active_only=active_only))

    async def get(self, plan_id: uuid.UUID) -> SubscriptionPlan:
        plan = await self.plans.get_by_id(plan_id)
        if plan is None:
            raise NotFoundError("Subscription plan")
        return plan

    async def create(
        self, payload: PlanCreate, principal: Principal, *, request_id: str | None = None
    ) -> SubscriptionPlan:
        if await self.plans.get_by_code(payload.code):
            raise AlreadyExistsError(f"A plan with code '{payload.code}' already exists.")
        plan = SubscriptionPlan(**payload.model_dump())
        await self.plans.create(plan)
        await AuditService.platform(
            self.central,
            action=AuditAction.PLAN_CREATED,
            principal=principal,
            target_type="subscription_plan",
            target_id=plan.id,
            changes={"after": {"code": plan.code, "price": str(plan.price)}},
            request_id=request_id,
        )
        await self.central.commit()
        return plan

    async def update(
        self,
        plan_id: uuid.UUID,
        payload: PlanUpdate,
        principal: Principal,
        *,
        request_id: str | None = None,
    ) -> SubscriptionPlan:
        plan = await self.get(plan_id)
        before = _snapshot(plan)
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(plan, field, value)
        await self.central.flush()
        await self.central.refresh(plan)
        await AuditService.platform(
            self.central,
            action=AuditAction.PLAN_UPDATED,
            principal=principal,
            target_type="subscription_plan",
            target_id=plan.id,
            changes=diff(before, _snapshot(plan)),
            request_id=request_id,
        )
        await self.central.commit()
        return plan


class SubscriptionService:
    def __init__(self, central: AsyncSession, manager: TenantDatabaseManager) -> None:
        self.central = central
        self.manager = manager
        self.subs = SubscriptionRepository(central)
        self.plans = SubscriptionPlanRepository(central)
        self.societies = SocietyRepository(central)

    async def assign(
        self, payload: SubscriptionAssign, principal: Principal, *, request_id: str | None = None
    ) -> Subscription:
        society = await self.societies.get_by_id(payload.society_id)
        if society is None:
            raise NotFoundError("Society")
        plan = await self.plans.get_by_id(payload.plan_id)
        if plan is None:
            raise NotFoundError("Subscription plan")

        start = payload.start_date or date.today()
        end = payload.end_date or (start + timedelta(days=_cycle_days(plan.billing_cycle)))
        if end < start:
            raise ValidationError("The subscription end date cannot precede the start date.")

        # Supersede rather than overwrite: the previous row stays as history.
        await self.subs.clear_current(society.id)
        subscription = Subscription(
            society_id=society.id,
            plan_id=plan.id,
            status=payload.status,
            start_date=start,
            end_date=end,
            is_current=True,
            price_snapshot=plan.price,
            max_flats_snapshot=plan.max_flats,
            max_users_snapshot=plan.max_users,
            notes=payload.notes,
            created_by=principal.platform_user_id,
        )
        # See the note in ProvisioningService._ensure_subscription: a new
        # instance has no loaded `plan`, and reading it later would attempt
        # synchronous IO inside async code.
        subscription.plan = plan
        await self.subs.create(subscription)
        await AuditService.platform(
            self.central,
            action=AuditAction.SUBSCRIPTION_ASSIGNED,
            principal=principal,
            society_id=society.id,
            target_type="subscription",
            target_id=subscription.id,
            changes={
                "after": {
                    "plan": plan.code,
                    "status": payload.status.value,
                    "end_date": str(end),
                }
            },
            request_id=request_id,
        )
        await self.central.commit()
        return subscription

    async def extend(
        self,
        subscription_id: uuid.UUID,
        payload: SubscriptionExtend,
        principal: Principal,
        *,
        request_id: str | None = None,
    ) -> Subscription:
        subscription = await self.subs.get_by_id(subscription_id)
        if subscription is None:
            raise NotFoundError("Subscription")
        if payload.days is None and payload.new_end_date is None:
            raise ValidationError("Provide either a number of days or a new end date.")

        before_end = subscription.end_date
        new_end = payload.new_end_date or (
            max(subscription.end_date, date.today()) + timedelta(days=payload.days or 0)
        )
        if new_end <= subscription.end_date:
            raise ValidationError("The new end date must be later than the current one.")

        subscription.end_date = new_end
        if subscription.status in (SubscriptionStatus.EXPIRED, SubscriptionStatus.SUSPENDED):
            subscription.status = SubscriptionStatus.ACTIVE
        if payload.notes:
            subscription.notes = payload.notes
        await self.central.flush()
        await self.central.refresh(subscription)

        await AuditService.platform(
            self.central,
            action=AuditAction.SUBSCRIPTION_EXTENDED,
            principal=principal,
            society_id=subscription.society_id,
            target_type="subscription",
            target_id=subscription.id,
            changes={"before": {"end_date": str(before_end)}, "after": {"end_date": str(new_end)}},
            request_id=request_id,
        )
        await self.central.commit()
        return subscription

    async def suspend(
        self,
        subscription_id: uuid.UUID,
        reason: str | None,
        principal: Principal,
        *,
        request_id: str | None = None,
    ) -> Subscription:
        subscription = await self.subs.get_by_id(subscription_id)
        if subscription is None:
            raise NotFoundError("Subscription")

        subscription.status = SubscriptionStatus.SUSPENDED
        subscription.notes = reason or subscription.notes
        await self.central.flush()
        await self.central.refresh(subscription)
        await self.manager.dispose(subscription.society_id)

        await AuditService.platform(
            self.central,
            action=AuditAction.SUBSCRIPTION_SUSPENDED,
            principal=principal,
            society_id=subscription.society_id,
            target_type="subscription",
            target_id=subscription.id,
            changes={"after": {"status": "SUSPENDED", "reason": reason}},
            request_id=request_id,
        )
        await self.central.commit()
        return subscription

    async def expire_due(self) -> int:
        """Flip subscriptions whose end date has passed. Run by the scheduler.

        Access control does not depend on this — ``PrincipalResolver`` checks the
        end date directly on every request, so an unrun sweep cannot grant
        access. This keeps reporting honest.
        """
        due = await self.subs.list_expiring(date.today())
        count = 0
        for subscription in due:
            if subscription.status in (SubscriptionStatus.TRIAL, SubscriptionStatus.ACTIVE):
                subscription.status = SubscriptionStatus.EXPIRED
                count += 1
        if count:
            await self.central.commit()
            log.info("subscriptions.expired", count=count)
        return count


class PlatformAuditService:
    def __init__(self, central: AsyncSession) -> None:
        self.repo = PlatformAuditRepository(central)

    async def list(
        self,
        *,
        page: int,
        limit: int,
        society_id: uuid.UUID | None = None,
        action: str | None = None,
    ) -> tuple[list[Any], int]:
        rows, total = await self.repo.list(
            page=page, limit=limit, society_id=society_id, action=action
        )
        return list(rows), total


class PlatformUserService:
    def __init__(self, central: AsyncSession) -> None:
        self.repo = PlatformUserRepository(central)

    async def list(
        self,
        *,
        page: int,
        limit: int,
        q: str | None = None,
        society_id: uuid.UUID | None = None,
    ) -> tuple[list[PlatformUser], int]:
        rows, total = await self.repo.list_all(
            page=page, limit=limit, q=q, society_id=society_id
        )
        return list(rows), total


# --------------------------------------------------------------------------- #


def _cycle_days(cycle: Any) -> int:
    return {
        "MONTHLY": 30,
        "QUARTERLY": 91,
        "HALF_YEARLY": 182,
        "YEARLY": 365,
    }.get(str(cycle), 365)


def _snapshot(obj: Any) -> dict[str, Any]:
    """Column values of a model instance, for audit diffing."""
    from sqlalchemy import inspect

    return {
        c.key: _plain(getattr(obj, c.key))
        for c in inspect(obj).mapper.column_attrs
        if c.key not in {"created_at", "updated_at"}
    }


def _plain(value: Any) -> Any:
    if isinstance(value, (uuid.UUID, date, datetime)):
        return str(value)
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, (int, float, str, bool, type(None), dict, list)):
        return value
    return str(value)
