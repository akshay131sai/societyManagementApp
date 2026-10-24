"""API v1 aggregator.

Modules are mounted here. The path layout is client-agnostic — there is no
``/api/web`` or ``/api/mobile``; web and mobile consume identical endpoints.
"""

from fastapi import APIRouter

from app.api.v1 import (
    auth,
    billing,
    community,
    health,
    notifications,
    operations,
    platform,
    reports,
    society,
    structure,
    utilities,
)

api_router = APIRouter()

api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(platform.router)
api_router.include_router(society.router)
api_router.include_router(structure.router)
api_router.include_router(billing.router)
api_router.include_router(utilities.router)
api_router.include_router(operations.router)
api_router.include_router(community.router)
api_router.include_router(notifications.router)
api_router.include_router(reports.router)
