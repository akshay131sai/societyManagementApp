"""Error taxonomy.

Every failure the API can return has a stable machine ``code``, a
user-presentable ``message`` and an HTTP status. Handlers in ``app.main`` turn
these into the envelope described in docs/api/api-contract.md.

Stack traces are never returned to a client; ``request_id`` is the correlation
key into the structured logs.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    # --- Authentication (401) -----------------------------------------------
    UNAUTHENTICATED = "UNAUTHENTICATED"
    TOKEN_INVALID = "TOKEN_INVALID"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    TOKEN_REVOKED = "TOKEN_REVOKED"
    USER_NOT_REGISTERED = "USER_NOT_REGISTERED"
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"

    # --- Authorization (403) ------------------------------------------------
    PERMISSION_DENIED = "PERMISSION_DENIED"
    USER_DISABLED = "USER_DISABLED"
    SOCIETY_LOCKED = "SOCIETY_LOCKED"
    SOCIETY_SUSPENDED = "SOCIETY_SUSPENDED"
    SOCIETY_ARCHIVED = "SOCIETY_ARCHIVED"
    SOCIETY_PROVISIONING = "SOCIETY_PROVISIONING"
    RESOURCE_FORBIDDEN = "RESOURCE_FORBIDDEN"

    # --- Entitlement (402) --------------------------------------------------
    SUBSCRIPTION_EXPIRED = "SUBSCRIPTION_EXPIRED"
    SUBSCRIPTION_SUSPENDED = "SUBSCRIPTION_SUSPENDED"
    SUBSCRIPTION_MISSING = "SUBSCRIPTION_MISSING"
    PLAN_LIMIT_EXCEEDED = "PLAN_LIMIT_EXCEEDED"

    # --- Resource / request -------------------------------------------------
    NOT_FOUND = "NOT_FOUND"
    ALREADY_EXISTS = "ALREADY_EXISTS"
    CONFLICT = "CONFLICT"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    RATE_LIMITED = "RATE_LIMITED"

    # --- Domain -------------------------------------------------------------
    INVALID_FORMULA = "INVALID_FORMULA"
    DIVISION_BY_ZERO = "DIVISION_BY_ZERO"
    BILL_IMMUTABLE = "BILL_IMMUTABLE"
    BILLING_RUN_IN_PROGRESS = "BILLING_RUN_IN_PROGRESS"
    DUPLICATE_BILLING_PERIOD = "DUPLICATE_BILLING_PERIOD"
    TEMPLATE_VERSION_PUBLISHED = "TEMPLATE_VERSION_PUBLISHED"
    PROVISIONING_FAILED = "PROVISIONING_FAILED"

    # --- Server (5xx) -------------------------------------------------------
    INTERNAL_ERROR = "INTERNAL_ERROR"
    DATABASE_UNAVAILABLE = "DATABASE_UNAVAILABLE"
    TENANT_DB_UNAVAILABLE = "TENANT_DB_UNAVAILABLE"


class NestFlowError(Exception):
    """Base for every deliberate application error."""

    status_code: int = 500
    code: ErrorCode = ErrorCode.INTERNAL_ERROR
    message: str = "An unexpected error occurred."

    def __init__(
        self,
        message: str | None = None,
        *,
        code: ErrorCode | None = None,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or self.message
        self.code = code or self.code
        self.status_code = status_code or self.status_code
        self.details = details
        super().__init__(self.message)


# --------------------------------------------------------------------------- #
# 401 Authentication
# --------------------------------------------------------------------------- #


class AuthenticationError(NestFlowError):
    status_code = 401
    code = ErrorCode.UNAUTHENTICATED
    message = "Authentication is required to access this resource."


class TokenInvalidError(AuthenticationError):
    code = ErrorCode.TOKEN_INVALID
    message = "Your sign-in could not be verified. Please sign in again."


class TokenExpiredError(AuthenticationError):
    code = ErrorCode.TOKEN_EXPIRED
    message = "Your session has expired. Please sign in again."


class TokenRevokedError(AuthenticationError):
    code = ErrorCode.TOKEN_REVOKED
    message = "Your session was ended. Please sign in again."


class InvalidCredentialsError(AuthenticationError):
    """Wrong email, wrong password, or no password set — deliberately one
    answer, so the login form cannot be used to discover which emails exist."""

    code = ErrorCode.INVALID_CREDENTIALS
    message = "That email address or password is not correct."


class UserNotRegisteredError(AuthenticationError):
    code = ErrorCode.USER_NOT_REGISTERED
    message = (
        "This account is not registered with any society. "
        "Please contact your society administrator."
    )


# --------------------------------------------------------------------------- #
# 403 Authorization
# --------------------------------------------------------------------------- #


class AuthorizationError(NestFlowError):
    status_code = 403
    code = ErrorCode.PERMISSION_DENIED
    message = "You do not have permission to perform this action."


class UserDisabledError(AuthorizationError):
    code = ErrorCode.USER_DISABLED
    message = "This account has been deactivated. Please contact your administrator."


class SocietyLockedError(AuthorizationError):
    code = ErrorCode.SOCIETY_LOCKED
    message = "This society has been locked. Please contact NestFlow support."


class SocietySuspendedError(AuthorizationError):
    code = ErrorCode.SOCIETY_SUSPENDED
    message = "This society is currently suspended. Please contact NestFlow support."


class SocietyArchivedError(AuthorizationError):
    code = ErrorCode.SOCIETY_ARCHIVED
    message = "This society has been archived and is no longer accessible."


class SocietyProvisioningError(AuthorizationError):
    code = ErrorCode.SOCIETY_PROVISIONING
    message = "This society is still being set up. Please try again in a few moments."


class ResourceForbiddenError(AuthorizationError):
    code = ErrorCode.RESOURCE_FORBIDDEN
    message = "You do not have access to this record."


# --------------------------------------------------------------------------- #
# 402 Entitlement
# --------------------------------------------------------------------------- #


class SubscriptionExpiredError(NestFlowError):
    status_code = 402
    code = ErrorCode.SUBSCRIPTION_EXPIRED
    message = (
        "Your society subscription has ended. "
        "Please contact your society administrator."
    )


class SubscriptionSuspendedError(SubscriptionExpiredError):
    code = ErrorCode.SUBSCRIPTION_SUSPENDED
    message = "Your society subscription is suspended. Please contact NestFlow support."


class SubscriptionMissingError(SubscriptionExpiredError):
    code = ErrorCode.SUBSCRIPTION_MISSING
    message = "No active subscription was found for this society."


class PlanLimitExceededError(SubscriptionExpiredError):
    code = ErrorCode.PLAN_LIMIT_EXCEEDED
    message = "Your subscription plan limit has been reached."


# --------------------------------------------------------------------------- #
# 4xx Resource / request
# --------------------------------------------------------------------------- #


class NotFoundError(NestFlowError):
    status_code = 404
    code = ErrorCode.NOT_FOUND
    message = "The requested resource was not found."

    def __init__(self, resource: str = "Resource", **kwargs: Any) -> None:
        super().__init__(f"{resource} was not found.", **kwargs)


class AlreadyExistsError(NestFlowError):
    status_code = 409
    code = ErrorCode.ALREADY_EXISTS
    message = "A record with these details already exists."


class ConflictError(NestFlowError):
    status_code = 409
    code = ErrorCode.CONFLICT
    message = "This action conflicts with the current state of the resource."


class ValidationError(NestFlowError):
    status_code = 422
    code = ErrorCode.VALIDATION_ERROR
    message = "The submitted data is not valid."


class RateLimitedError(NestFlowError):
    status_code = 429
    code = ErrorCode.RATE_LIMITED
    message = "Too many requests. Please slow down and try again shortly."

    def __init__(self, retry_after: int = 60, **kwargs: Any) -> None:
        self.retry_after = retry_after
        super().__init__(**kwargs)


# --------------------------------------------------------------------------- #
# Domain
# --------------------------------------------------------------------------- #


class ProvisioningFailedError(NestFlowError):
    status_code = 500
    code = ErrorCode.PROVISIONING_FAILED
    message = "Society setup could not be completed."

    def __init__(self, step: str, reason: str, **kwargs: Any) -> None:
        self.step = step
        super().__init__(
            f"Society setup failed during '{step}'.",
            details={"step": step, "reason": reason},
            **kwargs,
        )


# --------------------------------------------------------------------------- #
# 5xx Server
# --------------------------------------------------------------------------- #


class DatabaseUnavailableError(NestFlowError):
    status_code = 503
    code = ErrorCode.DATABASE_UNAVAILABLE
    message = "The service is temporarily unavailable. Please try again shortly."


class TenantDatabaseUnavailableError(DatabaseUnavailableError):
    code = ErrorCode.TENANT_DB_UNAVAILABLE
    message = "Your society's data is temporarily unavailable. Please try again shortly."
