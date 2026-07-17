from __future__ import annotations

import json
from decimal import Decimal

import httpx

from config.portal_targets import PORTAL_BASE_URL
from scripts.portal_http_dry_run import PortalHttpDryRun, build_portal_target_url


def _target() -> dict[str, object]:
    return {
        "label": "santiago_sale_apartment",
        "operation": "venta",
        "property_type": "apartment",
        "comuna": "Santiago",
        "base_url": PORTAL_BASE_URL,
        "enabled": True,
        "max_pages": 2,
    }


def _cards(*ids: str) -> str:
    return "".join(
        f"""<li class='ui-search-layout__item'><div class='poly-card'>
        <a class='poly-component__title' href='/MLC-{external_id}-x'>Listing {external_id}</a>
        <div class='poly-component__price'>UF 3.000</div>
        <span class='poly-component__location'>Santiago, Región Metropolitana</span>
        </div></li>"""
        for external_id in ids
    )


def _detail(external_id: str) -> str:
    state = {
        "appProps": {
            "pageProps": {
                "initialState": {
                    "id": f"MLC-{external_id}",
                    "components": [
                        {"id": "header", "title": f"Listing {external_id}"},
                        {"id": "price", "price": {"currency_id": "CLF", "value": 3000}},
                        {"id": "location", "content_rows": [{"title": {"text": "Santiago, Región Metropolitana"}}]},
                    ],
                    "breadcrumb": {"itemListElement": [{"item": {"name": "Santiago"}}]},
                }
            }
        }
    }
    return "<html><body><script id='__NORDIC_RENDERING_CTX__'>_n.ctx.r=" + json.dumps(state) + ";</script></body></html>"


async def test_dry_run_paginates_deduplicates_and_keeps_only_rm_details():
    target = _target()
    base = build_portal_target_url(target)  # type: ignore[arg-type]
    second = base + "_Desde_49"

    async def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == base:
            return httpx.Response(200, text=f"<html><body>{_cards('1', '2')}</body></html>")
        if url == second:
            return httpx.Response(200, text=f"<html><body>{_cards('1', '3')}</body></html>")
        if "MLC-" in url:
            external_id = url.split("MLC-", 1)[1].split("-x", 1)[0]
            return httpx.Response(200, text=_detail(external_id))
        raise AssertionError(url)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        report = await PortalHttpDryRun(
            client=client,
            targets=[target],  # type: ignore[list-item]
            max_pages_per_target=2,
            max_details=3,
            pause_s=0,
            uf_to_clp=Decimal("40000"),
        ).run()

    metrics = report["metrics"]
    assert metrics["pages_requested"] == 2
    assert metrics["cards_detected"] == 4
    assert metrics["publications_unique"] == 3
    assert metrics["duplicates"] == 1
    assert metrics["details_ok"] == 3
    assert metrics["unknown_comuna"] == 0
    assert metrics["by_comuna"] == {"Santiago": 3}
    assert metrics["by_currency_original"] == {"UF": 3}
    assert all(sample["price_clp_derived"] == 120_000_000 for sample in report["samples"])


async def test_dry_run_reports_the_exact_detail_request_that_returned_403():
    target = _target()
    base = build_portal_target_url(target)  # type: ignore[arg-type]

    async def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == base:
            return httpx.Response(200, text=f"<html><body>{_cards('403')}</body></html>")
        if "MLC-403" in url:
            return httpx.Response(403, text="blocked")
        raise AssertionError(url)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        report = await PortalHttpDryRun(
            client=client,
            targets=[target],  # type: ignore[list-item]
            max_pages_per_target=1,
            max_details=1,
            pause_s=0,
        ).run()

    assert report["stopped_reason"] == "http_403"
    assert report["metrics"]["block_events"] == [{
        "stage": "detail", "reason": "http_403", "http_status": 403,
        "external_id": "MLC-403",
        "url": "https://www.portalinmobiliario.com/MLC-403-x",
    }]


def test_target_url_is_scoped_to_configured_rm_comuna():
    url = build_portal_target_url(_target())  # type: ignore[arg-type]

    assert url == "https://www.portalinmobiliario.com/venta/departamento/santiago-metropolitana"
