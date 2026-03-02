"""Application configuration management using Pydantic Settings.

T007: Create src/config.py with Pydantic Settings for environment management
DoD: Config 可從 .env 讀取所有必要變數；missing var 時拋出 ValidationError
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # LINE Messaging API
    line_channel_access_token: str = Field(
        ..., description="LINE Channel Access Token"
    )
    line_channel_secret: str = Field(..., description="LINE Channel Secret")

    # Database
    database_url: str = Field(
        ...,
        description="PostgreSQL connection string (asyncpg)",
        examples=["postgresql+asyncpg://user:pass@host:port/db"],
    )

    # LLM API Keys
    anthropic_api_key: str = Field(..., description="Anthropic API Key")
    # Application
    app_env: Literal["development", "staging", "production"] = Field(
        default="development", description="Application environment"
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO", description="Logging level"
    )

    # Security
    user_id_salt: str = Field(
        ...,
        min_length=32,
        description="Salt for hashing user IDs (minimum 32 characters)",
    )

    # Gemini
    gemini_api_key: str = Field(default="", description="Google Gemini API Key（留空則停用 Gemini provider）")

    # LLM Mode
    default_llm_mode: Literal["free", "cheap", "rigorous"] = Field(
        default="free", description="Default LLM mode: free/cheap/rigorous"
    )
    daily_cap_tokens_free: int = Field(
        default=50000, ge=0, description="Daily free token cap per user"
    )

    # Rate Limiting（預留設定，目前尚未在執行層強制限制）
    llm_rate_limit_per_minute: int = Field(
        default=10, ge=1, le=100, description="LLM calls per minute per user (未實作)"
    )

    # LLM Settings
    llm_timeout_seconds: int = Field(
        default=15, ge=5, le=60, description="LLM API timeout in seconds"
    )

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        """Ensure database URL uses asyncpg driver."""
        if not v.startswith("postgresql+asyncpg://"):
            raise ValueError(
                "DATABASE_URL must use postgresql+asyncpg:// driver for async support"
            )
        return v

    @property
    def is_production(self) -> bool:
        """Check if running in production environment."""
        return self.app_env == "production"

    @property
    def is_development(self) -> bool:
        """Check if running in development environment."""
        return self.app_env == "development"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance.

    Returns:
        Settings: Application settings loaded from environment.

    Raises:
        ValidationError: If required environment variables are missing.
    """
    return Settings()


# Global settings instance for convenience
settings = get_settings()
