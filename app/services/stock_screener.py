"""
Stock screener that proactively discovers new value opportunities
beyond the static fallback ticker list.

Uses yfinance screeners and lightweight pre-filtering to find:
- Stocks with large drops from highs (value plays)
- Low P/E stocks with positive cash flow
- High insider-buying activity
- Stocks near 52-week lows with decent fundamentals
"""

import logging
import random
from datetime import datetime, timedelta
from typing import Optional

import yfinance as yf

logger = logging.getLogger(__name__)

# Pre-built yfinance screener queries
# These use Yahoo Finance's built-in screener to discover stocks
SCREEN_QUERIES = {
    "undervalued_large_caps": {
        "query": {
            "operator": "AND",
            "operands": [
                {"operator": "or", "operands": [
                    {"operator": "EQ", "operands": ["region", "us"]},
                ]},
                {"operator": "GT", "operands": ["intradaymarketcap", 2_000_000_000]},
                {"operator": "LT", "operands": ["peratio.lasttwelvemonths", 15]},
                {"operator": "GT", "operands": ["peratio.lasttwelvemonths", 0]},
            ],
        },
        "size": 100,
        "offset": 0,
        "sortField": "intradaymarketcap",
        "sortType": "DESC",
    },
    "undervalued_growth": {
        "query": {
            "operator": "AND",
            "operands": [
                {"operator": "or", "operands": [
                    {"operator": "EQ", "operands": ["region", "us"]},
                ]},
                {"operator": "GT", "operands": ["intradaymarketcap", 500_000_000]},
                {"operator": "LT", "operands": ["pegratio_5y", 1.0]},
                {"operator": "GT", "operands": ["pegratio_5y", 0]},
            ],
        },
        "size": 100,
        "offset": 0,
        "sortField": "pegratio_5y",
        "sortType": "ASC",
    },
    "high_dividend_value": {
        "query": {
            "operator": "AND",
            "operands": [
                {"operator": "or", "operands": [
                    {"operator": "EQ", "operands": ["region", "us"]},
                ]},
                {"operator": "GT", "operands": ["intradaymarketcap", 1_000_000_000]},
                {"operator": "GT", "operands": ["dividendyield", 3]},
                {"operator": "LT", "operands": ["peratio.lasttwelvemonths", 20]},
                {"operator": "GT", "operands": ["peratio.lasttwelvemonths", 0]},
            ],
        },
        "size": 50,
        "offset": 0,
        "sortField": "dividendyield",
        "sortType": "DESC",
    },
    "beaten_down_mid_caps": {
        "query": {
            "operator": "AND",
            "operands": [
                {"operator": "or", "operands": [
                    {"operator": "EQ", "operands": ["region", "us"]},
                ]},
                {"operator": "BTWN", "operands": ["intradaymarketcap", 1_000_000_000, 20_000_000_000]},
                {"operator": "LT", "operands": ["fiftytwowkchangepercent.currentprice", -25]},
                {"operator": "GT", "operands": ["peratio.lasttwelvemonths", 0]},
            ],
        },
        "size": 100,
        "offset": 0,
        "sortField": "fiftytwowkchangepercent.currentprice",
        "sortType": "ASC",
    },
    "small_cap_value": {
        "query": {
            "operator": "AND",
            "operands": [
                {"operator": "or", "operands": [
                    {"operator": "EQ", "operands": ["region", "us"]},
                ]},
                {"operator": "BTWN", "operands": ["intradaymarketcap", 300_000_000, 2_000_000_000]},
                {"operator": "LT", "operands": ["pricetobookvalue.quarterly", 1.5]},
                {"operator": "GT", "operands": ["pricetobookvalue.quarterly", 0]},
                {"operator": "GT", "operands": ["peratio.lasttwelvemonths", 0]},
                {"operator": "LT", "operands": ["peratio.lasttwelvemonths", 20]},
            ],
        },
        "size": 75,
        "offset": 0,
        "sortField": "intradaymarketcap",
        "sortType": "DESC",
    },
}

# Yahoo Finance predefined screener IDs
PREDEFINED_SCREENS = [
    "day_losers",
    "undervalued_large_caps",
    "undervalued_growth_stocks",
    "most_actives",
    "aggressive_small_caps",
]


def _run_predefined_screen(screen_id: str, max_results: int = 50) -> list[str]:
    """Run a Yahoo Finance predefined screener and return tickers."""
    tickers = []
    try:
        screener = yf.Screener()
        screener.set_predefined_body(screen_id)
        response = screener.response
        quotes = response.get("quotes", [])
        for quote in quotes[:max_results]:
            symbol = quote.get("symbol", "")
            # Filter to US-style tickers (no dots except .B, no numbers-only)
            if symbol and len(symbol) <= 5 and symbol.isalpha():
                tickers.append(symbol)
            elif "." in symbol and symbol.replace(".", "").isalpha():
                tickers.append(symbol)  # Allow BRK.B style
        logger.info(f"Predefined screen '{screen_id}' returned {len(tickers)} tickers")
    except Exception as e:
        logger.warning(f"Predefined screen '{screen_id}' failed: {e}")
    return tickers


def _run_custom_screen(name: str, body: dict, max_results: int = 75) -> list[str]:
    """Run a custom Yahoo Finance screener query and return tickers."""
    tickers = []
    try:
        screener = yf.Screener()
        screener.set_body(body)
        response = screener.response
        quotes = response.get("quotes", [])
        for quote in quotes[:max_results]:
            symbol = quote.get("symbol", "")
            if symbol and len(symbol) <= 5:
                # Filter out non-US tickers (contain numbers or weird chars)
                clean = symbol.replace(".", "").replace("-", "")
                if clean.isalpha():
                    tickers.append(symbol)
        logger.info(f"Custom screen '{name}' returned {len(tickers)} tickers")
    except Exception as e:
        logger.warning(f"Custom screen '{name}' failed: {e}")
    return tickers


def _get_sector_losers() -> list[str]:
    """Find the worst-performing stocks in each sector over the past month.
    These are potential value buys if fundamentals are intact."""
    tickers = []
    sectors = [
        "Technology", "Healthcare", "Financial Services",
        "Consumer Cyclical", "Consumer Defensive", "Industrials",
        "Energy", "Basic Materials", "Communication Services",
        "Real Estate", "Utilities",
    ]
    # Pick a random subset of sectors to avoid too many API calls
    selected = random.sample(sectors, min(4, len(sectors)))

    for sector in selected:
        try:
            screen_body = {
                "query": {
                    "operator": "AND",
                    "operands": [
                        {"operator": "or", "operands": [
                            {"operator": "EQ", "operands": ["region", "us"]},
                        ]},
                        {"operator": "EQ", "operands": ["sector", sector]},
                        {"operator": "GT", "operands": ["intradaymarketcap", 500_000_000]},
                        {"operator": "LT", "operands": ["fiftytwowkchangepercent.currentprice", -20]},
                    ],
                },
                "size": 25,
                "offset": 0,
                "sortField": "fiftytwowkchangepercent.currentprice",
                "sortType": "ASC",
            }
            sector_tickers = _run_custom_screen(f"sector_losers_{sector}", screen_body, max_results=25)
            tickers.extend(sector_tickers)
        except Exception as e:
            logger.warning(f"Sector loser scan for {sector} failed: {e}")

    return tickers


def discover_stocks(existing_tickers: list[str] = None, max_new: int = 150) -> list[str]:
    """
    Discover new stock opportunities beyond the static fallback list.

    Runs multiple screening strategies and returns deduplicated tickers,
    excluding any already in existing_tickers.

    Args:
        existing_tickers: Tickers already in the analysis pipeline
        max_new: Maximum new tickers to return

    Returns:
        List of newly discovered ticker symbols
    """
    existing = set(existing_tickers or [])
    discovered = []

    logger.info("Starting stock discovery scan...")

    # Strategy 1: Yahoo predefined screeners
    # Pick 2-3 random predefined screens to vary results across reports
    selected_screens = random.sample(PREDEFINED_SCREENS, min(3, len(PREDEFINED_SCREENS)))
    for screen_id in selected_screens:
        try:
            tickers = _run_predefined_screen(screen_id)
            new = [t for t in tickers if t not in existing and t not in discovered]
            discovered.extend(new)
            logger.info(f"Predefined '{screen_id}': {len(new)} new tickers")
        except Exception as e:
            logger.warning(f"Predefined screen {screen_id} failed: {e}")

    # Strategy 2: Custom value screens
    # Pick 2-3 custom screens randomly for variety
    screen_names = list(SCREEN_QUERIES.keys())
    selected_custom = random.sample(screen_names, min(3, len(screen_names)))
    for name in selected_custom:
        try:
            body = SCREEN_QUERIES[name]
            tickers = _run_custom_screen(name, body)
            new = [t for t in tickers if t not in existing and t not in discovered]
            discovered.extend(new)
            logger.info(f"Custom '{name}': {len(new)} new tickers")
        except Exception as e:
            logger.warning(f"Custom screen {name} failed: {e}")

    # Strategy 3: Sector losers (beaten-down stocks per sector)
    try:
        sector_tickers = _get_sector_losers()
        new = [t for t in sector_tickers if t not in existing and t not in discovered]
        discovered.extend(new)
        logger.info(f"Sector losers scan: {len(new)} new tickers")
    except Exception as e:
        logger.warning(f"Sector losers scan failed: {e}")

    # Deduplicate
    seen = set()
    unique = []
    for t in discovered:
        if t not in seen:
            seen.add(t)
            unique.append(t)

    # Shuffle so we don't always prioritize the same screens
    random.shuffle(unique)

    result = unique[:max_new]
    logger.info(f"Stock discovery complete: {len(result)} new tickers found (from {len(unique)} total)")

    return result
