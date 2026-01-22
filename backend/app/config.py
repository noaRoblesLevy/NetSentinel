"""Application configuration loaded from environment variables."""

from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings."""

    # Database
    database_url: str = "postgresql://netsentinel:netsentinel_dev@localhost:5432/netsentinel"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Security - NO DEFAULTS for secrets in production
    secret_key: str = ""  # REQUIRED - must be set via environment variable
    collector_api_key: str = ""  # REQUIRED - must be set via environment variable

    # JWT
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 7
    algorithm: str = "HS256"

    # CORS
    cors_origins: str = "http://localhost:3000,http://localhost:5173"

    @property
    def cors_origins_list(self) -> List[str]:
        return [origin.strip() for origin in self.cors_origins.split(",")]

    # Logging
    log_level: str = "info"

    # Environment
    environment: str = "development"

    def validate_production_settings(self) -> None:
        """Validate that required settings are configured for production."""
        if self.environment == "production":
            errors = []
            if not self.secret_key or self.secret_key in ["", "dev-secret-key-change-in-production"]:
                errors.append("SECRET_KEY must be set to a secure random value in production")
            if not self.collector_api_key or self.collector_api_key in ["", "dev-collector-key"]:
                errors.append("COLLECTOR_API_KEY must be set to a secure random value in production")
            if len(self.secret_key) < 32:
                errors.append("SECRET_KEY must be at least 32 characters long")
            if errors:
                raise ValueError(f"Production configuration errors: {'; '.join(errors)}")

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    settings = Settings()
    settings.validate_production_settings()
    return settings
