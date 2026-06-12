from __future__ import annotations

from pathlib import Path


UI_FILES = [
    Path("ui/valuation/form.py"),
    Path("ui/pages/tasacion.py"),
    Path("ui/redesign/tasar_playground.py"),
]


def test_ui_does_not_import_listing_url_lookup_service_directly() -> None:
    for path in UI_FILES:
        source = path.read_text(encoding="utf-8")

        assert "services.listing_url_lookup" not in source
        assert "lookup_listing_url import" not in source


def test_ui_does_not_import_product_usage_service_directly() -> None:
    for path in Path("ui").rglob("*.py"):
        source = path.read_text(encoding="utf-8")

        assert "services.product_usage" not in source
