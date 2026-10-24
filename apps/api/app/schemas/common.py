"""Response envelope and shared request shapes.

Every response the API emits is wrapped in :class:`Envelope`. The consistency is
what lets the frontend have exactly one error path.
"""

from __future__ import annotations

from math import ceil
from typing import Annotated, Any, Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class Envelope(BaseModel, Generic[T]):
    success: bool = True
    data: T | None = None
    message: str = ""

    model_config = ConfigDict(from_attributes=True)


class ErrorEnvelope(BaseModel):
    success: bool = False
    code: str
    message: str
    details: dict[str, Any] | None = None
    request_id: str | None = None


class Page(BaseModel, Generic[T]):
    items: list[T]
    page: int
    limit: int
    total: int
    pages: int
    has_next: bool
    has_prev: bool

    @classmethod
    def build(cls, items: list[T], *, page: int, limit: int, total: int) -> Page[T]:
        pages = ceil(total / limit) if limit else 0
        return cls(
            items=items,
            page=page,
            limit=limit,
            total=total,
            pages=pages,
            has_next=page < pages,
            has_prev=page > 1,
        )


class PageParams(BaseModel):
    """Standard pagination query parameters.

    ``limit`` is capped at 100 so no caller can ask for an unbounded result set.
    """

    page: Annotated[int, Query(ge=1)] = 1
    limit: Annotated[int, Query(ge=1, le=100)] = 25
    q: Annotated[str | None, Query(max_length=120)] = None

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.limit


def ok(data: Any = None, message: str = "") -> dict[str, Any]:
    """Build a success envelope."""
    return {"success": True, "data": data, "message": message}


class HealthStatus(BaseModel):
    status: str
    version: str
    environment: str


class ReadinessStatus(BaseModel):
    status: str
    central_database: str
    auth_provider: str
    tenant_engines_cached: int
    checks_passed: bool = Field(default=True)
