"""Read-only detail acquisition using the existing verified-session loader.

The scheduled runner owns session updates. Lookup never saves cookies, logs
session material, solves challenges or retries a rejected upstream request.
"""
from contextlib import asynccontextmanager
import logging
import os
from pathlib import Path

import httpx

from scripts.portal_session import load_session
from scripts.portal_smoke import DEFAULT_HEADERS

_log = logging.getLogger(__name__)


class PortalAcquisitionError(RuntimeError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


@asynccontextmanager
async def portal_lookup_client():
    configured = os.environ.get("PORTAL_SESSION_FILE")
    if not configured:
        raise PortalAcquisitionError("portal_session_unavailable")
    path = Path(configured)
    if (path.parent / "reauth_required.json").exists():
        raise PortalAcquisitionError("portal_reverification_required")
    try:
        jar = load_session(path)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        _log.warning("Portal verified-session unavailable; exception_type=%s", type(exc).__name__)
        raise PortalAcquisitionError("portal_session_unavailable") from exc
    async with httpx.AsyncClient(cookies=jar, headers=DEFAULT_HEADERS,
                                timeout=12.0, follow_redirects=False) as client:
        yield client
