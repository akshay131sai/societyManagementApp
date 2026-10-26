"""Email-and-password accounts (``AUTH_PROVIDER=password``).

Passwords live on the central ``platform_users`` row — the same row that maps
an identity to a society — so one check at ``/auth/login`` yields both.
"""

from __future__ import annotations

from datetime import datetime, timezone

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.passwords import (
    burn_time,
    hash_password,
    needs_rehash,
    password_problem,
    verify_password,
)
from app.auth.tokens import SessionService
from app.core.errors import InvalidCredentialsError, UserDisabledError, ValidationError
from app.models.central import PlatformUser

log = structlog.get_logger(__name__)


def check_password_strength(password: str, *, field: str = "password") -> None:
    problem = password_problem(password)
    if problem:
        raise ValidationError(problem, details={"fields": [{"field": field, "message": problem}]})


class CredentialService:
    def __init__(self, central: AsyncSession) -> None:
        self.central = central

    async def authenticate(self, email: str, password: str) -> PlatformUser:
        """The account these credentials open, or ``InvalidCredentialsError``.

        Email is unique per society, not globally: one person can hold accounts
        in two societies. Every candidate with a password is checked and the
        one whose password matches wins, so each account keeps its own
        password and the login form needs no society picker.
        """
        stmt = select(PlatformUser).where(
            func.lower(PlatformUser.email) == email.strip().lower(),
            PlatformUser.password_hash.is_not(None),
        )
        candidates = list(await self.central.scalars(stmt))
        if not candidates:
            burn_time(password)
            log.info("auth.password_rejected", reason="no_account")
            raise InvalidCredentialsError()

        user = next((u for u in candidates if verify_password(password, u.password_hash)), None)
        if user is None:
            log.info("auth.password_rejected", reason="mismatch")
            raise InvalidCredentialsError()
        if not user.is_active:
            raise UserDisabledError()

        assert user.password_hash is not None
        if needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)
        return user

    async def set_password(
        self, user: PlatformUser, password: str, *, field: str = "password"
    ) -> None:
        """Set a new password and sign the account out everywhere.

        Used for an administrator's reset and for the owner's own change; the
        owner's change then issues a fresh session for the device that made it.
        """
        check_password_strength(password, field=field)
        user.password_hash = hash_password(password)
        user.password_changed_at = datetime.now(timezone.utc)
        await SessionService(self.central).revoke_all(user.id)
        await self.central.flush()
        log.info("auth.password_set", platform_user_id=str(user.id))
