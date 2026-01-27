"""
Stock data fetcher using yfinance.
Retrieves comprehensive stock metrics for value analysis.
"""

import logging
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional

import yfinance as yf
import pandas as pd
import numpy as np

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class StockData:
    """Comprehensive stock data for analysis."""

    # Basic info
    ticker: str
    name: str = ""
    sector: str = ""
    industry: str = ""
    market_cap: float = 0.0
    market_cap_category: str = ""

    # Price data
    current_price: float = 0.0
    all_time_high: float = 0.0
    pct_from_ath: float = 0.0
    fifty_two_week_high: float = 0.0
    fifty_two_week_low: float = 0.0

    # Valuation metrics
    pe_ratio: Optional[float] = None
    forward_pe: Optional[float] = None
    pb_ratio: Optional[float] = None
    ps_ratio: Optional[float] = None
    peg_ratio: Optional[float] = None
    ev_ebitda: Optional[float] = None

    # Financial health
    debt_to_equity: Optional[float] = None
    current_ratio: Optional[float] = None
    free_cash_flow: Optional[float] = None  # In billions
    profit_margin: Optional[float] = None
    gross_margin: Optional[float] = None
    operating_margin: Optional[float] = None

    # Dividends
    dividend_yield: Optional[float] = None
    dividend_rate: Optional[float] = None

    # Momentum & Technical
    rsi: Optional[float] = None
    beta: Optional[float] = None
    avg_volume: float = 0.0
    recent_volume: float = 0.0

    # Performance
    one_year_return: Optional[float] = None
    ytd_return: Optional[float] = None
    one_month_return: Optional[float] = None

    # Ownership
    short_interest: Optional[float] = None
    institutional_ownership: Optional[float] = None
    insider_ownership: Optional[float] = None

    # Analyst data
    analyst_rating: str = ""
    analyst_count: int = 0
    target_price_low: Optional[float] = None
    target_price_high: Optional[float] = None
    target_price_mean: Optional[float] = None

    # Earnings
    next_earnings_date: Optional[datetime] = None
    earnings_surprise_pct: Optional[float] = None

    # Insider activity
    insider_activity: list = field(default_factory=list)

    # News
    recent_news: list = field(default_factory=list)

    # Validation
    is_valid: bool = True
    error_message: str = ""


class StockFetcher:
    """Fetches comprehensive stock data from Yahoo Finance."""

    def __init__(self):
        self.cache = {}
        self.cache_expiry = timedelta(hours=1)

    def _calculate_rsi(self, prices: pd.Series, period: int = 14) -> Optional[float]:
        """Calculate Relative Strength Index."""
        try:
            if len(prices) < period + 1:
                return None

            delta = prices.diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()

            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))

            return round(rsi.iloc[-1], 2) if not pd.isna(rsi.iloc[-1]) else None
        except Exception:
            return None

    def _get_market_cap_category(self, market_cap: float) -> str:
        """Categorize market cap."""
        if market_cap >= 200:
            return "mega"
        elif market_cap >= 10:
            return "large"
        elif market_cap >= 2:
            return "mid"
        elif market_cap >= 0.3:
            return "small"
        else:
            return "micro"

    def _safe_get(self, info: dict, key: str, default=None):
        """Safely get a value from info dict."""
        try:
            value = info.get(key, default)
            if value is None or (isinstance(value, float) and (np.isnan(value) or np.isinf(value))):
                return default
            return value
        except Exception:
            return default

    def _calculate_returns(self, history: pd.DataFrame) -> dict:
        """Calculate various return periods."""
        returns = {
            "one_year": None,
            "ytd": None,
            "one_month": None,
        }

        try:
            if history.empty or "Close" not in history.columns:
                return returns

            current_price = history["Close"].iloc[-1]

            # 1-year return
            if len(history) >= 252:
                year_ago_price = history["Close"].iloc[-252]
                returns["one_year"] = round(((current_price - year_ago_price) / year_ago_price) * 100, 2)

            # YTD return
            current_year = datetime.now().year
            ytd_data = history[history.index.year == current_year]
            if not ytd_data.empty:
                ytd_start_price = ytd_data["Close"].iloc[0]
                returns["ytd"] = round(((current_price - ytd_start_price) / ytd_start_price) * 100, 2)

            # 1-month return
            if len(history) >= 21:
                month_ago_price = history["Close"].iloc[-21]
                returns["one_month"] = round(((current_price - month_ago_price) / month_ago_price) * 100, 2)

        except Exception as e:
            logger.debug(f"Error calculating returns: {e}")

        return returns

    def _get_insider_activity(self, ticker: yf.Ticker) -> list:
        """Get recent insider trading activity."""
        activity = []
        try:
            insider_transactions = ticker.insider_transactions
            if insider_transactions is not None and not insider_transactions.empty:
                # Get last 5 transactions
                recent = insider_transactions.head(5)
                for _, row in recent.iterrows():
                    transaction = {
                        "type": "buy" if row.get("Shares", 0) > 0 else "sell",
                        "shares": abs(row.get("Shares", 0)),
                        "value": row.get("Value", 0),
                        "insider": row.get("Insider", "Unknown"),
                        "date": str(row.get("Start Date", ""))[:10],
                    }
                    activity.append(transaction)
        except Exception as e:
            logger.debug(f"Error getting insider activity: {e}")
        return activity

    def _get_recent_news(self, ticker: yf.Ticker) -> list:
        """Get recent news for the stock."""
        news_items = []
        try:
            news = ticker.news
            if news:
                for item in news[:5]:
                    news_items.append({
                        "title": item.get("title", ""),
                        "publisher": item.get("publisher", ""),
                        "link": item.get("link", ""),
                        "date": datetime.fromtimestamp(
                            item.get("providerPublishTime", 0)
                        ).strftime("%Y-%m-%d"),
                    })
        except Exception as e:
            logger.debug(f"Error getting news: {e}")
        return news_items

    def fetch_stock(self, ticker_symbol: str) -> StockData:
        """
        Fetch comprehensive data for a single stock.

        Args:
            ticker_symbol: Stock ticker (e.g., 'AAPL')

        Returns:
            StockData object with all available metrics
        """
        data = StockData(ticker=ticker_symbol)

        try:
            ticker = yf.Ticker(ticker_symbol)
            info = ticker.info

            # Check if valid ticker
            if not info or info.get("regularMarketPrice") is None:
                data.is_valid = False
                data.error_message = "Invalid ticker or no data available"
                return data

            # Basic info
            data.name = self._safe_get(info, "longName", self._safe_get(info, "shortName", ticker_symbol))
            data.sector = self._safe_get(info, "sector", "Unknown")
            data.industry = self._safe_get(info, "industry", "Unknown")

            # Market cap (convert to billions)
            market_cap_raw = self._safe_get(info, "marketCap", 0)
            data.market_cap = round(market_cap_raw / 1e9, 2) if market_cap_raw else 0.0
            data.market_cap_category = self._get_market_cap_category(data.market_cap)

            # Price data
            data.current_price = self._safe_get(info, "regularMarketPrice", 0.0)
            data.fifty_two_week_high = self._safe_get(info, "fiftyTwoWeekHigh", 0.0)
            data.fifty_two_week_low = self._safe_get(info, "fiftyTwoWeekLow", 0.0)

            # Get historical data for ATH and RSI calculation
            history = ticker.history(period="5y")
            if not history.empty:
                data.all_time_high = round(history["High"].max(), 2)
                if data.all_time_high > 0 and data.current_price > 0:
                    data.pct_from_ath = round(
                        ((data.all_time_high - data.current_price) / data.all_time_high) * 100, 2
                    )

                # Calculate RSI
                data.rsi = self._calculate_rsi(history["Close"])

                # Calculate returns
                returns = self._calculate_returns(history)
                data.one_year_return = returns["one_year"]
                data.ytd_return = returns["ytd"]
                data.one_month_return = returns["one_month"]

            # Valuation metrics
            data.pe_ratio = self._safe_get(info, "trailingPE")
            data.forward_pe = self._safe_get(info, "forwardPE")
            data.pb_ratio = self._safe_get(info, "priceToBook")
            data.ps_ratio = self._safe_get(info, "priceToSalesTrailing12Months")
            data.peg_ratio = self._safe_get(info, "pegRatio")
            data.ev_ebitda = self._safe_get(info, "enterpriseToEbitda")

            # Financial health
            data.debt_to_equity = self._safe_get(info, "debtToEquity")
            if data.debt_to_equity:
                data.debt_to_equity = round(data.debt_to_equity / 100, 2)  # Convert from percentage

            data.current_ratio = self._safe_get(info, "currentRatio")

            fcf = self._safe_get(info, "freeCashflow", 0)
            data.free_cash_flow = round(fcf / 1e9, 2) if fcf else None

            data.profit_margin = self._safe_get(info, "profitMargins")
            if data.profit_margin:
                data.profit_margin = round(data.profit_margin * 100, 2)

            data.gross_margin = self._safe_get(info, "grossMargins")
            if data.gross_margin:
                data.gross_margin = round(data.gross_margin * 100, 2)

            data.operating_margin = self._safe_get(info, "operatingMargins")
            if data.operating_margin:
                data.operating_margin = round(data.operating_margin * 100, 2)

            # Dividends
            data.dividend_yield = self._safe_get(info, "dividendYield")
            if data.dividend_yield:
                data.dividend_yield = round(data.dividend_yield * 100, 2)

            data.dividend_rate = self._safe_get(info, "dividendRate")

            # Technical
            data.beta = self._safe_get(info, "beta")
            data.avg_volume = self._safe_get(info, "averageVolume", 0)
            data.recent_volume = self._safe_get(info, "volume", 0)

            # Ownership
            short_pct = self._safe_get(info, "shortPercentOfFloat")
            data.short_interest = round(short_pct * 100, 2) if short_pct else None

            inst_own = self._safe_get(info, "heldPercentInstitutions")
            data.institutional_ownership = round(inst_own * 100, 2) if inst_own else None

            insider_own = self._safe_get(info, "heldPercentInsiders")
            data.insider_ownership = round(insider_own * 100, 2) if insider_own else None

            # Analyst data
            data.analyst_rating = self._safe_get(info, "recommendationKey", "")
            data.analyst_count = self._safe_get(info, "numberOfAnalystOpinions", 0)
            data.target_price_low = self._safe_get(info, "targetLowPrice")
            data.target_price_high = self._safe_get(info, "targetHighPrice")
            data.target_price_mean = self._safe_get(info, "targetMeanPrice")

            # Earnings
            earnings_dates = ticker.earnings_dates
            if earnings_dates is not None and not earnings_dates.empty:
                future_earnings = earnings_dates[earnings_dates.index > datetime.now()]
                if not future_earnings.empty:
                    data.next_earnings_date = future_earnings.index[0].to_pydatetime()

                # Get last earnings surprise
                past_earnings = earnings_dates[earnings_dates.index <= datetime.now()]
                if not past_earnings.empty and "Surprise(%)" in past_earnings.columns:
                    last_surprise = past_earnings["Surprise(%)"].iloc[0]
                    if not pd.isna(last_surprise):
                        data.earnings_surprise_pct = round(last_surprise, 2)

            # Insider activity
            data.insider_activity = self._get_insider_activity(ticker)

            # Recent news
            data.recent_news = self._get_recent_news(ticker)

            logger.info(f"Successfully fetched data for {ticker_symbol}")

        except Exception as e:
            logger.error(f"Error fetching data for {ticker_symbol}: {e}")
            data.is_valid = False
            data.error_message = str(e)

        return data

    def fetch_multiple(self, tickers: list[str]) -> dict[str, StockData]:
        """
        Fetch data for multiple stocks.

        Args:
            tickers: List of ticker symbols

        Returns:
            Dictionary mapping tickers to StockData objects
        """
        results = {}

        for ticker in tickers:
            logger.info(f"Fetching data for {ticker}...")
            results[ticker] = self.fetch_stock(ticker)

        return results

    def get_sector_averages(self, sector: str) -> dict:
        """
        Get average metrics for a sector.
        Uses a predefined set of sector leaders for comparison.
        """
        sector_leaders = {
            "Technology": ["AAPL", "MSFT", "GOOGL", "META", "NVDA"],
            "Healthcare": ["JNJ", "UNH", "PFE", "MRK", "ABBV"],
            "Financial Services": ["JPM", "BAC", "WFC", "GS", "MS"],
            "Consumer Cyclical": ["AMZN", "TSLA", "HD", "NKE", "MCD"],
            "Communication Services": ["GOOGL", "META", "DIS", "NFLX", "VZ"],
            "Industrials": ["CAT", "BA", "HON", "UPS", "GE"],
            "Energy": ["XOM", "CVX", "COP", "SLB", "EOG"],
        }

        leaders = sector_leaders.get(sector, [])
        if not leaders:
            return {}

        metrics = {
            "pe_ratio": [],
            "pb_ratio": [],
            "debt_to_equity": [],
            "profit_margin": [],
        }

        for ticker in leaders[:3]:  # Use top 3 to save API calls
            try:
                data = self.fetch_stock(ticker)
                if data.is_valid:
                    if data.pe_ratio:
                        metrics["pe_ratio"].append(data.pe_ratio)
                    if data.pb_ratio:
                        metrics["pb_ratio"].append(data.pb_ratio)
                    if data.debt_to_equity:
                        metrics["debt_to_equity"].append(data.debt_to_equity)
                    if data.profit_margin:
                        metrics["profit_margin"].append(data.profit_margin)
            except Exception:
                continue

        averages = {}
        for key, values in metrics.items():
            if values:
                averages[key] = round(sum(values) / len(values), 2)

        return averages


# Singleton instance
stock_fetcher = StockFetcher()
