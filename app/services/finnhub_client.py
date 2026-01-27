"""
Finnhub API client for social sentiment and stock data.
Free tier: 60 calls/minute, covers Reddit & Twitter sentiment.
"""

import logging
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Optional
import time

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

FINNHUB_BASE_URL = "https://finnhub.io/api/v1"


@dataclass
class SentimentData:
    """Social sentiment data for a stock."""
    ticker: str
    reddit_mentions: int = 0
    reddit_positive: int = 0
    reddit_negative: int = 0
    reddit_score: float = 0.0
    twitter_mentions: int = 0
    twitter_positive: int = 0
    twitter_negative: int = 0
    twitter_score: float = 0.0
    total_mentions: int = 0
    avg_sentiment: float = 0.0


class FinnhubClient:
    """Client for Finnhub API."""

    def __init__(self):
        self.api_key = getattr(settings, 'FINNHUB_API_KEY', '') or ''
        self.client = httpx.Client(timeout=30.0)
        self._last_request_time = 0
        self._min_request_interval = 0.02  # 50 requests/second max (staying under 60/min)

    def _rate_limit(self):
        """Simple rate limiting to stay under 60 calls/minute."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_request_interval:
            time.sleep(self._min_request_interval - elapsed)
        self._last_request_time = time.time()

    def _make_request(self, endpoint: str, params: dict = None) -> Optional[dict]:
        """Make a rate-limited request to Finnhub API."""
        if not self.api_key:
            logger.warning("Finnhub API key not configured")
            return None

        self._rate_limit()

        params = params or {}
        params["token"] = self.api_key

        try:
            response = self.client.get(f"{FINNHUB_BASE_URL}/{endpoint}", params=params)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                logger.warning("Finnhub rate limit hit, waiting...")
                time.sleep(1)
                return self._make_request(endpoint, params)
            logger.error(f"Finnhub API error: {e}")
            return None
        except Exception as e:
            logger.error(f"Finnhub request failed: {e}")
            return None

    def get_social_sentiment(self, ticker: str) -> Optional[SentimentData]:
        """
        Get social sentiment for a stock from Reddit and Twitter.

        Args:
            ticker: Stock symbol (e.g., 'AAPL')

        Returns:
            SentimentData object or None if failed
        """
        data = self._make_request("stock/social-sentiment", {"symbol": ticker})

        if not data:
            return None

        sentiment = SentimentData(ticker=ticker)

        # Parse Reddit data
        reddit_data = data.get("reddit", [])
        if reddit_data:
            # Get most recent data point
            latest = reddit_data[-1] if reddit_data else {}
            sentiment.reddit_mentions = latest.get("mention", 0)
            sentiment.reddit_positive = latest.get("positiveMention", 0)
            sentiment.reddit_negative = latest.get("negativeMention", 0)
            sentiment.reddit_score = latest.get("score", 0.0)

        # Parse Twitter data
        twitter_data = data.get("twitter", [])
        if twitter_data:
            latest = twitter_data[-1] if twitter_data else {}
            sentiment.twitter_mentions = latest.get("mention", 0)
            sentiment.twitter_positive = latest.get("positiveMention", 0)
            sentiment.twitter_negative = latest.get("negativeMention", 0)
            sentiment.twitter_score = latest.get("score", 0.0)

        # Calculate totals
        sentiment.total_mentions = sentiment.reddit_mentions + sentiment.twitter_mentions
        if sentiment.total_mentions > 0:
            # Weighted average sentiment
            reddit_weight = sentiment.reddit_mentions / sentiment.total_mentions if sentiment.total_mentions else 0
            twitter_weight = sentiment.twitter_mentions / sentiment.total_mentions if sentiment.total_mentions else 0
            sentiment.avg_sentiment = (
                sentiment.reddit_score * reddit_weight +
                sentiment.twitter_score * twitter_weight
            )

        return sentiment

    def get_stock_symbols(self, exchange: str = "US") -> list[dict]:
        """
        Get list of all stock symbols for an exchange.

        Args:
            exchange: Exchange code (default 'US' for all US stocks)

        Returns:
            List of stock dictionaries with symbol, name, type, etc.
        """
        data = self._make_request("stock/symbol", {"exchange": exchange})
        if not data:
            return []

        # Filter to common stocks only (not ETFs, warrants, etc.)
        stocks = [
            s for s in data
            if s.get("type") == "Common Stock"
        ]

        logger.info(f"Found {len(stocks)} common stocks on {exchange} exchange")
        return stocks

    def get_buzz_stocks(self) -> list[str]:
        """
        Get stocks with high social media buzz.
        Uses Finnhub's stock buzz endpoint.

        Returns:
            List of ticker symbols with high buzz
        """
        data = self._make_request("stock/social-sentiment/buzz")

        if not data or "buzz" not in data:
            return []

        # Sort by buzz score and return top tickers
        buzz_list = data.get("buzz", [])
        sorted_buzz = sorted(buzz_list, key=lambda x: x.get("buzz", 0), reverse=True)

        return [item.get("symbol") for item in sorted_buzz[:100] if item.get("symbol")]

    def search_symbol(self, query: str) -> list[dict]:
        """
        Search for stock symbols matching a query.

        Args:
            query: Search term

        Returns:
            List of matching stocks
        """
        data = self._make_request("search", {"q": query})
        if not data:
            return []

        return data.get("result", [])

    def get_trending_stocks(self, limit: int = 50) -> list[dict]:
        """
        Get stocks that are trending based on social sentiment.
        Combines buzz data with sentiment scores.

        Args:
            limit: Maximum number of stocks to return

        Returns:
            List of dicts with ticker and sentiment data
        """
        # First try to get buzz stocks
        buzz_tickers = self.get_buzz_stocks()

        if not buzz_tickers:
            logger.warning("No buzz data available from Finnhub")
            return []

        trending = []
        for ticker in buzz_tickers[:limit]:
            sentiment = self.get_social_sentiment(ticker)
            if sentiment and sentiment.total_mentions > 0:
                trending.append({
                    "ticker": ticker,
                    "total_mentions": sentiment.total_mentions,
                    "reddit_mentions": sentiment.reddit_mentions,
                    "twitter_mentions": sentiment.twitter_mentions,
                    "avg_sentiment": sentiment.avg_sentiment,
                    "reddit_score": sentiment.reddit_score,
                    "twitter_score": sentiment.twitter_score,
                })

        # Sort by total mentions
        trending.sort(key=lambda x: x["total_mentions"], reverse=True)

        logger.info(f"Found {len(trending)} trending stocks with sentiment data")
        return trending


# Singleton instance
finnhub_client = FinnhubClient()
