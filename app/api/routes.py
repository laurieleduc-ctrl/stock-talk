"""
API routes for Stock Talk application.
"""

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from app.core.config import settings
from app.core.database import get_db, SessionLocal
from app.models import DailyReport, ReportStock, Stock
from app.services.report_generator import generate_daily_report

router = APIRouter()


def _generate_full_report_background():
    """Background task to generate full report with worker settings."""
    db = SessionLocal()
    try:
        generate_daily_report(db, max_stocks=settings.MAX_STOCKS_WORKER)
    finally:
        db.close()


@router.get("/reports")
def get_reports(
    limit: int = Query(default=30, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """Get list of all reports with pagination."""
    reports = (
        db.query(DailyReport)
        .order_by(DailyReport.report_date.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    total = db.query(DailyReport).count()

    return {
        "reports": [
            {
                "id": r.id,
                "date": r.report_date.isoformat(),
                "stocks_analyzed": r.total_stocks_analyzed,
                "stocks_in_report": r.stocks_passing_criteria,
            }
            for r in reports
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/reports/latest")
def get_latest_report(db: Session = Depends(get_db)):
    """Get the most recent report with full details."""
    report = (
        db.query(DailyReport)
        .options(joinedload(DailyReport.stocks).joinedload(ReportStock.stock))
        .order_by(DailyReport.report_date.desc())
        .first()
    )

    if not report:
        raise HTTPException(status_code=404, detail="No reports found")

    return _format_report(report)


@router.get("/reports/generate")
def trigger_report_generation_get(db: Session = Depends(get_db)):
    """Manually trigger report generation (GET for easy browser access). Uses fast mode (15 stocks)."""
    try:
        report = generate_daily_report(db)
        if report:
            return {
                "status": "success",
                "report_id": report.id,
                "date": report.report_date.isoformat(),
                "message": "Report generated! Visit the homepage to view it.",
            }
        else:
            return {
                "status": "failed",
                "message": "No stocks met the criteria for today's report",
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/reports/generate-full")
def trigger_full_report_generation(background_tasks: BackgroundTasks):
    """
    Trigger full report generation (60 stocks, 3 years history) in background.
    This runs asynchronously and won't timeout.
    """
    background_tasks.add_task(_generate_full_report_background)
    return {
        "status": "started",
        "message": f"Full report generation started in background ({settings.MAX_STOCKS_WORKER} stocks). "
                   "Check back in a few minutes and refresh the homepage to see results.",
    }


@router.get("/reports/{report_id}")
def get_report(report_id: int, db: Session = Depends(get_db)):
    """Get a specific report by ID."""
    report = (
        db.query(DailyReport)
        .options(joinedload(DailyReport.stocks).joinedload(ReportStock.stock))
        .filter(DailyReport.id == report_id)
        .first()
    )

    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    return _format_report(report)


@router.get("/reports/date/{date}")
def get_report_by_date(date: str, db: Session = Depends(get_db)):
    """Get report for a specific date (YYYY-MM-DD format)."""
    try:
        report_date = datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

    # Look for report on this date
    start_of_day = report_date.replace(hour=0, minute=0, second=0)
    end_of_day = report_date.replace(hour=23, minute=59, second=59)

    report = (
        db.query(DailyReport)
        .options(joinedload(DailyReport.stocks).joinedload(ReportStock.stock))
        .filter(DailyReport.report_date >= start_of_day)
        .filter(DailyReport.report_date <= end_of_day)
        .first()
    )

    if not report:
        raise HTTPException(status_code=404, detail=f"No report found for {date}")

    return _format_report(report)


@router.get("/stocks/{ticker}")
def get_stock_history(
    ticker: str,
    limit: int = Query(default=30, le=100),
    db: Session = Depends(get_db),
):
    """Get historical report data for a specific stock."""
    stock = db.query(Stock).filter(Stock.ticker == ticker.upper()).first()

    if not stock:
        raise HTTPException(status_code=404, detail=f"Stock {ticker} not found")

    report_entries = (
        db.query(ReportStock)
        .options(joinedload(ReportStock.report))
        .filter(ReportStock.stock_id == stock.id)
        .order_by(ReportStock.created_at.desc())
        .limit(limit)
        .all()
    )

    return {
        "ticker": stock.ticker,
        "name": stock.name,
        "sector": stock.sector,
        "industry": stock.industry,
        "appearances": len(report_entries),
        "history": [
            {
                "report_date": entry.report.report_date.isoformat(),
                "rank": entry.rank,
                "is_dark_horse": entry.is_dark_horse,
                "price": entry.price_at_report,
                "pct_from_ath": entry.pct_from_ath,
                "pe_ratio": entry.pe_ratio,
                "rsi": entry.rsi,
                "reddit_mentions": entry.reddit_mentions_week,
                "sentiment": entry.sentiment_label,
                "buy_case": entry.buy_case,
            }
            for entry in report_entries
        ],
    }


@router.get("/stocks")
def search_stocks(
    q: str = Query(default="", min_length=1),
    sector: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Search stocks that have appeared in reports."""
    query = db.query(Stock)

    if q:
        search_term = f"%{q.upper()}%"
        query = query.filter(
            (Stock.ticker.ilike(search_term)) | (Stock.name.ilike(search_term))
        )

    if sector:
        query = query.filter(Stock.sector.ilike(f"%{sector}%"))

    stocks = query.limit(20).all()

    return {
        "results": [
            {
                "ticker": s.ticker,
                "name": s.name,
                "sector": s.sector,
                "industry": s.industry,
                "market_cap": s.market_cap,
            }
            for s in stocks
        ]
    }


@router.post("/reports/generate")
def trigger_report_generation(db: Session = Depends(get_db)):
    """Manually trigger report generation (for testing/admin use)."""
    try:
        report = generate_daily_report(db)
        if report:
            return {
                "status": "success",
                "report_id": report.id,
                "date": report.report_date.isoformat(),
            }
        else:
            return {
                "status": "failed",
                "message": "No stocks met the criteria for today's report",
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
def get_stats(db: Session = Depends(get_db)):
    """Get overall statistics."""
    total_reports = db.query(DailyReport).count()
    total_stocks = db.query(Stock).count()

    # Most featured stocks
    from sqlalchemy import func

    top_stocks = (
        db.query(Stock.ticker, Stock.name, func.count(ReportStock.id).label("count"))
        .join(ReportStock)
        .group_by(Stock.id)
        .order_by(func.count(ReportStock.id).desc())
        .limit(10)
        .all()
    )

    # Sector distribution
    sector_dist = (
        db.query(ReportStock.sector_category, func.count(ReportStock.id).label("count"))
        .group_by(ReportStock.sector_category)
        .all()
    )

    return {
        "total_reports": total_reports,
        "total_unique_stocks": total_stocks,
        "top_featured_stocks": [
            {"ticker": t[0], "name": t[1], "appearances": t[2]} for t in top_stocks
        ],
        "sector_distribution": {s[0]: s[1] for s in sector_dist if s[0]},
    }


def _format_report(report: DailyReport) -> dict:
    """Format a report with all its stocks for API response."""
    stocks_data = []

    for rs in sorted(report.stocks, key=lambda x: x.rank):
        stock = rs.stock

        # Calculate 52-week position (using getattr for potentially missing columns)
        week_52_position = None
        fifty_two_high = getattr(rs, 'fifty_two_week_high', None)
        fifty_two_low = getattr(rs, 'fifty_two_week_low', None)
        price_at_report = getattr(rs, 'price_at_report', None)
        if fifty_two_high and fifty_two_low and price_at_report:
            range_size = fifty_two_high - fifty_two_low
            if range_size > 0:
                week_52_position = round(
                    ((price_at_report - fifty_two_low) / range_size) * 100, 1
                )

        # Use getattr for columns that may not exist in older database schemas
        stocks_data.append({
            "rank": rs.rank,
            "ticker": stock.ticker,
            "name": stock.name,
            "sector": stock.sector,
            "industry": stock.industry,
            "sector_category": getattr(rs, 'sector_category', None),
            "is_dark_horse": getattr(rs, 'is_dark_horse', False),
            "market_cap": getattr(stock, 'market_cap', None),
            "market_cap_category": getattr(stock, 'market_cap_category', None),

            # Price data
            "price": getattr(rs, 'price_at_report', None),
            "pct_from_ath": getattr(rs, 'pct_from_ath', None),
            "fifty_two_week_high": getattr(rs, 'fifty_two_week_high', None),
            "fifty_two_week_low": getattr(rs, 'fifty_two_week_low', None),
            "week_52_position": week_52_position,

            # Valuation
            "pe_ratio": getattr(rs, 'pe_ratio', None),
            "pb_ratio": getattr(rs, 'pb_ratio', None),
            "peg_ratio": getattr(rs, 'peg_ratio', None),

            # Financial health
            "debt_to_equity": getattr(rs, 'debt_to_equity', None),
            "free_cash_flow": getattr(rs, 'free_cash_flow', None),
            "profit_margin": getattr(rs, 'profit_margin', None),

            # Dividends
            "dividend_yield": getattr(rs, 'dividend_yield', None),

            # Technical
            "rsi": getattr(rs, 'rsi', None),
            "beta": getattr(rs, 'beta', None),
            "one_year_return": getattr(rs, 'one_year_return', None),
            "three_month_return": getattr(rs, 'three_month_return', None),

            # Company info
            "business_summary": getattr(rs, 'business_summary', '') or "",

            # Ownership
            "short_interest": getattr(rs, 'short_interest', None),
            "institutional_ownership": getattr(rs, 'institutional_ownership', None),

            # Analyst
            "analyst_rating": getattr(rs, 'analyst_rating', None),
            "analyst_count": getattr(rs, 'analyst_count', None),
            "target_price_mean": getattr(rs, 'target_price_mean', None),
            "target_upside_pct": getattr(rs, 'target_upside_pct', None),

            # Earnings
            "next_earnings_date": getattr(rs, 'next_earnings_date', None).isoformat() if getattr(rs, 'next_earnings_date', None) else None,

            # Reddit
            "reddit_mentions": getattr(rs, 'reddit_mentions_week', None),
            "reddit_sentiment": getattr(rs, 'reddit_sentiment', None),
            "sentiment_label": getattr(rs, 'sentiment_label', None),

            # Activity & News
            "insider_activity": getattr(rs, 'insider_activity', None) or [],
            "recent_news": getattr(rs, 'recent_news', None) or [],

            # Analysis
            "buy_case": getattr(rs, 'buy_case', None),
            "risk_factors": getattr(rs, 'risk_factors', None) or [],
            "dark_horse_reasons": getattr(rs, 'dark_horse_reasons', None) or [],

            # Signals
            "bullish_signals": getattr(rs, 'bullish_signals', None),
            "bearish_signals": getattr(rs, 'bearish_signals', None),
            "neutral_signals": getattr(rs, 'neutral_signals', None),
        })

    # Sector summary
    sector_counts = {}
    for s in stocks_data:
        cat = s["sector_category"] or "other"
        sector_counts[cat] = sector_counts.get(cat, 0) + 1

    return {
        "id": report.id,
        "date": report.report_date.isoformat(),
        "stocks_analyzed": report.total_stocks_analyzed,
        "stocks_passing_criteria": report.stocks_passing_criteria,
        "market_summary": report.market_summary,
        "sp500_change": report.sp500_change,
        "nasdaq_change": report.nasdaq_change,
        "tip_of_the_day": {
            "title": report.tip_of_the_day_title,
            "content": report.tip_of_the_day_content,
        },
        "sector_breakdown": sector_counts,
        "stocks": stocks_data,
    }
