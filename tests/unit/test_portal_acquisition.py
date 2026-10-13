import json
import os
import time
from pathlib import Path

import httpx
import pytest

from infrastructure.scrapers.portal_acquisition import portal_lookup_client, PortalAcquisitionError
from services.listing_url_lookup import lookup_listing_url
from tests.unit.test_listing_url_lookup_endpoint import _client, _LookupResult

URL = "https://www.portalinmobiliario.com/MLC-123456789-departamento-_JM"


async def missing(_):
    return None


async def test_missing_session_fails_before_network(monkeypatch):
    monkeypatch.delenv("PORTAL_SESSION_FILE", raising=False)
    async def no_request(*a, **kw):
        raise AssertionError("No unauthenticated fallback allowed")
    monkeypatch.setattr(httpx.AsyncClient, "get", no_request)
    result = await lookup_listing_url(URL, listing_lookup=missing)
    assert result.status == "upstream_unavailable"
    assert result.warnings == ["portal_session_unavailable"]


async def test_reverification_circuit_fails_without_loading(monkeypatch, tmp_path):
    monkeypatch.setenv("PORTAL_SESSION_FILE", str(tmp_path / "session.json"))
    (tmp_path / "reauth_required.json").write_text("{}")
    with pytest.raises(PortalAcquisitionError, match="portal_reverification_required"):
        async with portal_lookup_client():
            raise AssertionError("Circuit must stop acquisition")


async def test_reuses_loader_without_persisting_response_cookies(monkeypatch, tmp_path):
    path = tmp_path / "session.json"
    path.write_text(json.dumps({"cookies":[{"name":"ssid","value":"synthetic-only","domain":".portalinmobiliario.com","secure":True,"expires":time.time()+600}]}))
    path.chmod(0o600);before=path.read_bytes()
    monkeypatch.setenv("PORTAL_SESSION_FILE", str(path))
    def verified_loader(configured):
        assert configured == path
        return httpx.Cookies({"ssid":"synthetic-only"})
    monkeypatch.setattr("infrastructure.scrapers.portal_acquisition.load_session", verified_loader)
    async with portal_lookup_client() as client:
        assert client.cookies.get("ssid") == "synthetic-only"
        assert client.headers["Accept-Language"].startswith("es-CL")
        client.cookies.set("synthetic-response", "ignored", domain=".portalinmobiliario.com")
    assert path.read_bytes() == before


@pytest.mark.parametrize("failure,reason", [(httpx.ReadTimeout,"portal_timeout"),(httpx.ConnectError,"portal_transport_error")])
async def test_transport_failures_are_distinct_and_not_retried(failure,reason):
    calls=[]
    def handler(request):
        calls.append(request);raise failure("synthetic",request=request)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result=await lookup_listing_url(URL,listing_lookup=missing,http_client=client)
    assert result.warnings==[reason] and result.listing_data=={} and len(calls)==1


@pytest.mark.parametrize("status,reason",[(401,"portal_access_denied"),(410,"portal_listing_unavailable"),(500,"portal_upstream_error"),(503,"portal_upstream_error")])
async def test_upstream_status_retained(status,reason):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _:httpx.Response(status))) as client:
        result=await lookup_listing_url(URL,listing_lookup=missing,http_client=client)
    assert result.status=="upstream_unavailable" and result.warnings==[reason] and result.listing_data=={}


@pytest.mark.parametrize("endpoint",["lookup-url","analyze-url"])
@pytest.mark.parametrize("reason,status",[("portal_session_unavailable",503),("portal_reverification_required",503),("portal_access_denied",503),("portal_rate_limited",503),("portal_listing_unavailable",404),("portal_timeout",504),("portal_transport_error",502),("portal_upstream_error",502)])
def test_api_preserves_upstream_reason(monkeypatch,endpoint,reason,status):
    from api.v1 import listings
    async def lookup(_):return _LookupResult("upstream_unavailable",{},[reason],"portalinmobiliario",URL)
    monkeypatch.setattr(listings,"lookup_listing_url",lookup)
    response=_client().post('/api/v1/listings/'+endpoint,json={"url":URL})
    assert response.status_code==status
    assert response.json()['detail']['code']==reason
    assert 'Portal' in response.json()['detail']['message']
