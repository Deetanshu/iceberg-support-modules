"""
Configuration management using Pydantic settings.

Loads configuration from environment variables and .env file.
"""
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

# Get the directory where this config file is located
_CONFIG_DIR = Path(__file__).parent


class Settings(BaseSettings):
    """Remediation service configuration."""
    
    model_config = SettingsConfigDict(
        env_file=_CONFIG_DIR / ".env",
        env_prefix="REMEDIATION_",
        case_sensitive=False,
        extra="ignore",
    )
    
    # PostgreSQL (Cloud SQL)
    db_host: str = "34.180.57.7"
    db_port: int = 5432
    db_user: str = "iceberg"
    db_password: str
    db_name: str = "iceberg"
    
    # Breeze API
    breeze_api_key: str
    breeze_api_secret: str
    breeze_session_token: str  # From results/breeze_session.json
    
    # Kite API (for SENSEX only - optional)
    kite_api_key: Optional[str] = None
    kite_access_token: Optional[str] = None
    
    # Remediation settings
    default_strike_range: int = 5  # ±5 ATM if no admin range
    batch_size: int = 100
    rate_limit_delay: float = 0.3  # Seconds between Breeze requests
    max_retries: int = 5
    
    # Local SQLite for progress tracking
    progress_db_path: str = "progress.db"
    
    # Logging
    log_level: str = "INFO"
    log_format: str = "json"  # "json" or "console"
    
    @property
    def postgres_dsn(self) -> str:
        """PostgreSQL connection string."""
        return f"postgresql://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"
    
    @property
    def asyncpg_dsn(self) -> str:
        """PostgreSQL connection string for asyncpg (without driver prefix)."""
        return f"postgresql://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
