"""OpenAPI / Swagger UI configuration.

Swagger is served at ``/docs`` and ReDoc at ``/redoc`` outside production.
This module only shapes what those pages show; it changes no behaviour.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from app.core.config import AuthProvider, Settings

# Order here is the order of sections in Swagger UI.
TAGS: list[dict[str, str]] = [
    {"name": "health", "description": "Liveness, readiness and build info. No authentication."},
    {"name": "auth", "description": "The current principal, its permissions and session bootstrap (`/auth/me`)."},
    {"name": "platform", "description": "**SUPER_ADMIN only.** Societies, plans, subscriptions, platform users and audit logs."},
    {"name": "society", "description": "Society profile, settings, dashboard, theme, users and roles."},
    {"name": "structure", "description": "Buildings, blocks, floors, flats, residents and family members."},
    {"name": "billing", "description": "Bill templates and assignments, billing periods and runs, bills and payments."},
    {"name": "electricity", "description": "Electricity meter readings and consumption trends."},
    {"name": "water", "description": "Water meter readings and consumption trends."},
    {"name": "utilities", "description": "Vehicles, pets, parking slots, and the resident and utilities dashboards."},
    {"name": "complaints", "description": "Complaint tickets: raise, assign, comment, resolve."},
    {"name": "maintenance", "description": "Recurring maintenance schedules and the tasks they generate."},
    {"name": "housekeeping", "description": "Housekeeping schedules and tasks."},
    {"name": "visitors", "description": "Visitor passes, pre-approvals, gate check-in and entry log."},
    {"name": "security", "description": "Security dashboard and incident reports."},
    {"name": "notices", "description": "Society notices, including scheduled publishing."},
    {"name": "amenities", "description": "Amenities and their bookings."},
    {"name": "notifications", "description": "In-app notification feed, read state and realtime socket status."},
    {"name": "reports", "description": "Downloadable society reports."},
]

_DESCRIPTION = """\
Multi-tenant society management API. Every response is wrapped in a
success/error envelope; the tenant is resolved server-side from the
authenticated principal and is never accepted from the request.

All endpoints live under `{prefix}`.

## Authentication

Every endpoint except `/auth/login`, `/auth/refresh`, `/auth/logout` and
`/health` requires a NestFlow **access token** (a JWT).

1. Call `POST {prefix}/auth/login` with `{{"id_token": "..."}}` (see below).
2. Copy `access_token` from the response, click **Authorize**, and paste it
   (without the `Bearer ` prefix).
3. The access token lasts `expires_in` seconds. Call `POST {prefix}/auth/refresh`
   with the `refresh_token` for a new pair — each refresh token works once.
{auth_help}
The token is remembered across page reloads in this browser.
"""

_DEV_AUTH_HELP = """
**Development auth is active.** The `id_token` for `/auth/login` is
`dev:<email>` of any existing user — no password is checked. For example:

| `id_token` | Role |
|---|---|
| `dev:superadmin@nestflow.in` | Super admin (platform endpoints) |
| `dev:admin@greenvalley.in` | Society admin — Green Valley Residency |
| `dev:resident@greenvalley.in` | Flat owner — Green Valley Residency |
| `dev:guard@greenvalley.in` | Security guard — Green Valley Residency |

Seeded users vary by database; `python -m app.cli list-societies` shows what exists.
"""

_FIREBASE_AUTH_HELP = """
The `id_token` for `/auth/login` is a Firebase ID token. Sign in to the web app
and copy it from `firebase.auth().currentUser.getIdToken()`.
"""

SWAGGER_UI_PARAMETERS: dict[str, Any] = {
    "persistAuthorization": True,
    "docExpansion": "none",
    "filter": True,
    "displayRequestDuration": True,
    "tryItOutEnabled": True,
}


def describe(settings: Settings) -> str:
    help_text = _DEV_AUTH_HELP if settings.AUTH_PROVIDER is AuthProvider.DEV else _FIREBASE_AUTH_HELP
    return _DESCRIPTION.format(prefix=settings.API_V1_PREFIX, auth_help=help_text)


def install(app: FastAPI) -> None:
    """Keep only the most specific tag on each operation.

    Nested routers inherit their parent's tags, so ``/complaints`` would be
    listed under both "operations" and "complaints". The child's tag is
    always last.
    """
    generate = app.openapi

    def openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = generate()
        for path in schema.get("paths", {}).values():
            for operation in path.values():
                tags = operation.get("tags")
                if isinstance(tags, list) and len(tags) > 1:
                    operation["tags"] = tags[-1:]
        return schema

    app.openapi = openapi  # type: ignore[method-assign]
