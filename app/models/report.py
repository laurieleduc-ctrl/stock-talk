from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, Text, ForeignKey, Boolean, Index, JSON
from sqlalchemy.orm import relationship

from app.core.database import Base


class DailyReport(Base):
    """Daily stock analysis report."""

    __tablename__ = "daily_reports"

    id = Column(Integer, primary_key=True, index=True)
    report_date = Column(DateTime, nullable=False, unique=True, index=True)

    # Market context
    market_summary = Column(Text)  # Brief market overview
    sp500_change = Column(Float)
    nasdaq_change = Column(Float)

    # Report metadata
    total_stocks_analyzed = Column(Integer)
    stocks_passing_criteria = Column(Integer)

    # Learning content
    tip_of_the_day_title = Column(String(255))
    tip_of_the_day_content = Column(Text)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    stocks = relationship("ReportStock", back_populates="report", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<DailyReport {self.report_date.strftime('%Y-%m-%d')}>"


class ReportStock(Base):
    """Individual stock entry within a daily report."""

    __tablename__ = "report_stocks"

    id = Column(Integer, primary_key=True, index=True)
    report_id = Column(Integer, ForeignKey("daily_reports.id"), nullable=False)
    stock_id = Column(Integer, ForeignKey("stocks.id"), nullable=False)

    # Ranking
    rank = Column(Integer, nullable=False)  # 1-20
    is_dark_horse = Column(Boolean, default=False)

    # Sector classification for this report
    sector_category = Column(String(50))  # tech, ai, medical, international

    # Snapshot of key metrics at report time
    price_at_report = Column(Float)
    pct_from_ath = Column(Float)
    pe_ratio = Column(Float)
    pb_ratio = Column(Float)
    peg_ratio = Column(Float)
    debt_to_equity = Column(Float)
    free_cash_flow = Column(Float)
    profit_margin = Column(Float)
    dividend_yield = Column(Float)
    rsi = Column(Float)
    short_interest = Column(Float)
    institutional_ownership = Column(Float)
    one_year_return = Column(Float)
    three_month_return = Column(Float)
    beta = Column(Float)

    # Company description
    business_summary = Column(Text)

    # 52-week range
    fifty_two_week_high = Column(Float)
    fifty_two_week_low = Column(Float)

    # Analyst data
    analyst_rating = Column(String(20))
    analyst_count = Column(Integer)
    target_price_mean = Column(Float)
    target_upside_pct = Column(Float)

    # Next earnings
    next_earnings_date = Column(DateTime)

    # Reddit data
    reddit_mentions_week = Column(Integer)
    reddit_sentiment = Column(Float)  # -1 to 1
    sentiment_label = Column(String(20))  # Bearish, Mixed, Bullish

    # Insider activity (JSON for flexibility)
    insider_activity = Column(JSON)  # [{"type": "buy", "amount": 1000000, "date": "2024-01-15", "role": "CEO"}]

    # Generated analysis
    buy_case = Column(Text)  # Why it might be a good buy today
    risk_factors = Column(JSON)  # ["Risk 1", "Risk 2", ...]
    recent_news = Column(JSON)  # [{"title": "...", "source": "...", "date": "..."}]

    # Dark horse specific
    dark_horse_reasons = Column(JSON)  # ["Low reddit mentions", "Under-followed by analysts", ...]

    # Signal summary
    bullish_signals = Column(Integer)  # Count of green flags
    bearish_signals = Column(Integer)  # Count of red flags
    neutral_signals = Column(Integer)  # Count of neutral indicators

    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    report = relationship("DailyReport", back_populates="stocks")
    stock = relationship("Stock", back_populates="report_entries")

    __table_args__ = (
        Index("ix_report_stocks_report_rank", "report_id", "rank"),
    )

    def __repr__(self):
        return f"<ReportStock #{self.rank} in Report {self.report_id}>"
