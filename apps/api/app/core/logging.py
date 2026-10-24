"""Structured logging with secret redaction.

The redaction processor runs on *every* event regardless of call site, so a
future contributor logging a whole request dict cannot leak a bearer token.
"""

from __future__ import annotations

import logging
import sys
from contextvars import ContextVar
from typing import Any

import structlog

request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)
firebase_uid_ctx: ContextVar[str | None] = ContextVar("firebase_uid", default=None)
society_id_ctx: ContextVar[str | None] = ContextVar("society_id", default=None)

SENSITIVE_KEYS = frozenset(
    {
        "authorization",
        "token",
        "id_token",
        "access_token",
        "refresh_token",
        "password",
        "passwd",
        "secret",
        "private_key",
        "firebase_private_key",
        "api_key",
        "apikey",
        "client_secret",
        "payment_provider_secret",
        "card_number",
        "cvv",
        "set-cookie",
        "cookie",
    }
)
REDACTED = "[REDACTED]"


def _redact(value: Any, depth: int = 0) -> Any:
    if depth > 6:
        return value
    if isinstance(value, dict):
        return {
            k: (REDACTED if str(k).lower() in SENSITIVE_KEYS else _redact(v, depth + 1))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return type(value)(_redact(v, depth + 1) for v in value)
    return value


def redact_processor(
    _logger: Any, _name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    return _redact(event_dict)  # type: ignore[return-value]


def context_processor(
    _logger: Any, _name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Attach per-request correlation fields to every event."""
    if (rid := request_id_ctx.get()) is not None:
        event_dict.setdefault("request_id", rid)
    if (uid := firebase_uid_ctx.get()) is not None:
        event_dict.setdefault("firebase_uid", uid)
    if (sid := society_id_ctx.get()) is not None:
        event_dict.setdefault("society_id", sid)
    return event_dict


def configure_logging(*, level: str = "INFO", json_output: bool = False) -> None:
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, level.upper(), logging.INFO),
    )
    # Access logs are emitted by our own middleware with full context; uvicorn's
    # duplicate would be noise without the correlation fields.
    logging.getLogger("uvicorn.access").disabled = True

    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        context_processor,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        redact_processor,
    ]
    processors.append(
        structlog.processors.JSONRenderer()
        if json_output
        else structlog.dev.ConsoleRenderer(colors=True)
    )

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
