from __future__ import annotations

import httpx
import pytest

from ui.api_client import ApiClient, ApiError


def _client(handler) -> ApiClient:
    transport = httpx.MockTransport(handler)
    return ApiClient(
        base_url="http://api.test",
        client=httpx.Client(transport=transport),
    )


def test_health_calls_expected_endpoint():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/health"
        return httpx.Response(200, json={"status": "ok"})

    assert _client(handler).health() == {"status": "ok"}


def test_login_posts_form_data():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/v1/auth/login"
        assert b"username=andy%40example.com" in request.content
        return httpx.Response(200, json={"access_token": "token", "token_type": "bearer"})

    result = _client(handler).login("andy@example.com", "secret")
    assert result["access_token"] == "token"


def test_me_sends_bearer_token():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer token"
        return httpx.Response(200, json={"email": "andy@example.com"})

    assert _client(handler).me("token")["email"] == "andy@example.com"


def test_data_methods_require_token():
    with pytest.raises(ApiError) as exc:
        _client(lambda request: httpx.Response(200)).list_listings()

    assert exc.value.status_code == 401
    assert "Inicia sesion" in exc.value.message

    with pytest.raises(ApiError) as lookup_exc:
        _client(lambda request: httpx.Response(200)).lookup_listing_url("https://www.yapo.cl/listing/123")

    assert lookup_exc.value.status_code == 401
    assert "Inicia sesion" in lookup_exc.value.message

    with pytest.raises(ApiError) as usage_exc:
        _client(lambda request: httpx.Response(200)).track_usage_event("page_view")

    assert usage_exc.value.status_code == 401
    assert "Inicia sesion" in usage_exc.value.message


def test_listings_sends_bearer_token():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer token"
        assert request.url.path == "/api/v1/listings"
        return httpx.Response(200, json=[])

    assert _client(handler).list_listings(token="token") == []


def test_lookup_listing_url_posts_with_bearer_token():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer token"
        assert request.method == "POST"
        assert request.url.path == "/api/v1/listings/lookup-url"
        assert json_from_request(request) == {"url": "https://www.yapo.cl/listing/123"}
        return httpx.Response(
            200,
            json={
                "status": "parsed_new",
                "listing_data": {"title": "Depto", "comuna": "nunoa"},
                "warnings": [],
                "source": "yapo",
                "url": "https://www.yapo.cl/listing/123",
            },
        )

    result = _client(handler).lookup_listing_url("https://www.yapo.cl/listing/123", token="token")

    assert result["status"] == "parsed_new"
    assert result["listing_data"]["comuna"] == "nunoa"


def test_track_usage_event_posts_with_bearer_token():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer token"
        assert request.method == "POST"
        assert request.url.path == "/api/v1/usage/events"
        assert json_from_request(request) == {
            "event_type": "page_view",
            "feature": "Radar",
            "metadata": {"page": "Radar"},
        }
        return httpx.Response(
            201,
            json={
                "id": 1,
                "event_type": "page_view",
                "user_id": 7,
                "payload": {"feature": "radar", "metadata": {"page": "radar"}},
                "created_at": "2026-06-04T00:00:00Z",
            },
        )

    result = _client(handler).track_usage_event(
        "page_view",
        token="token",
        feature="Radar",
        metadata={"page": "Radar"},
    )

    assert result["id"] == 1


def test_valuation_sends_bearer_token():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer token"
        assert request.url.path == "/api/v1/valuations"
        payload = json_from_request(request)
        assert payload == {"m2": 65}
        return httpx.Response(
            200,
            json={
                "status": "ok",
                "consensus": {"status": "ok"},
                "engine_results": [{"engine_name": "comparables_canonical_outliers"}],
            },
        )

    result = _client(handler).create_valuation({"m2": 65, "location_query": "Mujica"}, token="token")

    assert result["status"] == "ok"
    assert result["consensus"]["status"] == "ok"
    assert result["engine_results"][0]["engine_name"] == "comparables_canonical_outliers"


def test_submit_valuation_feedback_posts_without_token():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "Authorization" not in request.headers
        assert request.method == "POST"
        assert request.url.path == "/api/v1/valuations/feedback"
        payload = json_from_request(request)
        assert payload["feedback"] == "reasonable"
        assert payload["valuation_payload"]["comuna"] == "nunoa"
        return httpx.Response(200, json={"status": "ok", "record": {"feedback": "reasonable"}, "path": "x.jsonl"})

    result = _client(handler).submit_valuation_feedback(
        valuation_result={"estimated_price_clp": 180_000_000},
        valuation_payload={"comuna": "nunoa"},
        feedback="reasonable",
        comment="ok",
    )

    assert result["status"] == "ok"


def test_radar_sends_bearer_token():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer token"
        assert request.url.path == "/api/v1/radar/opportunities"
        return httpx.Response(200, json=[])

    assert _client(handler).get_radar_opportunities(token="token") == []


def test_radar_uses_longer_timeout():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.extensions["timeout"]["connect"] == 30.0
        assert request.extensions["timeout"]["read"] == 30.0
        return httpx.Response(200, json=[])

    assert _client(handler).get_radar_opportunities(token="token") == []


def test_alerts_use_real_authenticated_endpoint():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer token"
        assert request.url.path == "/api/v1/alerts"
        assert request.url.params["limit"] == "50"
        return httpx.Response(200, json=[])

    assert _client(handler).get_alerts("token") == []


def test_http_error_raises_friendly_api_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "Listing no encontrado"})

    with pytest.raises(ApiError) as exc:
        _client(handler).get_listing(123, token="token")

    assert exc.value.status_code == 404
    assert "Listing no encontrado" in exc.value.message


def test_connection_error_raises_friendly_api_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    with pytest.raises(ApiError) as exc:
        _client(handler).health()

    assert "No se pudo conectar con la API" in exc.value.message


def test_timeout_error_raises_specific_api_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(ApiError) as exc:
        _client(handler).health()

    assert "no respondio a tiempo" in exc.value.message
    assert "No se pudo conectar" not in exc.value.message


def json_from_request(request: httpx.Request) -> dict:
    import json

    return json.loads(request.content.decode("utf-8"))
