from types import SimpleNamespace

import ui.app as app
from ui.app import BETA_NAV_ITEMS, DEMO_NAV_ITEMS, NAV_ITEMS
from ui.app_shell import get_visible_demo_nav_items, get_visible_nav_items
from ui.lab import LAB_DISCLAIMER


def test_demo_navigation_is_product_lab_only() -> None:
    assert DEMO_NAV_ITEMS == [
        "Dashboard Lab",
        "Alertas Lab",
        "Checklist Lab",
        "Decision Board Lab",
        "Lab Feedback",
        "Buyer Journey",
        "Owner Journey",
        "Risk Report",
        "Autofact Demo",
        "Portfolio Demo",
    ]


def test_real_navigation_does_not_show_lab_modules() -> None:
    assert NAV_ITEMS == ["Tasar propiedad", "Radar", "Portafolio", "Alertas", "Estado"]
    assert not set(DEMO_NAV_ITEMS).intersection(NAV_ITEMS)


def test_beta_navigation_is_focused_by_default(monkeypatch) -> None:
    monkeypatch.setenv("BETA_MODE", "true")
    monkeypatch.delenv("BETA_SHOW_PORTFOLIO", raising=False)
    monkeypatch.delenv("BETA_SHOW_ALERTS", raising=False)
    monkeypatch.delenv("BETA_SHOW_STATUS", raising=False)

    assert BETA_NAV_ITEMS == ["Tasar propiedad", "Radar", "Estado"]
    assert get_visible_nav_items() == BETA_NAV_ITEMS


def test_beta_navigation_can_reenable_non_core_pages(monkeypatch) -> None:
    monkeypatch.setenv("BETA_MODE", "true")
    monkeypatch.setenv("BETA_SHOW_PORTFOLIO", "true")
    monkeypatch.setenv("BETA_SHOW_ALERTS", "true")

    assert get_visible_nav_items() == ["Tasar propiedad", "Radar", "Portafolio", "Alertas", "Estado"]


def test_beta_hides_demo_pages_by_default(monkeypatch) -> None:
    monkeypatch.setenv("BETA_MODE", "true")
    monkeypatch.delenv("BETA_SHOW_PRODUCT_LAB", raising=False)

    assert "Dashboard Lab" not in get_visible_demo_nav_items()
    assert "Risk Report" not in get_visible_demo_nav_items()


def test_lab_global_disclaimer_is_explicit() -> None:
    assert "Modo Lab" in LAB_DISCLAIMER
    assert "No usar para decisiones reales" in LAB_DISCLAIMER


def test_tasar_playground_radar_routes_to_redesign(monkeypatch) -> None:
    calls = []
    client = object()

    monkeypatch.setattr(app, "is_tasar_playground_mode", lambda: True)
    monkeypatch.setattr(app.radar, "render", lambda _client: calls.append("legacy"))
    monkeypatch.setattr(app.radar_lab, "render", lambda _client: calls.append("lab"))
    monkeypatch.setitem(
        __import__("sys").modules,
        "ui.redesign.radar_view",
        SimpleNamespace(render=lambda received_client: calls.append(received_client)),
    )

    app._render_page("Radar", client, "http://127.0.0.1:8000")

    assert calls == [client]
