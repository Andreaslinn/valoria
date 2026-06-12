"""HTTP client used by the Streamlit UI.

The UI talks to FastAPI only through this module. Keep domain, DB and service
imports out of ui/.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx

DEFAULT_API_BASE_URL = os.getenv("AVM_API_BASE_URL", "http://localhost:8000")
DEFAULT_TIMEOUT_SECONDS = 8.0
RADAR_TIMEOUT_SECONDS = 30.0
VALUATION_REQUEST_FIELDS = frozenset(
    {
        "comuna",
        "property_type",
        "m2",
        "built_area_m2",
        "land_area_m2",
        "usable_area_m2",
        "dormitorios",
        "banos",
        "estacionamientos",
        "precio_publicado_uf",
        "precio_publicado_clp",
    }
)


@dataclass
class ApiError(Exception):
    message: str
    status_code: int | None = None
    payload: Any | None = None

    def __str__(self) -> str:
        return self.message


class ApiClient:
    def __init__(
        self,
        base_url: str | None = None,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = (base_url or get_default_base_url()).rstrip("/")
        self._timeout = timeout
        self._client = client or httpx.Client(timeout=timeout)

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health")

    def login(self, email: str, password: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/v1/auth/login",
            data={"username": email, "password": password},
        )

    def me(self, token: str) -> dict[str, Any]:
        return self._request("GET", "/api/v1/auth/me", token=token)

    def list_users(self, token: str) -> list[dict[str, Any]]:
        return self._request("GET", "/api/v1/users", token=token)

    def create_user(self, token: str, email: str, password: str, role: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/v1/users",
            token=token,
            json={"email": email, "password": password, "role": role},
        )

    def activate_user(self, token: str, user_id: int) -> dict[str, Any]:
        return self._request("POST", f"/api/v1/users/{user_id}/activate", token=token)

    def deactivate_user(self, token: str, user_id: int) -> dict[str, Any]:
        return self._request("POST", f"/api/v1/users/{user_id}/deactivate", token=token)

    def list_listings(
        self,
        *,
        token: str | None = None,
        limit: int = 100,
        offset: int = 0,
        comuna: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if comuna:
            params["comuna"] = comuna
        if status:
            params["status"] = status
        return self._request("GET", "/api/v1/listings", token=_require_token(token), params=params)

    def get_current_uf(self) -> dict[str, Any]:
        return self._request("GET", "/api/v1/market/uf")

    def get_listing(self, listing_id: int, token: str | None = None) -> dict[str, Any]:
        return self._request("GET", f"/api/v1/listings/{listing_id}", token=_require_token(token))

    def lookup_listing_url(self, url: str, token: str | None = None) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/v1/listings/lookup-url",
            token=_require_token(token),
            json={"url": url},
        )

    def create_valuation(self, payload: dict[str, Any], token: str | None = None) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/v1/valuations",
            token=_require_token(token),
            json=valuation_api_payload(payload),
        )

    def submit_valuation_feedback(
        self,
        *,
        valuation_result: dict[str, Any],
        valuation_payload: dict[str, Any],
        feedback: str,
        comment: str | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/v1/valuations/feedback",
            json={
                "valuation_result": valuation_result,
                "valuation_payload": valuation_payload,
                "feedback": feedback,
                "comment": comment,
            },
        )

    def get_radar_opportunities(
        self,
        *,
        token: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        return self._request(
            "GET",
            "/api/v1/radar/opportunities",
            token=_require_token(token),
            params={"limit": limit},
            timeout=RADAR_TIMEOUT_SECONDS,
        )

    def list_watchlist(self, token: str) -> list[dict[str, Any]]:
        return self._request("GET", "/api/v1/watchlist", token=token)

    def save_to_watchlist(self, listing_id: int, token: str) -> dict[str, Any]:
        return self._request("POST", f"/api/v1/watchlist/{listing_id}", token=token)

    def remove_from_watchlist(self, listing_id: int, token: str) -> dict[str, Any]:
        return self._request("DELETE", f"/api/v1/watchlist/{listing_id}", token=token)

    def watchlist_status(self, listing_id: int, token: str) -> dict[str, Any]:
        return self._request("GET", f"/api/v1/watchlist/{listing_id}/status", token=token)

    def get_alerts(self, token: str, *, limit: int = 50) -> list[dict[str, Any]]:
        return self._request("GET", "/api/v1/alerts", token=token, params={"limit": limit})

    def mark_alert_read(self, alert_id: int, token: str) -> dict[str, Any]:
        return self._request("POST", f"/api/v1/alerts/{alert_id}/read", token=token)

    def track_usage_event(
        self,
        event_type: str,
        *,
        token: str | None = None,
        feature: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/v1/usage/events",
            token=_require_token(token),
            json={
                "event_type": event_type,
                "feature": feature,
                "metadata": metadata or {},
            },
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        **kwargs: Any,
    ) -> Any:
        headers = dict(kwargs.pop("headers", {}) or {})
        if token:
            headers["Authorization"] = f"Bearer {token}"

        timeout = kwargs.pop("timeout", self._timeout)
        try:
            response = self._client.request(
                method,
                f"{self.base_url}{path}",
                timeout=timeout,
                headers=headers,
                **kwargs,
            )
        except httpx.TimeoutException as e:
            raise ApiError(
                f"La API no respondio a tiempo en {self.base_url}. Intenta nuevamente o revisa los logs del backend.",
            ) from e
        except httpx.RequestError as e:
            raise ApiError(
                f"No se pudo conectar con la API. Verifica que FastAPI este corriendo en {self.base_url}",
            ) from e

        if response.status_code >= 400:
            raise _api_error_from_response(response)

        if not response.content:
            return None
        try:
            return response.json()
        except ValueError as e:
            raise ApiError("La API respondio con un formato inesperado") from e


def get_default_base_url() -> str:
    return os.getenv("AVM_API_BASE_URL", DEFAULT_API_BASE_URL)


def valuation_api_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return only fields accepted by the current valuation API schema."""
    return {key: value for key, value in payload.items() if key in VALUATION_REQUEST_FIELDS}


def _require_token(token: str | None) -> str:
    if token:
        return token
    raise ApiError("Inicia sesion para acceder a estos datos.", status_code=401)


def _api_error_from_response(response: httpx.Response) -> ApiError:
    payload: Any | None = None
    detail: Any = None
    try:
        payload = response.json()
        detail = payload.get("detail") if isinstance(payload, dict) else None
    except ValueError:
        detail = response.text

    messages = {
        400: detail or "La solicitud no cumple una regla de negocio.",
        401: "No autorizado. Inicia sesion o revisa tus credenciales.",
        404: detail or "Recurso no encontrado.",
        500: "La API tuvo un error interno. Revisa los logs del backend.",
    }
    return ApiError(
        str(messages.get(response.status_code, detail or "Error inesperado de la API.")),
        status_code=response.status_code,
        payload=payload,
    )
