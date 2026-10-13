"""Append-only, transactional history. Disabled until migration is approved/applied."""

from __future__ import annotations
from datetime import datetime
import json
import logging
import time
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import StatementError
from config import get_settings
from infrastructure.db.models import ListingObservationORM

_log = logging.getLogger(__name__)


async def append_observation(session, document, *, enabled: bool | None = None):
    if enabled is None:
        enabled = get_settings().ingestion_observation_history_enabled
    if not enabled:
        return
    dialect = session.get_bind().dialect.name
    insert = (
        pg_insert if dialect == "postgresql" else sqlite_insert if dialect == "sqlite" else None
    )
    if insert is None:
        raise RuntimeError("Observation history supports PostgreSQL/SQLite only")
    stmt = (
        insert(ListingObservationORM)
        .values(
            observation_id=document["observation_id"],
            listing_id=document["listing_id"],
            source=document["source"],
            external_id=document["external_id"],
            observed_at=datetime.fromisoformat(document["observed_at"]),
            event_kind=document["event_kind"],
            document=document,
        )
        .on_conflict_do_nothing(index_elements=["observation_id"])
    )
    started = time.perf_counter()
    size = len(json.dumps(document, ensure_ascii=False).encode('utf-8'))
    try:
        result = await session.execute(stmt)
    except Exception as exc:
        # Preserve exception class/retry behavior, but prevent callers' tracebacks
        # from rendering the private document as a SQL parameter.
        if isinstance(exc, StatementError):
            exc.hide_parameters = True
        _log.error('observation_write_failed source=%s event=%s error_type=%s elapsed_ms=%.3f',
            document['source'], document['event_kind'], type(exc).__name__,
            (time.perf_counter()-started)*1000)
        raise
    _log.info('observation_staged source=%s event=%s inserted=%s bytes=%d elapsed_ms=%.3f',
        document['source'], document['event_kind'], result.rowcount, size,
        (time.perf_counter()-started)*1000)
    # No commit: history and listing succeed or roll back in the caller transaction.
