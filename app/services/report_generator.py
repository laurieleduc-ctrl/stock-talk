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
from app.services.market_context import fetch_market_context

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

    def __init__(self, db: Session, max_stocks: int = None):
        self.db = db
        self.max_stocks = max_stocks or settings.MAX_STOCKS_WEB

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
        """Generate a data-specific explanation of why this stock might be a buy.
        Points are weighted by conviction strength and sorted by importance."""
        # (weight, text) — higher weight = stronger signal
        weighted_points: list[tuple[int, str]] = []

        # --- Valuation signals ---
        if stock.peg_ratio and stock.peg_ratio < 1:
            w = 90 if stock.peg_ratio < 0.5 else 75
            weighted_points.append((w, f"PEG of {stock.peg_ratio:.2f} suggests earnings growth outpaces the price—a classic value signal"))

        if stock.pe_ratio and stock.forward_pe:
            if stock.forward_pe < stock.pe_ratio * 0.8:
                improvement = round((1 - stock.forward_pe / stock.pe_ratio) * 100)
                weighted_points.append((70, f"Forward P/E ({stock.forward_pe:.1f}) is {improvement}% lower than trailing ({stock.pe_ratio:.1f}), pointing to accelerating earnings"))

        if stock.pe_ratio and stock.pe_ratio < 12:
            weighted_points.append((65, f"Trailing P/E of {stock.pe_ratio:.1f} is well below the market average, pricing in little growth"))

        if stock.pb_ratio and stock.pb_ratio < 1.0:
            weighted_points.append((60, f"Price-to-book of {stock.pb_ratio:.2f} means the market values it below its net assets"))

        # --- Price action signals ---
        if stock.pct_from_ath and stock.pct_from_ath >= 30:
            weighted_points.append((80, f"Trading {stock.pct_from_ath:.0f}% below its all-time high—if fundamentals are intact, this is a deep discount"))
        elif stock.pct_from_ath and stock.pct_from_ath >= 20:
            weighted_points.append((60, f"Down {stock.pct_from_ath:.0f}% from its all-time high, offering a potential discount entry"))

        if stock.rsi and stock.rsi < 25:
            weighted_points.append((85, f"RSI at {stock.rsi:.0f} is deeply oversold—selling pressure may be exhausted"))
        elif stock.rsi and stock.rsi < 30:
            weighted_points.append((65, f"RSI at {stock.rsi:.0f} suggests oversold conditions"))

        if stock.fifty_two_week_low and stock.current_price and stock.fifty_two_week_low > 0:
            pct_above_low = ((stock.current_price - stock.fifty_two_week_low) / stock.fifty_two_week_low) * 100
            if pct_above_low < 10:
                weighted_points.append((55, f"Only {pct_above_low:.0f}% above its 52-week low of ${stock.fifty_two_week_low:.2f}—near potential support"))

        # --- Financial strength ---
        if stock.free_cash_flow and stock.free_cash_flow > 0:
            if stock.market_cap and stock.market_cap > 0:
                fcf_yield = (stock.free_cash_flow / stock.market_cap) * 100
                if fcf_yield > 5:
                    weighted_points.append((80, f"Free cash flow yield of {fcf_yield:.1f}% (${stock.free_cash_flow:.1f}B FCF on ${stock.market_cap:.0f}B cap)—generating strong cash relative to price"))
                else:
                    weighted_points.append((55, f"Generating ${stock.free_cash_flow:.1f}B in free cash flow, demonstrating real profitability"))
            else:
                weighted_points.append((55, f"Generating ${stock.free_cash_flow:.1f}B in free cash flow"))

        if stock.profit_margin and stock.profit_margin > 20:
            weighted_points.append((50, f"Profit margin of {stock.profit_margin:.0f}% indicates pricing power and operational efficiency"))

        if stock.debt_to_equity is not None and stock.debt_to_equity < 0.3:
            weighted_points.append((55, f"Very low debt (D/E {stock.debt_to_equity:.2f}) gives flexibility to invest, acquire, or weather downturns"))
        elif stock.debt_to_equity is not None and 0 < stock.debt_to_equity < 0.5:
            weighted_points.append((40, f"Manageable debt levels (D/E {stock.debt_to_equity:.2f}) provide financial flexibility"))

        # --- Insider & institutional signals ---
        recent_buys = [a for a in stock.insider_activity if a.get("type") == "buy"]
        if recent_buys:
            total_value = sum(a.get("value", 0) for a in recent_buys)
            if total_value > 1_000_000:
                weighted_points.append((85, f"Insiders bought ${total_value/1e6:.1f}M recently—executives putting their own money on the line"))
            elif total_value > 0:
                weighted_points.append((65, f"Recent insider buying worth ${total_value/1e3:.0f}K signals management confidence"))

        # --- Analyst consensus ---
        if stock.target_price_mean and stock.current_price and stock.current_price > 0:
            upside = ((stock.target_price_mean - stock.current_price) / stock.current_price) * 100
            if upside > 40 and stock.analyst_count and stock.analyst_count >= 10:
                weighted_points.append((80, f"{stock.analyst_count} analysts see {upside:.0f}% upside to ${stock.target_price_mean:.0f}—strong Wall Street consensus"))
            elif upside > 20 and stock.analyst_count and stock.analyst_count >= 5:
                weighted_points.append((60, f"Analysts project {upside:.0f}% upside (target ${stock.target_price_mean:.0f}, {stock.analyst_count} analysts)"))
            elif upside > 20:
                weighted_points.append((45, f"Analyst target of ${stock.target_price_mean:.0f} implies {upside:.0f}% upside"))

        # --- Dividend ---
        if stock.dividend_yield and stock.dividend_yield > 3:
            weighted_points.append((50, f"Dividend yield of {stock.dividend_yield:.1f}% provides income while you wait for price recovery"))

        # --- Momentum recovery ---
        if stock.three_month_return and stock.one_year_return:
            if stock.three_month_return > 10 and stock.one_year_return < -10:
                weighted_points.append((60, f"Up {stock.three_month_return:.0f}% in 3 months after being down {abs(stock.one_year_return):.0f}% over the year—early turnaround signs"))

        # --- Reddit sentiment ---
        if sentiment > 0.4:
            weighted_points.append((40, f"Reddit sentiment is strongly bullish ({sentiment:.2f} score)"))
        elif sentiment > 0.3:
            weighted_points.append((30, "Positive Reddit sentiment suggests retail investor interest"))

        # Sort by weight descending, take top 4
        weighted_points.sort(key=lambda x: x[0], reverse=True)
        points = [text for _, text in weighted_points[:4]]

        if not points:
            # Build something specific even when signals are weak
            parts = []
            if stock.industry and stock.industry != "Unknown":
                parts.append(f"{stock.name} operates in {stock.industry}")
            elif stock.sector and stock.sector != "Unknown":
                parts.append(f"{stock.name} operates in the {stock.sector} sector")
            if stock.market_cap:
                parts.append(f"with a ${stock.market_cap:.0f}B market cap")
            if stock.pct_from_ath:
                parts.append(f"trading {stock.pct_from_ath:.0f}% off highs")
            points = [", ".join(parts) + "—worth monitoring for a clearer entry signal" if parts
                      else f"{stock.name} has limited data signals right now; review fundamentals before acting"]

        return " ".join(points) + "."

    def _generate_risk_factors(self, stock: StockData) -> list[str]:
        """Generate specific, company-level risk factors weighted by severity.
        Each risk includes concrete data and is prioritized by impact x likelihood."""
        # (severity, text) — higher severity = more important risk
        weighted_risks: list[tuple[int, str]] = []

        # --- Earnings timing (high impact, certain) ---
        if stock.next_earnings_date:
            days_until = (stock.next_earnings_date - datetime.now()).days
            if 0 < days_until <= 7:
                weighted_risks.append((95, f"Earnings in {days_until} day{'s' if days_until != 1 else ''}—a miss could trigger a sharp selloff"))
            elif 7 < days_until <= 14:
                weighted_risks.append((70, f"Earnings report in {days_until} days. Expect elevated volatility; consider waiting for results"))

        # --- Debt burden ---
        if stock.debt_to_equity and stock.debt_to_equity > 3.0:
            weighted_risks.append((90, f"D/E of {stock.debt_to_equity:.1f} is dangerously high—rising rates or a revenue slowdown could threaten solvency"))
        elif stock.debt_to_equity and stock.debt_to_equity > 2.0:
            weighted_risks.append((75, f"Heavy debt load (D/E {stock.debt_to_equity:.1f}) limits flexibility. Interest payments consume cash that could fund growth"))
        elif stock.debt_to_equity and stock.debt_to_equity > 1.5:
            weighted_risks.append((55, f"D/E of {stock.debt_to_equity:.1f} is above average—manageable now, but adds pressure if earnings dip"))

        # --- Cash burn ---
        if stock.free_cash_flow and stock.free_cash_flow < -1.0:
            weighted_risks.append((90, f"Burning ${abs(stock.free_cash_flow):.1f}B in cash annually—may need to raise capital through dilutive offerings or more debt"))
        elif stock.free_cash_flow and stock.free_cash_flow < 0:
            weighted_risks.append((70, f"Negative free cash flow (${stock.free_cash_flow:.1f}B)—spending more than it earns, needs a path to profitability"))

        # --- Negative profit margins ---
        if stock.profit_margin is not None and stock.profit_margin < -10:
            weighted_risks.append((80, f"Profit margin of {stock.profit_margin:.0f}% means {stock.ticker} loses money on every dollar of revenue"))
        elif stock.profit_margin is not None and stock.profit_margin < 0:
            weighted_risks.append((60, f"Operating at a loss ({stock.profit_margin:.1f}% margin)—revenue growth needs to outpace costs"))

        # --- Price decline momentum ---
        if stock.one_year_return and stock.three_month_return:
            if stock.one_year_return < -50 and stock.three_month_return < -20:
                weighted_risks.append((90, f"Down {abs(stock.one_year_return):.0f}% this year and still falling ({stock.three_month_return:+.0f}% last 3 months)—downtrend is accelerating"))
            elif stock.one_year_return < -40:
                weighted_risks.append((75, f"Down {abs(stock.one_year_return):.0f}% over the past year—steep decline may reflect structural issues, not just a dip"))
            elif stock.one_year_return < -25 and stock.three_month_return < 0:
                weighted_risks.append((65, f"Down {abs(stock.one_year_return):.0f}% this year with no recovery ({stock.three_month_return:+.0f}% last quarter)—momentum still negative"))
        elif stock.one_year_return and stock.one_year_return < -40:
            weighted_risks.append((70, f"Lost {abs(stock.one_year_return):.0f}% over the past year—significant shareholder value destruction"))

        # --- Short interest ---
        if stock.short_interest and stock.short_interest > 25:
            weighted_risks.append((85, f"{stock.short_interest:.0f}% short interest is extreme—hedge funds are aggressively betting against {stock.ticker}"))
        elif stock.short_interest and stock.short_interest > 15:
            weighted_risks.append((65, f"{stock.short_interest:.1f}% short interest—a significant number of professionals are betting on further declines"))
        elif stock.short_interest and stock.short_interest > 10:
            weighted_risks.append((45, f"Moderate short interest ({stock.short_interest:.1f}%)—some bearish positioning worth noting"))

        # --- Valuation still stretched ---
        if stock.pe_ratio and stock.pe_ratio > 50:
            weighted_risks.append((70, f"P/E of {stock.pe_ratio:.0f} requires exceptional growth to justify—any earnings miss could trigger a re-rating"))
        elif stock.pe_ratio and stock.pe_ratio > 35:
            weighted_risks.append((50, f"P/E of {stock.pe_ratio:.0f} prices in significant growth. A guidance cut could hurt"))

        # --- Volatility ---
        if stock.beta and stock.beta > 2.0:
            weighted_risks.append((65, f"Beta of {stock.beta:.1f}—a 5% market drop could mean ~{stock.beta * 5:.0f}% hit for {stock.ticker}"))
        elif stock.beta and stock.beta > 1.5:
            weighted_risks.append((45, f"Elevated volatility (beta {stock.beta:.1f})—swings amplified vs. the broader market"))

        # --- Small/micro cap ---
        if stock.market_cap_category == "micro" and stock.market_cap:
            weighted_risks.append((70, f"Micro-cap (${stock.market_cap:.1f}B) with likely thin volume—wide spreads make entry/exit costly"))
        elif stock.market_cap_category == "small" and stock.market_cap:
            weighted_risks.append((50, f"Small-cap (${stock.market_cap:.1f}B)—more vulnerable to slowdowns and less institutional support"))

        # --- Analyst skepticism ---
        if stock.analyst_rating and stock.analyst_rating.lower() in ["sell", "strong sell", "underperform"]:
            count_str = f" ({stock.analyst_count} analysts)" if stock.analyst_count else ""
            weighted_risks.append((75, f"Analyst consensus is \"{stock.analyst_rating}\"{count_str}—Wall Street sees more downside"))
        elif stock.analyst_count and stock.analyst_count < 3 and stock.market_cap and stock.market_cap < 5:
            weighted_risks.append((50, f"Only {stock.analyst_count} analyst{'s' if stock.analyst_count != 1 else ''} cover {stock.ticker}—low scrutiny may hide risks"))

        # --- Analyst target implies downside ---
        if stock.target_price_mean and stock.current_price and stock.current_price > 0:
            upside = ((stock.target_price_mean - stock.current_price) / stock.current_price) * 100
            if upside < -10:
                weighted_risks.append((80, f"Avg analyst target ${stock.target_price_mean:.0f} implies {abs(upside):.0f}% downside from current ${stock.current_price:.2f}"))

        # --- Insider selling ---
        recent_sells = [a for a in stock.insider_activity if a.get("type") == "sell"]
        recent_buys = [a for a in stock.insider_activity if a.get("type") == "buy"]
        if recent_sells and len(recent_sells) > len(recent_buys) + 1:
            total_sold = sum(a.get("value", 0) for a in recent_sells)
            if total_sold > 1_000_000:
                weighted_risks.append((70, f"Insiders net selling recently (${total_sold/1e6:.1f}M sold)—executives reducing their own exposure"))

        # --- RSI overbought ---
        if stock.rsi and stock.rsi > 75:
            weighted_risks.append((55, f"RSI at {stock.rsi:.0f} is overbought—recent rally may be overextended, pullback likely"))

        # --- Institutional crowding ---
        if stock.institutional_ownership and stock.institutional_ownership > 95:
            weighted_risks.append((45, f"{stock.institutional_ownership:.0f}% institutional ownership—any institutional selling would create outsized downward pressure"))

        # Sort by severity descending, take top 5
        weighted_risks.sort(key=lambda x: x[0], reverse=True)
        risks = [text for _, text in weighted_risks[:5]]

        # If no specific risks found, build company-specific context instead of generic message
        if not risks:
            metrics = []
            if stock.pe_ratio:
                metrics.append(f"P/E {stock.pe_ratio:.1f}")
            if stock.debt_to_equity is not None:
                metrics.append(f"D/E {stock.debt_to_equity:.1f}")
            if stock.beta:
                metrics.append(f"beta {stock.beta:.1f}")
            metrics_str = ", ".join(metrics) if metrics else "limited data"
            risks = [f"{stock.name} shows no major red flags ({metrics_str}), but verify with recent filings and news before acting"]

        return risks

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

        # Fall back to curated list + screener discovery
        if not aggregated:
            # Use screener for worker jobs (large max_stocks), skip for quick web requests
            use_screener = self.max_stocks >= settings.MAX_STOCKS_WORKER
            logger.info(f"Building stock list (screener={'on' if use_screener else 'off'})...")
            aggregated = get_fallback_mentions(use_screener=use_screener)

        logger.info(f"Found {len(aggregated)} unique tickers to analyze")

        # Step 2: Filter to stocks with minimum mentions and prioritize
        qualifying = [
            (ticker, data) for ticker, data in aggregated.items()
            if data["total_mentions"] >= settings.MIN_REDDIT_MENTIONS
        ]

        # Sort by priority: watchlist first, then by mentions (higher = more buzz)
        qualifying.sort(key=lambda x: (
            x[1].get("is_watchlist", False),  # Watchlist stocks first
            x[1]["total_mentions"],
        ), reverse=True)

        # Limit tickers based on context (web vs worker)
        max_stocks = getattr(self, 'max_stocks', settings.MAX_STOCKS_WEB)
        qualifying_tickers = [t for t, _ in qualifying[:max_stocks]]

        logger.info(f"Analyzing {len(qualifying_tickers)} tickers (from {len(qualifying)} candidates)")

        # Step 3: Fetch stock data for qualifying tickers
        logger.info("Fetching stock data from Yahoo Finance...")
        stock_data_map = stock_fetcher.fetch_multiple(qualifying_tickers)

        # Step 4: Filter and analyze stocks
        analyzed_stocks: list[AnalyzedStock] = []
        skipped_invalid = 0
        skipped_ath = 0

        for ticker, stock_data in stock_data_map.items():
            if not stock_data.is_valid:
                skipped_invalid += 1
                logger.debug(f"Skipping {ticker}: invalid data - {stock_data.error_message}")
                continue

            # Check if meets our criteria
            reddit_data = aggregated.get(ticker, {})
            mentions = reddit_data.get("total_mentions", 0)
            sentiment = reddit_data.get("avg_sentiment", 0.0)

            # For now, include all stocks with valid data (relaxed filter)
            # Value investors can filter by pct_from_ath in the UI
            # Original filter: must be 15% below ATH
            # if not stock_data.pct_from_ath or stock_data.pct_from_ath < settings.MIN_DROP_FROM_ATH * 100:
            #     skipped_ath += 1
            #     continue

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

        # Fetch market context (index performance + news)
        logger.info("Fetching market context...")
        try:
            market_ctx = fetch_market_context()
        except Exception as e:
            logger.warning(f"Failed to fetch market context: {e}")
            market_ctx = None

        report = DailyReport(
            report_date=report_date,
            total_stocks_analyzed=len(qualifying_tickers),
            stocks_passing_criteria=len(analyzed_stocks),
            tip_of_the_day_title=tip["title"],
            tip_of_the_day_content=tip["content"],
            market_summary=market_ctx.market_summary if market_ctx else None,
            sp500_change=market_ctx.sp500_change if market_ctx else None,
            nasdaq_change=market_ctx.nasdaq_change if market_ctx else None,
            dow_change=market_ctx.dow_change if market_ctx else None,
            vix_level=market_ctx.vix_level if market_ctx else None,
            market_news=market_ctx.market_news if market_ctx else None,
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
                three_month_return=stock_data.three_month_return,
                beta=stock_data.beta,
                forward_pe=stock_data.forward_pe,
                ps_ratio=stock_data.ps_ratio,
                ev_ebitda=stock_data.ev_ebitda,
                gross_margin=stock_data.gross_margin,
                operating_margin=stock_data.operating_margin,
                current_ratio=stock_data.current_ratio,
                ytd_return=stock_data.ytd_return,
                one_month_return=stock_data.one_month_return,
                earnings_surprise_pct=stock_data.earnings_surprise_pct,
                insider_ownership=stock_data.insider_ownership,
                target_price_low=stock_data.target_price_low,
                target_price_high=stock_data.target_price_high,
                avg_volume=stock_data.avg_volume,
                recent_volume=stock_data.recent_volume,
                sma_50=stock_data.sma_50,
                sma_200=stock_data.sma_200,
                business_summary=stock_data.business_summary,
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


def generate_daily_report(db: Session, max_stocks: int = None) -> Optional[DailyReport]:
    """Convenience function to generate daily report.

    Args:
        db: Database session
        max_stocks: Maximum stocks to analyze (default: MAX_STOCKS_WEB for web,
                    use MAX_STOCKS_WORKER for scheduled jobs)
    """
    generator = ReportGenerator(db, max_stocks=max_stocks)
    return generator.generate_report()
