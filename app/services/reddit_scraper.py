"""
Reddit scraper for extracting stock mentions from r/stocks and r/wallstreetbets.
Uses PRAW (Python Reddit API Wrapper) for official API access.
"""

import re
import logging
from datetime import datetime, timedelta
from collections import defaultdict
from dataclasses import dataclass

import praw
from praw.models import Submission

from app.core.config import settings

logger = logging.getLogger(__name__)

# Common words that look like tickers but aren't
FALSE_POSITIVE_TICKERS = {
    "A", "I", "AM", "PM", "CEO", "CFO", "COO", "CTO", "IPO", "ATH", "ATL",
    "DD", "DIP", "EPS", "ETF", "FDA", "FED", "GDP", "IMO", "ITM", "LOL",
    "OTM", "PE", "PT", "RH", "SEC", "TD", "USA", "USD", "WSB", "YOLO",
    "API", "CEO", "CPI", "DCA", "EV", "FD", "FOMO", "FUD", "HODL", "IRA",
    "IV", "LEAPS", "LMAO", "LPT", "MOASS", "MOM", "NET", "NFT", "NOW",
    "OP", "OTC", "POS", "PSA", "PUT", "QE", "RIP", "ROI", "RSI", "SPAC",
    "SP", "TA", "TDA", "THE", "TL", "DR", "TLDR", "US", "VIX", "VWAP",
    "WFH", "YOY", "ALL", "ANY", "ARE", "BIG", "CAN", "DAY", "FOR", "HAS",
    "HIS", "HOW", "ITS", "NEW", "NOT", "ONE", "OUR", "OUT", "OWN", "SAY",
    "SHE", "TWO", "WAY", "WHO", "WHY", "YOU", "GO", "ON", "IT", "AT",
    "BY", "OR", "AN", "BE", "SO", "TO", "UP", "WE", "IF", "MY", "NO",
    "OK", "TV", "AI", "UK", "EU", "UN", "ID", "DD", "CC", "PS",
}

# Valid US stock ticker pattern (1-5 uppercase letters)
TICKER_PATTERN = re.compile(r"\b([A-Z]{1,5})\b")

# Pattern for explicit ticker mentions like $AAPL or (AAPL)
EXPLICIT_TICKER_PATTERN = re.compile(r"(?:\$([A-Z]{1,5})\b|\(([A-Z]{1,5})\))")


@dataclass
class StockMentionData:
    """Data class for stock mention information."""

    ticker: str
    subreddit: str
    post_id: str
    post_title: str
    mention_count: int
    sentiment_score: float
    mentioned_at: datetime


class RedditScraper:
    """Scrapes Reddit for stock mentions and sentiment."""

    def __init__(self):
        self.reddit = None
        self._init_reddit()

    def _init_reddit(self):
        """Initialize Reddit API connection."""
        if settings.REDDIT_CLIENT_ID and settings.REDDIT_CLIENT_SECRET:
            try:
                self.reddit = praw.Reddit(
                    client_id=settings.REDDIT_CLIENT_ID,
                    client_secret=settings.REDDIT_CLIENT_SECRET,
                    user_agent=settings.REDDIT_USER_AGENT,
                )
                logger.info("Reddit API initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize Reddit API: {e}")
                self.reddit = None
        else:
            logger.warning("Reddit API credentials not configured")

    def _extract_tickers(self, text: str) -> list[str]:
        """Extract stock tickers from text."""
        tickers = set()

        # First, look for explicit ticker mentions ($AAPL, (AAPL))
        explicit_matches = EXPLICIT_TICKER_PATTERN.findall(text.upper())
        for match in explicit_matches:
            ticker = match[0] or match[1]  # Either $TICKER or (TICKER)
            if ticker and ticker not in FALSE_POSITIVE_TICKERS:
                tickers.add(ticker)

        # Then look for potential tickers in uppercase words
        # Only add if confidence is high (surrounded by context clues)
        words = TICKER_PATTERN.findall(text)
        for word in words:
            if word not in FALSE_POSITIVE_TICKERS and len(word) >= 2:
                # Check if it looks like a real ticker mention
                if self._is_likely_ticker(word, text):
                    tickers.add(word)

        return list(tickers)

    def _is_likely_ticker(self, word: str, text: str) -> bool:
        """Determine if a word is likely a stock ticker based on context."""
        # Check for common ticker context patterns
        context_patterns = [
            rf"\${word}\b",  # $AAPL
            rf"\({word}\)",  # (AAPL)
            rf"{word}\s+stock",  # AAPL stock
            rf"{word}\s+shares",  # AAPL shares
            rf"buy\s+{word}",  # buy AAPL
            rf"sell\s+{word}",  # sell AAPL
            rf"bought\s+{word}",  # bought AAPL
            rf"sold\s+{word}",  # sold AAPL
            rf"{word}\s+calls?",  # AAPL calls
            rf"{word}\s+puts?",  # AAPL puts
            rf"{word}\s+is\s+",  # AAPL is
            rf"{word}\s+earnings",  # AAPL earnings
        ]

        text_lower = text.lower()
        word_lower = word.lower()

        for pattern in context_patterns:
            if re.search(pattern.lower(), text_lower):
                return True

        return False

    def _analyze_sentiment(self, text: str) -> float:
        """
        Simple sentiment analysis based on keyword matching.
        Returns a score from -1 (bearish) to 1 (bullish).
        """
        text_lower = text.lower()

        bullish_words = [
            "buy", "bought", "long", "calls", "moon", "rocket", "bullish",
            "undervalued", "cheap", "discount", "opportunity", "upside",
            "breakout", "growth", "strong", "beat", "exceeded", "upgrade",
            "accumulate", "loading", "adding", "dip", "sale", "bargain",
        ]

        bearish_words = [
            "sell", "sold", "short", "puts", "dump", "crash", "bearish",
            "overvalued", "expensive", "downside", "breakdown", "weak",
            "miss", "missed", "downgrade", "avoid", "warning", "risk",
            "bubble", "fraud", "scam", "dead", "rip", "baghold",
        ]

        bullish_count = sum(1 for word in bullish_words if word in text_lower)
        bearish_count = sum(1 for word in bearish_words if word in text_lower)

        total = bullish_count + bearish_count
        if total == 0:
            return 0.0

        return (bullish_count - bearish_count) / total

    def scrape_subreddit(
        self,
        subreddit_name: str,
        limit: int = 100,
        time_filter: str = "week",
    ) -> list[StockMentionData]:
        """
        Scrape a subreddit for stock mentions.

        Args:
            subreddit_name: Name of subreddit (e.g., 'stocks', 'wallstreetbets')
            limit: Number of posts to fetch
            time_filter: Time filter for 'hot' and 'top' (hour, day, week, month, year, all)

        Returns:
            List of StockMentionData objects
        """
        if not self.reddit:
            logger.warning("Reddit API not initialized, returning empty results")
            return []

        mentions = []
        ticker_counts = defaultdict(lambda: {"count": 0, "sentiment": [], "posts": []})

        try:
            subreddit = self.reddit.subreddit(subreddit_name)

            # Fetch hot and rising posts
            posts: list[Submission] = []
            posts.extend(list(subreddit.hot(limit=limit)))
            posts.extend(list(subreddit.rising(limit=limit // 2)))

            # Also get top posts from past week for trend analysis
            posts.extend(list(subreddit.top(time_filter=time_filter, limit=limit // 2)))

            # Deduplicate posts
            seen_ids = set()
            unique_posts = []
            for post in posts:
                if post.id not in seen_ids:
                    seen_ids.add(post.id)
                    unique_posts.append(post)

            logger.info(f"Fetched {len(unique_posts)} unique posts from r/{subreddit_name}")

            for post in unique_posts:
                # Combine title and selftext for analysis
                full_text = f"{post.title} {post.selftext or ''}"
                tickers = self._extract_tickers(full_text)
                sentiment = self._analyze_sentiment(full_text)

                for ticker in tickers:
                    ticker_counts[ticker]["count"] += 1
                    ticker_counts[ticker]["sentiment"].append(sentiment)
                    ticker_counts[ticker]["posts"].append({
                        "id": post.id,
                        "title": post.title[:200],
                        "created": datetime.fromtimestamp(post.created_utc),
                    })

            # Convert to StockMentionData objects
            for ticker, data in ticker_counts.items():
                avg_sentiment = (
                    sum(data["sentiment"]) / len(data["sentiment"])
                    if data["sentiment"]
                    else 0.0
                )

                # Use the most recent post for the mention record
                latest_post = max(data["posts"], key=lambda x: x["created"])

                mentions.append(
                    StockMentionData(
                        ticker=ticker,
                        subreddit=subreddit_name,
                        post_id=latest_post["id"],
                        post_title=latest_post["title"],
                        mention_count=data["count"],
                        sentiment_score=round(avg_sentiment, 3),
                        mentioned_at=latest_post["created"],
                    )
                )

        except Exception as e:
            logger.error(f"Error scraping r/{subreddit_name}: {e}")

        return mentions

    def get_all_mentions(self, days_back: int = 7) -> dict[str, list[StockMentionData]]:
        """
        Get stock mentions from all target subreddits.

        Args:
            days_back: Number of days to look back

        Returns:
            Dictionary mapping subreddit names to lists of mentions
        """
        subreddits = ["stocks", "wallstreetbets"]
        all_mentions = {}

        for subreddit in subreddits:
            logger.info(f"Scraping r/{subreddit}...")
            mentions = self.scrape_subreddit(subreddit, limit=200)
            all_mentions[subreddit] = mentions
            logger.info(f"Found {len(mentions)} unique tickers in r/{subreddit}")

        return all_mentions

    def aggregate_mentions(
        self,
        all_mentions: dict[str, list[StockMentionData]],
    ) -> dict[str, dict]:
        """
        Aggregate mentions across all subreddits.

        Returns:
            Dictionary mapping tickers to aggregated data
        """
        aggregated = defaultdict(lambda: {
            "total_mentions": 0,
            "subreddits": {},
            "avg_sentiment": 0.0,
            "sentiment_scores": [],
        })

        for subreddit, mentions in all_mentions.items():
            for mention in mentions:
                ticker = mention.ticker
                aggregated[ticker]["total_mentions"] += mention.mention_count
                aggregated[ticker]["subreddits"][subreddit] = {
                    "count": mention.mention_count,
                    "sentiment": mention.sentiment_score,
                }
                aggregated[ticker]["sentiment_scores"].append(mention.sentiment_score)

        # Calculate average sentiment
        for ticker, data in aggregated.items():
            if data["sentiment_scores"]:
                data["avg_sentiment"] = round(
                    sum(data["sentiment_scores"]) / len(data["sentiment_scores"]),
                    3,
                )
            del data["sentiment_scores"]

        return dict(aggregated)


# Fallback list of stocks to analyze when Reddit API is not available
# Comprehensive coverage across sectors and market caps for diverse analysis
FALLBACK_TICKERS = [
    # ==================== TECHNOLOGY ====================
    # Mega-cap Tech
    "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "META", "NVDA", "TSM", "AVGO", "ORCL",
    # Semiconductors
    "AMD", "INTC", "QCOM", "TXN", "MU", "AMAT", "LRCX", "KLAC", "ADI", "MRVL",
    "ON", "NXPI", "MCHP", "SWKS", "QRVO", "ENTG", "MPWR", "ALGM", "WOLF",
    # Software & Cloud
    "CRM", "ADBE", "NOW", "INTU", "SNOW", "PANW", "CRWD", "DDOG", "ZS", "FTNT",
    "WDAY", "SPLK", "TEAM", "MDB", "NET", "OKTA", "HUBS", "VEEV", "CDNS", "SNPS",
    "ANSS", "PLTR", "PATH", "DOCN", "GTLB", "CFLT", "ESTC", "BILL", "PCTY",
    # AI / Machine Learning Focus
    "AI", "SMCI", "ARM", "IONQ", "RGTI", "QUBT", "SOUN", "BBAI", "UPST", "C3AI",

    # ==================== HEALTHCARE & BIOTECH ====================
    # Large-cap Healthcare
    "UNH", "JNJ", "LLY", "PFE", "ABBV", "MRK", "TMO", "ABT", "DHR", "BMY",
    "AMGN", "GILD", "VRTX", "REGN", "BIIB", "ILMN", "DXCM", "IDXX", "IQV", "ZTS",
    # Medical Devices
    "MDT", "SYK", "BSX", "EW", "ISRG", "BDX", "ZBH", "HOLX", "ALGN", "PODD",
    # Biotech Growth
    "MRNA", "BNTX", "SGEN", "ALNY", "BMRN", "INCY", "EXAS", "RARE", "IONS", "SRPT",
    "NBIX", "PCVX", "LEGN", "DAWN", "RXRX", "KRYS", "ARWR", "NTLA", "BEAM", "EDIT",
    # Healthcare Services
    "HCA", "ELV", "CI", "HUM", "CNC", "CVS", "MCK", "CAH", "ABC", "WBA",

    # ==================== FINANCIALS ====================
    # Major Banks
    "JPM", "BAC", "WFC", "C", "GS", "MS", "USB", "PNC", "TFC", "SCHW",
    # Insurance
    "BRK.B", "PRU", "MET", "AIG", "AFL", "ALL", "TRV", "CB", "PGR", "HIG",
    # Fintech & Payment
    "V", "MA", "PYPL", "SQ", "FIS", "FISV", "AXP", "COF", "DFS", "AFRM",
    "SOFI", "UPST", "COIN", "HOOD", "NU", "MELI", "ADYEN",
    # Asset Management & Exchanges
    "BLK", "KKR", "APO", "ARES", "BX", "ICE", "CME", "NDAQ", "MSCI", "SPGI",

    # ==================== CONSUMER DISCRETIONARY ====================
    # E-commerce & Retail
    "AMZN", "BABA", "JD", "PDD", "EBAY", "ETSY", "W", "CHWY", "RVLV",
    # Automotive
    "TSLA", "GM", "F", "RIVN", "LCID", "NIO", "XPEV", "LI", "STLA", "TM",
    "HMC", "RACE", "APTV", "LEA", "BWA", "GNTX",
    # Restaurants & Travel
    "MCD", "SBUX", "CMG", "DRI", "YUM", "DNUT", "WING", "CAVA",
    "MAR", "HLT", "H", "ABNB", "BKNG", "EXPE", "UBER", "LYFT",
    # Entertainment & Gaming
    "DIS", "NFLX", "WBD", "PARA", "LYV", "SPOT", "RBLX", "EA", "TTWO", "ATVI",
    "DKNG", "PENN", "MGM", "CZR", "WYNN", "LVS",
    # Apparel & Luxury
    "NKE", "LULU", "TJX", "ROST", "GPS", "ANF", "AEO", "TPR", "VFC", "RL",

    # ==================== CONSUMER STAPLES ====================
    "PG", "KO", "PEP", "COST", "WMT", "TGT", "PM", "MO", "MDLZ", "CL",
    "KMB", "GIS", "K", "HSY", "KHC", "SJM", "CAG", "CPB", "HRL", "TSN",
    "KR", "SYY", "ADM", "BG", "MNST", "STZ", "TAP", "SAM", "BF.B",

    # ==================== INDUSTRIALS ====================
    # Aerospace & Defense
    "BA", "LMT", "RTX", "NOC", "GD", "LHX", "TDG", "HWM", "AXON", "HEI",
    # Heavy Machinery & Equipment
    "CAT", "DE", "CNH", "AGCO", "CMI", "PCAR", "OSK", "TEX", "GNRC",
    # Logistics & Transportation
    "UPS", "FDX", "CSX", "UNP", "NSC", "ODFL", "XPO", "JBHT", "CHRW", "EXPD",
    # Airlines
    "DAL", "UAL", "LUV", "AAL", "ALK", "JBLU", "SAVE",
    # Conglomerates & Other Industrial
    "HON", "GE", "MMM", "EMR", "ETN", "ROK", "AME", "PH", "ITW", "SWK",
    "IR", "DOV", "ROP", "VRSK", "CTAS", "PAYX", "CINF", "FAST", "WSO",

    # ==================== ENERGY ====================
    # Oil & Gas Majors
    "XOM", "CVX", "COP", "EOG", "SLB", "OXY", "PSX", "MPC", "VLO", "PXD",
    "DVN", "FANG", "HES", "HAL", "BKR", "OKE", "WMB", "KMI", "ET", "EPD",
    # Clean Energy
    "NEE", "ENPH", "SEDG", "FSLR", "RUN", "NOVA", "PLUG", "BE", "ENVX",

    # ==================== MATERIALS ====================
    "LIN", "APD", "SHW", "ECL", "DD", "DOW", "PPG", "NEM", "FCX", "NUE",
    "STLD", "CLF", "X", "AA", "SCCO", "VMC", "MLM", "CX", "MOS", "CF",

    # ==================== REAL ESTATE ====================
    "AMT", "PLD", "CCI", "EQIX", "PSA", "SPG", "O", "WELL", "DLR", "AVB",
    "EQR", "VTR", "ARE", "BXP", "SLG", "VNO", "KIM", "REG", "FRT", "MAA",

    # ==================== UTILITIES ====================
    "NEE", "DUK", "SO", "D", "AEP", "SRE", "XEL", "ED", "PCG", "EXC",
    "WEC", "ES", "AWK", "AEE", "CMS", "DTE", "ETR", "FE", "PPL", "NI",

    # ==================== COMMUNICATION SERVICES ====================
    "GOOGL", "META", "VZ", "T", "TMUS", "CHTR", "CMCSA", "NFLX", "DIS",
    "EA", "TTWO", "MTCH", "SNAP", "PINS", "RDDT", "ZG", "Z", "IAC",

    # ==================== INTERNATIONAL / ADRs ====================
    # Asia
    "BABA", "JD", "PDD", "BIDU", "NIO", "XPEV", "LI", "TSM", "SONY", "TM",
    "HMC", "MUFG", "SMFG", "KB", "SHG", "WIT", "INFY", "HDB", "IBN",
    # Europe
    "ASML", "SAP", "NVO", "AZN", "GSK", "SNY", "NVS", "SHEL", "BP", "TTE",
    "UL", "DEO", "BUD", "RIO", "BHP", "VALE", "ABB", "SIEGY", "EADSY",
    # Latin America
    "MELI", "NU", "ITUB", "BBD", "PBR", "ABEV", "SQM", "BSBR", "ERJ",
    # Canada
    "SHOP", "TD", "RY", "BNS", "ENB", "CNQ", "SU", "TRP", "CP", "CNI",

    # ==================== POPULAR REDDIT / MOMENTUM ====================
    "GME", "AMC", "BBBY", "BB", "CLOV", "WISH", "SKLZ", "PLTR", "SOFI",
    "RIVN", "LCID", "NIO", "COIN", "HOOD", "RBLX", "ROKU", "ZM", "DOCU",
    "SNOW", "U", "DKNG", "SPCE", "ARKK", "SQQQ", "TQQQ", "UVXY",

    # ==================== SMALL/MID-CAP GROWTH ====================
    "CELH", "DUOL", "AXON", "TOST", "BROS", "RYAN", "GLBE", "RELY", "ONON",
    "BIRK", "IOT", "S", "FRSH", "MNDY", "APP", "GRAB", "SE", "CPNG",
]

# Remove duplicates while preserving order
FALLBACK_TICKERS = list(dict.fromkeys(FALLBACK_TICKERS))


def get_fallback_mentions() -> dict[str, dict]:
    """
    Generate fallback stock data when Reddit API is unavailable.
    Returns simulated mention data for popular stocks.
    """
    import random

    logger.info("Using fallback stock list (Reddit API not configured)")

    aggregated = {}
    for ticker in FALLBACK_TICKERS:
        # Simulate realistic mention counts and sentiment
        mentions = random.randint(10, 150)
        sentiment = round(random.uniform(-0.3, 0.5), 3)

        aggregated[ticker] = {
            "total_mentions": mentions,
            "subreddits": {
                "stocks": {"count": mentions // 2, "sentiment": sentiment},
                "wallstreetbets": {"count": mentions // 2, "sentiment": sentiment},
            },
            "avg_sentiment": sentiment,
        }

    return aggregated


# Singleton instance
reddit_scraper = RedditScraper()
