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

    # APIs externas
    uf_api_url: str = "https://mindicador.cl/api/uf"
    nominatim_url: str = "https://nominatim.openstreetmap.org/search"
    nominatim_user_agent: str = "AVM-v2-geocoder/0.1 (contact: dev-local)"

    # Entorno
    environment: Literal["local", "development", "beta", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    """Singleton cacheado. Usar get_settings() en lugar de instanciar Settings()."""
    return Settings()  # type: ignore[call-arg]
