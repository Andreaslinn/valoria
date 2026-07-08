from __future__ import annotations

import httpx
import pytest
from httpx import ASGITransport

from api.main import create_app
from config import get_settings
from config.settings import Settings


def test_backend_cors_origins_are_parsed_from_comma_separated_setting() -> None:
    settings = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        sync_database_url="sqlite:///:memory:",
        jwt_secret_key="0" * 32,
        backend_cors_origins=(
            " http://localhost:3000, http://127.0.0.1:3000/, "
            "https://app.valoria.cl "
        ),
    )

    assert settings.backend_cors_origin_list == (
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://app.valoria.cl",
    )


@pytest.mark.asyncio
async def test_cors_preflight_allows_configured_nextjs_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BACKEND_CORS_ORIGINS", "https://app.valoria.cl")
    get_settings.cache_clear()
    app = create_app()

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.options(
            "/api/v1/valuations",
            headers={
                "Origin": "https://app.valoria.cl",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )

    get_settings.cache_clear()
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://app.valoria.cl"
    assert "authorization" in response.headers["access-control-allow-headers"].lower()
