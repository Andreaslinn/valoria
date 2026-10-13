from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
import pytest
from api.v1.listings import _listing_out
from api.v1.watchlist import _watchlist_out
from core.ports.uf_service import UFRateInfo
from tests.unit.factories import make_listing
from infrastructure.db.mappers import listing_to_orm


@pytest.mark.parametrize("observed", [None, datetime(2026, 6, 5, 16, 23, tzinfo=UTC)])
def test_serializers_preserve_observed_date_and_null(observed):
    listing = make_listing(status="removed")
    listing.last_seen_at = observed
    info = UFRateInfo(rate=Decimal(39000), source="test", is_fallback=False)
    assert _listing_out(listing, uf_info=info).last_seen_at == observed
    orm = listing_to_orm(listing)
    orm.last_seen_at = observed
    saved = SimpleNamespace(id=1, listing_id=298, saved_at=datetime(2026, 7, 1, tzinfo=UTC),
                            saved_price_clp=180000000, saved_price_uf=None,
                            status="active", note=None, listing=orm)
    result = _watchlist_out(saved, uf_info=info)
    assert result.last_seen_at == observed
    assert result.listing_status == "removed"
