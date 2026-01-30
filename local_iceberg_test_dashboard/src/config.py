# Iceberg Test Dashboard - Configuration Module
"""
Configuration management using Pydantic Settings.

Loads configuration from environment variables with sensible defaults.
Requirements: 1.4, 3.3, 17.7
"""

import logging
from pathlib import Path
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict
import structlog


def configure_logging(log_dir: Path = None, debug: bool = False) -> None:
    """Configure structlog with file output in append mode.
    
    Requirement 17.7: Log all errors to console for debugging.
    Enhancement: Also log to file for persistent debugging.
    
    Args:
        log_dir: Directory for log files (defaults to logs/ in project root)
        debug: Enable debug level logging
    """
    if log_dir is None:
        log_dir = Path(__file__).parent.parent / "logs"
    
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / "dashboard.log"
    
    # Configure standard logging with both console and file handlers
    log_level = logging.DEBUG if debug else logging.INFO
    
    # Create handlers
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    
    file_handler = logging.FileHandler(log_file, mode='a', encoding='utf-8')
    file_handler.setLevel(log_level)
    
    # Configure root logger
    logging.basicConfig(
        level=log_level,
        format="%(message)s",
        handlers=[console_handler, file_handler],
        force=True,  # Override any existing configuration
    )
    
    # Configure structlog
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


class Settings(BaseSettings):
    """Dashboard configuration settings loaded from environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # API Configuration
    iceberg_api_url: str = "https://api.botbro.trade"

    # Dashboard port (Requirement 1.4: port 8509)
    dashboard_port: int = 8509

    # Google OAuth Configuration (Requirement 3.3)
    google_client_id: str = ""
    google_callback_uri: str = "https://botbro.ronykax.xyz/api/auth/callback/google"

    # Optional pre-configured JWT token for testing
    iceberg_jwt_token: str = ""

    # Debug mode
    debug: bool = False

    @property
    def ws_url(self) -> str:
        """WebSocket URL derived from API URL."""
        return self.iceberg_api_url.replace("https://", "wss://").replace(
            "http://", "ws://"
        )


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


def init_logging() -> None:
    """Initialize logging on module import.
    
    Call this early in application startup to ensure all logs are captured.
    """
    settings = get_settings()
    configure_logging(debug=settings.debug)
