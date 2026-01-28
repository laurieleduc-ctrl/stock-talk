import os
from functools import lru_cache
from dotenv import load_dotenv

load_dotenv()


class Settings:
    """Application settings loaded from environment variables."""

    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./stock_talk.db")

    # Reddit API (optional, fallback to Finnhub if not set)
    REDDIT_CLIENT_ID: str = os.getenv("REDDIT_CLIENT_ID", "")
    REDDIT_CLIENT_SECRET: str = os.getenv("REDDIT_CLIENT_SECRET", "")
    REDDIT_USER_AGENT: str = os.getenv("REDDIT_USER_AGENT", "StockTalk/1.0")

    # Finnhub API (primary source for social sentiment)
    FINNHUB_API_KEY: str = os.getenv("FINNHUB_API_KEY", "")

    # App Settings
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    SECRET_KEY: str = os.getenv("SECRET_KEY", "dev-secret-key-change-me")
    REPORT_TIMEZONE: str = os.getenv("REPORT_TIMEZONE", "America/Los_Angeles")
    REPORT_HOUR: int = int(os.getenv("REPORT_HOUR", "21"))

    # Stock Analysis Settings
    TOP_STOCKS_COUNT: int = 20
    DARK_HORSE_COUNT: int = 2
    MIN_REDDIT_MENTIONS: int = 5  # Minimum mentions to be considered
    DARK_HORSE_MAX_MENTIONS: int = 50  # Max mentions to qualify as dark horse
    DARK_HORSE_MAX_INSTITUTIONAL: float = 0.40  # Max institutional ownership for dark horse

    # Target sectors (case-insensitive matching)
    TARGET_SECTORS: list[str] = [
        "technology",
        "healthcare",
        "biotechnology",
        "pharmaceuticals",
        "medical",
        "semiconductors",
        "software",
        "artificial intelligence",
        "international",
    ]

    # Price drop threshold for value consideration (% from ATH)
    MIN_DROP_FROM_ATH: float = 0.15  # At least 15% below all-time high

    # Stock fetching settings
    STOCK_HISTORY_PERIOD: str = "3y"  # Historical data period for ATH calculation
    MAX_STOCKS_WEB: int = 15  # Max stocks for web request (fast, avoids timeout)
    MAX_STOCKS_WORKER: int = 60  # Max stocks for worker (no timeout constraint)

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def database_url_sync(self) -> str:
        """Convert async database URL to sync if needed."""
        url = self.DATABASE_URL
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
