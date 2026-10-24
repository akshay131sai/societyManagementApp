"""FastAPI dependencies.

Guards compose per-route in a fixed order (see
docs/architecture/tenant-isolation.md section 5):

    authenticated -> known user -> active society -> valid subscription
                  -> tenant session -> permission

Society and subscription guards run *before* the tenant session, so a locked
society never opens a connection to its database. The permission guard runs
last so "you are locked out" always beats "you lack this permission" — the more
actionable message reaches the user.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Annotated

import structlog
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import Principal
from app.auth.resolver import PrincipalResolver, ResolvedContext
from app.core.errors import AuthenticationError, AuthorizationError
from app.core.firebase import FirebaseIdentity, get_token_verifier
from app.core.logging import firebase_uid_ctx, society_id_ctx
from app.core.permissions import Permission
from app.database.central import get_central_sessionmaker
from app.database.manager import TenantDatabaseManager, get_tenant_manager
from app.realtime.outbox import bind_society

log = structlog.get_logger(__name__)

bearer_scheme = HTTPBearer(auto_error=False, description="Firebase ID token")


# --------------------------------------------------------------------------- #
# Sessions
# --------------------------------------------------------------------------- #


async def get_central_session() -> AsyncIterator[AsyncSession]:
    """Central DB session for the request. Commits on success."""
    factory = get_central_sessionmaker()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


CentralSession = Annotated[AsyncSession, Depends(get_central_session)]


def get_manager() -> TenantDatabaseManager:
    return get_tenant_manager()


TenantManager = Annotated[TenantDatabaseManager, Depends(get_manager)]


# --------------------------------------------------------------------------- #
# Identity
# --------------------------------------------------------------------------- #


async def get_firebase_identity(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
    ],
) -> FirebaseIdentity:
    if credentials is None or not credentials.credentials:
        raise AuthenticationError()

    verifier = get_token_verifier()
    identity = verifier.verify(credentials.credentials)
    firebase_uid_ctx.set(identity.uid)
    return identity


FirebaseIdentityDep = Annotated[FirebaseIdentity, Depends(get_firebase_identity)]


async def get_context(
    identity: FirebaseIdentityDep,
    central: CentralSession,
    manager: TenantManager,
    request: Request,
) -> ResolvedContext:
    """Resolve the full request context from the verified identity.

    Cached on ``request.state`` so several dependencies in one route resolve the
    principal once rather than once each.
    """
    cached = getattr(request.state, "context", None)
    if cached is not None:
        return cached  # type: ignore[no-any-return]

    resolver = PrincipalResolver(central, manager)
    context = await resolver.resolve(
        identity, auth_provider=get_token_verifier().name
    )
    request.state.context = context
    request.state.principal = context.principal
    if context.principal.society_id is not None:
        society_id_ctx.set(str(context.principal.society_id))
    return context


ContextDep = Annotated[ResolvedContext, Depends(get_context)]


async def get_principal(context: ContextDep) -> Principal:
    return context.principal


PrincipalDep = Annotated[Principal, Depends(get_principal)]


# --------------------------------------------------------------------------- #
# Guards
# --------------------------------------------------------------------------- #


async def require_super_admin(principal: PrincipalDep) -> Principal:
    if not principal.is_super_admin:
        raise AuthorizationError("This action is restricted to platform administrators.")
    return principal


SuperAdmin = Annotated[Principal, Depends(require_super_admin)]


async def require_society_member(principal: PrincipalDep) -> Principal:
    """Society status and subscription were already enforced during resolution.

    ``PrincipalResolver`` raises ``SocietyLockedError`` /
    ``SubscriptionExpiredError`` before a tenant session is opened, so reaching
    here means both gates passed.
    """
    if principal.society_id is None:
        raise AuthorizationError(
            "This action requires a society account. Platform administrators "
            "manage societies through the platform endpoints."
        )
    return principal


SocietyMember = Annotated[Principal, Depends(require_society_member)]


async def get_tenant_session(
    principal: SocietyMember,
    manager: TenantManager,
) -> AsyncIterator[AsyncSession]:
    """Session bound to the caller's own society database.

    ``principal.society_id`` came from ``platform_users``, never from the
    request — this is the sole entry point to tenant data.
    """
    assert principal.society_id is not None
    async with manager.session(principal.society_id) as session:
        # The realtime outbox releases its events when this session commits and
        # needs to know which society's connections to publish into. Binding it
        # here means no service has to pass a society id around to say so.
        bind_society(session, principal.society_id)
        yield session


TenantSession = Annotated[AsyncSession, Depends(get_tenant_session)]


def require_permission(*permissions: Permission) -> Callable[..., object]:
    """Dependency factory requiring **all** given permissions.

    Returns the ``Principal`` so a route can declare authentication and
    authorization in a single parameter.
    """

    async def _guard(principal: PrincipalDep) -> Principal:
        missing = [p for p in permissions if not principal.has(p)]
        if missing:
            log.info(
                "authz.denied",
                email=principal.email,
                required=[p.value for p in permissions],
                missing=[p.value for p in missing],
            )
            raise AuthorizationError()
        return principal

    return _guard


def require_any_permission(*permissions: Permission) -> Callable[..., object]:
    """Dependency factory requiring **at least one** of the given permissions."""

    async def _guard(principal: PrincipalDep) -> Principal:
        if not principal.has_any(*permissions):
            log.info(
                "authz.denied",
                email=principal.email,
                required_any=[p.value for p in permissions],
            )
            raise AuthorizationError()
        return principal

    return _guard
