from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, Text, ForeignKey, Index
from sqlalchemy.orm import relationship

from app.core.database import Base


class Stock(Base):
    """Core stock information."""

    __tablename__ = "stocks"

    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String(10), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    sector = Column(String(100))
    industry = Column(String(100))
    market_cap = Column(Float)  # In billions
    market_cap_category = Column(String(20))  # small, mid, large, mega
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    mentions = relationship("StockMention", back_populates="stock", cascade="all, delete-orphan")
    metrics = relationship("StockMetrics", back_populates="stock", cascade="all, delete-orphan")
    report_entries = relationship("ReportStock", back_populates="stock")

    def __repr__(self):
        return f"<Stock {self.ticker}: {self.name}>"


class StockMention(Base):
    """Reddit mentions for stocks."""

    __tablename__ = "stock_mentions"

    id = Column(Integer, primary_key=True, index=True)
    stock_id = Column(Integer, ForeignKey("stocks.id"), nullable=False)
    subreddit = Column(String(50), nullable=False)  # stocks, wallstreetbets
    post_id = Column(String(20))
    post_title = Column(Text)
    mention_count = Column(Integer, default=1)
    sentiment_score = Column(Float)  # -1 to 1 scale
    mentioned_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    stock = relationship("Stock", back_populates="mentions")

    __table_args__ = (
        Index("ix_stock_mentions_stock_date", "stock_id", "mentioned_at"),
        Index("ix_stock_mentions_subreddit", "subreddit"),
    )


class StockMetrics(Base):
    """Daily snapshot of stock metrics."""

    __tablename__ = "stock_metrics"

    id = Column(Integer, primary_key=True, index=True)
    stock_id = Column(Integer, ForeignKey("stocks.id"), nullable=False)
    date = Column(DateTime, nullable=False)

    # Price data
    current_price = Column(Float)
    all_time_high = Column(Float)
    pct_from_ath = Column(Float)  # Percentage below ATH
    fifty_two_week_high = Column(Float)
    fifty_two_week_low = Column(Float)

    # Valuation metrics
    pe_ratio = Column(Float)  # Price-to-Earnings
    forward_pe = Column(Float)  # Forward P/E
    pb_ratio = Column(Float)  # Price-to-Book
    ps_ratio = Column(Float)  # Price-to-Sales
    peg_ratio = Column(Float)  # P/E to Growth
    ev_ebitda = Column(Float)  # Enterprise Value / EBITDA

    # Financial health
    debt_to_equity = Column(Float)
    current_ratio = Column(Float)
    free_cash_flow = Column(Float)  # In billions
    profit_margin = Column(Float)  # Percentage
    gross_margin = Column(Float)
    operating_margin = Column(Float)

    # Dividends
    dividend_yield = Column(Float)  # Percentage
    dividend_rate = Column(Float)  # Annual dividend per share

    # Momentum & Technical
    rsi = Column(Float)  # Relative Strength Index
    beta = Column(Float)
    avg_volume = Column(Float)
    recent_volume = Column(Float)

    # Performance
    one_year_return = Column(Float)  # Percentage
    ytd_return = Column(Float)
    one_month_return = Column(Float)

    # Ownership
    short_interest = Column(Float)  # Percentage
    institutional_ownership = Column(Float)  # Percentage
    insider_ownership = Column(Float)

    # Analyst data
    analyst_rating = Column(String(20))  # Buy, Hold, Sell
    analyst_count = Column(Integer)
    target_price_low = Column(Float)
    target_price_high = Column(Float)
    target_price_mean = Column(Float)

    # Earnings
    next_earnings_date = Column(DateTime)
    earnings_surprise_pct = Column(Float)  # Last earnings surprise

    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    stock = relationship("Stock", back_populates="metrics")

    __table_args__ = (
        Index("ix_stock_metrics_stock_date", "stock_id", "date"),
    )

    def __repr__(self):
        return f"<StockMetrics {self.stock_id} @ {self.date}>"


class WatchlistStock(Base):
    """User's custom watchlist stocks to always include in analysis."""

    __tablename__ = "watchlist_stocks"

    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String(10), unique=True, nullable=False, index=True)
    notes = Column(Text)  # Optional notes about why it's on the watchlist
    priority = Column(Integer, default=0)  # Higher priority = analyzed first
    created_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<WatchlistStock {self.ticker}>"
