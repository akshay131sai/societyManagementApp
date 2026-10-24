"""Development server entry point.

    python run.py

Prefer this over ``uvicorn app.main:app`` on Windows: psycopg's async mode
cannot run on the default ``ProactorEventLoop``, so the server is started with
``loop="none"`` and the loop is created explicitly by ``asyncio.run``. On Linux
and macOS this behaves identically to a plain uvicorn launch.
"""

from __future__ import annotations

import asyncio

import uvicorn

from app.core.config import get_settings
from app.core.eventloop import loop_factory


def main() -> None:
    settings = get_settings()
    config = uvicorn.Config(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        # We own the loop; uvicorn must not install its own.
        loop="none",
        log_config=None,
        access_log=False,
        reload=False,
    )
    server = uvicorn.Server(config)
    asyncio.run(server.serve(), loop_factory=loop_factory())


if __name__ == "__main__":
    main()
