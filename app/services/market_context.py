"""
Market context fetcher.
Gets major index performance and top market news headlines
to provide context for the daily stock report.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

import yfinance as yf

logger = logging.getLogger(__name__)


@dataclass
class MarketContext:
    """Market context data for the daily report."""
    sp500_change: Optional[float] = None
    nasdaq_change: Optional[float] = None
    dow_change: Optional[float] = None
    vix_level: Optional[float] = None
    market_summary: str = ""
    market_news: list = field(default_factory=list)


def fetch_market_context() -> MarketContext:
    """
    Fetch market index performance and top news headlines.

    Returns:
        MarketContext with index changes and news items
    """
    ctx = MarketContext()

    # Fetch major index daily changes
    ctx.sp500_change = _get_index_change("^GSPC")
    ctx.nasdaq_change = _get_index_change("^IXIC")
    ctx.dow_change = _get_index_change("^DJI")
    ctx.vix_level = _get_vix_level()

    # Build a short summary from the data
    ctx.market_summary = _build_summary(ctx)

    # Fetch top market news via yfinance
    ctx.market_news = _fetch_market_news()

    logger.info(
        f"Market context: S&P {ctx.sp500_change:+.2f}%, "
        f"Nasdaq {ctx.nasdaq_change:+.2f}%, "
        f"Dow {ctx.dow_change:+.2f}%, "
        f"VIX {ctx.vix_level:.1f}, "
        f"{len(ctx.market_news)} news items"
        if ctx.sp500_change is not None else "Market context: partial data"
    )

    return ctx


def _get_index_change(symbol: str) -> Optional[float]:
    """Get the daily percentage change for a market index."""
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="5d")
        if hist is not None and len(hist) >= 2:
            prev_close = float(hist["Close"].iloc[-2])
            current = float(hist["Close"].iloc[-1])
            if prev_close > 0:
                return round(((current - prev_close) / prev_close) * 100, 2)
    except Exception as e:
        logger.warning(f"Failed to get change for {symbol}: {e}")
    return None


def _get_vix_level() -> Optional[float]:
    """Get the current VIX level."""
    try:
        ticker = yf.Ticker("^VIX")
        hist = ticker.history(period="1d")
        if hist is not None and not hist.empty:
            return round(float(hist["Close"].iloc[-1]), 1)
    except Exception as e:
        logger.warning(f"Failed to get VIX: {e}")
    return None


def _build_summary(ctx: MarketContext) -> str:
    """Build a one-line market summary from index data."""
    parts = []

    if ctx.sp500_change is not None:
        direction = "rose" if ctx.sp500_change > 0 else "fell"
        parts.append(f"The S&P 500 {direction} {abs(ctx.sp500_change):.1f}%")

    if ctx.nasdaq_change is not None:
        direction = "up" if ctx.nasdaq_change > 0 else "down"
        parts.append(f"Nasdaq {direction} {abs(ctx.nasdaq_change):.1f}%")

    if ctx.dow_change is not None:
        direction = "up" if ctx.dow_change > 0 else "down"
        parts.append(f"Dow {direction} {abs(ctx.dow_change):.1f}%")

    if ctx.vix_level is not None:
        if ctx.vix_level > 25:
            parts.append(f"VIX elevated at {ctx.vix_level:.0f}")
        elif ctx.vix_level < 15:
            parts.append(f"VIX calm at {ctx.vix_level:.0f}")

    if not parts:
        return "Market data unavailable."

    return ". ".join(parts) + "."


def _fetch_market_news() -> list[dict]:
    """
    Fetch top market news headlines via yfinance.
    Uses the S&P 500 ticker as a proxy for broad market news.
    Returns up to 3 news items.
    """
    news_items = []

    # Try multiple tickers to get diverse market news
    for symbol in ["^GSPC", "^IXIC", "SPY"]:
        try:
            ticker = yf.Ticker(symbol)
            news = ticker.news
            if not news:
                continue

            for item in news:
                title = item.get("title", "")
                link = item.get("link", "")
                publisher = item.get("publisher", "")

                # Skip duplicates by title
                if any(n["title"] == title for n in news_items):
                    continue

                if title and link:
                    news_items.append({
                        "title": title,
                        "source": publisher,
                        "url": link,
                    })

                if len(news_items) >= 3:
                    break

        except Exception as e:
            logger.debug(f"Error fetching news for {symbol}: {e}")
            continue

        if len(news_items) >= 3:
            break

    return news_items[:3]
