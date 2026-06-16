from __future__ import annotations

from ui.api_client import ApiError
from ui.pages import radar


def test_empty_radar_uses_normal_empty_state(monkeypatch) -> None:
    calls = _capture_empty_state(monkeypatch)

    radar._render_empty_radar()

    assert calls[0][0] == "Sin oportunidades claras por ahora"
    assert "No encontramos publicaciones" in calls[0][1]


def test_radar_error_message_for_unauthenticated(monkeypatch) -> None:
    calls = _capture_empty_state(monkeypatch)

    radar._render_api_error(ApiError("No autorizado", status_code=401))

    assert calls == [
        (
            "Sesion requerida para actualizar el radar",
            "Tu sesion expiro, no es valida o no se envio al backend. Inicia sesion nuevamente.",
            "No autorizado",
        )
    ]


def test_radar_error_message_for_forbidden(monkeypatch) -> None:
    calls = _capture_empty_state(monkeypatch)

    radar._render_api_error(ApiError("Prohibido", status_code=403))

    assert calls[0][0] == "No tienes permiso para usar el radar"


def test_radar_error_message_for_connection_failure(monkeypatch) -> None:
    calls = _capture_empty_state(monkeypatch)

    radar._render_api_error(ApiError("No se pudo conectar con la API"))

    assert calls[0][0] == "No pudimos conectar con la API"
    assert "FastAPI" in calls[0][1]


def test_radar_error_message_for_timeout(monkeypatch) -> None:
    calls = _capture_empty_state(monkeypatch)

    radar._render_api_error(ApiError("La API no respondio a tiempo en http://127.0.0.1:8000"))

    assert calls[0][0] == "El radar tardo demasiado en responder"
    assert "FastAPI esta disponible" in calls[0][1]


def test_radar_error_message_for_backend_error(monkeypatch) -> None:
    calls = _capture_empty_state(monkeypatch)

    radar._render_api_error(ApiError("La API tuvo un error interno", status_code=500))

    assert calls[0][0] == "El backend no pudo actualizar el radar"


def _capture_empty_state(monkeypatch) -> list[tuple[str, str, str | None]]:
    calls: list[tuple[str, str, str | None]] = []

    def fake_empty_state(title: str, body: str, action_label: str | None = None) -> None:
        calls.append((title, body, action_label))

    monkeypatch.setattr(radar, "empty_state", fake_empty_state)
    return calls
