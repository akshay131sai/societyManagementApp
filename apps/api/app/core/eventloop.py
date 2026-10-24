"""Event loop selection.

psycopg's async mode cannot run on Windows' default ``ProactorEventLoop`` — it
needs a ``SelectorEventLoop``. Rather than reach for the deprecated
``set_event_loop_policy`` (slated for removal in Python 3.16), every entry point
we control passes ``loop_factory`` explicitly:

    asyncio.run(main(), loop_factory=loop_factory())

On Linux and macOS this is a no-op and the default loop is used, so the
production path is unaffected.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable

IS_WINDOWS = sys.platform == "win32"


def loop_factory() -> Callable[[], asyncio.AbstractEventLoop] | None:
    """Loop factory for ``asyncio.run`` / ``asyncio.Runner``.

    Returns ``None`` off Windows so the platform default is kept.
    """
    if IS_WINDOWS:
        return asyncio.SelectorEventLoop
    return None


def run(coro: object) -> object:
    """``asyncio.run`` with the right loop for this platform."""
    return asyncio.run(coro, loop_factory=loop_factory())  # type: ignore[arg-type]
