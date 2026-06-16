from __future__ import annotations

from ui.pages import tracking


def test_market_filters_cover_type_price_surface_source_and_status() -> None:
    listings = [
        {
            "id": 1,
            "comuna": "nunoa",
            "property_type": "apartment",
            "source": "yapo",
            "status": "active",
            "price_clp": 180_000_000,
            "m2": 75,
        },
        {
            "id": 2,
            "comuna": "nunoa",
            "property_type": "house",
            "source": "yapo",
            "status": "active",
            "price_clp": 350_000_000,
            "m2": 140,
        },
        {
            "id": 3,
            "comuna": "providencia",
            "property_type": "apartment",
            "source": "other",
            "status": "inactive",
            "price_clp": None,
            "m2": None,
        },
    ]

    filtered = tracking._filter_listings(
        listings,
        comuna="nunoa",
        property_type="apartment",
        source="yapo",
        status="active",
        min_price=150_000_000,
        max_price=220_000_000,
        min_m2=60,
        max_m2=90,
        view="Cards",
    )

    assert [item["id"] for item in filtered] == [1]


def test_missing_listing_values_render_as_unavailable() -> None:
    assert tracking._format_m2(None) == "No disponible"
    assert tracking._text(None) == "No disponible"
    assert tracking._property_type_label("unknown") == "No disponible"


def test_surface_falls_back_to_built_or_usable_area() -> None:
    assert tracking._listing_surface_m2({"m2": None, "built_area_m2": 72}) == 72
    assert tracking._listing_surface_m2({"usable_area_m2": "64.5"}) == 64.5
    assert tracking._listing_surface_m2({}) is None


def test_real_portfolio_loader_returns_market_and_watchlist(monkeypatch) -> None:
    class FakeClient:
        def list_watchlist(self, token: str):
            assert token == "token"
            return [{"id": 1, "title": "Guardada"}]

        def list_listings(self, *, token: str, limit: int):
            assert token == "token"
            assert limit == 100
            return [{"id": 2, "title": "Mercado"}]

    monkeypatch.setattr(tracking, "get_token", lambda: "token")
    monkeypatch.setattr(tracking.st, "success", lambda *args, **kwargs: None)

    market, watchlist = tracking._load_real_portfolio(FakeClient(), 100)

    assert market == [{"id": 2, "title": "Mercado"}]
    assert watchlist == [{"id": 1, "title": "Guardada"}]
