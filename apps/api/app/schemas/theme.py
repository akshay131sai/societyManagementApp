"""Theme schemas.

Only the four brand colours, a mode and a radius cross the wire. Every derived
token (hover, active, subtle, foreground) is computed on the client in OKLCH —
see docs/architecture/theme-system.md section 3.

The hex pattern is enforced here *and* by a database CHECK constraint. Both
matter: these values are written into CSS custom properties.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

HexColor = Annotated[
    str,
    Field(pattern=r"^#[0-9A-Fa-f]{6}$", description="6-digit hex colour, e.g. #4F46E5"),
]

THEME_PRESETS: dict[str, str] = {
    "indigo": "#4F46E5",
    "blue": "#2563EB",
    "purple": "#7C3AED",
    "pink": "#DB2777",
    "green": "#059669",
    "orange": "#EA580C",
}


class ThemeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    theme_mode: str
    primary_color: str
    secondary_color: str
    accent_color: str
    sidebar_color: str
    border_radius: int
    logo_url: str | None = None
    society_name: str | None = None
    updated_at: datetime | None = None


class ThemeUpdate(BaseModel):
    theme_mode: Annotated[str | None, Field(pattern=r"^(light|dark|system)$")] = None
    primary_color: HexColor | None = None
    secondary_color: HexColor | None = None
    accent_color: HexColor | None = None
    sidebar_color: HexColor | None = None
    border_radius: Annotated[int | None, Field(ge=0, le=32)] = None
    logo_url: Annotated[str | None, Field(max_length=500)] = None


class ThemePresets(BaseModel):
    presets: dict[str, str] = THEME_PRESETS
    default_radius: int = 14
    modes: list[str] = ["light", "dark", "system"]
