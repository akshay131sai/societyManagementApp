"""Token verification.

Two verifiers behind one interface:

* :class:`FirebaseTokenVerifier` — the real thing, via the Firebase Admin SDK.
* :class:`DevTokenVerifier` — accepts ``dev:<email>``, for local work before a
  Firebase project exists.

The dev verifier cannot reach production. ``Settings`` refuses to construct when
``ENVIRONMENT=production`` and ``AUTH_PROVIDER=dev``, so the process does not
boot; a startup banner and an ``auth_provider`` field on ``/auth/me`` make its
use obvious in development.

Only ``uid``, ``email`` and ``email_verified`` are taken from a verified token.
Firebase custom claims are **never** read for authorization — see
docs/architecture/authentication.md section 1.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Protocol

import structlog

from app.core.config import AuthProvider, Settings, get_settings
from app.core.errors import (
    TokenExpiredError,
    TokenInvalidError,
    TokenRevokedError,
)

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class FirebaseIdentity:
    """What a verified token yields. Nothing more is trusted."""

    uid: str
    email: str
    email_verified: bool
    provider: str


class TokenVerifier(Protocol):
    def verify(self, token: str) -> FirebaseIdentity: ...

    @property
    def name(self) -> str: ...


class FirebaseTokenVerifier:
    """Verifies signature, issuer, audience and expiry via the Admin SDK."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._app = None
        self._lock = threading.Lock()

    @property
    def name(self) -> str:
        return "firebase"

    def _ensure_initialised(self) -> None:
        if self._app is not None:
            return
        with self._lock:
            if self._app is not None:
                return
            import firebase_admin
            from firebase_admin import credentials

            s = self._settings
            cred = credentials.Certificate(
                {
                    "type": "service_account",
                    "project_id": s.FIREBASE_PROJECT_ID,
                    "client_email": s.FIREBASE_CLIENT_EMAIL,
                    "private_key": s.FIREBASE_PRIVATE_KEY,
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            )
            try:
                self._app = firebase_admin.get_app()
            except ValueError:
                self._app = firebase_admin.initialize_app(
                    cred, {"projectId": s.FIREBASE_PROJECT_ID}
                )
            log.info("firebase.initialised", project_id=s.FIREBASE_PROJECT_ID)

    def verify(self, token: str) -> FirebaseIdentity:
        self._ensure_initialised()
        from firebase_admin import auth as fb_auth

        try:
            decoded = fb_auth.verify_id_token(
                token,
                app=self._app,
                check_revoked=self._settings.FIREBASE_CHECK_REVOKED,
            )
        except fb_auth.ExpiredIdTokenError as exc:
            raise TokenExpiredError() from exc
        except fb_auth.RevokedIdTokenError as exc:
            raise TokenRevokedError() from exc
        except (fb_auth.InvalidIdTokenError, fb_auth.CertificateFetchError, ValueError) as exc:
            log.warning("firebase.token_invalid", error=str(exc))
            raise TokenInvalidError() from exc

        email = decoded.get("email")
        if not email:
            raise TokenInvalidError("The sign-in provider did not supply an email address.")

        return FirebaseIdentity(
            uid=decoded["uid"],
            email=email.lower(),
            email_verified=bool(decoded.get("email_verified", False)),
            provider=str(decoded.get("firebase", {}).get("sign_in_provider", "unknown")),
        )


class DevTokenVerifier:
    """Development-only verifier. Accepts ``dev:<email>``.

    This grants an identity with **no credential check**, which is precisely why
    ``Settings._validate_safety`` refuses to construct with it in production.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def name(self) -> str:
        return "dev"

    def verify(self, token: str) -> FirebaseIdentity:
        if not token.startswith("dev:"):
            raise TokenInvalidError(
                "Development auth is active; use a token of the form 'dev:<email>'."
            )
        email = token.removeprefix("dev:").strip().lower()
        if not email or "@" not in email:
            raise TokenInvalidError("Development token must carry a valid email address.")
        return FirebaseIdentity(
            uid=f"dev-uid-{email}",
            email=email,
            email_verified=True,
            provider="dev",
        )


class PasswordProvider:
    """``AUTH_PROVIDER=password``: there is no identity token to verify.

    ``/auth/login`` checks the email and password itself
    (:mod:`app.auth.passwords`). This class exists so ``name`` reports the
    provider to ``/auth/me`` and ``/health``, and so an ``id_token`` sent to a
    password server is refused rather than silently accepted.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def name(self) -> str:
        return "password"

    def verify(self, token: str) -> FirebaseIdentity:
        raise TokenInvalidError("This server signs in with an email address and password.")


_verifier: TokenVerifier | None = None


def get_token_verifier() -> TokenVerifier:
    global _verifier
    if _verifier is None:
        settings = get_settings()
        if settings.AUTH_PROVIDER is AuthProvider.FIREBASE:
            _verifier = FirebaseTokenVerifier(settings)
        elif settings.AUTH_PROVIDER is AuthProvider.PASSWORD:
            _verifier = PasswordProvider(settings)
        else:
            _verifier = DevTokenVerifier(settings)
            log.warning(
                "auth.dev_provider_active",
                message=(
                    "DEVELOPMENT AUTH IS ACTIVE. Any 'dev:<email>' token is accepted "
                    "without a credential. Never use this outside local development."
                ),
            )
    return _verifier


def reset_token_verifier() -> None:
    """Test hook — clears the cached verifier."""
    global _verifier
    _verifier = None
