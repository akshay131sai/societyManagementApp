"""Report schemas.

Every report shares one envelope — ``ReportResult`` — carrying columns, rows
and totals. That is what lets one screen render all of them, one CSV writer
export all of them, and a new report ship without a frontend release.

The cost of the uniformity is that a row is ``dict[str, Any]`` rather than a
typed model. It is paid back in the ``columns`` list, which tells the client the
type, alignment and label of every field it is about to render.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any

from pydantic import BaseModel, Field


class ColumnType(StrEnum):
    TEXT = "text"
    NUMBER = "number"
    MONEY = "money"
    DATE = "date"
    PERCENT = "percent"
    STATUS = "status"


class ReportColumn(BaseModel):
    key: str
    label: str
    type: ColumnType = ColumnType.TEXT
    """Drives alignment and formatting. ``money`` gets Indian digit grouping and
    right alignment; ``status`` gets a badge."""

    total: bool = False
    """Whether this column is summed in the footer."""


class ReportMeta(BaseModel):
    key: str
    title: str
    description: str
    permission: str
    accepts_period: bool = True
    accepts_dates: bool = True


class ReportResult(BaseModel):
    key: str
    title: str
    description: str
    generated_at: date
    period_label: str | None = None
    from_date: date | None = None
    to_date: date | None = None
    columns: list[ReportColumn]
    rows: list[dict[str, Any]]
    totals: dict[str, Decimal | int] = {}
    summary: dict[str, Any] = {}
    """Headline figures rendered above the table — collection rate, open count,
    average resolution time. Report-specific by design."""

    row_count: int = 0
    truncated: bool = False
    """True when the row cap was hit. A report that silently drops rows is a
    report that lies, so the client says so."""


class ReportRequest(BaseModel):
    """Filters common to every report.

    A report that does not use one ignores it rather than rejecting it — the
    client sends the same filter bar for all of them.
    """

    from_date: date | None = None
    to_date: date | None = None
    period_key: Annotated[str | None, Field(max_length=20)] = None
    building_id: str | None = None
    limit: Annotated[int, Field(ge=1, le=5000)] = 1000

    # The from/to ordering is checked in the service rather than here. This
    # model is resolved through ``Depends()``, and a model_validator failure on
    # a dependency escapes FastAPI's request-validation handling as a 500
    # instead of the 422 envelope the client knows how to render.
