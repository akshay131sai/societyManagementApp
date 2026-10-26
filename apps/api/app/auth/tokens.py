"""NestFlow session tokens: a short-lived access JWT and a rotating refresh JWT.

The identity provider (Firebase, or the dev verifier) is consulted exactly once,
at ``POST /auth/login``. It proves who the caller is; this module then issues
NestFlow's own pair:

* **Access token** — HS256 JWT, ``ACCESS_TOKEN_TTL_MINUTES`` long, sent as
  ``Authorization: Bearer`` on every request. Stateless: verifying it costs no
  query. It carries identity only (``sub`` = provider uid, ``email``) — never
  roles or society. Authorization is still resolved from PostgreSQL on every
  request, so a lock or role change takes effect on the next request, not when
  the token expires (docs/architecture/authentication.md section 1).
* **Refresh token** — HS256 JWT, ``REFRESH_TOKEN_TTL_DAYS`` long, exchanged at
  ``POST /auth/refresh`` for a new pair. Recorded in ``refresh_tokens`` by
  ``jti`` so it can be revoked, and rotated on every use (see
  :mod:`app.models.central.token` for reuse detection).

``typ`` is checked on both sides, so a refresh token is useless as a bearer
token and an access token cannot be used to refresh.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
import structlog
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import (
    TokenExpiredError,
    TokenInvalidError,
    TokenRevokedError,
    UserDisabledError,
)
from app.core.firebase import FirebaseIdentity
from app.models.central import PlatformUser, RefreshToken

log = structlog.get_logger(__name__)

ALGORITHM = "HS256"
ACCESS = "access"
REFRESH = "refresh"


@dataclass(frozen=True, slots=True)
class TokenPair:
    access_token: str
    refresh_token: str
    expires_in: int
    """Seconds until the access token expires."""
    refresh_expires_in: int

    def as_response(self) -> dict[str, Any]:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "token_type": "bearer",
            "expires_in": self.expires_in,
            "refresh_expires_in": self.refresh_expires_in,
        }


# --------------------------------------------------------------------------- #
# Encoding
# --------------------------------------------------------------------------- #


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _encode(claims: dict[str, Any], *, typ: str, lifetime: timedelta) -> str:
    settings = get_settings()
    issued = _now()
    payload = {
        **claims,
        "typ": typ,
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
        "iat": issued,
        "nbf": issued,
        "exp": issued + lifetime,
    }
    payload.setdefault("jti", str(uuid.uuid4()))
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def _decode(token: str, *, typ: str, verify_exp: bool = True) -> dict[str, Any]:
    settings = get_settings()
    try:
        claims: dict[str, Any] = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[ALGORITHM],
            audience=settings.JWT_AUDIENCE,
            issuer=settings.JWT_ISSUER,
            options={
                "require": ["exp", "iat", "sub", "jti", "typ"],
                "verify_exp": verify_exp,
            },
            leeway=10,
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenExpiredError() from exc
    except jwt.InvalidTokenError as exc:
        raise TokenInvalidError() from exc

    if claims.get("typ") != typ:
        raise TokenInvalidError()
    return claims


def create_access_token(*, uid: str, email: str, platform_user_id: uuid.UUID | None = None) -> str:
    claims: dict[str, Any] = {"sub": uid, "email": email.lower()}
    if platform_user_id is not None:
        claims["pid"] = str(platform_user_id)
    lifetime = timedelta(minutes=get_settings().ACCESS_TOKEN_TTL_MINUTES)
    return _encode(claims, typ=ACCESS, lifetime=lifetime)


def decode_access_token(token: str) -> FirebaseIdentity:
    """Verify an access token and return the identity it carries.

    The result has the same shape the identity provider produced at login, so
    :class:`~app.auth.resolver.PrincipalResolver` runs unchanged behind it.
    """
    claims = _decode(token, typ=ACCESS)
    email = claims.get("email")
    if not isinstance(email, str) or not email:
        raise TokenInvalidError()
    return FirebaseIdentity(
        uid=str(claims["sub"]),
        email=email,
        email_verified=True,
        provider="nestflow",
    )


# --------------------------------------------------------------------------- #
# Sessions
# --------------------------------------------------------------------------- #


class SessionService:
    """Issues, rotates and revokes refresh tokens against the central database."""

    def __init__(self, central: AsyncSession) -> None:
        self.central = central

    async def issue(
        self,
        user: PlatformUser,
        *,
        family_id: uuid.UUID | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> TokenPair:
        pair, _ = await self._issue(
            user, family_id=family_id, ip_address=ip_address, user_agent=user_agent
        )
        return pair

    async def _issue(
        self,
        user: PlatformUser,
        *,
        family_id: uuid.UUID | None,
        ip_address: str | None,
        user_agent: str | None,
    ) -> tuple[TokenPair, uuid.UUID]:
        settings = get_settings()
        access_ttl = timedelta(minutes=settings.ACCESS_TOKEN_TTL_MINUTES)
        refresh_ttl = timedelta(days=settings.REFRESH_TOKEN_TTL_DAYS)

        jti = uuid.uuid4()
        family = family_id or uuid.uuid4()
        refresh = _encode(
            {"sub": str(user.id), "jti": str(jti), "fam": str(family)},
            typ=REFRESH,
            lifetime=refresh_ttl,
        )
        self.central.add(
            RefreshToken(
                id=jti,
                platform_user_id=user.id,
                family_id=family,
                expires_at=_now() + refresh_ttl,
                ip_address=ip_address,
                user_agent=(user_agent or "")[:500] or None,
            )
        )
        await self.central.flush()

        pair = TokenPair(
            access_token=create_access_token(
                uid=user.firebase_uid, email=user.email, platform_user_id=user.id
            ),
            refresh_token=refresh,
            expires_in=int(access_ttl.total_seconds()),
            refresh_expires_in=int(refresh_ttl.total_seconds()),
        )
        return pair, jti

    async def start(
        self,
        user: PlatformUser,
        *,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> TokenPair:
        """A fresh sign-in: new family. Expired rows for the user are pruned here
        so the table stays proportional to live sessions without a sweep."""
        await self.central.execute(
            delete(RefreshToken).where(
                RefreshToken.platform_user_id == user.id,
                RefreshToken.expires_at < _now(),
            )
        )
        return await self.issue(user, ip_address=ip_address, user_agent=user_agent)

    async def rotate(
        self,
        refresh_token: str,
        *,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> TokenPair:
        claims = _decode(refresh_token, typ=REFRESH)
        row = await self._row(claims, lock=True)
        if row is None:
            raise TokenInvalidError()

        if row.revoked_at is not None:
            if row.replaced_by is not None:
                # Rotated already, and presented again: a copy is in use.
                await self._revoke_family(row.family_id)
                await self.central.commit()
                log.warning(
                    "auth.refresh_reuse_detected",
                    platform_user_id=str(row.platform_user_id),
                    family_id=str(row.family_id),
                )
            raise TokenRevokedError()

        user = await self.central.get(PlatformUser, row.platform_user_id)
        if user is None:
            raise TokenInvalidError()
        if not user.is_active:
            await self._revoke_family(row.family_id)
            await self.central.commit()
            raise UserDisabledError()

        pair, successor = await self._issue(
            user, family_id=row.family_id, ip_address=ip_address, user_agent=user_agent
        )
        row.revoked_at = _now()
        row.replaced_by = successor
        await self.central.flush()
        return pair

    async def revoke(self, refresh_token: str) -> None:
        """Sign out: end the whole family the token belongs to.

        An expired token still identifies its family, so signing out after a
        long idle period works. An unrecognised token is ignored — sign-out
        must never fail in a way the user has to deal with.
        """
        try:
            claims = _decode(refresh_token, typ=REFRESH, verify_exp=False)
        except TokenInvalidError:
            return
        row = await self._row(claims)
        if row is not None:
            await self._revoke_family(row.family_id)

    async def revoke_all(self, platform_user_id: uuid.UUID) -> None:
        await self.central.execute(
            update(RefreshToken)
            .where(
                RefreshToken.platform_user_id == platform_user_id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=_now())
        )

    # ------------------------------------------------------------------ #

    async def _row(self, claims: dict[str, Any], *, lock: bool = False) -> RefreshToken | None:
        try:
            jti = uuid.UUID(str(claims["jti"]))
            sub = uuid.UUID(str(claims["sub"]))
        except ValueError:
            raise TokenInvalidError() from None
        stmt = select(RefreshToken).where(
            RefreshToken.id == jti, RefreshToken.platform_user_id == sub
        )
        if lock:
            stmt = stmt.with_for_update()
        return await self.central.scalar(stmt)

    async def _revoke_family(self, family_id: uuid.UUID) -> None:
        await self.central.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=_now())
        )
