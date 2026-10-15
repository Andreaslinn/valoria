"""Bounded official calendar refresh; failure defers conversion, never stops discovery."""
import asyncio
import json
import httpx

from infrastructure.db.database import get_session_factory
from services.ingestion_uf import refresh_calendar
from services.ingestion_state import safe_error


async def run():
    async with httpx.AsyncClient() as http:
        return await refresh_calendar(get_session_factory(), http)


def main():
    try:
        result = asyncio.run(run())
        print(json.dumps(result))
        return 0 if result["calendar_days_saved"] else 1
    except Exception as exc:
        print(json.dumps({"error": safe_error(exc, stage="uf_calendar_refresh")}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
