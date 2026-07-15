from __future__ import annotations

from collections import Counter
from pathlib import Path

from api.main import app

REQUIRED_DASHBOARD_ROUTES = {
    "/api/v1/market/briefing",
    "/api/v1/market/liquidity/summary",
    "/api/v1/market/microzones/summary",
    "/api/v1/market/pulse",
    "/api/v1/market/communes/summary",
    "/api/v1/market/dynamism/summary",
    "/api/v1/radar/summary",
}


def test_dashboard_routes_are_registered_on_main_app() -> None:
    paths = {route.path for route in app.routes}

    assert paths >= REQUIRED_DASHBOARD_ROUTES


def test_main_app_has_no_duplicate_routes() -> None:
    route_keys = [
        (route.path, tuple(sorted(getattr(route, "methods", ()) or ())))
        for route in app.routes
    ]
    duplicate_paths = [
        path for path, count in Counter(route_keys).items() if count > 1
    ]

    assert duplicate_paths == []


def test_radar_summary_route_does_not_resolve_heavy_detector() -> None:
    route = next(route for route in app.routes if route.path == "/api/v1/radar/summary")
    dependency_call_names = {
        getattr(dependant.call, "__name__", str(dependant.call))
        for dependant in route.dependant.dependencies
    }

    assert "get_radar_service" not in dependency_call_names


def test_dashboard_radar_panel_does_not_turn_summary_errors_into_zero() -> None:
    source = Path("frontend/src/features/dashboard/DashboardWorkspace.tsx").read_text(encoding="utf-8")

    assert 'error: "Resumen Radar no disponible"' in source
    assert "state.error ||" in source
    assert "ready_for_radar_count ?? 0" not in source
    assert "fresh_candidates_count ?? 0" not in source
