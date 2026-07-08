"""Settings cargados desde .env mediante pydantic-settings.

Uso:
    from config import get_settings
    settings = get_settings()  # singleton cacheado
"""
from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    # Database
    database_url: str = Field(..., description="Async URL (asyncpg) para la app")
    sync_database_url: str = Field(
        ...,
        validation_alias=AliasChoices("SYNC_DATABASE_URL", "DATABASE_URL_SYNC"),
        description="Sync URL (psycopg) para Alembic",
    )

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Auth
    jwt_secret_key: str = Field(
        ...,
        validation_alias=AliasChoices("JWT_SECRET_KEY", "SECRET_KEY"),
        min_length=32,
    )
    jwt_algorithm: str = "HS256"
    jwt_expiration_minutes: int = Field(
        60,
        validation_alias=AliasChoices("JWT_EXPIRATION_MINUTES", "ACCESS_TOKEN_EXPIRE_MINUTES"),
    )
    beta_signup_enabled: bool = False

    # APIs externas
    uf_api_url: str = "https://mindicador.cl/api/uf"
    uf_cache_ttl_hours: int = 24
    uf_max_staleness_days: int = 1
    uf_allow_stale_on_failure: bool = False
    uf_require_fresh_for_radar: bool = True
    nominatim_url: str = "https://nominatim.openstreetmap.org/search"
    nominatim_user_agent: str = "AVM-v2-geocoder/0.1 (contact: dev-local)"

    # Entorno
    environment: Literal["local", "development", "beta", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    backend_cors_origins: str = Field(
        "http://localhost:3000,http://127.0.0.1:3000",
        validation_alias=AliasChoices("BACKEND_CORS_ORIGINS", "CORS_ORIGINS"),
        description="Comma-separated browser origins allowed to call the API.",
    )

    # Radar beta
    radar_allowed_property_types: str = "apartment"
    radar_require_fresh_listings: bool = True
    radar_max_listing_staleness_days: int = 7
    radar_exclude_refresh_failed: bool = True
    radar_exclude_removed_or_unavailable: bool = True

    # Market Intelligence v1
    market_commune_min_active_listings: int = 30
    market_commune_min_time_sample: int = 20
    market_commune_min_price_history_sample: int = 15

    # On-demand listing verification for strong-intent user flows.
    listing_on_demand_refresh_enabled: bool = True
    listing_on_demand_refresh_cooldown_hours: int = 24
    listing_on_demand_refresh_skip_blocked_hours: int = 24
    listing_on_demand_refresh_timeout_sec: float = 12.0

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def backend_cors_origin_list(self) -> tuple[str, ...]:
        return tuple(
            origin.strip().rstrip("/")
            for origin in self.backend_cors_origins.split(",")
            if origin.strip()
        )


@lru_cache
def get_settings() -> Settings:
    """Singleton cacheado. Usar get_settings() en lugar de instanciar Settings()."""
    return Settings()  # type: ignore[call-arg]
