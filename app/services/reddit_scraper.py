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


# Singleton instance
reddit_scraper = RedditScraper()
