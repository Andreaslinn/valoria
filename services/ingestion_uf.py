"""UF resilience ONLY for acquisition: dated calendar, never fabricated conversion."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select

from core.ports.uf_service import UFRateInfo
from infrastructure.db.ingestion_models import IngestionUFCalendar
from infrastructure.db.models import UFRateORM

MONTHS = "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre".split()


def chile_today():
    return datetime.now(ZoneInfo("America/Santiago")).date()


@dataclass(frozen=True)
class IngestionRate:
    exact: UFRateInfo | None
    reference: UFRateInfo | None
    errors: tuple[str, ...] = ()


def parse_calendar(html: str, year: int) -> dict[date, Decimal]:
    result = {}
    for table in BeautifulSoup(html, "html.parser").find_all("table"):
        heading = table.find("h2")
        if heading is None or heading.get_text(strip=True).lower() not in MONTHS:
            continue
        month = MONTHS.index(heading.get_text(strip=True).lower()) + 1
        for tr in table.find_all("tr"):
            cells = tr.find_all(["th", "td"], recursive=False)
            for i in range(0, len(cells) - 1, 2):
                day, amount = (c.get_text(strip=True) for c in cells[i:i+2])
                if not day.isdecimal() or not amount:
                    continue
                try:
                    value = Decimal(amount.replace(".", "").replace(",", "."))
                    rate_date = date(year, month, int(day))
                except (ValueError, InvalidOperation):
                    continue
                if value.is_finite() and Decimal("1000") < value < Decimal("1000000"):
                    if rate_date in result and result[rate_date] != value:
                        raise ValueError("conflicting_calendar_values")
                    result[rate_date] = value
    if not result:
        raise ValueError("empty_official_calendar")
    return result


async def refresh_calendar(factory, http, *, today=None, attempts=2, sleep=asyncio.sleep):
    """At most two attempts per year, year-boundary aware; persist all published days."""
    today = today or chile_today()
    saved = 0
    errors = []
    years = [today.year] + ([today.year + 1] if today.month == 12 else [])
    for year in years:
        values = None
        for attempt in range(min(2, max(1, attempts))):
            try:
                response = await http.get(f"https://www.sii.cl/valores_y_fechas/uf/uf{year}.htm",
                                          timeout=15, follow_redirects=False)
                response.raise_for_status()
                if len(response.content) > 2_000_000:
                    raise ValueError("calendar_response_too_large")
                values = parse_calendar(response.text, year)
                break
            except (httpx.HTTPError, ValueError) as exc:
                errors.append(type(exc).__name__)
                if attempt + 1 < min(2, max(1, attempts)):
                    await sleep(2 ** attempt)
        if values is None:
            continue
        async with factory() as s:
            for day, value in values.items():
                existing = await s.get(IngestionUFCalendar, day)
                if existing is None:
                    s.add(IngestionUFCalendar(date=day, value=value, source="sii.cl",
                                              fetched_at=datetime.now(UTC)))
                else:
                    existing.value, existing.fetched_at = value, datetime.now(UTC)
                saved += 1
            await s.commit()
    return {"calendar_days_saved": saved, "errors": errors}


def _info(row, *, stale=False):
    return UFRateInfo(rate=Decimal(getattr(row, "value", None) or row.value_clp),
                      source=row.source, rate_date=row.date, fetched_at=row.fetched_at,
                      is_stale=stale, stale_reason="reference_only_not_today" if stale else None)


async def resolve_ingestion_rate(factory, http, *, today=None, refresh=True):
    today = today or chile_today()
    errors = ()
    async with factory() as s:
        exact = await s.get(IngestionUFCalendar, today)
        # Reuse real dated API snapshots without changing valuation's UF client/cache.
        exact = exact or await s.scalar(select(UFRateORM).where(UFRateORM.date == today))
    if exact is None and refresh:
        result = await refresh_calendar(factory, http, today=today)
        errors = tuple(result["errors"])
        async with factory() as s:
            exact = await s.get(IngestionUFCalendar, today)
    if exact is not None:
        info = _info(exact)
        return IngestionRate(info, info, errors)
    async with factory() as s:
        a = await s.scalar(select(IngestionUFCalendar).where(IngestionUFCalendar.date <= today)
                           .order_by(IngestionUFCalendar.date.desc()).limit(1))
        b = await s.scalar(select(UFRateORM).where(UFRateORM.date <= today)
                           .order_by(UFRateORM.date.desc()).limit(1))
    latest = max((r for r in (a, b) if r is not None), key=lambda r: r.date, default=None)
    return IngestionRate(None, _info(latest, stale=True) if latest else None, errors)


def annotate_pending(raw, resolution):
    """Latest known UF is a transparent reference; canonical CLP remains pending."""
    import copy
    result = copy.deepcopy(raw)
    metadata = result.setdefault("raw_metadata", {})
    metadata.update(price_clp_missing_reason="missing_uf_rate", conversion_status="pending")
    reference = resolution.reference if resolution else None
    if reference:
        amount = result.get("price_uf") or metadata.get("price_uf")
        metadata.update(reference_uf_rate=str(reference.rate),
                        reference_uf_date=reference.rate_date.isoformat(),
                        provisional_price_clp=str(Decimal(str(amount)) * reference.rate))
    result["price_clp"] = None
    return result
