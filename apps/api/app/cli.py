"""Operational CLI.

    python -m app.cli bootstrap            create super admin + default plans
    python -m app.cli create-super-admin   add a platform administrator
    python -m app.cli set-password         set an account's sign-in password
    python -m app.cli migrate-tenants      roll tenant migrations across societies
    python -m app.cli list-societies       registry overview
    python -m app.cli verify-tenant <id>   inspect one tenant database
    python -m app.cli sync-rbac            re-seed roles/permissions after an RBAC change
    python -m app.cli expire-subscriptions sweep past-due subscriptions
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from decimal import Decimal

import structlog

from app.core.eventloop import loop_factory
from app.core.logging import configure_logging
from app.database.central import central_session, dispose_central_engine
from app.database.manager import dispose_tenant_manager, get_tenant_manager

log = structlog.get_logger(__name__)


# --------------------------------------------------------------------------- #


async def bootstrap(email: str, name: str, firebase_uid: str | None) -> int:
    """Idempotent first-run setup: default plans plus one super admin."""
    from app.models.central import BillingCycle, PlatformUser, SubscriptionPlan
    from app.repositories.central import PlatformUserRepository, SubscriptionPlanRepository

    defaults = [
        {
            "name": "Starter",
            "code": "STARTER",
            "description": "For small societies getting started.",
            "price": Decimal("999.00"),
            "billing_cycle": BillingCycle.MONTHLY,
            "max_flats": 50,
            "max_users": 100,
            "trial_days": 14,
            "sort_order": 1,
            "features": {"billing": True, "visitors": True, "reports": False},
        },
        {
            "name": "Growth",
            "code": "GROWTH",
            "description": "For growing societies with multiple buildings.",
            "price": Decimal("2499.00"),
            "billing_cycle": BillingCycle.MONTHLY,
            "max_flats": 250,
            "max_users": 600,
            "trial_days": 14,
            "sort_order": 2,
            "features": {"billing": True, "visitors": True, "reports": True},
        },
        {
            "name": "Enterprise",
            "code": "ENTERPRISE",
            "description": "Unlimited flats, priority support.",
            "price": Decimal("6999.00"),
            "billing_cycle": BillingCycle.MONTHLY,
            "max_flats": None,
            "max_users": None,
            "trial_days": 30,
            "sort_order": 3,
            "features": {"billing": True, "visitors": True, "reports": True, "api": True},
        },
    ]

    async with central_session() as session:
        plan_repo = SubscriptionPlanRepository(session)
        created_plans = 0
        for spec in defaults:
            if await plan_repo.get_by_code(str(spec["code"])) is None:
                await plan_repo.create(SubscriptionPlan(**spec))  # type: ignore[arg-type]
                created_plans += 1

        user_repo = PlatformUserRepository(session)
        existing = await user_repo.get_by_email_in_society(email, None)
        if existing is not None:
            print(f"  super admin already exists: {existing.email}")
        else:
            await user_repo.create(
                PlatformUser(
                    firebase_uid=firebase_uid or f"pending:{email.lower()}",
                    email=email.lower(),
                    display_name=name,
                    is_super_admin=True,
                    society_id=None,
                    is_active=True,
                )
            )
            print(f"  super admin created: {email}")

        print(f"  subscription plans created: {created_plans}")
    return 0


async def create_super_admin(email: str, name: str, firebase_uid: str | None) -> int:
    from app.models.central import PlatformUser
    from app.repositories.central import PlatformUserRepository

    async with central_session() as session:
        repo = PlatformUserRepository(session)
        if await repo.get_by_email_in_society(email, None) is not None:
            print(f"  already exists: {email}")
            return 1
        await repo.create(
            PlatformUser(
                firebase_uid=firebase_uid or f"pending:{email.lower()}",
                email=email.lower(),
                display_name=name,
                is_super_admin=True,
                society_id=None,
                is_active=True,
            )
        )
        print(f"  created super admin: {email}")
    return 0


def _read_new_password() -> str:
    """Prompt twice without echo; read one line from stdin when piped.

    Never a command-line argument: those land in shell history and in the
    process list for every user on the machine to read.
    """
    import getpass

    if not sys.stdin.isatty():
        return sys.stdin.readline().rstrip("\r\n")
    first = getpass.getpass("  New password: ")
    if getpass.getpass("  Repeat it:    ") != first:
        raise SystemExit("  The passwords did not match.")
    return first


async def set_password(email: str, society_slug: str | None) -> int:
    """Set the password an account signs in with (``AUTH_PROVIDER=password``)."""
    from sqlalchemy import func, select

    from app.core.errors import ValidationError
    from app.models.central import PlatformUser, Society
    from app.services.credentials import CredentialService

    async with central_session() as session:
        stmt = select(PlatformUser).where(func.lower(PlatformUser.email) == email.lower())
        if society_slug:
            stmt = stmt.join(Society, Society.id == PlatformUser.society_id).where(
                Society.slug == society_slug
            )
        accounts = list(await session.scalars(stmt))
        if not accounts:
            print(f"  no account found for {email}" + (f" in {society_slug}" if society_slug else ""))
            return 1
        if len(accounts) > 1:
            print(f"  {email} has accounts in several societies; pass --society <slug>.")
            return 1

        try:
            await CredentialService(session).set_password(accounts[0], _read_new_password())
        except ValidationError as exc:
            print(f"  {exc.message}")
            return 1
        print(f"  password set for {email}; existing sessions signed out")
    return 0


async def migrate_tenants(dry_run: bool, society_id: str | None) -> int:
    """Roll tenant migrations across societies, halting on the first failure.

    Halting matters: continuing past a failure would leave the estate on mixed
    revisions with no clear recovery point.
    """
    from app.repositories.central import DatabaseRegistryRepository

    manager = get_tenant_manager()
    failures = 0

    async with central_session() as session:
        registries = await DatabaseRegistryRepository(session).list_all()
        if society_id:
            target = uuid.UUID(society_id)
            registries = [r for r in registries if r.society_id == target]
            if not registries:
                print(f"  no registry found for society {society_id}")
                return 1

        print(f"  {len(registries)} tenant database(s)")
        for registry in registries:
            label = f"{registry.database_name} (society {registry.society_id})"
            if dry_run:
                print(f"  [dry-run] would migrate {label} (at {registry.alembic_revision})")
                continue
            try:
                revision = await manager.run_migrations(registry.database_name)
                registry.alembic_revision = revision
                print(f"  OK   {label} -> {revision}")
            except Exception as exc:
                failures += 1
                print(f"  FAIL {label}: {exc}", file=sys.stderr)
                print("  halting; fix this society before continuing.", file=sys.stderr)
                break

    return 1 if failures else 0


async def list_societies() -> int:
    from app.repositories.central import DatabaseRegistryRepository, SocietyRepository

    async with central_session() as session:
        societies, total = await SocietyRepository(session).list(
            page=1, limit=200, include_archived=True
        )
        registries = {
            r.society_id: r for r in await DatabaseRegistryRepository(session).list_all()
        }
        print(f"  {total} society/societies\n")
        print(f"  {'SLUG':<24} {'STATUS':<20} {'DATABASE':<26} {'REVISION'}")
        print(f"  {'-'*24} {'-'*20} {'-'*26} {'-'*14}")
        for society in societies:
            reg = registries.get(society.id)
            print(
                f"  {society.slug[:23]:<24} {society.status.value:<20} "
                f"{(reg.database_name if reg else '-'):<26} "
                f"{(reg.alembic_revision if reg else '-') or '-'}"
            )
    return 0


async def verify_tenant(society_id: str) -> int:
    from app.repositories.central import DatabaseRegistryRepository
    from app.services.provisioning import ProvisioningService

    manager = get_tenant_manager()
    sid = uuid.UUID(society_id)

    async with central_session() as session:
        registry = await DatabaseRegistryRepository(session).get_by_society(sid)
        if registry is None:
            print(f"  no registry for society {society_id}", file=sys.stderr)
            return 1
        await manager.register(sid, registry.database_name)
        info = await ProvisioningService(session, manager).verify_tenant(sid)

    print(f"  database   : {info['database']}")
    print(f"  tables     : {len(info['tables'])}")
    for table in info["tables"]:
        print(f"               - {table}")
    print(f"  roles      : {', '.join(info['roles'])}")
    print(f"  permissions: {info['permissions']}")
    print(f"  users      : {info['users']}")
    return 0


async def sync_rbac(society_id: str | None) -> int:
    """Push a ROLE_PERMISSIONS change into already-provisioned societies.

    Runtime authorization reads the tenant tables, not the Python constant, so
    editing ``app/core/permissions.py`` has no effect on existing societies
    until this runs. Grants are added *and* revoked so the tables converge on
    the code rather than only ever growing.
    """
    from app.repositories.central import DatabaseRegistryRepository
    from app.services.provisioning import ProvisioningService

    manager = get_tenant_manager()
    failures = 0

    async with central_session() as session:
        registries = await DatabaseRegistryRepository(session).list_all()
        if society_id:
            target = uuid.UUID(society_id)
            registries = [r for r in registries if r.society_id == target]
            if not registries:
                print(f"  no registry found for society {society_id}")
                return 1

        service = ProvisioningService(session, manager)
        print(f"  {len(registries)} society/societies")
        for registry in registries:
            await manager.register(registry.society_id, registry.database_name)
            try:
                result = await service.sync_rbac(registry.society_id)
                delta = result["delta"]
                change = (
                    "unchanged"
                    if delta == 0
                    else f"{delta:+d} grant(s)"
                )
                print(
                    f"  OK   {registry.database_name}: "
                    f"{result['permissions']} permission(s), "
                    f"{result['grants_after']} grant(s) — {change}"
                )
            except Exception as exc:
                failures += 1
                print(f"  FAIL {registry.database_name}: {exc}", file=sys.stderr)

    return 1 if failures else 0


async def expire_subscriptions() -> int:
    from app.services.platform import SubscriptionService

    manager = get_tenant_manager()
    async with central_session() as session:
        count = await SubscriptionService(session, manager).expire_due()
    print(f"  expired {count} subscription(s)")
    return 0


async def run_job(name: str | None, society_id: str | None) -> int:
    """Run a scheduled job by hand.

    The scheduler runs these nightly. Running one on demand is how a job that
    misbehaved in production gets reproduced — against one society if you name
    it, so a fix can be checked without touching the other ninety-nine.
    """
    from app.workers.jobs import CENTRAL_JOBS, TENANT_JOBS, run_for_all_societies, run_for_society

    if name is None:
        print("  available jobs:")
        for job_name in (*TENANT_JOBS, *CENTRAL_JOBS):
            print(f"    {job_name}")
        return 0

    if name in CENTRAL_JOBS:
        affected = await CENTRAL_JOBS[name]()
        print(f"  {name}: {affected} affected")
        return 0

    job = TENANT_JOBS.get(name)
    if job is None:
        print(f"  unknown job: {name}")
        return 1

    if society_id is not None:
        affected = await run_for_society(job, uuid.UUID(society_id))
        print(f"  {name}: {affected} affected in {society_id}")
        return 0

    result = await run_for_all_societies(name, job)
    print(
        f"  {name}: {result.affected} affected across {result.societies} society(ies)"
        + (f", {result.failures} failed" if result.failures else "")
    )
    return 1 if result.failures else 0


# --------------------------------------------------------------------------- #


def main() -> int:
    configure_logging(level="INFO")

    parser = argparse.ArgumentParser(prog="app.cli", description="NestFlow operations CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("bootstrap", help="Create default plans and a super admin")
    p.add_argument("--email", required=True)
    p.add_argument("--name", default="Platform Administrator")
    p.add_argument("--firebase-uid", default=None)

    p = sub.add_parser("create-super-admin", help="Add a platform administrator")
    p.add_argument("--email", required=True)
    p.add_argument("--name", default="Platform Administrator")
    p.add_argument("--firebase-uid", default=None)

    p = sub.add_parser("set-password", help="Set an account's sign-in password (prompts)")
    p.add_argument("--email", required=True)
    p.add_argument("--society", default=None, help="society slug, when the email is in several")

    p = sub.add_parser("migrate-tenants", help="Run tenant migrations across societies")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--society-id", default=None)

    sub.add_parser("list-societies", help="Show societies and their databases")

    p = sub.add_parser("verify-tenant", help="Inspect one tenant database")
    p.add_argument("society_id")

    p = sub.add_parser("sync-rbac", help="Re-seed roles and permissions into existing societies")
    p.add_argument("--society-id", default=None)

    sub.add_parser("expire-subscriptions", help="Mark past-due subscriptions EXPIRED")

    p = sub.add_parser("run-job", help="Run a scheduled job now (omit NAME to list them)")
    p.add_argument("name", nargs="?", default=None)
    p.add_argument("--society-id", default=None)

    args = parser.parse_args()

    async def run() -> int:
        try:
            match args.command:
                case "bootstrap":
                    return await bootstrap(args.email, args.name, args.firebase_uid)
                case "create-super-admin":
                    return await create_super_admin(args.email, args.name, args.firebase_uid)
                case "set-password":
                    return await set_password(args.email, args.society)
                case "migrate-tenants":
                    return await migrate_tenants(args.dry_run, args.society_id)
                case "list-societies":
                    return await list_societies()
                case "verify-tenant":
                    return await verify_tenant(args.society_id)
                case "sync-rbac":
                    return await sync_rbac(args.society_id)
                case "expire-subscriptions":
                    return await expire_subscriptions()
                case "run-job":
                    return await run_job(args.name, args.society_id)
                case _:
                    parser.print_help()
                    return 1
        finally:
            await dispose_tenant_manager()
            await dispose_central_engine()

    # loop_factory: psycopg async needs a SelectorEventLoop on Windows.
    return asyncio.run(run(), loop_factory=loop_factory())


if __name__ == "__main__":
    raise SystemExit(main())
