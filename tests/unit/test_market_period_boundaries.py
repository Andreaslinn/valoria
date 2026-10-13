from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from services.market_dashboard_overview import period_bounds, _activity_for_period, _daily_pulse, CHILE
from services.market_intelligence import MarketDataset


def test_midnight_and_dst_calendar_boundaries():
    # Chile's September 2026 transition skips an hour inside this seven-date window.
    start, end = period_bounds(datetime(2026, 9, 10, 12, tzinfo=UTC), 7)
    assert start.astimezone(CHILE).date().isoformat() == "2026-09-03"
    assert end.astimezone(CHILE).date().isoformat() == "2026-09-10"
    assert (end-start).total_seconds() == 7*86400-3600
    assert period_bounds(end-timedelta(microseconds=1), 7) != (start,end)
    assert period_bounds(end, 7) == (start,end)


def test_chart_kpi_and_partition_reconcile_at_boundaries():
    now = datetime(2026, 10, 12, 12, tzinfo=UTC)
    start,end = period_bounds(now,30)
    rows = [SimpleNamespace(id=i, created_at=dt, scraped_at=dt) for i,dt in enumerate(
        [start-timedelta(microseconds=1), start, end-timedelta(microseconds=1), end, now])]
    dataset = MarketDataset(now=now, scoped=rows, active=rows, removed=[], price_points=[])
    events = [(r.id,r.created_at) for r in rows]
    activity = _activity_for_period(dataset,events=events,days=30)
    series = _daily_pulse(dataset,events=events,cutoff=start)
    assert len(series)==30
    assert activity["new_listings"] == sum(p["new_listings"] for p in series) == 2
    assert activity["price_drop_events"] == sum(p["price_drop_events"] for p in series) == 2
    partitions = [MarketDataset(now=now,scoped=rows[:2],active=[],removed=[],price_points=[]),
                  MarketDataset(now=now,scoped=rows[2:],active=[],removed=[],price_points=[])]
    assert sum(_activity_for_period(p,events=[],days=30)["new_listings"] for p in partitions)==2
