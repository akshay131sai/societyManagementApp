"""Structure and resident repositories.

All SQL for buildings, blocks, floors, flats, residents and family members.
No ``society_id`` filters — the session is already bound to one society's
database, so scoping is structural.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import Select, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.tenant import (
    Block,
    Building,
    FamilyMember,
    Flat,
    Floor,
    OccupancyStatus,
    Resident,
    RoleRow,
    TenantUser,
    UserRole,
)


async def _count(session: AsyncSession, stmt: Select) -> int:
    subq = stmt.order_by(None).subquery()
    return int(await session.scalar(select(func.count()).select_from(subq)) or 0)


class BuildingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, building_id: uuid.UUID) -> Building | None:
        return await self.session.get(Building, building_id)

    async def get_by_code(self, code: str) -> Building | None:
        return await self.session.scalar(
            select(Building).where(func.upper(Building.code) == code.upper())
        )

    async def list(self, *, include_inactive: bool = False) -> Sequence[Building]:
        stmt = select(Building)
        if not include_inactive:
            stmt = stmt.where(Building.is_active.is_(True))
        rows = await self.session.scalars(stmt.order_by(Building.sort_order, Building.name))
        return list(rows)

    async def create(self, building: Building) -> Building:
        self.session.add(building)
        await self.session.flush()
        return building

    async def counts(self) -> dict[uuid.UUID, dict[str, int]]:
        """Block, floor and flat counts per building, in three queries not 3N."""
        blocks = dict(
            (
                await self.session.execute(
                    select(Block.building_id, func.count())
                    .where(Block.is_active.is_(True))
                    .group_by(Block.building_id)
                )
            ).all()
        )
        floors = dict(
            (
                await self.session.execute(
                    select(Block.building_id, func.count())
                    .join(Floor, Floor.block_id == Block.id)
                    .group_by(Block.building_id)
                )
            ).all()
        )
        flats = dict(
            (
                await self.session.execute(
                    select(Flat.building_id, func.count())
                    .where(Flat.is_active.is_(True))
                    .group_by(Flat.building_id)
                )
            ).all()
        )
        keys = set(blocks) | set(floors) | set(flats)
        return {
            k: {
                "blocks": int(blocks.get(k, 0)),
                "floors": int(floors.get(k, 0)),
                "flats": int(flats.get(k, 0)),
            }
            for k in keys
        }


class BlockRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, block_id: uuid.UUID) -> Block | None:
        return await self.session.get(Block, block_id)

    async def get_by_code(self, building_id: uuid.UUID, code: str) -> Block | None:
        return await self.session.scalar(
            select(Block).where(
                Block.building_id == building_id, func.upper(Block.code) == code.upper()
            )
        )

    async def list(
        self, *, building_id: uuid.UUID | None = None, include_inactive: bool = False
    ) -> Sequence[Block]:
        stmt = select(Block).options(selectinload(Block.building))
        if building_id is not None:
            stmt = stmt.where(Block.building_id == building_id)
        if not include_inactive:
            stmt = stmt.where(Block.is_active.is_(True))
        rows = await self.session.scalars(stmt.order_by(Block.sort_order, Block.name))
        return list(rows)

    async def create(self, block: Block) -> Block:
        self.session.add(block)
        await self.session.flush()
        return block

    async def counts(self) -> dict[uuid.UUID, dict[str, int]]:
        floors = dict(
            (
                await self.session.execute(
                    select(Floor.block_id, func.count()).group_by(Floor.block_id)
                )
            ).all()
        )
        flats = dict(
            (
                await self.session.execute(
                    select(Flat.block_id, func.count())
                    .where(Flat.is_active.is_(True))
                    .group_by(Flat.block_id)
                )
            ).all()
        )
        keys = set(floors) | set(flats)
        return {
            k: {"floors": int(floors.get(k, 0)), "flats": int(flats.get(k, 0))} for k in keys
        }


class FloorRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, floor_id: uuid.UUID) -> Floor | None:
        return await self.session.get(Floor, floor_id)

    async def get_with_parents(self, floor_id: uuid.UUID) -> Floor | None:
        """Floor plus its block and building — needed to derive a flat's parents."""
        return await self.session.scalar(
            select(Floor)
            .where(Floor.id == floor_id)
            .options(selectinload(Floor.block).selectinload(Block.building))
        )

    async def get_by_number(self, block_id: uuid.UUID, number: int) -> Floor | None:
        return await self.session.scalar(
            select(Floor).where(Floor.block_id == block_id, Floor.number == number)
        )

    async def list(
        self, *, block_id: uuid.UUID | None = None, building_id: uuid.UUID | None = None
    ) -> Sequence[Floor]:
        stmt = select(Floor).options(selectinload(Floor.block).selectinload(Block.building))
        if block_id is not None:
            stmt = stmt.where(Floor.block_id == block_id)
        if building_id is not None:
            stmt = stmt.where(
                Floor.block_id.in_(select(Block.id).where(Block.building_id == building_id))
            )
        rows = await self.session.scalars(stmt.order_by(Floor.number))
        return list(rows)

    async def create(self, floor: Floor) -> Floor:
        self.session.add(floor)
        await self.session.flush()
        return floor

    async def flat_counts(self) -> dict[uuid.UUID, int]:
        rows = await self.session.execute(
            select(Flat.floor_id, func.count())
            .where(Flat.is_active.is_(True))
            .group_by(Flat.floor_id)
        )
        return {k: int(v) for k, v in rows}


class FlatRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, flat_id: uuid.UUID) -> Flat | None:
        return await self.session.get(Flat, flat_id)

    async def get_detailed(self, flat_id: uuid.UUID) -> Flat | None:
        return await self.session.scalar(
            select(Flat)
            .where(Flat.id == flat_id)
            .options(
                selectinload(Flat.floor).selectinload(Floor.block).selectinload(Block.building)
            )
        )

    async def get_by_number(self, building_id: uuid.UUID, flat_number: str) -> Flat | None:
        """Flat numbers are unique per building, so the building scopes the lookup."""
        return await self.session.scalar(
            select(Flat).where(
                Flat.building_id == building_id,
                func.upper(Flat.flat_number) == flat_number.upper(),
            )
        )

    async def existing_numbers(
        self, building_id: uuid.UUID, numbers: Sequence[str]
    ) -> set[str]:
        """Which of these numbers already exist in this building. One query."""
        if not numbers:
            return set()
        rows = await self.session.scalars(
            select(Flat.flat_number).where(
                Flat.building_id == building_id,
                func.upper(Flat.flat_number).in_([n.upper() for n in numbers]),
            )
        )
        return {n.upper() for n in rows}

    async def list(
        self,
        *,
        page: int = 1,
        limit: int = 25,
        q: str | None = None,
        building_id: uuid.UUID | None = None,
        block_id: uuid.UUID | None = None,
        floor_id: uuid.UUID | None = None,
        occupancy_status: OccupancyStatus | None = None,
        flat_type: str | None = None,
        only_ids: Sequence[uuid.UUID] | None = None,
        include_inactive: bool = False,
    ) -> tuple[Sequence[Flat], int]:
        stmt = select(Flat).options(
            selectinload(Flat.floor).selectinload(Floor.block).selectinload(Block.building)
        )
        if not include_inactive:
            stmt = stmt.where(Flat.is_active.is_(True))
        if q:
            stmt = stmt.where(func.lower(Flat.flat_number).like(f"%{q.lower()}%"))
        if building_id is not None:
            stmt = stmt.where(Flat.building_id == building_id)
        if block_id is not None:
            stmt = stmt.where(Flat.block_id == block_id)
        if floor_id is not None:
            stmt = stmt.where(Flat.floor_id == floor_id)
        if occupancy_status is not None:
            stmt = stmt.where(Flat.occupancy_status == occupancy_status)
        if flat_type:
            stmt = stmt.where(Flat.flat_type == flat_type)
        if only_ids is not None:
            # Owner scoping. An empty list must match nothing, not everything.
            stmt = stmt.where(Flat.id.in_(list(only_ids)) if only_ids else False)

        total = await _count(self.session, stmt)

        # Order by the hierarchy, not the text of the flat number: a plain
        # ORDER BY flat_number puts "A-1001" before "A-101" and "A-1201"
        # before "A-201", which reads as broken to anyone looking at a list.
        rows = await self.session.scalars(
            stmt.join(Floor, Floor.id == Flat.floor_id)
            .order_by(Flat.building_id, Flat.block_id, Floor.number, Flat.flat_number)
            .offset((page - 1) * limit)
            .limit(limit)
        )
        return list(rows), total

    async def create(self, flat: Flat) -> Flat:
        self.session.add(flat)
        await self.session.flush()
        return flat

    async def create_many(self, flats: Sequence[Flat]) -> None:
        self.session.add_all(list(flats))
        await self.session.flush()

    async def count(self, *, active_only: bool = True) -> int:
        stmt = select(func.count()).select_from(Flat)
        if active_only:
            stmt = stmt.where(Flat.is_active.is_(True))
        return int(await self.session.scalar(stmt) or 0)

    async def counts_by_occupancy(self) -> dict[str, int]:
        rows = await self.session.execute(
            select(Flat.occupancy_status, func.count())
            .where(Flat.is_active.is_(True))
            .group_by(Flat.occupancy_status)
        )
        return {str(status.value): int(count) for status, count in rows}

    async def resident_counts(self, flat_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, int]:
        if not flat_ids:
            return {}
        rows = await self.session.execute(
            select(Resident.flat_id, func.count())
            .where(Resident.flat_id.in_(list(flat_ids)), Resident.is_active.is_(True))
            .group_by(Resident.flat_id)
        )
        return {k: int(v) for k, v in rows}

    async def distinct_types(self) -> list[str]:
        rows = await self.session.scalars(
            select(Flat.flat_type)
            .where(Flat.flat_type.is_not(None), Flat.is_active.is_(True))
            .distinct()
            .order_by(Flat.flat_type)
        )
        return [t for t in rows if t]

    async def total_area(self) -> float:
        return float(
            await self.session.scalar(
                select(func.coalesce(func.sum(Flat.area_sqft), 0)).where(Flat.is_active.is_(True))
            )
            or 0
        )


class ResidentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, resident_id: uuid.UUID) -> Resident | None:
        return await self.session.get(Resident, resident_id)

    async def get_detailed(self, resident_id: uuid.UUID) -> Resident | None:
        return await self.session.scalar(
            select(Resident)
            .where(Resident.id == resident_id)
            .options(
                selectinload(Resident.flat),
                selectinload(Resident.family_members),
            )
        )

    async def list(
        self,
        *,
        page: int = 1,
        limit: int = 25,
        q: str | None = None,
        flat_id: uuid.UUID | None = None,
        building_id: uuid.UUID | None = None,
        resident_type: str | None = None,
        only_flat_ids: Sequence[uuid.UUID] | None = None,
        include_inactive: bool = False,
    ) -> tuple[Sequence[Resident], int]:
        stmt = select(Resident).options(selectinload(Resident.flat))
        if not include_inactive:
            stmt = stmt.where(Resident.is_active.is_(True))
        if q:
            pattern = f"%{q.lower()}%"
            stmt = stmt.where(
                func.lower(Resident.full_name).like(pattern)
                | func.lower(func.coalesce(Resident.email, "")).like(pattern)
                | func.coalesce(Resident.phone, "").like(pattern)
            )
        if flat_id is not None:
            stmt = stmt.where(Resident.flat_id == flat_id)
        if building_id is not None:
            stmt = stmt.where(
                Resident.flat_id.in_(select(Flat.id).where(Flat.building_id == building_id))
            )
        if resident_type:
            stmt = stmt.where(Resident.resident_type == resident_type)
        if only_flat_ids is not None:
            stmt = stmt.where(
                Resident.flat_id.in_(list(only_flat_ids)) if only_flat_ids else False
            )

        total = await _count(self.session, stmt)
        rows = await self.session.scalars(
            stmt.order_by(Resident.full_name, Resident.is_primary.desc())
            .offset((page - 1) * limit)
            .limit(limit)
        )
        return list(rows), total

    async def list_for_flat(self, flat_id: uuid.UUID) -> Sequence[Resident]:
        rows = await self.session.scalars(
            select(Resident)
            .where(Resident.flat_id == flat_id, Resident.is_active.is_(True))
            .order_by(Resident.is_primary.desc(), Resident.full_name)
        )
        return list(rows)

    async def flat_ids_for_user(self, user_id: uuid.UUID) -> set[uuid.UUID]:
        rows = await self.session.scalars(
            select(Resident.flat_id).where(
                Resident.user_id == user_id, Resident.is_active.is_(True)
            )
        )
        return set(rows)

    async def current_primary(self, flat_id: uuid.UUID) -> Resident | None:
        return await self.session.scalar(
            select(Resident).where(
                Resident.flat_id == flat_id,
                Resident.is_primary.is_(True),
                Resident.is_active.is_(True),
            )
        )

    async def create(self, resident: Resident) -> Resident:
        self.session.add(resident)
        await self.session.flush()
        return resident

    async def count(self, *, active_only: bool = True) -> int:
        stmt = select(func.count()).select_from(Resident)
        if active_only:
            stmt = stmt.where(Resident.is_active.is_(True))
        return int(await self.session.scalar(stmt) or 0)

    async def counts_by_type(self) -> dict[str, int]:
        rows = await self.session.execute(
            select(Resident.resident_type, func.count())
            .where(Resident.is_active.is_(True))
            .group_by(Resident.resident_type)
        )
        return {str(t.value): int(c) for t, c in rows}


class FamilyMemberRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, member_id: uuid.UUID) -> FamilyMember | None:
        return await self.session.get(FamilyMember, member_id)

    async def list_for_resident(self, resident_id: uuid.UUID) -> Sequence[FamilyMember]:
        rows = await self.session.scalars(
            select(FamilyMember)
            .where(FamilyMember.resident_id == resident_id)
            .order_by(FamilyMember.full_name)
        )
        return list(rows)

    async def create(self, member: FamilyMember) -> FamilyMember:
        self.session.add(member)
        await self.session.flush()
        return member

    # -- flat admin --------------------------------------------------------- #

    async def is_flat_admin(self, flat_id: uuid.UUID, tenant_user_id: uuid.UUID) -> bool:
        """Whether this user runs the flat: primary resident, or a co-admin.

        ``ux_residents_primary`` guarantees at most one active primary row per
        flat, so the first arm identifies exactly one person.
        """
        primary = await self.session.scalar(
            select(func.count())
            .select_from(Resident)
            .where(
                Resident.flat_id == flat_id,
                Resident.user_id == tenant_user_id,
                Resident.is_primary.is_(True),
                Resident.is_active.is_(True),
            )
        )
        if primary:
            return True

        co_admin = await self.session.scalar(
            select(func.count())
            .select_from(FamilyMember)
            .join(Resident, Resident.id == FamilyMember.resident_id)
            .where(
                Resident.flat_id == flat_id,
                Resident.is_active.is_(True),
                FamilyMember.user_id == tenant_user_id,
                FamilyMember.is_active.is_(True),
                FamilyMember.access_level == "CO_ADMIN",
            )
        )
        return bool(co_admin)

    # -- logins ------------------------------------------------------------- #

    async def email_taken(self, email: str, *, exclude: uuid.UUID | None = None) -> bool:
        """True if the address belongs to any user, resident or family member.

        The tenant ``users`` table has a society-wide unique index on
        ``lower(email)``, so a clash there would surface as an IntegrityError
        mid-transaction. Checking all three up front turns that into a sentence
        the flat admin can act on.
        """
        lowered = email.lower()

        if await self.session.scalar(
            select(func.count())
            .select_from(TenantUser)
            .where(func.lower(TenantUser.email) == lowered)
        ):
            return True

        if await self.session.scalar(
            select(func.count())
            .select_from(Resident)
            .where(func.lower(Resident.email) == lowered, Resident.is_active.is_(True))
        ):
            return True

        stmt = (
            select(func.count())
            .select_from(FamilyMember)
            .where(
                func.lower(FamilyMember.email) == lowered,
                FamilyMember.is_active.is_(True),
            )
        )
        if exclude is not None:
            stmt = stmt.where(FamilyMember.id != exclude)
        return bool(await self.session.scalar(stmt))

    async def reclaimable_login(self, email: str) -> uuid.UUID | None:
        """A dormant account at this address that a re-invite may adopt.

        ``ux_users_email_lower`` is society-wide and unconditional, so revoking
        access leaves the deactivated user still holding the address — a second
        insert can never succeed and re-inviting somebody would be impossible.

        Adoption is deliberately narrow. The account must be inactive *and*
        unclaimed by any active resident or family member; anything else is a
        genuine clash, and adopting it would be an account takeover dressed up
        as a convenience.
        """
        lowered = email.lower()
        user_id = await self.session.scalar(
            select(TenantUser.id).where(
                func.lower(TenantUser.email) == lowered,
                TenantUser.is_active.is_(False),
            )
        )
        if user_id is None:
            return None

        claimed_by_resident = await self.session.scalar(
            select(func.count())
            .select_from(Resident)
            .where(Resident.user_id == user_id, Resident.is_active.is_(True))
        )
        claimed_by_family = await self.session.scalar(
            select(func.count())
            .select_from(FamilyMember)
            .where(FamilyMember.user_id == user_id, FamilyMember.is_active.is_(True))
        )
        if claimed_by_resident or claimed_by_family:
            return None

        return user_id

    async def create_login(self, *, email: str, full_name: str, phone: str | None) -> uuid.UUID:
        """Tenant half of a family account. No password is involved."""
        user = TenantUser(
            firebase_uid=f"pending:{email.lower()}",
            email=email.lower(),
            phone=phone,
            full_name=full_name,
            is_active=True,
        )
        self.session.add(user)
        await self.session.flush()
        return user.id

    async def update_login_email(self, user_id: uuid.UUID, email: str) -> None:
        user = await self.session.get(TenantUser, user_id)
        if user is None:
            return
        user.email = email.lower()
        # Only rebind the placeholder. An account already bound to a real
        # Firebase UID keeps it, exactly as PrincipalResolver._link_by_email
        # refuses to re-bind a live account.
        if user.firebase_uid.startswith("pending:"):
            user.firebase_uid = f"pending:{email.lower()}"
        await self.session.flush()

    async def set_login_role(
        self, user_id: uuid.UUID, role: object, assigned_by: uuid.UUID | None
    ) -> None:
        """Replace every role on the account with the one the tier maps to."""
        role_id = await self.session.scalar(select(RoleRow.id).where(RoleRow.code == str(role)))
        if role_id is None:
            raise LookupError(f"Role {role} is not seeded in this society — run sync-rbac.")

        await self.session.execute(delete(UserRole).where(UserRole.user_id == user_id))
        self.session.add(
            UserRole(user_id=user_id, role_id=role_id, assigned_by=assigned_by)
        )
        await self.session.flush()

    async def reactivate_user(self, user_id: uuid.UUID) -> None:
        user = await self.session.get(TenantUser, user_id)
        if user is not None:
            user.is_active = True
            await self.session.flush()

    async def deactivate_user(self, user_id: uuid.UUID) -> None:
        user = await self.session.get(TenantUser, user_id)
        if user is not None:
            user.is_active = False
            await self.session.flush()
