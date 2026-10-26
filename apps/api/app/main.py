"""NestFlow API — application entry point.

Wires middleware, exception handlers, routers and lifecycle. Business logic
lives in services; this module only assembles the application.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import openapi as openapi_docs
from app.api.v1.router import api_router
from app.core.config import AuthProvider, get_settings
from app.core.errors import (
    AlreadyExistsError,
    ConflictError,
    ErrorCode,
    NestFlowError,
    RateLimitedError,
)
from app.core.firebase import get_token_verifier
from app.core.logging import (
    configure_logging,
    firebase_uid_ctx,
    request_id_ctx,
    society_id_ctx,
)
from app.core.ratelimit import get_rate_limiter
from app.database.central import dispose_central_engine, get_central_engine
from app.database.manager import dispose_tenant_manager
from app.realtime.hub import get_hub
from app.workers.scheduler import shutdown_scheduler, start_scheduler

log = structlog.get_logger(__name__)

SAFE_PATHS = frozenset({"/health", "/health/ready", "/health/info", "/docs", "/redoc", "/openapi.json"})


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(level=settings.LOG_LEVEL, json_output=settings.LOG_JSON)

    log.info(
        "app.starting",
        name=settings.APP_NAME,
        version=settings.APP_VERSION,
        environment=settings.ENVIRONMENT.value,
        auth_provider=settings.AUTH_PROVIDER.value,
    )

    if settings.AUTH_PROVIDER is AuthProvider.DEV:
        # Loud, unmissable, and impossible to reach in production (Settings
        # refuses to construct there).
        for line in (
            "=" * 78,
            "  SECURITY WARNING — DEVELOPMENT AUTHENTICATION IS ACTIVE",
            "  /auth/login accepts any 'dev:<email>' with NO credential check.",
            "  Set AUTH_PROVIDER=firebase before exposing this service.",
            "=" * 78,
        ):
            log.warning("app.dev_auth_banner", banner=line)

    if settings.JWT_SECRET_KEY is None:
        log.warning(
            "app.dev_jwt_secret",
            message="JWT_SECRET_KEY is unset; signing tokens with the public development key.",
        )

    get_central_engine()
    get_token_verifier()
    start_scheduler()

    yield

    log.info("app.stopping")
    # Stop the clock before the engines: a sweep that starts during teardown
    # would open a tenant session against a pool that is being disposed.
    shutdown_scheduler()
    get_hub().clear()
    await dispose_tenant_manager()
    await dispose_central_engine()


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description=openapi_docs.describe(settings),
        openapi_tags=openapi_docs.TAGS,
        swagger_ui_parameters=openapi_docs.SWAGGER_UI_PARAMETERS,
        docs_url=settings.docs_url,
        redoc_url=settings.redoc_url,
        openapi_url=None if settings.is_production else f"{settings.API_V1_PREFIX}/openapi.json",
        lifespan=lifespan,
    )

    _register_middleware(app, settings)
    _register_exception_handlers(app)
    app.include_router(api_router, prefix=settings.API_V1_PREFIX)
    openapi_docs.install(app)
    return app


# --------------------------------------------------------------------------- #
# Middleware
# --------------------------------------------------------------------------- #


def _register_middleware(app: FastAPI, settings: Any) -> None:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        # Token-based, not cookie-based: no credentials means no wildcard risk
        # and no CSRF surface.
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
        expose_headers=["X-Request-Id", "Retry-After", "X-RateLimit-Remaining"],
        max_age=600,
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next: Any) -> Any:
        request_id = request.headers.get("X-Request-Id") or uuid.uuid4().hex[:16]
        request.state.request_id = request_id
        request_id_ctx.set(request_id)
        firebase_uid_ctx.set(None)
        society_id_ctx.set(None)

        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            log.exception(
                "request.failed",
                method=request.method,
                path=request.url.path,
                duration_ms=duration_ms,
            )
            raise

        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        response.headers["X-Request-Id"] = request_id

        # Security headers. HSTS is only meaningful over TLS and is set by the
        # reverse proxy in production, but harmless to assert here too.
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        if settings.is_production:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )

        log.info(
            "request.completed",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=duration_ms,
        )
        return response

    if settings.RATE_LIMIT_ENABLED:

        @app.middleware("http")
        async def rate_limit(request: Request, call_next: Any) -> Any:
            if request.url.path.endswith(SAFE_PATHS_SUFFIXES) or request.method == "OPTIONS":
                return await call_next(request)

            limiter = get_rate_limiter()
            auth = request.headers.get("authorization", "")
            if auth.lower().startswith("bearer "):
                # Key on the token, not the resolved uid: the principal has not
                # been resolved yet at middleware time.
                key = f"tok:{hash(auth[7:])}"
                limit = (
                    settings.RATE_LIMIT_WRITE_PER_MIN
                    if request.method in {"POST", "PUT", "PATCH", "DELETE"}
                    else settings.RATE_LIMIT_USER_PER_MIN
                )
            else:
                key = f"ip:{request.client.host if request.client else 'unknown'}"
                limit = settings.RATE_LIMIT_ANON_PER_MIN

            decision = limiter.check(key, limit)
            if not decision.allowed:
                return _error_response(
                    RateLimitedError(retry_after=decision.retry_after),
                    getattr(request.state, "request_id", None),
                )

            response = await call_next(request)
            response.headers["X-RateLimit-Remaining"] = str(decision.remaining)
            return response


SAFE_PATHS_SUFFIXES = ("/health", "/health/ready", "/health/info", "/openapi.json")


# --------------------------------------------------------------------------- #
# Exception handlers
# --------------------------------------------------------------------------- #


def _error_response(exc: NestFlowError, request_id: str | None) -> JSONResponse:
    headers: dict[str, str] = {}
    if isinstance(exc, RateLimitedError):
        headers["Retry-After"] = str(exc.retry_after)
    if request_id:
        headers["X-Request-Id"] = request_id

    return JSONResponse(
        status_code=exc.status_code,
        headers=headers,
        content={
            "success": False,
            "code": exc.code.value,
            "message": exc.message,
            "details": exc.details,
            "request_id": request_id,
        },
    )


def _trigger_message(exc: IntegrityError) -> str:
    """The first line of a PL/pgSQL RAISE, which our triggers write for humans."""
    raw = str(getattr(exc.orig, "args", [""])[0] if getattr(exc.orig, "args", None) else exc.orig)
    first = raw.strip().splitlines()[0].strip()
    return first or "This action conflicts with the current state of the record."


def _register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(NestFlowError)
    async def handle_nestflow(request: Request, exc: NestFlowError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        if exc.status_code >= 500:
            log.error("error.server", code=exc.code.value, message=exc.message, exc_info=True)
        else:
            log.info("error.client", code=exc.code.value, status=exc.status_code)
        return _error_response(exc, request_id)

    @app.exception_handler(RequestValidationError)
    async def handle_validation(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        fields = [
            {
                "field": ".".join(str(p) for p in err["loc"][1:]) or str(err["loc"][0]),
                "message": err["msg"],
            }
            for err in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "success": False,
                "code": ErrorCode.VALIDATION_ERROR.value,
                "message": "The submitted data is not valid.",
                "details": {"fields": fields},
                "request_id": getattr(request.state, "request_id", None),
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {
            401: ErrorCode.UNAUTHENTICATED,
            403: ErrorCode.PERMISSION_DENIED,
            404: ErrorCode.NOT_FOUND,
            409: ErrorCode.CONFLICT,
            429: ErrorCode.RATE_LIMITED,
        }.get(exc.status_code, ErrorCode.INTERNAL_ERROR)
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "success": False,
                "code": code.value,
                "message": str(exc.detail),
                "details": None,
                "request_id": getattr(request.state, "request_id", None),
            },
        )

    @app.exception_handler(IntegrityError)
    async def handle_integrity(request: Request, exc: IntegrityError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        sqlstate = getattr(exc.orig, "sqlstate", None)

        # Our immutability triggers raise restrict_violation with a message
        # written for a person ("Bill NF/... is published; issue a credit note
        # instead"). Surfacing that beats a generic conflict.
        if sqlstate in {"23001", "P0001"}:
            message = _trigger_message(exc)
            log.warning("db.rule_violation", sqlstate=sqlstate, message=message)
            return _error_response(ConflictError(message), request_id)

        # Other constraint violations are a client problem too, but the driver
        # message can leak schema detail — so it is logged, not returned.
        log.warning("db.integrity_error", sqlstate=sqlstate, error=str(exc.orig))
        return _error_response(
            AlreadyExistsError(
                "This action conflicts with an existing record or a data constraint."
            ),
            request_id,
        )

    @app.exception_handler(SQLAlchemyError)
    async def handle_sqlalchemy(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        log.error("db.error", error=str(exc), exc_info=True)
        from app.core.errors import DatabaseUnavailableError

        return _error_response(
            DatabaseUnavailableError(), getattr(request.state, "request_id", None)
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        log.error("error.unhandled", error=str(exc), exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "code": ErrorCode.INTERNAL_ERROR.value,
                "message": "An unexpected error occurred. Please try again.",
                "details": None,
                "request_id": request_id,
            },
        )


app = create_app()
