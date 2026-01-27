"""
Report generator that combines Reddit mentions and stock data
to create daily value stock analysis reports.
"""

import logging
import random
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import DailyReport, ReportStock, Stock, StockMention, StockMetrics
from app.services.reddit_scraper import reddit_scraper, StockMentionData, get_fallback_mentions
from app.services.stock_fetcher import stock_fetcher, StockData
from app.services.finnhub_client import finnhub_client

logger = logging.getLogger(__name__)


# Investment tips for the "tip of the day" feature
INVESTMENT_TIPS = [
    {
        "title": "P/E Ratio Basics",
        "content": "The P/E (Price-to-Earnings) ratio shows how much you're paying for each dollar of a company's profit. A P/E of 20 means you pay $20 for every $1 of earnings. Lower P/E can mean undervalued, but could also signal problems. Always compare to the sector average."
    },
    {
        "title": "What Free Cash Flow Tells You",
        "content": "Free Cash Flow (FCF) is the actual cash a company generates after expenses. Unlike earnings, it's hard to manipulate. Positive FCF means the company can pay dividends, buy back stock, or invest in growth without taking on debt."
    },
    {
        "title": "Understanding RSI",
        "content": "RSI (Relative Strength Index) measures momentum on a 0-100 scale. Below 30 is considered 'oversold' (potentially a buying opportunity), above 70 is 'overbought' (might be due for a pullback). It's not a guarantee—just one signal among many."
    },
    {
        "title": "Debt-to-Equity Explained",
        "content": "Debt-to-Equity shows how much debt a company uses compared to shareholder equity. Under 1.0 is generally healthy. High D/E isn't always bad (utilities often run higher), but during tough times, heavily indebted companies struggle more."
    },
    {
        "title": "Why Insider Buying Matters",
        "content": "When executives buy their own company's stock with personal money, it's often a bullish signal—they have inside knowledge and are betting on success. Selling is less meaningful (they might just need cash), but unusual buying patterns are worth noting."
    },
    {
        "title": "The PEG Ratio Advantage",
        "content": "PEG adjusts P/E for growth rate. A P/E of 30 sounds expensive, but if earnings grow 30% yearly, the PEG is 1.0 (fairly valued). Under 1.0 often suggests you're getting growth at a discount."
    },
    {
        "title": "Short Interest as a Contrarian Signal",
        "content": "High short interest means many investors are betting against a stock. If the company proves them wrong, shorts must buy to cover, driving prices up fast (a 'short squeeze'). But high shorts can also mean real problems—do your research."
    },
    {
        "title": "52-Week Range Context",
        "content": "A stock near its 52-week low isn't automatically a bargain—it might be falling for good reasons. But combined with strong fundamentals, it could signal a value opportunity. Check why it's down before buying."
    },
    {
        "title": "Institutional Ownership Sweet Spot",
        "content": "High institutional ownership (60%+) means professionals believe in it, adding stability. Very low (<20%) could mean undiscovered value or red flags. The sweet spot is often 40-70%: validated but not overcrowded."
    },
    {
        "title": "Earnings Dates Matter",
        "content": "Stock prices often swing wildly around earnings reports. If you buy just before earnings, you're essentially gambling on the results. Some prefer buying after earnings settle, even if they miss the initial pop."
    },
    {
        "title": "Price-to-Book for Value Hunters",
        "content": "P/B ratio compares stock price to the company's book value (assets minus liabilities). Under 1.0 means you could theoretically buy the company for less than its assets are worth. Common in banks and insurance—less useful for tech."
    },
    {
        "title": "The Dividend Yield Trade-off",
        "content": "High dividend yields are attractive but can be a trap. If a stock drops 50%, its yield doubles—but that high yield reflects distress, not generosity. Look for consistent dividend growth, not just high current yields."
    },
]


@dataclass
class AnalyzedStock:
    """Stock with complete analysis for report."""

    ticker: str
    name: str
    sector: str
    industry: str
    stock_data: StockData
    reddit_mentions: int = 0
    reddit_sentiment: float = 0.0
    score: float = 0.0
    is_dark_horse: bool = False
    sector_category: str = ""
    buy_case: str = ""
    risk_factors: list = field(default_factory=list)
    dark_horse_reasons: list = field(default_factory=list)
    bullish_signals: int = 0
    bearish_signals: int = 0
    neutral_signals: int = 0


class ReportGenerator:
    """Generates daily stock analysis reports."""

    def __init__(self, db: Session):
        self.db = db

    def _categorize_sector(self, sector: str, industry: str) -> str:
        """Categorize stock into one of our focus sectors."""
        sector_lower = sector.lower()
        industry_lower = industry.lower()

        # Tech/AI detection
        tech_keywords = ["technology", "software", "semiconductor", "internet", "computer"]
        ai_keywords = ["artificial intelligence", "machine learning", "ai ", "neural", "data"]

        if any(kw in industry_lower for kw in ai_keywords):
            return "ai"
        if any(kw in sector_lower or kw in industry_lower for kw in tech_keywords):
            return "tech"

        # Medical/Healthcare
        medical_keywords = ["health", "medical", "biotech", "pharma", "drug", "therapeutic"]
        if any(kw in sector_lower or kw in industry_lower for kw in medical_keywords):
            return "medical"

        # International (harder to detect, would need country data)
        # For now, check for ADR or international keywords
        intl_keywords = ["adr", "international", "global", "foreign"]
        if any(kw in industry_lower for kw in intl_keywords):
            return "international"

        return "other"

    def _calculate_score(self, stock: StockData, reddit_mentions: int, sentiment: float) -> float:
        """
        Calculate a composite score for ranking stocks.
        Higher score = more attractive value opportunity.
        """
        score = 0.0

        # Price drop from ATH (more drop = higher score, up to a point)
        if stock.pct_from_ath:
            if 15 <= stock.pct_from_ath <= 50:
                score += min(stock.pct_from_ath, 40) * 1.5  # Max 60 points
            elif stock.pct_from_ath > 50:
                score += 40  # Cap it—might be falling knife

        # Reddit mentions (moderate mentions preferred)
        if 10 <= reddit_mentions <= 100:
            score += 20
        elif reddit_mentions > 100:
            score += 10  # Still good, but crowded

        # Sentiment bonus
        if sentiment > 0.3:
            score += 15
        elif sentiment > 0:
            score += 10

        # RSI oversold bonus
        if stock.rsi and stock.rsi < 30:
            score += 25
        elif stock.rsi and stock.rsi < 40:
            score += 15

        # P/E value (lower is better, but not too low)
        if stock.pe_ratio:
            if 5 < stock.pe_ratio < 15:
                score += 20
            elif 15 <= stock.pe_ratio < 25:
                score += 10

        # PEG under 1 is attractive
        if stock.peg_ratio and stock.peg_ratio < 1:
            score += 20

        # Low debt is good
        if stock.debt_to_equity and stock.debt_to_equity < 0.5:
            score += 15
        elif stock.debt_to_equity and stock.debt_to_equity < 1.0:
            score += 10

        # Positive free cash flow
        if stock.free_cash_flow and stock.free_cash_flow > 0:
            score += 15

        # Insider buying (check for recent buys)
        recent_buys = [a for a in stock.insider_activity if a.get("type") == "buy"]
        if recent_buys:
            score += 20

        # Analyst upside
        if stock.target_price_mean and stock.current_price:
            upside = ((stock.target_price_mean - stock.current_price) / stock.current_price) * 100
            if upside > 30:
                score += 20
            elif upside > 15:
                score += 10

        return round(score, 2)

    def _count_signals(self, stock: StockData) -> tuple[int, int, int]:
        """Count bullish, bearish, and neutral signals."""
        bullish = 0
        bearish = 0
        neutral = 0

        # RSI
        if stock.rsi:
            if stock.rsi < 30:
                bullish += 1
            elif stock.rsi > 70:
                bearish += 1
            else:
                neutral += 1

        # P/E
        if stock.pe_ratio:
            if stock.pe_ratio < 15:
                bullish += 1
            elif stock.pe_ratio > 30:
                bearish += 1
            else:
                neutral += 1

        # PEG
        if stock.peg_ratio:
            if stock.peg_ratio < 1:
                bullish += 1
            elif stock.peg_ratio > 2:
                bearish += 1
            else:
                neutral += 1

        # Debt
        if stock.debt_to_equity:
            if stock.debt_to_equity < 0.5:
                bullish += 1
            elif stock.debt_to_equity > 1.5:
                bearish += 1
            else:
                neutral += 1

        # FCF
        if stock.free_cash_flow:
            if stock.free_cash_flow > 0:
                bullish += 1
            else:
                bearish += 1

        # Short interest
        if stock.short_interest:
            if stock.short_interest > 20:
                bearish += 1
            elif stock.short_interest < 5:
                bullish += 1
            else:
                neutral += 1

        # Insider activity
        recent_buys = [a for a in stock.insider_activity if a.get("type") == "buy"]
        recent_sells = [a for a in stock.insider_activity if a.get("type") == "sell"]
        if len(recent_buys) > len(recent_sells):
            bullish += 1
        elif len(recent_sells) > len(recent_buys):
            bearish += 1

        # 1-year return
        if stock.one_year_return:
            if stock.one_year_return < -30:
                neutral += 1  # Could be value or falling knife
            elif stock.one_year_return > 20:
                bullish += 1

        return bullish, bearish, neutral

    def _generate_buy_case(self, stock: StockData, reddit_mentions: int, sentiment: float) -> str:
        """Generate a plain-English explanation of why this stock might be a buy."""
        points = []

        # Price drop
        if stock.pct_from_ath and stock.pct_from_ath >= 20:
            points.append(f"Trading {stock.pct_from_ath:.0f}% below its all-time high, offering a potential discount entry")

        # RSI
        if stock.rsi and stock.rsi < 30:
            points.append(f"RSI at {stock.rsi:.0f} indicates oversold conditions—the selling may be overdone")

        # Fundamentals
        if stock.free_cash_flow and stock.free_cash_flow > 0:
            points.append(f"Generating ${stock.free_cash_flow:.1f}B in free cash flow, showing real financial strength")

        if stock.debt_to_equity and stock.debt_to_equity < 0.5:
            points.append("Low debt levels provide financial flexibility and lower risk")

        if stock.peg_ratio and stock.peg_ratio < 1:
            points.append(f"PEG ratio of {stock.peg_ratio:.2f} suggests you're getting growth at a reasonable price")

        # Insider activity
        recent_buys = [a for a in stock.insider_activity if a.get("type") == "buy"]
        if recent_buys:
            total_value = sum(a.get("value", 0) for a in recent_buys)
            if total_value > 0:
                points.append(f"Insiders have recently bought ${total_value/1e6:.1f}M worth—they're betting on the company")

        # Analyst upside
        if stock.target_price_mean and stock.current_price:
            upside = ((stock.target_price_mean - stock.current_price) / stock.current_price) * 100
            if upside > 20:
                points.append(f"Analysts see {upside:.0f}% upside to their average price target")

        # Reddit sentiment
        if sentiment > 0.3:
            points.append("Reddit sentiment is notably bullish")

        if not points:
            points.append("Shows potential value characteristics worth investigating further")

        return " ".join(points[:4]) + "."  # Limit to 4 points

    def _generate_risk_factors(self, stock: StockData) -> list[str]:
        """Generate plain-English risk factors."""
        risks = []

        # Earnings timing
        if stock.next_earnings_date:
            days_until = (stock.next_earnings_date - datetime.now()).days
            if 0 < days_until <= 14:
                risks.append(f"Earnings report in {days_until} days—expect potential price swings")

        # High debt
        if stock.debt_to_equity and stock.debt_to_equity > 1.5:
            risks.append("High debt levels could pressure the company if conditions worsen")

        # Negative cash flow
        if stock.free_cash_flow and stock.free_cash_flow < 0:
            risks.append("Burning cash—needs to improve profitability or raise capital")

        # High short interest
        if stock.short_interest and stock.short_interest > 15:
            risks.append(f"{stock.short_interest:.1f}% of shares are sold short—many investors are betting against it")

        # Price momentum
        if stock.one_year_return and stock.one_year_return < -40:
            risks.append("Down significantly over the past year—could continue falling")

        # Low analyst coverage
        if stock.analyst_count and stock.analyst_count < 5:
            risks.append("Limited analyst coverage means less scrutiny and research available")

        # High beta
        if stock.beta and stock.beta > 1.5:
            risks.append(f"High volatility (beta {stock.beta:.1f})—expect bigger swings than the market")

        # Small cap
        if stock.market_cap_category in ["small", "micro"]:
            risks.append("Smaller company with less liquidity and potentially higher risk")

        # Add generic risk if none found
        if not risks:
            risks.append("Standard market risks apply—always do your own research")

        return risks[:5]  # Limit to 5 risks

    def _identify_dark_horses(self, analyzed: list[AnalyzedStock]) -> list[AnalyzedStock]:
        """Identify dark horse candidates from analyzed stocks."""
        dark_horses = []

        for stock in analyzed:
            reasons = []

            # Low reddit mentions
            if stock.reddit_mentions < settings.DARK_HORSE_MAX_MENTIONS:
                reasons.append(f"Only {stock.reddit_mentions} Reddit mentions this week—under the radar")

            # Low institutional ownership
            if (stock.stock_data.institutional_ownership and
                    stock.stock_data.institutional_ownership < settings.DARK_HORSE_MAX_INSTITUTIONAL * 100):
                reasons.append(
                    f"Only {stock.stock_data.institutional_ownership:.0f}% institutional ownership—"
                    "big money hasn't piled in yet"
                )

            # Small/mid cap
            if stock.stock_data.market_cap_category in ["small", "mid"]:
                reasons.append(f"{stock.stock_data.market_cap_category.title()}-cap with less analyst coverage")

            # Low analyst coverage
            if stock.stock_data.analyst_count and stock.stock_data.analyst_count < 10:
                reasons.append(f"Only {stock.stock_data.analyst_count} analysts covering—potentially undiscovered")

            # Must have at least 2 dark horse reasons and good fundamentals
            if len(reasons) >= 2 and stock.score > 50:
                stock.is_dark_horse = True
                stock.dark_horse_reasons = reasons
                dark_horses.append(stock)

        return dark_horses

    def _get_or_create_stock(self, stock_data: StockData) -> Stock:
        """Get existing stock from DB or create new one."""
        stock = self.db.query(Stock).filter(Stock.ticker == stock_data.ticker).first()

        if not stock:
            stock = Stock(
                ticker=stock_data.ticker,
                name=stock_data.name,
                sector=stock_data.sector,
                industry=stock_data.industry,
                market_cap=stock_data.market_cap,
                market_cap_category=stock_data.market_cap_category,
            )
            self.db.add(stock)
            self.db.flush()
        else:
            # Update existing stock info
            stock.name = stock_data.name
            stock.sector = stock_data.sector
            stock.industry = stock_data.industry
            stock.market_cap = stock_data.market_cap
            stock.market_cap_category = stock_data.market_cap_category
            stock.updated_at = datetime.utcnow()

        return stock

    def _get_sentiment_label(self, sentiment: float) -> str:
        """Convert sentiment score to label."""
        if sentiment > 0.3:
            return "Bullish"
        elif sentiment < -0.3:
            return "Bearish"
        else:
            return "Mixed"

    def generate_report(self) -> Optional[DailyReport]:
        """
        Generate the daily stock analysis report.

        Returns:
            DailyReport object saved to database, or None if generation fails
        """
        logger.info("Starting daily report generation...")

        # Step 1: Get stock mentions from available sources
        # For now, use fallback list to ensure fast report generation
        # TODO: Re-enable Finnhub/Reddit once we optimize API calls
        aggregated = {}

        # Try Reddit API first if configured
        if settings.REDDIT_CLIENT_ID:
            logger.info("Fetching from Reddit API...")
            all_mentions = reddit_scraper.get_all_mentions()
            aggregated = reddit_scraper.aggregate_mentions(all_mentions)

        # Fall back to curated list (fast, reliable)
        if not aggregated:
            logger.info("Using curated stock list for analysis")
            aggregated = get_fallback_mentions()

        logger.info(f"Found {len(aggregated)} unique tickers to analyze")

        # Step 2: Filter to stocks with minimum mentions
        qualifying_tickers = [
            ticker for ticker, data in aggregated.items()
            if data["total_mentions"] >= settings.MIN_REDDIT_MENTIONS
        ]

        # Limit to top 40 tickers to keep report generation fast
        # (we'll select top 20 from these after analysis)
        qualifying_tickers = qualifying_tickers[:40]

        logger.info(f"Analyzing {len(qualifying_tickers)} tickers")

        # Step 3: Fetch stock data for qualifying tickers
        logger.info("Fetching stock data from Yahoo Finance...")
        stock_data_map = stock_fetcher.fetch_multiple(qualifying_tickers)

        # Step 4: Filter and analyze stocks
        analyzed_stocks: list[AnalyzedStock] = []

        for ticker, stock_data in stock_data_map.items():
            if not stock_data.is_valid:
                continue

            # Check if meets our criteria
            reddit_data = aggregated.get(ticker, {})
            mentions = reddit_data.get("total_mentions", 0)
            sentiment = reddit_data.get("avg_sentiment", 0.0)

            # Must have dropped from ATH
            if not stock_data.pct_from_ath or stock_data.pct_from_ath < settings.MIN_DROP_FROM_ATH * 100:
                continue

            # Categorize sector
            sector_category = self._categorize_sector(stock_data.sector, stock_data.industry)

            # Calculate score
            score = self._calculate_score(stock_data, mentions, sentiment)

            # Count signals
            bullish, bearish, neutral = self._count_signals(stock_data)

            # Generate analysis
            buy_case = self._generate_buy_case(stock_data, mentions, sentiment)
            risk_factors = self._generate_risk_factors(stock_data)

            analyzed = AnalyzedStock(
                ticker=ticker,
                name=stock_data.name,
                sector=stock_data.sector,
                industry=stock_data.industry,
                stock_data=stock_data,
                reddit_mentions=mentions,
                reddit_sentiment=sentiment,
                score=score,
                sector_category=sector_category,
                buy_case=buy_case,
                risk_factors=risk_factors,
                bullish_signals=bullish,
                bearish_signals=bearish,
                neutral_signals=neutral,
            )

            analyzed_stocks.append(analyzed)

        logger.info(f"{len(analyzed_stocks)} stocks pass all criteria")

        if not analyzed_stocks:
            logger.warning("No stocks passed all criteria")
            return None

        # Step 5: Identify dark horses
        dark_horses = self._identify_dark_horses(analyzed_stocks)
        logger.info(f"Identified {len(dark_horses)} potential dark horse picks")

        # Step 6: Rank and select top stocks
        # Sort by score descending
        analyzed_stocks.sort(key=lambda x: x.score, reverse=True)

        # Select top stocks, ensuring we include dark horses
        main_picks_count = settings.TOP_STOCKS_COUNT - settings.DARK_HORSE_COUNT
        main_picks = [s for s in analyzed_stocks if not s.is_dark_horse][:main_picks_count]

        # Add dark horses
        dark_horse_picks = dark_horses[:settings.DARK_HORSE_COUNT]

        # Combine and assign ranks
        final_picks = main_picks + dark_horse_picks

        # Step 7: Create report in database
        report_date = datetime.now().replace(hour=21, minute=0, second=0, microsecond=0)

        # Check if report already exists for today
        existing = self.db.query(DailyReport).filter(
            DailyReport.report_date == report_date
        ).first()

        if existing:
            logger.info("Report already exists for today, updating...")
            self.db.delete(existing)
            self.db.flush()

        # Select random tip of the day
        tip = random.choice(INVESTMENT_TIPS)

        report = DailyReport(
            report_date=report_date,
            total_stocks_analyzed=len(qualifying_tickers),
            stocks_passing_criteria=len(analyzed_stocks),
            tip_of_the_day_title=tip["title"],
            tip_of_the_day_content=tip["content"],
        )
        self.db.add(report)
        self.db.flush()

        # Step 8: Add stocks to report
        for rank, analyzed in enumerate(final_picks, 1):
            stock_data = analyzed.stock_data

            # Get or create stock in DB
            stock = self._get_or_create_stock(stock_data)

            # Calculate target upside
            target_upside = None
            if stock_data.target_price_mean and stock_data.current_price:
                target_upside = round(
                    ((stock_data.target_price_mean - stock_data.current_price) /
                     stock_data.current_price) * 100, 2
                )

            report_stock = ReportStock(
                report_id=report.id,
                stock_id=stock.id,
                rank=rank,
                is_dark_horse=analyzed.is_dark_horse,
                sector_category=analyzed.sector_category,
                price_at_report=stock_data.current_price,
                pct_from_ath=stock_data.pct_from_ath,
                pe_ratio=stock_data.pe_ratio,
                pb_ratio=stock_data.pb_ratio,
                peg_ratio=stock_data.peg_ratio,
                debt_to_equity=stock_data.debt_to_equity,
                free_cash_flow=stock_data.free_cash_flow,
                profit_margin=stock_data.profit_margin,
                dividend_yield=stock_data.dividend_yield,
                rsi=stock_data.rsi,
                short_interest=stock_data.short_interest,
                institutional_ownership=stock_data.institutional_ownership,
                one_year_return=stock_data.one_year_return,
                beta=stock_data.beta,
                fifty_two_week_high=stock_data.fifty_two_week_high,
                fifty_two_week_low=stock_data.fifty_two_week_low,
                analyst_rating=stock_data.analyst_rating,
                analyst_count=stock_data.analyst_count,
                target_price_mean=stock_data.target_price_mean,
                target_upside_pct=target_upside,
                next_earnings_date=stock_data.next_earnings_date,
                reddit_mentions_week=analyzed.reddit_mentions,
                reddit_sentiment=analyzed.reddit_sentiment,
                sentiment_label=self._get_sentiment_label(analyzed.reddit_sentiment),
                insider_activity=stock_data.insider_activity,
                buy_case=analyzed.buy_case,
                risk_factors=analyzed.risk_factors,
                recent_news=stock_data.recent_news,
                dark_horse_reasons=analyzed.dark_horse_reasons if analyzed.is_dark_horse else None,
                bullish_signals=analyzed.bullish_signals,
                bearish_signals=analyzed.bearish_signals,
                neutral_signals=analyzed.neutral_signals,
            )
            self.db.add(report_stock)

        self.db.commit()
        logger.info(f"Report generated successfully with {len(final_picks)} stocks")

        return report


def generate_daily_report(db: Session) -> Optional[DailyReport]:
    """Convenience function to generate daily report."""
    generator = ReportGenerator(db)
    return generator.generate_report()
